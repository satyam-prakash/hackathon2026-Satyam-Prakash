# 🤖 ShopWave Autonomous Support Agent
### Agentic AI Hackathon 2026

An end-to-end autonomous customer support agent for ShopWave that resolves support tickets without human intervention using a **ReAct (Reasoning + Acting) loop** powered by Gemini.

---

## ✨ Key Features

| Feature | Implementation |
|---|---|
| **ReAct Loop** | Think → Act → Observe × N steps until resolved |
| **Concurrent Processing** | All tickets processed simultaneously via `asyncio.gather()` |
| **9 Tools** | get_customer, get_order, get_product, search_kb, check_eligibility, issue_refund, cancel_order, send_reply, escalate |
| **Fault Tolerance** | Exponential backoff retry (3 attempts: 1s→2s→4s) on tool failures |
| **Dead-Letter Queue** | Failed tickets saved to `output/dead_letter_queue.json` — never lost |
| **Confidence Scoring** | Every decision scored 0.0–1.0; auto-escalate if < 0.6 |
| **Full Audit Log** | Every step, tool call, input/output saved to `output/audit_log.json` |
| **REST API** | FastAPI server — resolve any ticket via HTTP POST |

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Gemini API key
```powershell
$env:GOOGLE_API_KEY = "your-key-here"
```

### 3. Run the agent

```bash
# Process all 20 sample tickets concurrently
python main.py

# Process a single sample ticket with full detail
python main.py --ticket TKT-001

# Start the live API server
python main.py --serve
```

---

## 🌐 Live API

Once the server is running at `http://localhost:8000`:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Health check |
| `/docs` | GET | Interactive Swagger UI |
| `/resolve` | POST | Resolve **any** customer request |
| `/resolve/full/{ticket_id}` | GET | Full audit for a sample ticket |
| `/tickets/batch` | POST | Run all 20 sample tickets |
| `/audit` | GET | View last batch audit log |

### Example: Resolve any ticket
```bash
curl -X POST http://localhost:8000/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "LIVE-001",
    "customer_email": "alice.turner@email.com",
    "subject": "My headphones stopped working",
    "body": "Hi, I bought headphones last month (ORD-1001) and they broke. I want a refund."
  }'
```

---

## 🏗️ Architecture

```
Customer Ticket (any source)
         │
         ▼
   ┌─────────────┐     asyncio.gather()
   │ Orchestrator│─────────────────────► [ticket 1] [ticket 2] ... [ticket N]
   └─────────────┘                              │
                                                ▼
                              ┌─────────────────────────────┐
                              │      ReAct Agent Loop        │
                              │                              │
                              │  THINK (Gemini LLM)          │
                              │     ↓                        │
                              │  ACT  (tool call)            │
                              │     ↓                        │
                              │  OBSERVE (tool result)       │
                              │     ↓ repeat up to 12 steps  │
                              │  FINISH (reply or escalate)  │
                              └────────────┬────────────────┘
                                           │
                              ┌────────────▼────────────────┐
                              │        Tools (9)             │
                              │  • get_customer              │
                              │  • get_order                 │
                              │  • get_product               │
                              │  • search_knowledge_base     │
                              │  • check_refund_eligibility  │
                              │  • issue_refund (with retry) │
                              │  • cancel_order              │
                              │  • send_reply                │
                              │  • escalate                  │
                              └─────────────────────────────┘
                                           │
                              ┌────────────▼────────────────┐
                              │    Audit Log + Dead-Letter   │
                              │    output/audit_log.json     │
                              │    output/dead_letter_queue  │
                              └─────────────────────────────┘
```

---

## 📁 Project Structure

```
shopwave-agent/
├── main.py               # CLI entry point
├── orchestrator.py       # Concurrent multi-ticket runner
├── requirements.txt
├── data/                 # Sample data (from hackathon)
│   ├── customers.json
│   ├── orders.json
│   ├── products.json
│   ├── tickets.json
│   └── knowledge-base.md
├── agent/
│   ├── __init__.py
│   └── react_agent.py    # Core ReAct loop (Think→Act→Observe)
├── tools/
│   ├── __init__.py
│   └── mock_tools.py     # 9 tool implementations + fault injection
├── api/
│   ├── __init__.py
│   └── server.py         # FastAPI REST server
└── output/
    ├── audit_log.json     # Per-ticket step-by-step audit trail
    └── dead_letter_queue.json  # Failed tickets (never lost)
```

---

## 🎯 Failure Mode Handling

| Failure | How Agent Handles It |
|---|---|
| Tool timeout (e.g. refund service) | Exponential backoff × 3, then dead-letter |
| Unknown customer email | Asks for order ID + registered email |
| Non-existent order ID | Flags error, asks customer for correct ID |
| Social engineering (fake tier claim) | Verifies tier via `get_customer`, declines politely |
| Ambiguous ticket (no order, no product) | Asks targeted clarifying questions |
| Confidence < 0.6 | Auto-escalates with priority rating |
| LLM parse error | Logged, ticket moved to dead-letter queue |
