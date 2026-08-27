"""
Synthetic data generator for LedgerGuard demo.

Deliberately injects the failure modes the pitch is built around:
  - clean exact matches (majority, ~55%)
  - MDR-fee-only variance (fuzzy match territory, ~20%)
  - FX-rate variance for foreign-currency orders (~10%)
  - split payments: one invoice, 2-3 bank credits (~8%)
  - true exceptions: refund/discount not reflected anywhere obvious,
    requiring the agent to read a contract clause or a Slack message (~7%)

Run: python -m app.data_generator          # 500 transactions (default)
     python -m app.data_generator 1000     # custom count
"""
import random
import uuid
from datetime import datetime, timedelta

from faker import Faker
from sqlalchemy.orm import Session

from app.database import Base, engine, SessionLocal
from app.models import (
    SalesInvoice, GatewaySettlement, BankCredit, ContractChunk, CommsMessage, MatchStatus
)
from app.llm_provider import get_llm

fake = Faker()
random.seed(42)

MERCHANTS = ["merchant_apex", "merchant_bluepeak", "merchant_civet"]
MDR_RATE = 0.021  # 2.1% standard MDR

CONTRACT_TEXT = {
    "merchant_apex": (
        "Apex Retail Pvt Ltd Merchant Agreement, Clause 4.2 (Fee Schedule): "
        "The Merchant Discount Rate (MDR) applicable to all UPI and card transactions "
        "shall be 2.1% of the gross transaction value, deducted at source prior to "
        "settlement. For international card transactions, an additional 1.5% currency "
        "conversion markup applies, calculated on the gross INR-converted amount."
    ),
    "merchant_bluepeak": (
        "Bluepeak Commerce Merchant Agreement, Clause 3.1 (Settlement Terms): "
        "Standard domestic transactions carry a 2.1% MDR. Bluepeak has negotiated a "
        "promotional MDR waiver of 0.5% for transactions above INR 50,000, valid "
        "through Q4. Refunds processed within 48 hours of the original transaction "
        "are settled net of the original MDR, with no additional refund processing fee."
    ),
    "merchant_civet": (
        "Civet Foods Merchant Agreement, Clause 5.0 (Fees and Charges): "
        "MDR is fixed at 2.1% for all payment modes. Any transaction flagged for "
        "manual fraud review incurs a INR 25 flat review fee, deducted from the "
        "settlement amount and itemized separately in the monthly statement."
    ),
}


def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_contracts(db: Session):
    """Chunk + embed the mock contract text per merchant using the local
    embedding model, so the agent's RAG tool has something real to search."""
    llm = get_llm()
    for merchant_id, text in CONTRACT_TEXT.items():
        # naive single-chunk per merchant is fine for demo scale; for a real
        # doc you'd split into ~300-token chunks
        try:
            embedding = llm.embed(text)
        except Exception as e:
            print(f"WARNING: embedding failed ({e}); is Ollama running with nomic-embed-text pulled?")
            embedding = [0.0] * 768
        chunk = ContractChunk(
            merchant_id=merchant_id,
            source_file=f"{merchant_id}_agreement.pdf",
            chunk_text=text,
            embedding=embedding,
        )
        db.add(chunk)
    db.commit()
    print(f"Seeded {len(CONTRACT_TEXT)} contract chunks.")


