"""
Trains a supervised classifier that predicts, BEFORE the LLM agent is ever
called, how likely a reconciliation exception is to be auto-resolvable
(AGENT_RESOLVED) versus needing a human (ESCALATED).

This is deliberately a *second*, different model from the anomaly detector:
- anomaly_model.joblib        (Isolation Forest, unsupervised) flags unusual transactions
- exception_classifier.joblib (Random Forest, supervised) predicts resolution outcome

Labels come from the agent's own history -- every time resolve_exception()
finishes with AGENT_RESOLVED or ESCALATED, that outcome becomes a training
example for this model. The more the system is used, the more accurate this
gets -- a genuine feedback loop where past agent runs train a model that
helps route future ones, rather than a static heuristic.

Features (all knowable BEFORE calling the LLM, using the same deterministic
prefetch logic the orchestrator already uses -- so this model's inputs cost
nothing extra to compute):
  - amount
  - mdr_fee_ratio
  - hour_of_day, day_of_week
  - merchant_encoded
  - has_contract_context   (1 if contract_rag_search finds something for this merchant)
  - has_comms_context      (1 if comms_search finds something for this order_id)

Run: python -m app.ml.train_exception_classifier
Produces: app/ml/models/exception_classifier.joblib

Honesty note: with a small hackathon-scale dataset, this model starts with
very few labeled examples. The script refuses to train (and says so clearly)
until there's a reasonable minimum of both outcome classes, rather than
silently producing a model that's just memorizing noise.
"""
import os
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

from app.database import SessionLocal
from app.models import ReconciliationMatch, SalesInvoice, GatewaySettlement, MatchStatus
from app.agent.orchestrator import _prefetch_contract_context, _prefetch_comms_context

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "exception_classifier.joblib")

FEATURE_COLUMNS = [
    "amount", "mdr_fee_ratio", "hour_of_day", "day_of_week",
    "merchant_encoded", "has_contract_context", "has_comms_context",
]

MIN_SAMPLES = 10
MIN_PER_CLASS = 3


def build_training_frame(db) -> pd.DataFrame:
    matches = (
        db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.match_stage == "exception")
        .filter(ReconciliationMatch.status.in_([MatchStatus.AGENT_RESOLVED, MatchStatus.ESCALATED]))
        .all()
    )

    settlements_by_order = {s.order_id: s for s in db.query(GatewaySettlement).all()}

    rows = []
    for match in matches:
        invoice = db.query(SalesInvoice).filter(SalesInvoice.id == match.sales_invoice_id).first()
        if not invoice:
            continue
        settlement = settlements_by_order.get(match.order_id)
        mdr_fee_ratio = (settlement.mdr_fee / invoice.amount) if (settlement and invoice.amount) else 0.0

        contract_context = _prefetch_contract_context(db, invoice.merchant_id)
        comms_context = _prefetch_comms_context(db, match.order_id)

        rows.append({
            "order_id": match.order_id,
            "merchant_id": invoice.merchant_id,
            "amount": invoice.amount,
            "mdr_fee_ratio": mdr_fee_ratio,
            "hour_of_day": invoice.created_at.hour,
            "day_of_week": invoice.created_at.weekday(),
            "has_contract_context": 1 if contract_context else 0,
            "has_comms_context": 1 if comms_context else 0,
            "label": 1 if match.status == MatchStatus.AGENT_RESOLVED else 0,
        })

    return pd.DataFrame(rows)


def train():
    db = SessionLocal()
    try:
        df = build_training_frame(db)
    finally:
        db.close()

    if len(df) < MIN_SAMPLES:
        print(
            f"Only {len(df)} labeled exceptions found (need at least {MIN_SAMPLES}). "
            "Run /reconcile/run and /agent/resolve-all on more data first, then retrain. "
            "Skipping training for now."
        )
        return

    class_counts = df["label"].value_counts()
    if len(class_counts) < 2 or class_counts.min() < MIN_PER_CLASS:
        print(
            f"Not enough examples of both outcomes yet (counts: {class_counts.to_dict()}). "
            f"Need at least {MIN_PER_CLASS} of each (AGENT_RESOLVED=1 and ESCALATED=0). "
            "Skipping training for now -- predictions will fall back to 'unknown' until "
            "there's enough history."
        )
        return

    merchant_encoder = LabelEncoder()
    df["merchant_encoded"] = merchant_encoder.fit_transform(df["merchant_id"])

    X = df[FEATURE_COLUMNS]
    y = df["label"]

    if len(df) >= 20:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
        eval_note = "held-out test set"
    else:
        # Too few rows for a meaningful holdout split -- train on everything
        # and report training-set fit, honestly labeled as such below rather
        # than presenting it as a real generalization estimate.
        X_train, X_test, y_train, y_test = X, X, y, y
        eval_note = "training set (too few rows for a real holdout)"

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump({
        "model": model,
        "merchant_encoder": merchant_encoder,
        "feature_columns": FEATURE_COLUMNS,
        "trained_on_n_rows": len(df),
        "class_counts": class_counts.to_dict(),
        "eval_accuracy": round(acc, 3),
        "eval_note": eval_note,
    }, MODEL_PATH)

    print(f"Trained exception-routing classifier on {len(df)} labeled exceptions.")
    print(f"Class balance (1=AGENT_RESOLVED, 0=ESCALATED): {class_counts.to_dict()}")
    print(f"Accuracy on {eval_note}: {acc:.1%}")
    print(f"Model saved to: {MODEL_PATH}")


if __name__ == "__main__":
    train()