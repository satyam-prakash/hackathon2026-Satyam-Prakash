"""
Main entry point — run the agent from CLI.

Usage:
  python main.py                    # batch process all 20 sample tickets
  python main.py --serve            # start the FastAPI server
  python main.py --ticket TKT-001   # process a single sample ticket
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

# Load .env file automatically — GOOGLE_API_KEY can be stored there
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="ShopWave Autonomous Support Agent")
    parser.add_argument("--serve", action="store_true", help="Start the FastAPI API server")
    parser.add_argument("--ticket", type=str, help="Process a single ticket ID from sample data")
    parser.add_argument("--port", type=int, default=8000, help="API server port (default: 8000)")
    args = parser.parse_args()

    # Validate API key
    if not os.getenv("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY environment variable is not set.")
        print("  Set it with:  $env:GOOGLE_API_KEY = 'your-key-here'")
        sys.exit(1)

    if args.serve:
        # Start FastAPI server
        import uvicorn
        print(f"\n🚀 Starting ShopWave Agent API on http://localhost:{args.port}")
        print(f"   Docs: http://localhost:{args.port}/docs\n")
        uvicorn.run("api.server:app", host="0.0.0.0", port=args.port, reload=False)

    elif args.ticket:
        # Single ticket mode
        import json
        from pathlib import Path
        from google import genai

        data_path = Path(__file__).parent / "data" / "tickets.json"
        tickets = json.loads(data_path.read_text())
        ticket = next((t for t in tickets if t["ticket_id"] == args.ticket), None)
        if not ticket:
            print(f"Ticket '{args.ticket}' not found in sample data.")
            sys.exit(1)

        from agent import ShopWaveAgent
        result = asyncio.run(ShopWaveAgent().solve(ticket))
        print(json.dumps(result, indent=2, default=str))

    else:
        # Default: batch all tickets
        from orchestrator import run_all
        asyncio.run(run_all())


if __name__ == "__main__":
    main()