def generate_transactions(db: Session, n: int = 500):
    base_date = datetime.utcnow() - timedelta(days=30)
    comms_to_add = []

    for i in range(n):
        order_id = f"ORD{100000 + i}"
        merchant_id = random.choice(MERCHANTS)
        amount = round(random.uniform(500, 75000), 2)
        created_at = base_date + timedelta(days=random.randint(0, 25), hours=random.randint(0, 23))
        currency = "INR"

        invoice = SalesInvoice(
            invoice_id=f"INV-{uuid.uuid4().hex[:8]}",
            order_id=order_id,
            merchant_id=merchant_id,
            amount=amount,
            currency=currency,
            created_at=created_at,
        )
        db.add(invoice)

        bucket = random.random()

        if bucket < 0.55:
            # ---- Clean exact match ----
            mdr_fee = round(amount * MDR_RATE, 2)
            net = round(amount - mdr_fee, 2)
            # exact-match bucket: pretend no MDR was separately deducted at gateway
            # (net == gross for simplicity, so it clears stage 1)
            settlement = GatewaySettlement(
                settlement_id=f"STL-{uuid.uuid4().hex[:8]}",
                order_id=order_id, merchant_id=merchant_id,
                gross_amount=amount, mdr_fee=0.0, net_amount=amount,
                currency=currency, settled_at=created_at + timedelta(hours=2),
            )
            credit = BankCredit(
                txn_ref=f"BNK-{uuid.uuid4().hex[:8]}",
                order_id=order_id, amount=amount, currency=currency,
                credited_at=created_at + timedelta(hours=3),
                narration=f"NEFT CR {order_id}",
            )
            db.add_all([settlement, credit])

        elif bucket < 0.75:
            # ---- MDR-fee variance (needs fuzzy match / contract lookup) ----
            mdr_fee = round(amount * MDR_RATE, 2)
            net = round(amount - mdr_fee, 2)
            settlement = GatewaySettlement(
                settlement_id=f"STL-{uuid.uuid4().hex[:8]}",
                order_id=order_id, merchant_id=merchant_id,
                gross_amount=amount, mdr_fee=mdr_fee, net_amount=net,
                currency=currency, settled_at=created_at + timedelta(hours=2),
            )
            credit = BankCredit(
                txn_ref=f"BNK-{uuid.uuid4().hex[:8]}",
                order_id=order_id, amount=net, currency=currency,
                credited_at=created_at + timedelta(hours=3),
                narration=f"NEFT CR {order_id}",
            )
            db.add_all([settlement, credit])

        elif bucket < 0.85:
            # ---- FX variance (foreign currency order, needs fx_lookup tool) ----
            fx_rate = 83.20
            usd_amount = round(amount / fx_rate, 2)
            mdr_fee = round(amount * (MDR_RATE + 0.015), 2)  # extra intl markup
            net = round(amount - mdr_fee, 2)
            settlement = GatewaySettlement(
                settlement_id=f"STL-{uuid.uuid4().hex[:8]}",
                order_id=order_id, merchant_id=merchant_id,
                gross_amount=amount, mdr_fee=mdr_fee, net_amount=net,
                currency=currency, settled_at=created_at + timedelta(hours=2),
            )
            credit = BankCredit(
                txn_ref=f"BNK-{uuid.uuid4().hex[:8]}",
                order_id=order_id, amount=net, currency=currency,
                credited_at=created_at + timedelta(hours=3),
                narration=f"INTL WIRE CR {order_id} USD {usd_amount}",
            )
            db.add_all([settlement, credit])

        elif bucket < 0.93:
            # ---- Split payment: invoice paid via 2 bank credits ----
            settlement = GatewaySettlement(
                settlement_id=f"STL-{uuid.uuid4().hex[:8]}",
                order_id=order_id, merchant_id=merchant_id,
                gross_amount=amount, mdr_fee=0.0, net_amount=amount,
                currency=currency, settled_at=created_at + timedelta(hours=2),
            )
            db.add(settlement)
            part1 = round(amount * 0.6, 2)
            part2 = round(amount - part1, 2)
            db.add(BankCredit(
                txn_ref=f"BNK-{uuid.uuid4().hex[:8]}", order_id=None,
                amount=part1, currency=currency,
                credited_at=created_at + timedelta(hours=3),
                narration=f"PARTIAL CR ref {order_id[-4:]}",
            ))
            db.add(BankCredit(
                txn_ref=f"BNK-{uuid.uuid4().hex[:8]}", order_id=None,
                amount=part2, currency=currency,
                credited_at=created_at + timedelta(hours=5),
                narration=f"PARTIAL CR ref {order_id[-4:]}",
            ))

        else:
            # ---- True exception: partial refund, only explained in comms ----
            refund_amount = round(amount * 0.15, 2)
            net = round(amount - refund_amount, 2)
            settlement = GatewaySettlement(
                settlement_id=f"STL-{uuid.uuid4().hex[:8]}",
                order_id=order_id, merchant_id=merchant_id,
                gross_amount=amount, mdr_fee=0.0, net_amount=net,
                currency=currency, settled_at=created_at + timedelta(hours=2),
            )
            credit = BankCredit(
                txn_ref=f"BNK-{uuid.uuid4().hex[:8]}",
                order_id=order_id, amount=net, currency=currency,
                credited_at=created_at + timedelta(hours=3),
                narration=f"NEFT CR {order_id}",
            )
            db.add_all([settlement, credit])
            comms_to_add.append(CommsMessage(
                order_id=order_id, channel="slack", sender="support@merchant.internal",
                text=(f"Processed a partial refund of INR {refund_amount} on {order_id} "
                      f"per customer complaint (damaged item, case #{fake.uuid4()[:6]}). "
                      f"Approved by ops lead, no further action needed."),
                sent_at=created_at + timedelta(hours=4),
            ))

    for c in comms_to_add:
        db.add(c)

    db.commit()
    print(f"Generated {n} synthetic transactions across {len(MERCHANTS)} merchants.")


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    reset_db()
    db = SessionLocal()
    try:
        seed_contracts(db)
        generate_transactions(db, n=n)
    finally:
        db.close()
    print("Done. Now run: uvicorn app.main:app --reload  then POST /reconcile/run")