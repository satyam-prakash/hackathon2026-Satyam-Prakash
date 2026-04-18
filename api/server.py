"""
FastAPI web server — exposes the agent as a REST API.
Every resolved ticket is automatically saved to the audit log.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="ShopWave Support Agent API",
    description="Autonomous support resolution agent — Agentic AI Hackathon 2026",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class TicketRequest(BaseModel):
    ticket_id:      Optional[str] = None   # auto-generated if not provided
    customer_email: str
    subject:        str
    body:           str
    source:         Optional[str] = "api"


class TicketSummary(BaseModel):
    ticket_id:    str
    status:       str
    action_taken: str
    confidence:   float
    escalated:    bool
    tool_calls:   list[str]
    duration_ms:  int
    timestamp:    str
    logged_to:    str


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/", summary="Health check")
async def health():
    return {
        "status": "ok",
        "agent": "ShopWave Support Agent",
        "hackathon": "Agentic AI Hackathon 2026",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/resolve", response_model=TicketSummary, summary="Resolve any customer support request")
async def resolve_ticket(ticket: TicketRequest):
    """
    Submit any customer support request and get it resolved autonomously.
    The agent looks up customer data, applies policies, and takes action.
    Every request is saved to the audit log automatically.
    """
    from agent import ShopWaveAgent
    from audit_logger import append_audit

    # Auto-generate ticket_id if not provided
    ticket_id = ticket.ticket_id or f"API-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:17]}"

    ticket_dict = {
        "ticket_id":      ticket_id,
        "customer_email": ticket.customer_email,
        "subject":        ticket.subject,
        "body":           ticket.body,
        "source":         ticket.source or "api",
    }

    agent = ShopWaveAgent()
    result = await agent.solve(ticket_dict)

    # Save to audit log
    append_audit(result, source=ticket.source or "api")

    audit_path = str(Path(__file__).parent.parent / "output" / "audit_log.jsonl")

    return TicketSummary(
        ticket_id=result["ticket_id"],
        status=result["status"],
        action_taken=result.get("action_taken", ""),
        confidence=result["confidence"],
        escalated=result["escalated"],
        tool_calls=result["tool_calls"],
        duration_ms=result["duration_ms"],
        timestamp=result["timestamp"],
        logged_to=audit_path,
    )


@app.post("/resolve/full", summary="Resolve ticket — returns full step-by-step audit trail")
async def resolve_ticket_full(ticket: TicketRequest):
    """
    Same as /resolve but returns the complete ReAct trace:
    every thought, every tool call, every result.
    """
    from agent import ShopWaveAgent
    from audit_logger import append_audit

    ticket_id = ticket.ticket_id or f"API-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:17]}"
    ticket_dict = {
        "ticket_id":      ticket_id,
        "customer_email": ticket.customer_email,
        "subject":        ticket.subject,
        "body":           ticket.body,
        "source":         ticket.source or "api",
    }

    agent = ShopWaveAgent()
    result = await agent.solve(ticket_dict)
    append_audit(result, source=ticket.source or "api")
    return result


@app.get("/resolve/sample/{ticket_id}", summary="Resolve a sample ticket by ID")
async def resolve_sample_ticket(ticket_id: str):
    """Resolve one of the 20 sample tickets by its ID (e.g. TKT-001)."""
    from agent import ShopWaveAgent
    from audit_logger import append_audit

    data_path = Path(__file__).parent.parent / "data" / "tickets.json"
    tickets = json.loads(data_path.read_text())
    ticket = next((t for t in tickets if t["ticket_id"] == ticket_id.upper()), None)
    if not ticket:
        raise HTTPException(404, f"Sample ticket '{ticket_id}' not found. Valid IDs: TKT-001 to TKT-020")

    agent = ShopWaveAgent()
    result = await agent.solve(ticket)
    append_audit(result, source="api_sample")
    return result


@app.post("/tickets/batch", summary="Run all 20 sample tickets concurrently")
async def batch_resolve():
    """Processes all 20 sample tickets concurrently and saves every result to the audit log."""
    from orchestrator import run_all
    summary = await run_all()
    return {
        "total_tickets":          summary["total_tickets"],
        "resolved":               summary["resolved"],
        "escalated":              summary["escalated"],
        "dead_letter":            summary["dead_letter"],
        "avg_confidence":         summary["avg_confidence"],
        "avg_tool_calls":         summary["avg_tool_calls_per_ticket"],
        "total_duration_ms":      summary["total_duration_ms"],
        "results": [
            {
                "ticket_id":   r["ticket_id"],
                "subject":     r["subject"],
                "status":      r["status"],
                "action_taken":r["action_taken"],
                "confidence":  r["confidence"],
                "escalated":   r["escalated"],
                "tool_calls":  r["tool_calls"],
            }
            for r in summary["results"]
        ],
    }


@app.get("/audit", summary="View audit log index (all requests)")
async def get_audit_index():
    """Returns a summary of every ticket ever resolved — from CLI, API, or batch."""
    from audit_logger import read_index
    return read_index()


@app.get("/audit/full", summary="View full audit log (every detail)")
async def get_audit_full():
    """Returns the complete audit trail with full step-by-step details for every ticket."""
    from audit_logger import read_all_logs
    logs = read_all_logs()
    return {"total": len(logs), "records": logs}
