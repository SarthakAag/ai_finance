from fastapi import FastAPI, Depends, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

import time
import statistics


from app.database import Base, engine, get_db

from app.models import (
    ReconciliationMatch,
    AgentTrace,
    InquiryTicket,
    MatchStatus,
    SalesInvoice,
    GatewaySettlement,
    BankCredit,
)

from app.schemas import MatchOut, TraceOut, TicketOut

from app.matching_engine import run_reconciliation

from app.agent.orchestrator import resolve_exception

from app.ingestion.file_upload import (
    UploadValidationError,
    process_upload,
)

from app.ingestion.normalizer import NormalizedTransaction
from app.ingestion.persistence import persist_transactions
from datetime import datetime


# ============================================================================
# APPLICATION
# ============================================================================

app = FastAPI(
    title="LedgerGuard API",
    version="2.0.0",
    description=(
        "AI-assisted financial reconciliation platform with "
        "multi-source file ingestion, deterministic matching, "
        "ML resolution, AI investigation, and human escalation."
    ),
)


# ============================================================================
# CORS
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
def on_startup():
    """
    Create database tables when the application starts.
    """
    Base.metadata.create_all(bind=engine)


# ============================================================================
# HEALTH
# ============================================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ledgerguard",
        "version": "2.0.0",
    }


# ============================================================================
# WORKSPACE RESET
# ============================================================================

@app.post("/workspace/reset")
def reset_workspace(
    db: Session = Depends(get_db),
):
    """
    Start a completely fresh reconciliation workspace.

    This removes:
        - reconciliation matches
        - AI traces
        - inquiry tickets
        - bank records
        - gateway records
        - invoice records

    Physical uploaded files are also removed.

    Uploading a file does NOT automatically reset the database.
    """

    from pathlib import Path

    upload_root = (
        Path(__file__).resolve().parents[2]
        / "uploads"
    )

    deleted = {}

    try:
        # -------------------------------------------------------------
        # Delete child records first.
        # -------------------------------------------------------------

        deleted["agent_traces"] = db.query(
            AgentTrace
        ).delete(
            synchronize_session=False
        )

        deleted["inquiry_tickets"] = db.query(
            InquiryTicket
        ).delete(
            synchronize_session=False
        )

        deleted["reconciliation_matches"] = db.query(
            ReconciliationMatch
        ).delete(
            synchronize_session=False
        )

        # -------------------------------------------------------------
        # Delete source records.
        # -------------------------------------------------------------

        deleted["bank_credits"] = db.query(
            BankCredit
        ).delete(
            synchronize_session=False
        )

        deleted["gateway_settlements"] = db.query(
            GatewaySettlement
        ).delete(
            synchronize_session=False
        )

        deleted["sales_invoices"] = db.query(
            SalesInvoice
        ).delete(
            synchronize_session=False
        )

        db.commit()

        # -------------------------------------------------------------
        # Remove physical uploaded files.
        # -------------------------------------------------------------

        removed_files = 0

        source_directories = {
            "bank": upload_root / "bank",
            "razorpay": upload_root / "razorpay",
            "ledger": upload_root / "ledger",
            "invoice": upload_root / "invoices",
            "documents": upload_root / "documents",
        }

        for directory in source_directories.values():

            if not directory.exists():
                continue

            for file_path in directory.iterdir():

                if not file_path.is_file():
                    continue

                try:
                    file_path.unlink()
                    removed_files += 1

                except OSError:
                    # Database reset has already succeeded.
                    continue

        return {
            "success": True,
            "message": "LedgerGuard workspace reset successfully.",
            "deleted": deleted,
            "uploaded_files_removed": removed_files,
        }

    except Exception as exc:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset LedgerGuard workspace: {exc}",
        )


# ============================================================================
# FILE UPLOAD / INGESTION
# ============================================================================

