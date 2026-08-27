# LedgerGuard

Hybrid deterministic-agentic 3-way reconciliation. A rule engine resolves
the easy majority of matches instantly; an AI agent (local via Ollama,
Claude as a swappable fallback) is spun up only for the exceptions that
need investigation — reading contract PDFs, searching internal comms, and
checking FX rates before drafting a correction or an inquiry ticket.

## Architecture

```
React (Vite) frontend  →  FastAPI backend  →  Ollama (local LLM + embeddings)
                                ↓
                    Deterministic matching engine (3 stages)
                                ↓ (only exceptions)
                       Agentic resolution layer
                    (contract RAG, comms search, FX lookup)
                                ↓
                          PostgreSQL + pgvector
```

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 18+
- ~8GB free RAM if running a 7B Ollama model locally

## 1. Start infrastructure (Postgres + Ollama)

```bash
docker compose up -d
```

Pull the models once the Ollama container is up:

```bash
docker exec -it ledgerguard_ollama ollama pull qwen2.5:7b-instruct
docker exec -it ledgerguard_ollama ollama pull nomic-embed-text
```

## 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # defaults already point at local Postgres + Ollama
```

Enable pgvector extension (one-time, if the image doesn't do it automatically):

```bash
docker exec -it ledgerguard_db psql -U ledgerguard -d ledgerguard -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Generate synthetic data (creates tables, seeds contracts + transactions):

```bash
python -m app.data_generator
```

Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/health` → `{"status": "ok"}`

## 3. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`.

## 4. Demo flow

1. Click **Run Deterministic Reconciliation** — watch exact/fuzzy-MDR/split-payment
   counts populate. This is your headline number: what % resolved *without* touching
   the LLM at all.
2. Open the **Exception Queue** — these are the cases the rule engine couldn't
   explain.
3. Click **Investigate with Agent** on one — this triggers the tool-calling loop
   (contract RAG → comms search → FX lookup → write_correction).
4. Click **View Trace** — shows every tool call, its input/output, and the
   agent's reasoning at each step. This auditability is the differentiator:
   nothing is a black box.
5. Check **Auto-Drafted Inquiry Tickets** for cases the agent couldn't resolve
   with evidence — it drafts a structured ticket instead of guessing.

## Swapping LLM providers

Everything routes through `backend/app/llm_provider.py`. To fall back to
Claude if Ollama's tool-calling proves unreliable during demo prep, set in
`backend/.env`:

```
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

No other code changes needed — the agent orchestrator and tools call
`get_llm()` and never know which backend is behind it. Note: embeddings for
contract RAG stay on Ollama's `nomic-embed-text` either way (see
`ClaudeLLM.embed`), so keep the Ollama container running even if chat falls
back to Claude.

## Known rough edges to test before demo day

- Small local models can occasionally skip a tool call or malform JSON
  arguments — the orchestrator nudges once and otherwise degrades gracefully
  to `ESCALATED` rather than crashing. Test your specific model against a
  few exceptions ahead of time.
- `MAX_STEPS` in `agent/orchestrator.py` caps the investigation loop at 6
  steps to avoid runaway costs/latency during a live demo — raise it if a
  case needs more tool calls to resolve.
- The split-payment matcher (`_find_summing_subset`) is brute-force over a
  narrow date window, fine at demo scale (~100 transactions) but not
  optimized for production volume.
