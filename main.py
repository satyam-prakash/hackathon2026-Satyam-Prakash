"""
Main entry point — run the agent from CLI.

Usage:
  python main.py                    # batch process all 20 sample tickets
  python main.py --serve            # start the FastAPI server (live API)
  python main.py --ask              # interactive conversational session
  python main.py --ticket TKT-001   # process a single sample ticket
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="ShopWave Autonomous Support Agent")
    parser.add_argument("--serve",  action="store_true", help="Start the FastAPI API server")
    parser.add_argument("--ask",    action="store_true", help="Interactive conversational session")
    parser.add_argument("--ticket", type=str, help="Process a single ticket ID from sample data")
    parser.add_argument("--port",   type=int, default=8000, help="API server port (default: 8000)")
    args = parser.parse_args()

    if not os.getenv("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    if args.serve:
        import uvicorn
        print(f"\nStarting ShopWave Agent API on http://localhost:{args.port}")
        print(f"  Interactive docs: http://localhost:{args.port}/docs\n")
        uvicorn.run("api.server:app", host="0.0.0.0", port=args.port, reload=False)

    elif args.ask:
        asyncio.run(_chat_session())

    elif args.ticket:
        import json
        from pathlib import Path
        data_path = Path(__file__).parent / "data" / "tickets.json"
        tickets = json.loads(data_path.read_text())
        ticket = next((t for t in tickets if t["ticket_id"] == args.ticket), None)
        if not ticket:
            print(f"Ticket '{args.ticket}' not found.")
            sys.exit(1)
        from agent import ShopWaveAgent
        from audit_logger import append_audit
        result = asyncio.run(ShopWaveAgent().solve(ticket))
        append_audit(result, source="cli_single")
        _print_result(result)

    else:
        from orchestrator import run_all
        asyncio.run(run_all())


# ══════════════════════════════════════════════════════════════════════════════
#  CONVERSATIONAL SESSION
# ══════════════════════════════════════════════════════════════════════════════

async def _chat_session():
    """
    Full multi-turn conversational session:
      1. Identify customer (or offer registration)
      2. Handle their queries one by one
      3. Offer product catalog / ordering
      4. Continue until they say goodbye
    """
    from agent import ShopWaveAgent
    from audit_logger import append_audit
    from tools import TOOLS

    agent = ShopWaveAgent()

    _banner()

    # ── Step 1: Identify the customer ─────────────────────────────────────────
    customer = await _identify_or_register(TOOLS)
    if customer is None:
        print("\n  Goodbye! Have a great day!\n")
        return

    name      = customer.get("name", "Customer").split()[0]   # first name
    email     = customer.get("email")
    ticket_no = 1

    print(f"\n  Welcome back, {name}! How can I help you today?")
    print("  (Type 'quit' to exit | 'order' to browse products | 'help' for tips)\n")

    # ── Step 2: Conversation loop ─────────────────────────────────────────────
    while True:
        query = _ask("  You")
        if not query:
            continue
        if query.lower() in ("quit", "exit", "bye", "goodbye", "q"):
            print(f"\n  Thank you for contacting ShopWave, {name}! Have a great day!\n")
            break

        # ── Shortcut: product catalog / ordering ──────────────────────────────
        if _wants_to_order(query):
            await _ordering_flow(email, name, TOOLS, append_audit, ticket_no)
            ticket_no += 1
            print(f"\n  Is there anything else I can help you with, {name}?")
            continue

        # ── Regular support query — send to agent ─────────────────────────────
        ticket_id = f"CHAT-{ticket_no:03d}"
        ticket_no += 1

        ticket = {
            "ticket_id":      ticket_id,
            "customer_email": email,
            "subject":        query[:80],
            "body":           query,
            "source":         "interactive_chat",
        }

        print(f"\n  [Agent is working on {ticket_id}...]")
        result = await agent.solve(ticket)
        append_audit(result, source="interactive_chat")

        # Print the reply the agent sent
        _print_agent_reply(result)

        # Check if agent says customer not found (shouldn't happen — already verified)
        if "CUSTOMER_NOT_FOUND" in result.get("resolution", {}).get("final_action", ""):
            print(f"\n  Hmm, there seems to be an issue finding your account. "
                  f"Please contact support.")

        print(f"\n  Is there anything else I can help you with, {name}?")


async def _identify_or_register(TOOLS) -> dict | None:
    """
    Ask for email → look up customer → if not found, offer registration.
    Returns the customer dict, or None if user quits.
    """
    while True:
        print()
        email = _ask("  Please enter your email address")
        if not email:
            continue
        if email.lower() in ("quit", "exit", "q"):
            return None

        print(f"  Looking up your account...", end="", flush=True)
        customer = await TOOLS["get_customer"](email)
        print()

        # ── Existing customer ─────────────────────────────────────────────────
        if "error" not in customer:
            return customer

        # ── Customer not found — offer registration ───────────────────────────
        print(f"\n  We couldn't find an account for '{email}'.")
        print("  Would you like to create a free ShopWave account?")
        choice = _ask("  (yes / no)").lower()

        if choice in ("yes", "y", "yeah", "sure", "ok", "yep"):
            new_customer = await _registration_flow(email, TOOLS)
            if new_customer:
                return new_customer
            # Registration failed or cancelled — ask again
            continue
        else:
            print("\n  No problem! Feel free to come back anytime.")
            return None


async def _registration_flow(email: str, TOOLS) -> dict | None:
    """Collect name and details, then call register_customer."""
    print("\n  Great! Let's get you set up. (Takes 30 seconds!)")
    print()

    name = _ask("  Full name")
    if not name:
        return None

    phone = _ask("  Phone number (optional, press Enter to skip)")
    city  = _ask("  City (optional, press Enter to skip)")

    print(f"\n  Creating your account...", end="", flush=True)
    result = await TOOLS["register_customer"](
        name=name, email=email, phone=phone or "", city=city or ""
    )
    print()

    if result.get("success"):
        print(f"\n  {result['message']}")
        print(f"  Your account ID : {result['customer_id']}")
        print(f"  Membership tier : Standard")
        print()
        # Return a customer-like dict
        return {
            "customer_id": result["customer_id"],
            "name":        result["name"],
            "email":       email,
            "tier":        "standard",
        }
    else:
        print(f"\n  Registration failed: {result.get('error')}")
        return None


async def _ordering_flow(email: str, name: str, TOOLS, append_audit, ticket_no: int):
    """Show product catalog and let customer place an order."""
    from audit_logger import append_audit as _log

    print(f"\n  Here's what we have in stock, {name}!\n")
    products = await TOOLS["list_products"]()

    # Display catalog
    print(f"  {'#':<4} {'Product':<40} {'Price':>8}  {'Return':>10}  {'Warranty'}")
    print("  " + "-"*78)
    pid_map = {}
    for i, p in enumerate(products, 1):
        warranty = f"{p['warranty_months']}mo" if p["warranty_months"] else "None"
        ret_win  = f"{p['return_window_days']}d"
        print(f"  {i:<4} {p['name']:<40} ${p['price']:>7.2f}  {ret_win:>10}  {warranty}")
        pid_map[str(i)] = p

    print()

    # Choose product
    choice = _ask("  Enter # or product name to order (or 'back' to cancel)")
    if choice.lower() in ("back", "cancel", "quit", ""):
        print("  No problem! Let me know if you need anything else.")
        return

    # Resolve product
    product = None
    if choice in pid_map:
        product = pid_map[choice]
    else:
        # Try name match
        for p in products:
            if choice.lower() in p["name"].lower():
                product = p
                break

    if not product:
        print(f"\n  Sorry, I couldn't find '{choice}' in our catalog.")
        return

    # Choose quantity
    qty_str = _ask(f"  How many '{product['name']}' would you like? (default: 1)")
    try:
        quantity = int(qty_str) if qty_str.strip() else 1
    except ValueError:
        quantity = 1

    # Confirm order
    total = product["price"] * quantity
    print(f"\n  Order Summary:")
    print(f"    Product  : {product['name']}")
    print(f"    Quantity : {quantity}")
    print(f"    Total    : ${total:.2f}")
    print(f"    Delivery : 3-5 business days")

    confirm = _ask("\n  Confirm order? (yes / no)").lower()
    if confirm not in ("yes", "y", "sure", "ok", "yep"):
        print("  Order cancelled. No charges made.")
        return

    print(f"\n  Placing your order...", end="", flush=True)
    result = await TOOLS["place_order"](email=email, product_id=product["product_id"], quantity=quantity)
    print()

    if result.get("success"):
        print(f"\n  {result['message']}")
        print(f"  Order ID : {result['order_id']}")
        print(f"  You can track or cancel using this order ID.\n")
        # Log this as an audit entry
        _log({
            "ticket_id":      f"ORDER-{ticket_no:03d}",
            "metadata": {
                "customer_email": email,
                "subject":        f"New order: {product['name']}",
                "source": "interactive_chat"
            },
            "resolution": {
                "status":         "resolved",
                "final_action":   f"Order {result['order_id']} placed for {product['name']} x{quantity} (${total:.2f})",
                "confidence":     1.0,
                "escalated":      False,
            },
            "system_telemetry": {
                "tool_calls":     ["list_products", "place_order"],
                "total_tool_calls": 2,
                "duration_ms":    0
            },
            "trace":          [],
        })
    else:
        print(f"\n  Sorry, the order could not be placed: {result.get('error')}")


def _wants_to_order(query: str) -> bool:
    """Detect if the user wants to browse or buy products."""
    q = query.lower()
    
    # Exact matches for quick commands
    if q in ("order", "shop", "buy", "catalog", "products"):
        return True
        
    # Exclude typical support queries
    support_keywords = ["cancel", "cancle", "cacle", "where", "track", "refund", "return", "status", "broken", "missing", "wrong", "issue", "help"]
    if any(kw in q for kw in support_keywords):
        return False
        
    # Only match specific buying intents to avoid false positives with the word "order"
    buy_keywords = ["buy something", "purchase", "what do you sell", "what can i buy", "browse", "place an order"]
    return any(kw in q for kw in buy_keywords)


def _print_agent_reply(result: dict):
    """Print the customer-facing reply from the agent."""
    # Find the send_reply tool output
    for step in result.get("trace", []):
        for tc in step.get("tool_results", []):
            if tc.get("tool") == "send_reply" and tc.get("success"):
                msg = tc["result"].get("message_sent", "")
                print()
                print("  " + "-"*58)
                for line in msg.splitlines():
                    print(f"  {line}")
                print("  " + "-"*58)
                return

    # Fallback if no send_reply
    action = result.get("resolution", {}).get("final_action", "")
    if action:
        print(f"\n  Agent: {action}")


def _ask(prompt: str) -> str:
    """Safe input() that handles Ctrl+C."""
    try:
        val = input(f"{prompt}: ").strip()
        return val
    except (KeyboardInterrupt, EOFError):
        print()
        return "quit"


def _banner():
    print()
    print("  " + "="*60)
    print("  |   ShopWave Virtual Support Assistant                    |")
    print("  |   Powered by Gemini 2.5 Flash                          |")
    print("  " + "="*60)
    print()
    print("  Hello! I'm your ShopWave support assistant.")
    print("  I can help with orders, refunds, returns, and more.")


def _print_result(result: dict):
    """Pretty-print for --ticket mode."""
    from pathlib import Path
    print(f"\n  STATUS     : {result.get('resolution', {}).get('status','').upper()}")
    print(f"  CONFIDENCE : {result.get('resolution', {}).get('confidence', 0):.0%}")
    print(f"  TOOLS USED : {', '.join(result.get('system_telemetry', {}).get('tool_calls', []))}")
    print(f"  DURATION   : {result.get('system_telemetry', {}).get('duration_ms', 0)}ms")
    _print_agent_reply(result)
    print(f"\n  Audit log  : output/audit_log.jsonl")


if __name__ == "__main__":
    main()
