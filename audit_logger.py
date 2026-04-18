"""
Shared audit logger — appends every resolved ticket to output/audit_log.jsonl
(one JSON object per line = append-friendly, no need to rewrite the whole file).
Also maintains a summary index in output/audit_index.json.
"""
import json
import os
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

AUDIT_LOG   = OUTPUT_DIR / "audit_log.jsonl"   # one record per line
AUDIT_INDEX = OUTPUT_DIR / "audit_index.json"  # running summary stats


def append_audit(result: dict, source: str = "unknown") -> None:
    """
    Append a single ticket resolution to the audit log.
    Call this after every agent.solve() — from CLI, API, or batch mode.
    """
    record = {
        **result,
        "source": source,
        "logged_at": datetime.utcnow().isoformat() + "Z",
    }

    # ── Append to JSONL file (one record per line) ────────────────────────────
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

    # ── Update running index ──────────────────────────────────────────────────
    _update_index(record)


def _update_index(record: dict) -> None:
    """Maintain a lightweight summary index file."""
    # Load existing index
    if AUDIT_INDEX.exists():
        with open(AUDIT_INDEX, encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {
            "total": 0,
            "resolved": 0,
            "escalated": 0,
            "dead_letter": 0,
            "avg_confidence": 0.0,
            "tickets": []
        }

    # Update counters
    index["total"] += 1
    res = record.get("resolution", {})
    status = res.get("status", "unknown")
    if status == "resolved":
        index["resolved"] += 1
    elif status == "escalated":
        index["escalated"] += 1
    elif status == "dead_letter":
        index["dead_letter"] += 1

    # Rolling average confidence
    conf = res.get("confidence", 0)
    index["avg_confidence"] = round(
        (index["avg_confidence"] * (index["total"] - 1) + conf) / index["total"], 3
    )

    # Append summary entry
    index["tickets"].append({
        "ticket_id":    record.get("ticket_id"),
        "source":       record.get("metadata", {}).get("source", "unknown"),
        "status":       status,
        "confidence":   conf,
        "escalated":    res.get("escalated", False),
        "tool_calls":   record.get("system_telemetry", {}).get("tool_calls", []),
        "duration_ms":  record.get("system_telemetry", {}).get("duration_ms", 0),
        "logged_at":    record.get("metadata", {}).get("received_at", ""),
    })

    with open(AUDIT_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, default=str)


def read_all_logs() -> list[dict]:
    """Return all audit records as a list (for the /audit API endpoint)."""
    if not AUDIT_LOG.exists():
        return []
    records = []
    with open(AUDIT_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def read_index() -> dict:
    """Return the summary index."""
    if not AUDIT_INDEX.exists():
        return {"total": 0, "resolved": 0, "escalated": 0, "dead_letter": 0, "tickets": []}
    with open(AUDIT_INDEX, encoding="utf-8") as f:
        return json.load(f)