@app.post("/uploads")
async def upload_payment_file(
    file: UploadFile = File(...),
    source: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload, normalize, validate and persist a LedgerGuard file."""

    start_time = time.time()
    filename = file.filename or "uploaded_file"

    allowed_sources = {
        "bank",
        "razorpay",
        "ledger",
        "invoice",
    }

    if source:
        source = source.strip().lower()
        if source not in allowed_sources:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid source '{source}'. "
                    f"Allowed values: {sorted(allowed_sources)}"
                ),
            )

    print(
        f"[UPLOAD] START file={filename} source={source}",
        flush=True,
    )

    try:
        # Existing parser/normalizer.
        result = await process_upload(
            upload_file=file,
            source_override=source,
        )

        detected_source = (
            result.get("source") or source
        )
        detected_source = (
            str(detected_source).strip().lower()
            if detected_source
            else None
        )

        if detected_source not in allowed_sources:
            raise HTTPException(
                status_code=400,
                detail="Could not determine a supported upload source.",
            )

        # process_upload returns JSON-safe transaction dictionaries.
        # Convert them back to NormalizedTransaction objects for persistence.
        transactions = []

        for item in result.get("transactions", []):
            if not isinstance(item, dict):
                continue

            transaction_date = item.get("transaction_date")

            if isinstance(transaction_date, str):
                try:
                    transaction_date = datetime.fromisoformat(
                        transaction_date.replace("Z", "+00:00")
                    )
                except ValueError:
                    transaction_date = None
            elif transaction_date is not None and not isinstance(
                transaction_date, datetime
            ):
                transaction_date = None

            transactions.append(
                NormalizedTransaction(
                    source=str(
                        item.get("source") or detected_source
                    ).lower(),
                    transaction_id=item.get("transaction_id"),
                    invoice_id=item.get("invoice_id"),
                    order_id=item.get("order_id"),
                    settlement_id=item.get("settlement_id"),
                    merchant_id=item.get("merchant_id"),
                    amount=item.get("amount"),
                    gross_amount=item.get("gross_amount"),
                    net_amount=item.get("net_amount"),
                    fee=item.get("fee"),
                    currency=item.get("currency") or "INR",
                    transaction_date=transaction_date,
                    narration=item.get("narration"),
                    raw_data=item.get("raw_data"),
                )
            )

        persistence = {
            "source": detected_source,
            "received": len(transactions),
            "created": 0,
            "existing": 0,
            "errors": [],
        }

        if transactions:
            print(
                f"[UPLOAD] Persisting {len(transactions)} "
                f"transactions source={detected_source}",
                flush=True,
            )

            persistence = persist_transactions(
                db=db,
                source=detected_source,
                transactions=transactions,
            )

            print(
                f"[UPLOAD] PERSISTENCE RESULT {persistence}",
                flush=True,
            )

        result["persistence"] = persistence

        elapsed = round(
            time.time() - start_time,
            3,
        )

        result["processing_time_seconds"] = elapsed

        print(
            "[UPLOAD] SUCCESS "
            f"file={filename} "
            f"source={detected_source} "
            f"rows={result.get('rows_read', 0)} "
            f"transactions={len(transactions)} "
            f"created={persistence.get('created', 0)} "
            f"existing={persistence.get('existing', 0)} "
            f"time={elapsed}s",
            flush=True,
        )

        return {
            "success": True,
            "message": (
                "File uploaded, processed and stored successfully."
            ),
            **result,
        }

    except UploadValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        print(
            "[UPLOAD] EXCEPTION "
            f"file={filename} "
            f"type={type(exc).__name__} "
            f"error={exc}",
            flush=True,
        )

        import traceback
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to process uploaded file: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    finally:
        try:
            await file.close()
        except Exception:
            pass


# ============================================================================
# LIST UPLOADED FILES
# ============================================================================

@app.get("/uploads")
def list_uploaded_files():
    """
    Return all uploaded payment-related files.
    """

    from pathlib import Path

    upload_root = (
        Path(__file__).resolve().parents[2]
        / "uploads"
    )

    source_directories = {
        "bank": upload_root / "bank",
        "razorpay": upload_root / "razorpay",
        "ledger": upload_root / "ledger",
        "invoice": upload_root / "invoices",
        "documents": upload_root / "documents",
    }

    files = []

    for source, directory in source_directories.items():

        if not directory.exists():
            continue

        for file_path in directory.iterdir():

            if not file_path.is_file():
                continue

            try:

                stat = file_path.stat()

                files.append(
                    {
                        "filename": file_path.name,
                        "source": source,
                        "extension": file_path.suffix.lower(),
                        "size_bytes": stat.st_size,
                        "size_kb": round(
                            stat.st_size / 1024,
                            2,
                        ),
                    }
                )

            except OSError:
                continue

    files.sort(
        key=lambda item: item["filename"]
    )

    return {
        "success": True,
        "count": len(files),
        "files": files,
    }


# ============================================================================
# DETERMINISTIC RECONCILIATION
# ============================================================================

@app.post("/reconcile/run")
def reconcile_run(
    db: Session = Depends(get_db),
):
    """
    Runs deterministic reconciliation.

    Flow:

        Exact Match
             ↓
        MDR Match
             ↓
        Split Payment
             ↓
        Exception
    """

    summary = run_reconciliation(db)

    resolved = (
        summary["exact"]
        + summary["fuzzy_mdr"]
        + summary["split_payment"]
    )

    resolved_pct = (
        round(
            100 * resolved / summary["total"],
            1,
        )
        if summary["total"]
        else 0.0
    )

    return {
        **summary,
        "resolved_without_llm_pct": resolved_pct,
    }




def _resolution_type(match: ReconciliationMatch) -> str | None:
    """Derive resolution type without requiring a model/database column."""
    stage = getattr(match, "match_stage", None)
    reason = getattr(match, "variance_reason", None)

    if stage == "exact":
        return "exact"
    if stage == "fuzzy_mdr" and reason == "mdr_fee":
        return "mdr"
    if reason == "fx_rate":
        return "fx"
    if stage == "split_payment":
        return "split"
    if stage == "ml_ai_review":
        return "ml"
    if stage == "ai_review":
        return "ai"

    # Backward/forward compatibility if the model gains this field later.
    return getattr(match, "resolution_type", None)


def _match_with_financials(db: Session, match: ReconciliationMatch) -> dict:
    """Serialize a reconciliation match together with source amounts.

    ReconciliationMatch stores only foreign-key IDs for invoice/gateway/bank
    records, so the frontend cannot display Expected/Actual unless we join
    those source records here.
    """

    invoice = None
    gateway = None
    bank = None

    if match.sales_invoice_id:
        invoice = (
            db.query(SalesInvoice)
            .filter(SalesInvoice.id == match.sales_invoice_id)
            .first()
        )

    if match.gateway_settlement_id:
        gateway = (
            db.query(GatewaySettlement)
            .filter(
                GatewaySettlement.id == match.gateway_settlement_id
            )
            .first()
        )

    if match.bank_credit_id:
        bank = (
            db.query(BankCredit)
            .filter(BankCredit.id == match.bank_credit_id)
            .first()
        )

    expected = (
        float(invoice.amount)
        if invoice is not None and invoice.amount is not None
        else None
    )

    gateway_amount = (
        float(gateway.net_amount)
        if gateway is not None and gateway.net_amount is not None
        else None
    )

    bank_amount = (
        float(bank.amount)
        if bank is not None and bank.amount is not None
        else None
    )

    actual = (
        bank_amount
        if bank_amount is not None
        else gateway_amount
    )

    variance = match.variance_amount

    # Older rows may have a NULL/zero variance even though source amounts
    # are available. Calculate it for the UI without modifying the database.
    if expected is not None and actual is not None:
        calculated_variance = round(expected - actual, 2)
        if variance is None or (variance == 0 and calculated_variance != 0):
            variance = calculated_variance

    status = (
        match.status.value
        if hasattr(match.status, "value")
        else str(match.status)
    )

    return {
        "id": match.id,
        "order_id": match.order_id,
        "sales_invoice_id": match.sales_invoice_id,
        "gateway_settlement_id": match.gateway_settlement_id,
        "bank_credit_id": match.bank_credit_id,
        "status": status,
        "match_stage": match.match_stage,
        "expected_amount": expected,
        "actual_amount": actual,
        "invoice_amount": expected,
        "gateway_net_amount": gateway_amount,
        "gateway_amount": gateway_amount,
        "bank_amount": bank_amount,
        "net_amount": gateway_amount,
        "variance_amount": variance,
        "variance_reason": match.variance_reason,
        "confidence": match.confidence,
        "resolution_type": _resolution_type(match),
        "created_at": (
            match.created_at.isoformat()
            if match.created_at
            else None
        ),
    }


# ============================================================================
# RECONCILIATION MATCHES
# ============================================================================

@app.get("/reconcile/matches")
def list_matches(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List reconciliation matches with invoice/gateway/bank amounts."""

    q = db.query(ReconciliationMatch)

    if status:
        try:
            status_enum = MatchStatus(str(status).upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reconciliation status: {status}",
            )

        q = q.filter(
            ReconciliationMatch.status == status_enum
        )

    matches = (
        q.order_by(
            ReconciliationMatch.created_at.desc()
        )
        .limit(200)
        .all()
    )

    return [
        _match_with_financials(db, match)
        for match in matches
    ]


# ============================================================================
# EXCEPTIONS
# ============================================================================

@app.get("/reconcile/exceptions")
def list_exceptions(
    db: Session = Depends(get_db),
):
    """Return unresolved exception rows with complete financial values."""

    matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status == MatchStatus.PENDING
        )
        .filter(
            ReconciliationMatch.match_stage == "exception"
        )
        .order_by(
            ReconciliationMatch.created_at.desc()
        )
        .all()
    )

    return [
        _match_with_financials(db, match)
        for match in matches
    ]


