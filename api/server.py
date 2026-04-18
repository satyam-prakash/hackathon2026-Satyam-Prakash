"""
FastAPI web server — exposes the agent as a REST API.
Judges can call POST /resolve with any ticket JSON to test live.
Also provides a GET /tickets/batch endpoint to run all sample tickets at once.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

from google import genai

app = FastAPI(
    title="ShopWave Support Agent API",
    description="Autonomous support resolution agent for the Agentic AI Hackathon 2026",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configure Gemini on startup ───────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not set")


# ── Schemas ───────────────────────────────────────────────────────────────────
class TicketRequest(BaseModel):
    ticket_id: str = "TKT-LIVE"
    customer_email: str
    subject: str
    body: str
    source: Optional[str] = "api"


class TicketResponse(BaseModel):
    ticket_id: str
    status: str
    action_taken: str
    confidence: float
    escalated: bool
    tool_calls: list[str]
    duration_ms: int
    timestamp: str


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/", summary="Health check")
async def health():
    return {
        "status": "ok",
        "agent": "ShopWave Support Agent",
        "hackathon": "Agentic AI Hackathon 2026",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.post("/resolve", response_model=TicketResponse, summary="Resolve a single ticket")
async def resolve_ticket(ticket: TicketRequest):
    """
    Submit any customer support request and get it resolved by the AI agent.
    The agent will look up customer data, check policies, and take action.
    """
    from agent import ShopWaveAgent
    agent = ShopWaveAgent()

    result = await agent.solve(ticket.dict())

    return TicketResponse(
        ticket_id=result["ticket_id"],
        status=result["status"],
        action_taken=result.get("action_taken", ""),
        confidence=result["confidence"],
        escalated=result["escalated"],
        tool_calls=result["tool_calls"],
        duration_ms=result["duration_ms"],
        timestamp=result["timestamp"],
    )


@app.get("/resolve/full/{ticket_id}", summary="Resolve ticket — full audit detail")
async def resolve_ticket_full(ticket_id: str):
    """Returns the full step-by-step audit trail for a sample ticket."""
    DATA_DIR = Path(__file__).parent / "data"
    with open(DATA_DIR / "tickets.json") as f:
        tickets = json.load(f)

    ticket = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
    if not ticket:
        raise HTTPException(404, f"Ticket '{ticket_id}' not found in sample data.")

    from agent import ShopWaveAgent
    agent = ShopWaveAgent()
    result = await agent.solve(ticket)
    return result


@app.post("/tickets/batch", summary="Run all sample tickets concurrently")
async def batch_resolve():
    """
    Processes all 20 sample tickets concurrently.
    This demonstrates the agent's autonomous, concurrent resolution capability.
    """
    from orchestrator import run_all
    summary = await run_all()
    # Don't return full step details in batch (too large)
    return {
        "total_tickets": summary["total_tickets"],
        "resolved": summary["resolved"],
        "escalated": summary["escalated"],
        "dead_letter": summary["dead_letter"],
        "avg_confidence": summary["avg_confidence"],
        "avg_tool_calls_per_ticket": summary["avg_tool_calls_per_ticket"],
        "total_duration_ms": summary["total_duration_ms"],
        "results": [
            {
                "ticket_id": r["ticket_id"],
                "subject": r["subject"],
                "status": r["status"],
                "action_taken": r["action_taken"],
                "confidence": r["confidence"],
                "escalated": r["escalated"],
                "tool_calls": r["tool_calls"],
            }
            for r in summary["results"]
        ]
    }


@app.get("/audit", summary="Get last audit log")
async def get_audit():
    """Returns the most recent audit log from a batch run."""
    audit_path = Path(__file__).parent / "output" / "audit_log.json"
    if not audit_path.exists():
        raise HTTPException(404, "No audit log found. Run /tickets/batch first.")
    with open(audit_path) as f:
        return json.load(f)
