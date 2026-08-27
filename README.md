# 🛡️ LedgerGuard

## AI-Powered Financial Reconciliation & Exception Investigation Platform

> **Reconcile faster. Investigate smarter. Escalate safely.**

LedgerGuard is an AI-assisted financial reconciliation platform that automates the comparison of **sales invoices, payment-gateway settlements, and bank credits**.

It combines a **deterministic reconciliation engine**, **MDR/FX tolerance matching**, **split-payment detection**, **financial variance analysis**, **AI-powered exception investigation**, **RAG/evidence retrieval**, and **human-in-the-loop escalation** into a single workflow.

### Core Principle

```text
Financial Data
      │
      ▼
Deterministic Reconciliation
      │
      ├── Exact Match
      ├── MDR / FX Match
      └── Split Payment
      │
      ▼
Unresolved Exceptions
      │
      ▼
AI Investigation
      │
      ├── Resolved
      └── Escalated
             │
             ▼
       Human Review
```

---

## 🚀 Why LedgerGuard?

Financial reconciliation often requires finance teams to compare multiple spreadsheets and systems:

- Sales invoices
- Payment gateway settlements
- Bank statements
- MDR / processing fees
- Partial and split payments
- FX differences
- Missing transaction references
- Settlement discrepancies

LedgerGuard automates this workflow while keeping financial decisions explainable and safe.

Instead of sending every transaction to an LLM, LedgerGuard follows:

> **Deterministic logic first → AI investigation second → Human review when necessary**

This reduces unnecessary AI calls and keeps routine reconciliation fast and auditable.

---

# ✨ Key Features

## 📊 1. Executive Dashboard

The dashboard provides a centralized view of the reconciliation workspace.

It can surface:

- Total invoices
- Reconciled transactions
- Pending transactions
- Exceptions
- AI-reviewed cases
- Agent-resolved cases
- Escalated cases
- Reconciliation rate
- Financial variance
- Risk indicators
- AI activity
- Human review activity

---

## 🧭 2. Enterprise-Style Sidebar

The frontend is organized into clear operational sections:

```text
Overview
Reconciliation
Exceptions
Review Tickets
```

This separates routine reconciliation from investigation and human review.

---

## 📈 3. KPI Cards

Important financial and operational metrics are presented through KPI cards.

Example:

```text
┌─────────────────┐
│ Total Invoices  │
│       12        │
└─────────────────┘

┌─────────────────┐
│ Reconciled      │
│       75%       │
└─────────────────┘

┌─────────────────┐
│ Exceptions      │
│        3        │
└─────────────────┘

┌─────────────────┐
│ AI Reviewed     │
│        2        │
└─────────────────┘
```

---

# 🔄 4. Three-Way Reconciliation

LedgerGuard reconciles three financial sources:

```text
┌──────────────────┐
│   Sales Invoice  │
│                  │
│   Amount ₹10,000 │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Payment Gateway  │
│                  │
│ Net ₹9,750       │
│ MDR ₹250         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Bank Credit    │
│                  │
│ Amount ₹9,750    │
└──────────────────┘
```

For reconciliation records, LedgerGuard tracks information such as:

- Order ID
- Invoice
- Gateway settlement
- Bank credit
- Expected amount
- Actual amount
- Variance
- Variance reason
- Match stage
- Final status

---

# 🎯 5. Exact Matching

The first reconciliation stage uses deterministic matching.

When:

```text
Invoice Amount
      =
Gateway Net Amount
      =
Bank Credit
```

the transaction can be marked:

```text
RECONCILED
```

No AI call is required.

This keeps routine transactions fast and reduces unnecessary AI usage.

---

# 💳 6. MDR / Processing Fee Matching

Payment gateways may deduct processing fees before transferring money to the merchant.

Example:

```text
Invoice Amount       ₹10,000
MDR Fee                  ₹250
                         ─────
Expected Net          ₹9,750

Gateway Net           ₹9,750
Bank Credit           ₹9,750
```

The system can reconcile the transaction while accounting for the gateway fee.

The MDR tolerance is configurable.

---

# 💱 7. FX / Tolerance Matching

Small differences can occur because of:

- FX conversion
- Rounding
- Settlement calculations
- Processing fees
- Currency conversion

Example:

```text
Expected: ₹10,000
Actual:    ₹9,980
Difference:   ₹20
```

If the difference is within the configured tolerance, the transaction can be reconciled.