# ============================================================================
# AI AGENT
# ============================================================================

@app.post("/agent/resolve/{match_id}")
def agent_resolve(
    match_id: str,
    db: Session = Depends(get_db),
):
    """
    Invoke the AI agent for one AI-review or unresolved exception.
    """

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id == match_id
        )
        .first()
    )

    if not match:

        raise HTTPException(
            status_code=404,
            detail="match not found",
        )

    result = resolve_exception(
        db,
        match_id,
    )

    return result


# ============================================================================
# AI RESOLVE ALL
# ============================================================================

@app.post("/agent/resolve-all")
def agent_resolve_all(
    db: Session = Depends(get_db),
):
    """
    Run the AI agent over every unresolved exception.
    """

    exceptions = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.PENDING
        )
        .filter(
            ReconciliationMatch.match_stage.in_(
                ["ai_review", "exception"]
            )
        )
        .order_by(
            ReconciliationMatch.created_at.asc()
        )
        .all()
    )

    results = []

    for i, match in enumerate(exceptions):

        if i > 0:
            time.sleep(5)

        try:

            results.append(
                resolve_exception(
                    db,
                    match.id,
                )
            )

        except Exception as exc:

            results.append(
                {
                    "match_id": match.id,
                    "error": str(exc),
                }
            )

    return {
        "processed": len(results),
        "results": results,
    }


