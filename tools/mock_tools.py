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

# Running counters for new IDs (session-based)
_next_customer_num = 11    # C001-C010 are taken
_next_order_num    = 1016  # ORD-1001 to ORD-1015 are taken


# ── READ TOOLS ────────────────────────────────────────────────────────────────

async def get_customer(email: str) -> dict:
    """Fetch customer profile, tier, and history by email."""
    await asyncio.sleep(0.05)
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


async def list_products() -> list:
    """Return all available products in the ShopWave catalog."""
    await asyncio.sleep(0.05)
    return list(_products.values())


async def search_knowledge_base(query: str) -> str:
    """Semantic search on ShopWave policy docs."""
    await asyncio.sleep(0.05)
    query_lower = query.lower()
    sections = _kb_text.split("\n## ")
    relevant = []
    for section in sections:
        if any(kw in section.lower() for kw in query_lower.split()):
            relevant.append(section[:800])
    if relevant:
        return "\n\n---\n\n".join(relevant[:3])
    return _kb_text[:2000]


# ── WRITE TOOLS ───────────────────────────────────────────────────────────────

async def register_customer(name: str, email: str, phone: str = "", city: str = "") -> dict:
    """
    Register a new customer account in the ShopWave system.
    Call this when get_customer() returns an error and the user wants to sign up.
    """
    global _next_customer_num
    await asyncio.sleep(0.1)

    email = email.lower().strip()
    if email in _customers:
        return {"error": f"An account with email '{email}' already exists."}

    customer_id = f"C{_next_customer_num:03d}"
    _next_customer_num += 1

    new_customer = {
        "customer_id": customer_id,
        "name": name.strip().title(),
        "email": email,
        "phone": phone or "N/A",
        "tier": "standard",
        "member_since": datetime.utcnow().strftime("%Y-%m-%d"),
        "total_orders": 0,
        "total_spent": 0.0,
        "address": {
            "street": "",
            "city": city or "N/A",
            "state": "",
            "zip": ""
        },
        "notes": "Newly registered customer via support chat."
    }
    _customers[email] = new_customer

    return {
        "success": True,
        "customer_id": customer_id,
        "name": new_customer["name"],
        "email": email,
        "tier": "standard",
        "message": f"Account created successfully! Welcome to ShopWave, {new_customer['name']}!"
    }


async def place_order(email: str, product_id: str, quantity: int = 1) -> dict:
    """
    Place a new order for a customer.
    Call after confirming product_id and quantity with the customer.
    """
    global _next_order_num
    await asyncio.sleep(0.1)

    customer = _customers.get(email.lower().strip())
    if not customer:
        return {"error": f"Customer '{email}' not found. Please register first."}

    product = _products.get(product_id.strip().upper())
    if not product:
        return {"error": f"Product '{product_id}' not found."}

    if quantity < 1:
        return {"error": "Quantity must be at least 1."}

    order_id  = f"ORD-{_next_order_num}"
    _next_order_num += 1
    amount    = round(product["price"] * quantity, 2)
    order_date = datetime.utcnow().strftime("%Y-%m-%d")

    new_order = {
        "order_id": order_id,
        "customer_id": customer["customer_id"],
        "product_id": product_id.upper(),
        "quantity": quantity,
        "amount": amount,
        "status": "processing",
        "order_date": order_date,
        "delivery_date": None,
        "return_deadline": None,
        "refund_status": None,
        "notes": f"Placed via support chat on {order_date}."
    }
    _orders[order_id] = new_order
    _customers[email.lower()]["total_orders"] += 1
    _customers[email.lower()]["total_spent"] = round(
        _customers[email.lower()]["total_spent"] + amount, 2
    )

    return {
        "success": True,
        "order_id": order_id,
        "product": product["name"],
        "quantity": quantity,
        "amount": amount,
        "status": "processing",
        "estimated_delivery": "3-5 business days",
        "message": f"Order {order_id} placed successfully! Total: ${amount:.2f}. "
                   f"Estimated delivery: 3-5 business days."
    }


async def check_refund_eligibility(order_id: str) -> dict:
    """Checks whether a refund can be issued for this order."""
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

    return_deadline = order.get("return_deadline")
    if return_deadline:
        deadline = date.fromisoformat(return_deadline)
        if date.today() > deadline:
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
    if random.random() < 0.20:
        raise TimeoutError(f"Refund service timed out for order '{order_id}'. Retry.")

    order = _orders.get(order_id.strip().upper())
    if not order:
        return {"success": False, "error": f"Order '{order_id}' not found."}

    _orders[order_id]["refund_status"] = "refunded"
    return {
        "success": True,
        "order_id": order_id,
        "amount_refunded": amount,
        "message": f"Refund of ${amount:.2f} issued. Will appear in 5-7 business days.",
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
        "message": "Order cancelled. Confirmation email sent within 1 hour."
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
    """Escalate a ticket to a human agent. priority: low|medium|high|urgent"""
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


# ── Tool registry ─────────────────────────────────────────────────────────────
TOOLS = {
    "get_customer":            get_customer,
    "get_order":               get_order,
    "get_product":             get_product,
    "get_orders_by_customer":  get_orders_by_customer,
    "list_products":           list_products,
    "search_knowledge_base":   search_knowledge_base,
    "register_customer":       register_customer,
    "place_order":             place_order,
    "check_refund_eligibility":check_refund_eligibility,
    "issue_refund":            issue_refund,
    "cancel_order":            cancel_order,
    "send_reply":              send_reply,
    "escalate":                escalate,
}
