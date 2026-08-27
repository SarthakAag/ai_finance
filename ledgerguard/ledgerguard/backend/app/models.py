import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey, Text, Enum, JSON, Integer, Boolean
)
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class MatchStatus(str, enum.Enum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"          # matched by deterministic engine
    AGENT_RESOLVED = "AGENT_RESOLVED"  # matched by agent after investigation
    ESCALATED = "ESCALATED"            # agent could not resolve -> ticket drafted


# ---- Source 1: Internal sales / invoice records ----
class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id = Column(String, primary_key=True, default=gen_uuid)
    invoice_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    merchant_id = Column(String, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(MatchStatus), default=MatchStatus.PENDING)


# ---- Source 2: Payment gateway settlement logs (e.g. Razorpay) ----
class GatewaySettlement(Base):
    __tablename__ = "gateway_settlements"

    id = Column(String, primary_key=True, default=gen_uuid)
    settlement_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    merchant_id = Column(String, index=True)
    gross_amount = Column(Float, nullable=False)
    mdr_fee = Column(Float, default=0.0)
    net_amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    settled_at = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(MatchStatus), default=MatchStatus.PENDING)


# ---- Source 3: Bank statement credit lines ----
class BankCredit(Base):
    __tablename__ = "bank_credits"

    id = Column(String, primary_key=True, default=gen_uuid)
    txn_ref = Column(String, unique=True, index=True)
    order_id = Column(String, index=True, nullable=True)  # often missing/garbled from bank feed
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    credited_at = Column(DateTime, default=datetime.utcnow)
    narration = Column(Text, default="")
    status = Column(Enum(MatchStatus), default=MatchStatus.PENDING)


# ---- Reconciliation result linking the three sources ----
class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_id = Column(String, index=True)
    sales_invoice_id = Column(String, ForeignKey("sales_invoices.id"), nullable=True)
    gateway_settlement_id = Column(String, ForeignKey("gateway_settlements.id"), nullable=True)
    bank_credit_id = Column(String, ForeignKey("bank_credits.id"), nullable=True)

    status = Column(Enum(MatchStatus), default=MatchStatus.PENDING)
    match_stage = Column(String)  # "exact" | "fuzzy_mdr" | "split_payment" | "agent"
    variance_amount = Column(Float, default=0.0)
    variance_reason = Column(String, nullable=True)  # e.g. "mdr_fee", "fx_rate", "refund"
    confidence = Column(String, nullable=True)  # "high" | "medium" | "low" -- how much independent evidence supported an agent resolution
    created_at = Column(DateTime, default=datetime.utcnow)


# ---- Agent execution trace (auditability layer) ----
class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id = Column(String, primary_key=True, default=gen_uuid)
    reconciliation_match_id = Column(String, ForeignKey("reconciliation_matches.id"))
    step_number = Column(Integer)
    tool_name = Column(String)          # "contract_rag" | "comms_search" | "fx_lookup" | "write_correction"
    tool_input = Column(JSON)
    tool_output = Column(JSON)
    reasoning = Column(Text)            # agent's stated reasoning for this step
    tokens_used = Column(Integer, nullable=True)  # total tokens for this LLM call, if available
    created_at = Column(DateTime, default=datetime.utcnow)


# ---- Auto-drafted inquiry tickets for unresolved exceptions ----
class InquiryTicket(Base):
    __tablename__ = "inquiry_tickets"

    id = Column(String, primary_key=True, default=gen_uuid)
    reconciliation_match_id = Column(String, ForeignKey("reconciliation_matches.id"))
    subject = Column(String)
    body = Column(Text)
    expected_amount = Column(Float, nullable=True)
    actual_amount = Column(Float, nullable=True)
    missing_fields = Column(JSON, default=list)
    resolved = Column(Boolean, default=False)          # manually closed by a human reviewer
    resolution_note = Column(Text, nullable=True)       # what the human found/decided
    created_at = Column(DateTime, default=datetime.utcnow)


# ---- RAG source: chunked contract PDF text with embeddings ----
class ContractChunk(Base):
    __tablename__ = "contract_chunks"

    id = Column(String, primary_key=True, default=gen_uuid)
    merchant_id = Column(String, index=True)
    source_file = Column(String)
    chunk_text = Column(Text)
    embedding = Column(Vector(768))  # nomic-embed-text dim
    created_at = Column(DateTime, default=datetime.utcnow)


# ---- Mock internal comms (emails / Slack) the agent can search ----
class CommsMessage(Base):
    __tablename__ = "comms_messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_id = Column(String, index=True, nullable=True)
    channel = Column(String)  # "email" | "slack"
    sender = Column(String)
    text = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)