# ============================================================================
# AGENT TRACE
# ============================================================================

@app.get(
    "/agent/trace/{match_id}",
    response_model=list[TraceOut],
)
def agent_trace(
    match_id: str,
    db: Session = Depends(get_db),
):
    """
    Return complete AI investigation trace.
    """

    return (
        db.query(AgentTrace)
        .filter(
            AgentTrace.reconciliation_match_id
            == match_id
        )
        .order_by(
            AgentTrace.step_number
        )
        .all()
    )


# ============================================================================
# LEGACY HUMAN INQUIRY TICKETS
# ============================================================================

@app.get(
    "/tickets",
    response_model=list[TicketOut],
)
def list_tickets(
    resolved: bool | None = None,
    db: Session = Depends(get_db),
):
    """
    Legacy ticket endpoint.
    """

    q = db.query(
        InquiryTicket
    )

    if resolved is not None:

        q = q.filter(
            InquiryTicket.resolved
            == resolved
        )

    return (
        q.order_by(
            InquiryTicket.created_at.desc()
        )
        .all()
    )


# ============================================================================
# LEGACY TICKET RESOLUTION
# ============================================================================

class TicketResolveRequest(BaseModel):
    resolution_note: str | None = None


@app.patch(
    "/tickets/{ticket_id}/resolve"
)
def resolve_ticket(
    ticket_id: str,
    body: TicketResolveRequest,
    db: Session = Depends(get_db),
):
    """
    Legacy manual ticket resolution.
    """

    ticket = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.id == ticket_id
        )
        .first()
    )

    if not ticket:

        raise HTTPException(
            status_code=404,
            detail="ticket not found",
        )

    ticket.resolved = True

    ticket.resolution_note = (
        body.resolution_note
    )

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    if match:

        match.status = (
            MatchStatus.AGENT_RESOLVED
        )

        match.variance_reason = (
            "Manually resolved: "
            f"{body.resolution_note or 'no note provided'}"
        )[:255]

    db.commit()

    return {
        "ticket_id": ticket_id,
        "resolved": True,
        "resolution_note": body.resolution_note,
    }


# ============================================================================
# RISK SIGNALS
# ============================================================================