Example configuration:

```env
MDR_TOLERANCE_PCT=0.05
FX_TOLERANCE_PCT=0.02
```

---

# 💰 8. Split Payment Detection

A single invoice can be paid through multiple bank credits.

Example:

```text
Invoice
₹10,000
   │
   ├── Bank Credit #1  ₹4,000
   ├── Bank Credit #2  ₹3,500
   └── Bank Credit #3  ₹2,500
                         ─────
                         ₹10,000
```

LedgerGuard searches for small combinations of bank credits that satisfy the configured tolerance.

---

# ⚠️ 9. Exception Detection

Transactions that cannot be confidently reconciled are placed into the exception workflow.

Possible reasons include:

- Missing gateway settlement
- Missing bank credit
- Incorrect amount
- Partial payment
- Unknown transaction
- Large variance
- Missing order ID
- Settlement discrepancy
- Insufficient evidence

Example:

```text
Invoice       ₹10,260.49
Gateway        ₹9,822.00
Bank           ₹9,822.00
Variance         ₹438.49

Status:
⚠ EXCEPTION
```

---

# 💹 10. Financial Variance

LedgerGuard calculates and surfaces financial discrepancies.

Conceptually:

```text
Variance = Expected Amount - Actual Amount
```

Example:

```text
Invoice Amount       ₹10,260.49
Bank Amount            ₹9,822.00
────────────────────────────────
Variance                  ₹438.49
```

The UI can display:

- Expected amount
- Actual amount
- Absolute variance
- Variance direction
- Variance reason
- Risk level

---

# 🧾 11. Bill Explorer

Users can inspect individual reconciliation records.

A transaction can expose:

```text
Order ID
Invoice ID
Invoice Amount
Gateway Gross Amount
Gateway MDR
Gateway Net Amount
Bank Credit
Variance
Currency
Status
Match Stage
Risk
AI Status
```

This provides a complete financial trail for each bill.

---

# 🔗 12. Invoice → Gateway → Bank Visualization

A transaction can be visualized as:

```text
            INVOICE
           ₹10,260.49
               │
               ▼
        PAYMENT GATEWAY
            ₹9,822
         MDR ₹438.49
               │
               ▼
              BANK
            ₹9,822
```

This makes discrepancies easier to understand without manually comparing spreadsheets.

---

# 📊 13. Reconciliation Pipeline

Transactions move through multiple stages:

```text
Exact Match
     │
     ▼
MDR / FX
     │
     ▼
Split Payment
     │
     ▼
Exception
     │
     ▼
AI Review
     │
     ├──────────────┐
     ▼              ▼
 Resolved       Escalated
                    │
                    ▼
              Human Review
```

---

# 🛡️ 14. Exception Risk Scoring

Exceptions can be prioritized using indicators such as:

- Financial variance
- Missing transaction information
- Missing settlement
- Exception status
- AI investigation result
- Escalation status

Example levels:

```text
🟢 LOW
🟡 MEDIUM
🟠 HIGH
🔴 CRITICAL
```

This helps reviewers focus on the most important cases first.

---

# 🤖 15. AI Investigation

AI is used after deterministic reconciliation cannot confidently resolve a transaction.

Workflow:

```text
Transaction
     │
     ▼
Deterministic Engine
     │
     ▼
Unresolved Exception
     │
     ▼
AI Investigation
```

Depending on the available evidence, the AI investigation can consider:

- Transaction details
- Settlement information
- Variance information
- Contract clauses
- Internal communications
- Supporting records

The goal is not simply to generate an answer, but to produce an understandable investigation result.

---

# 🧠 16. RAG / Evidence Retrieval

Where configured, supporting documents can be used as evidence for AI investigation.

Conceptual pipeline:

```text
PDF / Documents
      │
      ▼
Text Extraction
      │
      ▼
Chunking
      │
      ▼
Embeddings
      │
      ▼
Vector Database
      │
      ▼
Relevant Evidence
      │
      ▼
AI Agent
```

The architecture supports vector-based retrieval so that the AI can use relevant business evidence instead of relying only on general model knowledge.

---

# 💬 17. Business-Friendly AI Explanation

AI results are presented in understandable business language.

Example:

> The invoice amount is ₹10,260.49 while the actual settlement is ₹9,822.00, creating a variance of ₹438.49. The discrepancy may be related to a payment gateway fee, partial settlement, FX conversion, refund, or missing settlement record. No sufficient supporting evidence was found, so the case has been escalated for human review.

