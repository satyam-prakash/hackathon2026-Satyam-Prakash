"""
Orchestrator — runs all tickets concurrently with asyncio.gather().
Handles the dead-letter queue for permanently failed tickets.
Writes a full audit log to output/audit_log.json.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Pick up GOOGLE_API_KEY from .env if present

DATA_DIR   = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def _load_tickets() -> list[dict]:
    with open(DATA_DIR / "tickets.json", encoding="utf-8") as f:
        return json.load(f)


async def process_ticket_safe(agent, ticket: dict, dead_letter: list) -> dict | None:
    """Wrap agent.solve() so a crash in one ticket doesn't stop the others."""
    try:
        return await agent.solve(ticket)
    except Exception as e:
        record = {
            "ticket_id": ticket.get("ticket_id", "UNKNOWN"),
            "customer_email": ticket.get("customer_email"),
            "subject": ticket.get("subject"),
            "status": "dead_letter",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        dead_letter.append(record)
        print(f"  [DEAD LETTER] {ticket.get('ticket_id')}: {e}")
        return None


async def run_all() -> dict:
    """Main orchestration loop — concurrent processing of all tickets."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GOOGLE_API_KEY in .env file or as environment variable.")
        sys.exit(1)

    from agent import ShopWaveAgent
    agent = ShopWaveAgent()

    tickets = _load_tickets()
    dead_letter: list[dict] = []

    print(f"\n{'='*60}")
    print(f"  ShopWave Support Agent -- Processing {len(tickets)} tickets")
    print(f"{'='*60}\n")

    start = datetime.utcnow()

    # Concurrent processing with 0.5s stagger to avoid rate-limit spikes
    async def launch_with_stagger(ticket, delay):
        await asyncio.sleep(delay)
        return await process_ticket_safe(agent, ticket, dead_letter)

    tasks = [
        launch_with_stagger(ticket, i * 0.5)
        for i, ticket in enumerate(tickets)
    ]
    raw_results = await asyncio.gather(*tasks)

    end = datetime.utcnow()
    total_ms = int((end - start).total_seconds() * 1000)

    results = [r for r in raw_results if r is not None]

    resolved  = [r for r in results if r["status"] == "resolved"]
    escalated = [r for r in results if r["status"] == "escalated"]
    avg_conf  = sum(r["confidence"] for r in results) / max(len(results), 1)
    avg_tools = sum(r["total_tool_calls"] for r in results) / max(len(results), 1)

    summary = {
        "run_timestamp": start.isoformat() + "Z",
        "total_tickets": len(tickets),
        "resolved": len(resolved),
        "escalated": len(escalated),
        "dead_letter": len(dead_letter),
        "avg_confidence": round(avg_conf, 3),
        "avg_tool_calls_per_ticket": round(avg_tools, 1),
        "total_duration_ms": total_ms,
        "results": results,
        "dead_letter_queue": dead_letter,
    }

    # Save full audit log
    audit_path = OUTPUT_DIR / "audit_log.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    if dead_letter:
        dlq_path = OUTPUT_DIR / "dead_letter_queue.json"
        with open(dlq_path, "w", encoding="utf-8") as f:
            json.dump(dead_letter, f, indent=2, default=str)

    # Console summary
    print(f"\n{'='*60}")
    print(f"  [OK]   Resolved    : {len(resolved)}")
    print(f"  [UP]   Escalated   : {len(escalated)}")
    print(f"  [ERR]  Dead-letter : {len(dead_letter)}")
    print(f"  [AVG]  Confidence  : {avg_conf:.0%}")
    print(f"  [AVG]  Tool calls  : {avg_tools:.1f}")
    print(f"  [TIME] Duration    : {total_ms}ms")
    print(f"\n  Full audit log -> {audit_path}")
    print(f"{'='*60}\n")

    for r in results:
        icon = "[OK]" if r["status"] == "resolved" else "[UP]"
        conf = f"{r['confidence']:.0%}"
        print(f"  {icon} [{r['ticket_id']}] {r['subject'][:45]:<45} | conf={conf} | {r['action_taken'][:50]}")

    return summary


if __name__ == "__main__":
    asyncio.run(run_all())