@app.get(
    "/dashboard/risk-signals"
)
def risk_signals(
    db: Session = Depends(get_db),
):
    """
    Detection layer beyond simple reconciliation.
    """

    invoices = (
        db.query(SalesInvoice)
        .all()
    )

    by_merchant: dict[str, list] = {}

    for invoice in invoices:

        by_merchant.setdefault(
            invoice.merchant_id,
            [],
        ).append(invoice)

    outliers = []

    for merchant_id, merchant_invoices in by_merchant.items():

        amounts = [
            invoice.amount
            for invoice in merchant_invoices
            if invoice.amount is not None
        ]

        if len(amounts) < 3:
            continue

        mean = statistics.mean(
            amounts
        )

        stdev = (
            statistics.pstdev(
                amounts
            )
            or 1
        )

        for invoice in merchant_invoices:

            if invoice.amount is None:
                continue

            z = (
                invoice.amount - mean
            ) / stdev

            if z > 2:

                outliers.append(
                    {
                        "order_id": invoice.order_id,
                        "merchant_id": merchant_id,
                        "amount": round(
                            invoice.amount,
                            2,
                        ),
                        "merchant_avg": round(
                            mean,
                            2,
                        ),
                        "times_above_average": (
                            round(
                                invoice.amount
                                / mean,
                                1,
                            )
                            if mean
                            else None
                        ),
                    }
                )

    outliers.sort(
        key=lambda item: -(
            item[
                "times_above_average"
            ]
            or 0
        )
    )

    top_variance = (
        db.query(
            ReconciliationMatch
        )
        .filter(
            ReconciliationMatch.variance_amount.isnot(
                None
            )
        )
        .filter(
            ReconciliationMatch.variance_amount
            != 0
        )
        .order_by(
            func.abs(
                ReconciliationMatch.variance_amount
            ).desc()
        )
        .limit(5)
        .all()
    )

    oldest_unresolved = (
        db.query(
            ReconciliationMatch
        )
        .filter(
            ReconciliationMatch.status
            == MatchStatus.PENDING
        )
        .order_by(
            ReconciliationMatch.created_at
        )
        .limit(5)
        .all()
    )

    return {
        "unusually_large_transactions": (
            outliers[:5]
        ),

        "top_variance_cases": [
            {
                "order_id": match.order_id,
                "variance_amount": (
                    match.variance_amount
                ),
                "reason": (
                    match.variance_reason
                ),
                "stage": (
                    match.match_stage
                ),
            }
            for match in top_variance
        ],

        "oldest_unresolved": [
            {
                "order_id": match.order_id,
                "created_at": str(
                    match.created_at
                ),
                "stage": (
                    match.match_stage
                ),
            }
            for match in oldest_unresolved
        ],
    }


# ============================================================================
# AI COST COMPARISON
# ============================================================================

@app.get(
    "/dashboard/cost-comparison"
)
def cost_comparison(
    db: Session = Depends(get_db),
):
    """
    Shows how many transactions were routed
    to the AI agent instead of every transaction
    being sent to an LLM.
    """

    total_invoices = (
        db.query(
            func.count(
                SalesInvoice.id
            )
        )
        .scalar()
        or 0
    )

    exceptions_investigated = (
        db.query(
            func.count(
                func.distinct(
                    AgentTrace.reconciliation_match_id
                )
            )
        )
        .scalar()
        or 0
    )

    total_tokens = (
        db.query(
            func.coalesce(
                func.sum(
                    AgentTrace.tokens_used
                ),
                0,
            )
        )
        .scalar()
        or 0
    )

    total_agent_calls = (
        db.query(
            func.count(
                AgentTrace.id
            )
        )
        .scalar()
        or 0
    )

    avg_tokens_per_case = (
        round(
            total_tokens
            / exceptions_investigated,
            1,
        )
        if exceptions_investigated
        else 0
    )

    est_cost_per_1k_tokens = 0.0003

    actual_cost = round(
        (
            total_tokens
            / 1000
        )
        * est_cost_per_1k_tokens,
        4,
    )

    projected_cost_if_all_llm = (
        round(
            (
                avg_tokens_per_case
                * total_invoices
                / 1000
            )
            * est_cost_per_1k_tokens,
            4,
        )
        if avg_tokens_per_case
        else 0
    )

    return {
        "total_invoices": total_invoices,

        "exceptions_investigated_by_agent": (
            exceptions_investigated
        ),

        "pct_routed_to_llm": (
            round(
                100
                * exceptions_investigated
                / total_invoices,
                1,
            )
            if total_invoices
            else 0
        ),

        "total_agent_llm_calls": (
            total_agent_calls
        ),

        "total_tokens_used": (
            total_tokens
        ),

        "avg_tokens_per_investigated_case": (
            avg_tokens_per_case
        ),

        "actual_estimated_cost_usd": (
            actual_cost
        ),

        "projected_cost_if_every_invoice_hit_llm": (
            projected_cost_if_all_llm
        ),

        "note": (
            "Cost figures are illustrative "
            "estimates based on token counts, "
            "not real billing data."
        ),
    }