This makes AI output useful to finance and operations teams rather than only technical users.

---

# 🔍 18. AI Investigation Trace

AI investigations can expose an audit-friendly trace.

A trace may contain:

```text
Step Number
Tool Name
Tool Input
Tool Output
Investigation Explanation
Token Usage
Timestamp
```

Example:

```text
Step 1
  ↓
Search Contract

Step 2
  ↓
Search Internal Communications

Step 3
  ↓
Analyze Variance

Step 4
  ↓
Determine Resolution
```

This improves transparency and auditability.

---

# ✅ 19. AI Resolution

If sufficient evidence is available:

```text
Exception
    ↓
AI Investigation
    ↓
Evidence Found
    ↓
AI Resolution
    ↓
AGENT_RESOLVED
```

---

# 🚨 20. AI Escalation

If AI cannot confidently resolve a financial discrepancy:

```text
AI Investigation
      ↓
Insufficient Evidence
      ↓
ESCALATED
      ↓
Human Review
```

LedgerGuard therefore avoids blindly making unsupported financial decisions.

---

# 👨‍💼 21. Human Review

Human review provides the final safety layer.

Reviewers can inspect:

- Invoice details
- Gateway details
- Bank details
- Variance
- Risk
- AI explanation
- Agent trace
- Review ticket
- Resolution notes

The overall approach is:

```text
Automation
    ↓
AI
    ↓
Human
```

---

# 🎫 22. Review Tickets

Unresolved cases can be represented as review/inquiry tickets.

Tickets can contain:

```text
Ticket ID
Order ID
Subject
Description
Expected Amount
Actual Amount
Missing Fields
Resolution Status
Resolution Note
Created At
```

---

# 📤 23. Multi-Source File Upload

LedgerGuard supports financial data ingestion through uploaded files.

Example demo files:

```text
01_demo_invoices.xlsx
02_demo_razorpay_settlements.xlsx
03_demo_bank_statement.xlsx
```

The ingestion flow is:

```text
Upload
  ↓
Validation
  ↓
Parsing
  ↓
Persistence
  ↓
Reconciliation
```

The upload layer can report created, updated, and skipped records.

---

# 🔄 24. Idempotent Reconciliation

The reconciliation engine is designed to avoid unnecessarily creating duplicate reconciliation records when the process is run repeatedly.

This is useful during:

- Development
- Testing
- Repeated dashboard actions
- Hackathon demonstrations

---

# 🧹 25. Workspace Reset

A workspace reset endpoint is available for starting a fresh demonstration.

```http
POST /workspace/reset
```

This is useful when demonstrating the application multiple times with the same demo dataset.

---

# 💡 26. AI Cost Optimization

LedgerGuard follows a deterministic-first strategy.

Instead of:

```text
1000 Transactions
       ↓
1000 AI Calls
```

the system aims for:

```text
1000 Transactions
       ↓
Deterministic Engine
       ↓
Most Transactions Resolved
       ↓
Small Exception Set
       ↓
AI Investigation
```

Benefits:

- Lower AI usage
- Lower cost
- Faster processing
- Better explainability
- More predictable behavior

---

# 🏗️ System Architecture

```text
                    ┌──────────────────────┐
                    │      React UI        │
                    │ Dashboard / Review   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │       FastAPI        │
                    │       Backend        │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
       File Ingestion   Reconciliation      AI Agent
              │             Engine             │
              ▼                │                ▼
         PostgreSQL       Match Results     RAG / Tools
                                               │
                                               ▼
                                         Evidence Search
                                               │
                                               ▼
                                         AI Explanation
                                               │
                                               ▼
                                         Human Review
```

---

# 🛠️ Technology Stack

## Frontend

- React
- Vite
- JavaScript
- Tailwind CSS

## Backend

- Python
- FastAPI
- SQLAlchemy

## Database

- PostgreSQL
- pgvector where configured

## Data Processing

- Pandas
- OpenPyXL

## AI

- Ollama
- Local LLM
- Agentic investigation
- RAG / vector search where configured

## Testing

- Pytest

---

# 📁 Project Structure

