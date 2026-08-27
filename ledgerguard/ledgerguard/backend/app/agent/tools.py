"""
Tools available to the exception-resolution agent. Each tool returns a
plain dict -- these get logged verbatim into AgentTrace so every decision
is auditable after the fact.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.models import ContractChunk, CommsMessage, ReconciliationMatch, MatchStatus
from app.llm_provider import get_llm

# Mock static FX table for demo purposes -- swap for a real FX API if desired
MOCK_FX_RATES = {
    ("USD", "INR"): 83.20,
    ("EUR", "INR"): 90.10,
    ("GBP", "INR"): 105.40,
}


def contract_rag_search(db: Session, merchant_id: str, query: str, top_k: int = 3) -> dict:
    """Semantic search over chunked contract PDFs for a merchant's agreed MDR/fee terms."""
    if not merchant_id or not query:
        return {
            "tool": "contract_rag",
            "error": "Both merchant_id and query are required. Please call this tool again with both arguments filled in.",
        }

    llm = get_llm()
    query_embedding = llm.embed(query)

    if not query_embedding:
        return {"tool": "contract_rag", "query": query, "error": "Embedding generation failed; try a different query."}

    # pgvector cosine distance search
    rows = db.execute(
        sql_text(
            """
            SELECT chunk_text, source_file, 1 - (embedding <=> :qvec) AS similarity
            FROM contract_chunks
            WHERE merchant_id = :merchant_id
            ORDER BY embedding <=> :qvec
            LIMIT :k
            """
        ),
        {"qvec": str(query_embedding), "merchant_id": merchant_id, "k": top_k},
    ).fetchall()

    results = [
        {"text": r[0], "source_file": r[1], "similarity": round(float(r[2]), 3)}
        for r in rows
    ]
    return {"tool": "contract_rag", "query": query, "results": results}


def comms_search(db: Session, order_id: str, keyword: str | None = None) -> dict:
    """Searches mock email/Slack messages for context on a given order
    (e.g. a refund explanation, a manual discount approval)."""
    if not order_id:
        return {"tool": "comms_search", "error": "order_id is required. Please call this tool again with order_id filled in."}

    q = db.query(CommsMessage).filter(CommsMessage.order_id == order_id)
    messages = q.all()
    if keyword:
        messages = [m for m in messages if keyword.lower() in m.text.lower()]

    results = [
        {"channel": m.channel, "sender": m.sender, "text": m.text, "sent_at": str(m.sent_at)}
        for m in messages
    ]
    return {"tool": "comms_search", "order_id": order_id, "results": results}


def fx_lookup(from_currency: str, to_currency: str) -> dict:
    rate = MOCK_FX_RATES.get((from_currency, to_currency))
    return {
        "tool": "fx_lookup",
        "from": from_currency,
        "to": to_currency,
        "rate": rate,
        "found": rate is not None,
    }


def write_correction(db: Session, match_id: str, resolution_note: str, resolved: bool) -> dict:
    """Writes the agent's final decision back to the ledger."""
    match = db.query(ReconciliationMatch).filter(ReconciliationMatch.id == match_id).first()
    if not match:
        return {"tool": "write_correction", "success": False, "error": "match not found"}

    match.status = MatchStatus.AGENT_RESOLVED if resolved else MatchStatus.ESCALATED
    match.variance_reason = resolution_note[:255]
    db.commit()
    return {"tool": "write_correction", "success": True, "new_status": match.status.value}


# Tool schema definitions passed to the LLM (Ollama-compatible function format)
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "contract_rag_search",
            "description": "Search the merchant's contract PDF for agreed MDR/fee/rate clauses relevant to a discrepancy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_id": {"type": "string"},
                    "query": {"type": "string", "description": "what to look for, e.g. 'MDR rate for UPI transactions'"},
                },
                "required": ["merchant_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comms_search",
            "description": "Search internal email/Slack messages related to an order for context (refunds, manual approvals).",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "keyword": {"type": "string"},
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fx_lookup",
            "description": "Look up the FX conversion rate between two currencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_currency": {"type": "string"},
                    "to_currency": {"type": "string"},
                },
                "required": ["from_currency", "to_currency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_correction",
            "description": "Finalize the investigation: write the resolution back to the ledger, or mark unresolved for escalation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_id": {"type": "string"},
                    "resolution_note": {"type": "string"},
                    "resolved": {"type": "boolean"},
                },
                "required": ["match_id", "resolution_note", "resolved"],
            },
        },
    },
]