# ============================================================================
# DASHBOARD STATS
# ============================================================================

@app.get(
    "/dashboard/stats"
)
def dashboard_stats(
    db: Session = Depends(get_db),
):
    """Return live dashboard statistics directly from the database."""

    total = (
        db.query(
            func.count(SalesInvoice.id)
        )
        .scalar()
        or 0
    )

    by_status = dict(
        db.query(
            ReconciliationMatch.status,
            func.count(ReconciliationMatch.id),
        )
        .group_by(
            ReconciliationMatch.status
        )
        .all()
    )

    by_stage = dict(
        db.query(
            ReconciliationMatch.match_stage,
            func.count(ReconciliationMatch.id),
        )
        .group_by(
            ReconciliationMatch.match_stage
        )
        .all()
    )

    def enum_key(value):
        return (
            value.value
            if hasattr(value, "value")
            else value
        )

    status_counts = {
        enum_key(key): value
        for key, value in by_status.items()
        if key is not None
    }

    stage_counts = {
        enum_key(key): value
        for key, value in by_stage.items()
        if key is not None
    }

    reconciled = (
        status_counts.get("RECONCILED", 0)
        + status_counts.get("AGENT_RESOLVED", 0)
    )

    # Review stages are stored on ReconciliationMatch.match_stage.
    # ML/AI rows intentionally stay PENDING while waiting for review,
    # so they must not be inferred from status alone.
    ml_review = (
        stage_counts.get("ml_ai_review", 0)
        + stage_counts.get("ml_review", 0)
    )
    ai_review = stage_counts.get("ai_review", 0)

    # A pending ML/AI review is not a human-review ticket. Human review
    # begins only when the AI layer escalates the case.
    exceptions = stage_counts.get("exception", 0)
    pending = status_counts.get("PENDING", 0)
    escalated = status_counts.get("ESCALATED", 0)

    return {
        "success": True,
        "total_invoices": total,
        "by_status": status_counts,
        "by_stage": stage_counts,

        # Compatibility fields for the React dashboard.
        "total": total,
        "reconciled": reconciled,
        "exceptions": exceptions,
        "pending": pending,
        "ml_review": ml_review,
        "ai_review": ai_review,
        "escalated": escalated,
        "human_review": escalated,
    }


# ============================================================================
# HUMAN REVIEW SUMMARY
# ============================================================================

class HumanReviewResolveRequest(BaseModel):
    resolution_note: str


class HumanReviewRejectRequest(BaseModel):
    resolution_note: str


@app.get(
    "/review/summary"
)
def review_summary(
    db: Session = Depends(get_db),
):
    """
    Summary used by the human-review dashboard.
    """

    open_tickets = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.resolved.is_(False)
        )
        .count()
    )

    resolved_tickets = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.resolved.is_(True)
        )
        .count()
    )

    escalated_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.ESCALATED
        )
        .count()
    )

    agent_resolved_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.AGENT_RESOLVED
        )
        .count()
    )

    reconciled_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.RECONCILED
        )
        .count()
    )

    return {
        "success": True,
        "open_tickets": open_tickets,
        "resolved_tickets": resolved_tickets,
        "escalated_matches": escalated_matches,
        "agent_resolved_matches": agent_resolved_matches,
        "reconciled_matches": reconciled_matches,
    }


# ============================================================================
# HUMAN REVIEW TICKETS
# ============================================================================