```text
ledgerguard/
│
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   ├── ingestion/
│   │   ├── matching_engine.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── database.py
│   │   └── main.py
│   │
│   ├── tests/
│   │   └── test_matching_engine.py
│   │
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
│
├── demo_data/
│   ├── 01_demo_invoices.xlsx
│   ├── 02_demo_razorpay_settlements.xlsx
│   └── 03_demo_bank_statement.xlsx
│
├── docs/
│   └── screenshots/
│
├── .gitignore
├── README.md
└── LICENSE
```

> Keep this structure synchronized with the actual repository before submission.

---

# ⚙️ Installation

## Prerequisites

Install:

- Python 3.12+
- Node.js 18+
- PostgreSQL
- Ollama
- Git

---

# 🐍 Backend Setup

From the project root:

```bash
cd backend
```

Create a virtual environment:

```bash
python3 -m venv venv_linux
```

Activate it:

```bash
source venv_linux/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Create the local environment file:

```bash
cp .env.example .env
```

Configure PostgreSQL and AI settings in `.env`.

Start FastAPI:

```bash
uvicorn app.main:app --reload --port 8000
```

Backend:

```text
http://127.0.0.1:8000
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

---

# ⚛️ Frontend Setup

Open another terminal:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Start Vite:

```bash
npm run dev
```

Frontend:

```text
http://localhost:5173
```

---

# 🦙 Ollama Setup

LedgerGuard can use Ollama for local AI inference.

After installing Ollama:

```bash
ollama pull llama3.2
```

Check installed models:

```bash
ollama list
```

Check that Ollama is available:

```bash
curl http://localhost:11434/api/tags
```

Typical configuration:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

> Model availability depends on the local Ollama installation and configuration.

---

# 🔐 Environment Configuration

Create:

```text
backend/.env
```

from:

```bash
cp backend/.env.example backend/.env
```

Example:

```env
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/ledgerguard

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

MDR_TOLERANCE_PCT=0.05
FX_TOLERANCE_PCT=0.02

AI_ENABLED=true
```

## Never commit

```text
.env
API keys
Database passwords
Authentication tokens
Private keys
Production customer data
```

Commit only:

```text
.env.example
```

with placeholder values.

---

# 🧪 Testing

Activate the backend environment:

```bash
cd backend
source venv_linux/bin/activate
```

Run:

```bash
python -m pytest -v
```

Core reconciliation tests should cover areas such as:

- Percentage tolerance
- Exact matching
- Split-payment detection
- Tolerance-based matching
- No-match cases

---

# 🔌 API Endpoints

## Health

```http
GET /health
```

## Upload

```http
POST /uploads
```

## Reconciliation

```http
POST /reconcile/run
GET /reconcile/matches
GET /reconcile/exceptions
```

## Dashboard

```http
GET /dashboard/stats
GET /dashboard/risk-signals
GET /dashboard/cost-comparison
```

## Review

```http
GET /review/tickets
GET /review/tickets/{ticket_id}
GET /review/summary
```

## AI Agent

```http
POST /agent/resolve/{match_id}
POST /agent/resolve-all
GET /agent/trace/{match_id}
```

## Workspace

```http
POST /workspace/reset
```

Full interactive documentation is available through FastAPI Swagger:

```text
http://127.0.0.1:8000/docs
```

---

# 🎬 Recommended Hackathon Demo

A strong demonstration can be completed in approximately 3–5 minutes.

## Step 1 — Dashboard

Start on the Overview page.

Show:

- KPI cards
- Reconciliation rate
- Financial variance
- Risk indicators
- AI activity

Say:

> LedgerGuard provides a centralized control center for financial reconciliation and exception management.

---

## Step 2 — Upload Data

Upload:

```text
Invoices
Gateway Settlements
Bank Statement
```

Show the ingestion result.

---

## Step 3 — Run Reconciliation

Click:

```text
Run Reconciliation
```

Explain:

> LedgerGuard first uses deterministic financial rules before involving AI.

---

## Step 4 — Show Exact Match

Open a successful transaction:

```text
Invoice
   ↓
Gateway
   ↓
Bank
```

Explain why it was automatically reconciled.

---

## Step 5 — Show Split Payment

Open a split-payment transaction and demonstrate how multiple bank credits can satisfy one invoice.

---

## Step 6 — Show Variance

Open an exception and show:

```text
Expected Amount
Actual Amount
Variance
Risk
```

---

## Step 7 — Run AI Investigation

Click:

```text
Investigate with AI
```

Show:

```text
Evidence
Investigation Steps
AI Explanation
Recommendation
Final Status
```

---

## Step 8 — Human Escalation

