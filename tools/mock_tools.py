"""
ShopWave Mock Tools — simulates a real backend API.
Loads data from JSON files and provides tool functions the agent can call.
One tool (issue_refund) has a simulated 20% failure rate to test resilience.
"""
import json
import random
import asyncio
from pathlib import Path
from datetime import datetime, date

# ── Data loading ──────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"

def _load(filename: str) -> list:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)

_customers = {c["email"]: c for c in _load("customers.json")}
_orders    = {o["order_id"]: o for o in _load("orders.json")}
_products  = {p["product_id"]: p for p in _load("products.json")}

with open(DATA_DIR / "knowledge-base.md", encoding="utf-8") as f:
    _kb_text = f.read()


# ── READ TOOLS ────────────────────────────────────────────────────────────────

async def get_customer(email: str) -> dict:
    """Fetch customer profile, tier, and history by email."""
    await asyncio.sleep(0.05)   # simulate latency
    customer = _customers.get(email.lower().strip())
    if not customer:
        return {"error": f"No customer found with email '{email}'"}
    return customer


async def get_order(order_id: str) -> dict:
    """Retrieve order status, details, timestamps, and refund status."""
    await asyncio.sleep(0.05)
    order = _orders.get(order_id.strip().upper())
    if not order:
        return {"error": f"No order found with ID '{order_id}'"}
    return order


async def get_product(product_id: str) -> dict:
    """Retrieve product metadata, return window, and warranty info."""
    await asyncio.sleep(0.05)
    product = _products.get(product_id.strip().upper())
    if not product:
        return {"error": f"No product found with ID '{product_id}'"}
    return product


async def get_orders_by_customer(email: str) -> list:
    """Look up ALL orders for a customer by their email address.
    Useful when the customer hasn't provided an order ID."""
    await asyncio.sleep(0.05)
    customer = _customers.get(email.lower().strip())
    if not customer:
        return [{"error": f"No customer found with email '{email}'"}]
    customer_id = customer["customer_id"]
    orders = [o for o in _orders.values() if o["customer_id"] == customer_id]
    if not orders:
        return [{"info": f"No orders found for customer '{email}'"}]
    return orders


async def search_knowledge_base(query: str) -> str:
    """
    Semantic search on ShopWave policy docs.
    (Mock: returns the full KB — a real impl would do vector search.)
    """
    await asyncio.sleep(0.05)
    query_lower = query.lower()
    # Return the most relevant sections based on keywords
    sections = _kb_text.split("\n## ")
    relevant = []
    for section in sections:
        if any(kw in section.lower() for kw in query_lower.split()):
            relevant.append(section[:800])   # first 800 chars of section
    if relevant:
        return "\n\n---\n\n".join(relevant[:3])
    return _kb_text[:2000]   # fallback: top of KB


# ── WRITE TOOLS ───────────────────────────────────────────────────────────────

async def check_refund_eligibility(order_id: str) -> dict:
    """
    Checks whether a refund can be issued for this order.
    Returns eligibility flag + reason.
    """
    await asyncio.sleep(0.05)
    order = _orders.get(order_id.strip().upper())
    if not order:
        return {"eligible": False, "reason": f"Order '{order_id}' not found."}

    if order.get("refund_status") == "refunded":
        return {"eligible": False, "reason": "Refund already processed for this order."}

    if order["status"] in ("processing", "shipped"):
        return {"eligible": False, "reason": f"Order is '{order['status']}' — not yet delivered."}

    if order["status"] != "delivered":
        return {"eligible": False, "reason": f"Order status is '{order['status']}' — cannot issue refund."}

    # Check return window
    return_deadline = order.get("return_deadline")
    if return_deadline:
        deadline = date.fromisoformat(return_deadline)
        today = date.today()
        if today > deadline:
            return {
                "eligible": False,
                "reason": f"Return window expired on {return_deadline}.",
                "return_deadline": return_deadline
            }

    return {
        "eligible": True,
        "reason": "Order is within return window and eligible for refund.",
        "amount": order["amount"],
        "return_deadline": return_deadline
    }


async def issue_refund(order_id: str, amount: float) -> dict:
    """
    Processes a refund. IRREVERSIBLE.
    Has a simulated 20% failure rate to test agent resilience.
    """
    await asyncio.sleep(0.1)

    # Simulate occasional backend failure
    if random.random() < 0.20:
        raise TimeoutError(f"Refund service timed out for order '{order_id}'. Retry.")

    order = _orders.get(order_id.strip().upper())
    if not order:
        return {"success": False, "error": f"Order '{order_id}' not found."}

    # Mark as refunded in memory (for this session)
    _orders[order_id]["refund_status"] = "refunded"

    return {
        "success": True,
        "order_id": order_id,
        "amount_refunded": amount,
        "message": f"Refund of ${amount:.2f} issued successfully. Will appear in 5–7 business days.",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


async def cancel_order(order_id: str) -> dict:
    """Cancel an order that is still in 'processing' status."""
    await asyncio.sleep(0.05)
    order = _orders.get(order_id.strip().upper())
    if not order:
        return {"success": False, "error": f"Order '{order_id}' not found."}
    if order["status"] != "processing":
        return {
            "success": False,
            "error": f"Cannot cancel — order is '{order['status']}'. Only 'processing' orders can be cancelled."
        }
    _orders[order_id]["status"] = "cancelled"
    return {
        "success": True,
        "order_id": order_id,
        "message": "Order cancelled successfully. Confirmation email will be sent within 1 hour."
    }


async def send_reply(ticket_id: str, message: str) -> dict:
    """Send a reply message to the customer."""
    await asyncio.sleep(0.05)
    return {
        "success": True,
        "ticket_id": ticket_id,
        "message_sent": message,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


async def escalate(ticket_id: str, summary: str, priority: str) -> dict:
    """
    Escalate a ticket to a human agent.
    priority: 'low' | 'medium' | 'high' | 'urgent'
    """
    await asyncio.sleep(0.05)
    valid_priorities = {"low", "medium", "high", "urgent"}
    if priority.lower() not in valid_priorities:
        priority = "medium"
    return {
        "success": True,
        "ticket_id": ticket_id,
        "escalated": True,
        "priority": priority.lower(),
        "summary": summary,
        "assigned_to": "human_support_team",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ── Tool registry (for the agent to discover tools) ───────────────────────────
TOOLS = {
    "get_customer": get_customer,
    "get_order": get_order,
    "get_product": get_product,
    "get_orders_by_customer": get_orders_by_customer,
    "search_knowledge_base": search_knowledge_base,
    "check_refund_eligibility": check_refund_eligibility,
    "issue_refund": issue_refund,
    "cancel_order": cancel_order,
    "send_reply": send_reply,
    "escalate": escalate,
}