@app.get(
    "/review/tickets"
)
def review_tickets(
    db: Session = Depends(get_db),
):
    """
    Return unresolved tickets for the human-review dashboard.
    """

    tickets = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.resolved.is_(False)
        )
        .order_by(
            InquiryTicket.created_at.desc()
        )
        .all()
    )

    result = []

    for ticket in tickets:

        match = (
            db.query(ReconciliationMatch)
            .filter(
                ReconciliationMatch.id
                == ticket.reconciliation_match_id
            )
            .first()
        )

        result.append(
            {
                "id": ticket.id,

                "subject": ticket.subject,

                "reconciliation_match_id": (
                    ticket.reconciliation_match_id
                ),

                "order_id": (
                    match.order_id
                    if match
                    else None
                ),

                "status": (
                    match.status.value
                    if match
                    and hasattr(
                        match.status,
                        "value",
                    )
                    else str(
                        match.status
                    )
                    if match
                    else None
                ),

                "expected_amount": (
                    ticket.expected_amount
                ),

                "actual_amount": (
                    ticket.actual_amount
                ),

                "missing_fields": (
                    ticket.missing_fields
                    or []
                ),

                "created_at": (
                    ticket.created_at.isoformat()
                    if ticket.created_at
                    else None
                ),
            }
        )

    return {
        "success": True,
        "count": len(result),
        "tickets": result,
    }


# ============================================================================
# HUMAN REVIEW TICKET DETAIL
# ============================================================================