Show an example where AI cannot find sufficient evidence:

```text
AI Investigation
      ↓
Insufficient Evidence
      ↓
Human Review Ticket
```

Explain:

> LedgerGuard does not blindly trust AI. Uncertain financial cases are escalated to a human reviewer.

---

# 🏆 What Makes LedgerGuard Different?

LedgerGuard is designed as more than an LLM wrapper.

It combines:

```text
Financial Rules
       +
Three-Way Reconciliation
       +
MDR / FX Matching
       +
Split Payment Detection
       +
Variance Analysis
       +
Risk Prioritization
       +
RAG / Evidence Retrieval
       +
AI Investigation
       +
Audit Trace
       +
Human Review
```

The result is a complete financial exception-management workflow.

---

# 🎯 Core Design Principle

> **Deterministic logic first. AI second. Human review when necessary.**

This balances:

### Speed

Routine transactions can be resolved without AI.

### Cost

Only unresolved cases need AI investigation.

### Explainability

Deterministic rules provide clear reasons for normal reconciliation.

### Safety

Uncertain cases can be escalated to humans.

### Auditability

AI investigations can be represented through traces and evidence.

---

# 📈 Business Impact

LedgerGuard aims to reduce:

- Manual spreadsheet reconciliation
- Repetitive finance operations
- Exception investigation time
- Unnecessary AI calls
- Delayed issue resolution

And improve:

- Financial visibility
- Reconciliation accuracy
- Exception prioritization
- Auditability
- Investigation speed
- Operational efficiency

---

# 🔮 Future Roadmap

Potential production extensions include:

- ERP integrations
- Real payment gateway integrations
- Real-time reconciliation
- Role-based access control
- SSO
- Multi-tenant architecture
- Merchant risk scoring
- Advanced anomaly detection
- Automated email notifications
- WhatsApp notifications
- Cloud deployment
- Production observability
- Advanced audit logging
- AI confidence calibration
- Model evaluation
- Human approval workflows

---

# 🔒 Security

## Safe to commit

```text
Source code
README.md
Tests
Synthetic demo data
.env.example
.gitignore
Architecture diagrams
```

## Never commit

```text
.env
Real API keys
Database passwords
Private credentials
Production data
Customer information
Private certificates
```

If a real credential is accidentally committed:

1. Revoke the credential immediately.
2. Generate a replacement.
3. Remove the secret from the repository history where appropriate.
4. Update your local `.env`.

---

# 🏁 Hackathon Submission Checklist

Before submitting:

- [ ] Backend starts successfully
- [ ] Frontend starts successfully
- [ ] PostgreSQL connection works
- [ ] Ollama works
- [ ] Demo files are included
- [ ] File upload works
- [ ] Reconciliation works
- [ ] Exact matching works
- [ ] MDR matching works
- [ ] Split payment works
- [ ] Variance is displayed
- [ ] Exceptions are displayed
- [ ] AI investigation works
- [ ] AI explanation is visible
- [ ] Agent trace works
- [ ] Human review works
- [ ] Dashboard works
- [ ] Swagger works
- [ ] Tests pass
- [ ] `.env` is not committed
- [ ] `.env.example` is included
- [ ] README is complete
- [ ] Screenshots are included
- [ ] Demo video is ready

---

# 📸 Screenshots

For the final GitHub repository, add screenshots under:

```text
docs/screenshots/
```

Recommended screenshots:

```text
docs/screenshots/dashboard.png
docs/screenshots/reconciliation.png
docs/screenshots/exception.png
docs/screenshots/ai-investigation.png
```

Then add them here:

```markdown
## Dashboard

![LedgerGuard Dashboard](docs/screenshots/dashboard.png)

## Reconciliation

![LedgerGuard Reconciliation](docs/screenshots/reconciliation.png)

## AI Investigation

![LedgerGuard AI Investigation](docs/screenshots/ai-investigation.png)
```

---

# 🎯 One-Line Pitch

> **LedgerGuard is an AI-assisted financial reconciliation platform that automatically matches invoices, payment settlements, and bank credits, investigates unresolved discrepancies with AI, and safely escalates uncertain cases to humans.**

---

# 👥 Project

**LedgerGuard**

AI-assisted financial reconciliation and exception investigation platform.

Built for demonstration, learning, and hackathon purposes.

---

## 📜 License

This project is intended for educational, demonstration, and hackathon purposes.