@app.get(
    "/review/tickets/{ticket_id}"
)
def review_ticket_detail(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    Return complete evidence for a human reviewer.
    """

    ticket = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.id == ticket_id
        )
        .first()
    )

    if not ticket:

        raise HTTPException(
            status_code=404,
            detail="review ticket not found",
        )

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    if not match:

        raise HTTPException(
            status_code=404,
            detail=(
                "associated reconciliation "
                "match not found"
            ),
        )

    invoice = None
    gateway = None
    bank = None

    if match.sales_invoice_id:

        invoice = (
            db.query(SalesInvoice)
            .filter(
                SalesInvoice.id
                == match.sales_invoice_id
            )
            .first()
        )

    if match.gateway_settlement_id:

        gateway = (
            db.query(GatewaySettlement)
            .filter(
                GatewaySettlement.id
                == match.gateway_settlement_id
            )
            .first()
        )

    if match.bank_credit_id:

        bank = (
            db.query(BankCredit)
            .filter(
                BankCredit.id
                == match.bank_credit_id
            )
            .first()
        )

    traces = (
        db.query(AgentTrace)
        .filter(
            AgentTrace.reconciliation_match_id
            == match.id
        )
        .order_by(
            AgentTrace.step_number.asc(),
            AgentTrace.created_at.asc(),
        )
        .all()
    )

    return {
        "success": True,

        "ticket": {
            "id": ticket.id,
            "subject": ticket.subject,
            "body": ticket.body,

            "expected_amount": (
                ticket.expected_amount
            ),

            "actual_amount": (
                ticket.actual_amount
            ),

            "missing_fields": (
                ticket.missing_fields
                or []
            ),

            "resolved": ticket.resolved,

            "resolution_note": (
                ticket.resolution_note
            ),

            "created_at": (
                ticket.created_at.isoformat()
                if ticket.created_at
                else None
            ),
        },

        "match": {
            "id": match.id,
            "order_id": match.order_id,

            "status": (
                match.status.value
                if hasattr(
                    match.status,
                    "value",
                )
                else str(match.status)
            ),

            "match_stage": match.match_stage,

            "variance_amount": (
                match.variance_amount
            ),

            "variance_reason": (
                match.variance_reason
            ),

            "confidence": match.confidence,

            "created_at": (
                match.created_at.isoformat()
                if match.created_at
                else None
            ),
        },

        "invoice": (
            {
                "id": invoice.id,

                "invoice_id": (
                    invoice.invoice_id
                ),

                "order_id": invoice.order_id,

                "merchant_id": (
                    invoice.merchant_id
                ),

                "amount": invoice.amount,

                "currency": invoice.currency,

                "status": (
                    invoice.status.value
                    if hasattr(
                        invoice.status,
                        "value",
                    )
                    else str(
                        invoice.status
                    )
                ),

                "created_at": (
                    invoice.created_at.isoformat()
                    if invoice.created_at
                    else None
                ),
            }
            if invoice
            else None
        ),

        "gateway": (
            {
                "id": gateway.id,

                "settlement_id": (
                    gateway.settlement_id
                ),

                "order_id": gateway.order_id,

                "merchant_id": (
                    gateway.merchant_id
                ),

                "gross_amount": (
                    gateway.gross_amount
                ),

                "mdr_fee": gateway.mdr_fee,

                "net_amount": gateway.net_amount,

                "currency": gateway.currency,

                "settled_at": (
                    gateway.settled_at.isoformat()
                    if gateway.settled_at
                    else None
                ),
            }
            if gateway
            else None
        ),

        "bank": (
            {
                "id": bank.id,

                "txn_ref": bank.txn_ref,

                "order_id": bank.order_id,

                "amount": bank.amount,

                "currency": bank.currency,

                "credited_at": (
                    bank.credited_at.isoformat()
                    if bank.credited_at
                    else None
                ),

                "narration": bank.narration,
            }
            if bank
            else None
        ),

        "agent_traces": [
            {
                "id": trace.id,

                "step_number": (
                    trace.step_number
                ),

                "tool_name": (
                    trace.tool_name
                ),

                "tool_input": (
                    trace.tool_input
                ),

                "tool_output": (
                    trace.tool_output
                ),

                "reasoning": (
                    trace.reasoning
                ),

                "tokens_used": (
                    trace.tokens_used
                ),

                "created_at": (
                    trace.created_at.isoformat()
                    if trace.created_at
                    else None
                ),
            }
            for trace in traces
        ],
    }


# ============================================================================
# HUMAN REVIEW RESOLVE
# ============================================================================

@app.post(
    "/review/tickets/{ticket_id}/resolve"
)
def human_review_resolve(
    ticket_id: str,
    body: HumanReviewResolveRequest,
    db: Session = Depends(get_db),
):
    """
    Human reviewer confirms the final reconciliation.
    """

    note = body.resolution_note.strip()

    if len(note) < 3:

        raise HTTPException(
            status_code=400,
            detail=(
                "resolution_note must contain "
                "at least 3 characters"
            ),
        )

    ticket = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.id == ticket_id
        )
        .first()
    )

    if not ticket:

        raise HTTPException(
            status_code=404,
            detail="review ticket not found",
        )

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    if not match:

        raise HTTPException(
            status_code=404,
            detail=(
                "associated reconciliation "
                "match not found"
            ),
        )

    if ticket.resolved:

        return {
            "success": True,
            "message": "ticket already resolved",
            "ticket_id": ticket.id,
            "match_id": match.id,
            "status": (
                match.status.value
                if hasattr(
                    match.status,
                    "value",
                )
                else str(match.status)
            ),
        }

    ticket.resolved = True

    ticket.resolution_note = note

    match.status = (
        MatchStatus.AGENT_RESOLVED
    )

    match.variance_reason = (
        f"Human review: {note}"
    )[:255]

    db.commit()

    db.refresh(ticket)
    db.refresh(match)

    return {
        "success": True,
        "message": (
            "review ticket resolved successfully"
        ),
        "ticket_id": ticket.id,
        "match_id": match.id,
        "status": match.status.value,
        "resolution_note": (
            ticket.resolution_note
        ),
    }


# ============================================================================
# HUMAN REVIEW REJECT
# ============================================================================

@app.post(
    "/review/tickets/{ticket_id}/reject"
)
def human_review_reject(
    ticket_id: str,
    body: HumanReviewRejectRequest,
    db: Session = Depends(get_db),
):
    """
    Human reviewer rejects the available evidence.

    The ticket remains open and the match remains
    ESCALATED for further investigation.
    """

    note = body.resolution_note.strip()

    if len(note) < 3:

        raise HTTPException(
            status_code=400,
            detail=(
                "resolution_note must contain "
                "at least 3 characters"
            ),
        )

    ticket = (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.id == ticket_id
        )
        .first()
    )

    if not ticket:

        raise HTTPException(
            status_code=404,
            detail="review ticket not found",
        )

    if ticket.resolved:

        raise HTTPException(
            status_code=400,
            detail=(
                "cannot reject an already "
                "resolved ticket"
            ),
        )

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    if not match:

        raise HTTPException(
            status_code=404,
            detail=(
                "associated reconciliation "
                "match not found"
            ),
        )

    ticket.resolution_note = note

    match.status = (
        MatchStatus.ESCALATED
    )

    match.variance_reason = (
        f"Human review: {note}"
    )[:255]

    db.commit()

    return {
        "success": True,
        "message": (
            "ticket remains open for "
            "further investigation"
        ),
        "ticket_id": ticket.id,
        "match_id": match.id,
        "status": match.status.value,
        "resolution_note": note,
    }