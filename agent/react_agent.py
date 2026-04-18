"""
Core ReAct Agent — implements the Think → Act → Observe loop.

The agent:
1. Analyses the ticket with an LLM (Gemini)
2. Decides which tool to call
3. Executes the tool, observes the result
4. Repeats until it can send a final reply or escalate
5. Tracks confidence and auto-escalates if < 0.6
"""
import asyncio
import json
import re
from datetime import datetime
from typing import Any

from google import genai
from google.genai import types

from pydantic import ValidationError
from .schemas import ToolCall, FinalResolution
from tools import TOOLS

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an Autonomous Support Resolution Agent for ShopWave.

Your job is NOT to chat. Your job is to RESOLVE support tickets using tools, policies, and structured reasoning.

You MUST follow a ReAct-style reasoning loop:
THINK → ACT (tool call) → OBSERVE → repeat until resolution.

━━━━━━━━━━━━━━━━━━━━━━━
🎯 CORE OBJECTIVE
━━━━━━━━━━━━━━━━━━━━━━━
For every ticket:
1. Understand the issue
2. Retrieve required data using tools
3. Apply company policies strictly
4. Take action (refund / reply / cancel / escalate)
5. Log reasoning and decisions

You MUST NOT guess. Always verify using tools.

━━━━━━━━━━━━━━━━━━━━━━━
🧰 AVAILABLE TOOLS
━━━━━━━━━━━━━━━━━━━━━━━
You can use these tools:

READ:
- get_customer(email)
- get_order(order_id)
- get_orders_by_customer(email)
- get_product(product_id)
- list_products()
- search_knowledge_base(query)

ACT:
- register_customer(name, email, phone, city)
- place_order(email, product_id, quantity)
- check_refund_eligibility(order_id)
- issue_refund(order_id, amount)
- cancel_order(order_id)
- send_reply(ticket_id, message)
- escalate(ticket_id, summary, priority)

IMPORTANT:
- issue_refund is IRREVERSIBLE → ALWAYS check eligibility first
- You MUST use at least 3 tools before making a final decision

━━━━━━━━━━━━━━━━━━━━━━━
⚠️ STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━

1. TOOL USAGE RULE
- Do NOT answer directly without using tools
- Minimum 3 tool calls per ticket

2. POLICY RULE
- Always follow knowledge base policies
- Never invent rules

3. SAFETY RULE
- Never issue refund without eligibility check
- Never trust customer claims without verification

4. EXPLAINABILITY RULE
- Every decision must be explainable
- Maintain structured reasoning

━━━━━━━━━━━━━━━━━━━━━━━
🧠 DECISION LOGIC
━━━━━━━━━━━━━━━━━━━━━━━

You must classify the ticket into one of:
- refund_request
- return_request
- warranty_claim
- cancellation
- product_issue
- general_query
- fraud_risk
- ambiguous

Then decide action:

REFUND → only if eligible  
REPLY → if informational  
CANCEL → if order in processing  
ESCALATE → if uncertain or restricted  

━━━━━━━━━━━━━━━━━━━━━━━
🚨 ESCALATION RULES (CRITICAL)
━━━━━━━━━━━━━━━━━━━━━━━

You MUST escalate if:

- Warranty claim
- Customer requests replacement (not refund)
- Refund amount > $200
- Tool fails after retries
- Data is missing or conflicting
- Fraud / legal threat detected
- Confidence < 0.6

━━━━━━━━━━━━━━━━━━━━━━━
🧾 ESCALATION FORMAT (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━

When escalating, summary MUST be structured:

{
  "issue": "...",
  "customer_email": "...",
  "order_id": "...",
  "actions_taken": [...],
  "reason_for_escalation": "...",
  "recommended_action": "...",
  "priority": "low | medium | high | urgent"
}

━━━━━━━━━━━━━━━━━━━━━━━
📊 CONFIDENCE SCORING
━━━━━━━━━━━━━━━━━━━━━━━

After decision, assign confidence (0.0–1.0):

- High confidence → clear policy + valid data
- Medium → minor uncertainty
- Low (<0.6) → MUST escalate

━━━━━━━━━━━━━━━━━━━━━━━
🧯 FAILURE HANDLING
━━━━━━━━━━━━━━━━━━━━━━━

If tool fails:
- Retry up to 3 times (exponential backoff)
- If still failing → escalate

Never crash. Always recover.

━━━━━━━━━━━━━━━━━━━━━━━
🧠 SPECIAL CASES
━━━━━━━━━━━━━━━━━━━━━━━

- VIP customers → allow exceptions (check notes)
- Premium → small flexibility
- Standard → strict policy

- If order already refunded → DO NOT refund again
- If order not found → ask for correct details (Include CUSTOMER_NOT_FOUND in final_action so system can register)
- If ambiguous → ask clarifying questions

━━━━━━━━━━━━━━━━━━━━━━━
📤 OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━

When calling a tool, return this JSON:
{
  "thought": "step-by-step reasoning",
  "action": "tool_name",
  "action_input": { "arg1": "value" },
  "confidence": 0.0-1.0
}

When resolving the ticket (after calling send_reply or escalate), always produce structured output:

{
  "ticket_id": "...",
  "decision": "refund | reply | cancel | escalate",
  "reasoning": ["..."],
  "tool_calls": ["..."],
  "final_action": "...",
  "confidence": 0.0-1.0
}

━━━━━━━━━━━━━━━━━━━━━━━
🚫 WHAT NOT TO DO
━━━━━━━━━━━━━━━━━━━━━━━

- Do NOT give direct answers without tools
- Do NOT hallucinate policies
- Do NOT skip reasoning
- Do NOT ignore escalation rules

━━━━━━━━━━━━━━━━━━━━━━━
🏁 GOAL
━━━━━━━━━━━━━━━━━━━━━━━

Act like a production-grade autonomous agent:
- Accurate
- Safe
- Explainable
- Deterministic when needed

If unsure → ESCALATE, not guess.
"""


class ShopWaveAgent:
    """A single-ticket ReAct agent with retry logic and confidence scoring."""

    MAX_STEPS = 12
    MAX_RETRIES = 3
    CONFIDENCE_ESCALATION_THRESHOLD = 0.6

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name
        self.client = genai.Client()
        self.state = {
            "eligibility_checked": set()
        }

    async def _call_llm(self, messages: list[dict]) -> str:
        """Call Gemini with exponential backoff retry (handles 429 rate limits)."""
        prompt_parts = [f"[SYSTEM]\n{SYSTEM_PROMPT}"]
        for msg in messages:
            role = msg["role"].upper()
            prompt_parts.append(f"[{role}]\n{msg['content']}")
        full_prompt = "\n\n".join(prompt_parts)

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=1024,
                    )
                )
                return response.text.strip()
            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                wait = (2 ** attempt) * 5   # 5s, 10s, 20s
                if attempt < self.MAX_RETRIES - 1 and is_rate_limit:
                    print(f"  [RETRY] Rate limit hit - retrying in {wait}s (attempt {attempt+1}/{self.MAX_RETRIES})...")
                    await asyncio.sleep(wait)
                else:
                    raise   # Re-raise so solve() catches it

    def _parse_llm_output(self, raw: str) -> dict:
        """Extract JSON from LLM output and validate against Pydantic schemas."""
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        parsed_dict = None
        try:
            parsed_dict = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    parsed_dict = json.loads(match.group())
                except json.JSONDecodeError:
                    raise ValueError(f"Could not parse LLM output as JSON:\n{raw}")
            else:
                raise ValueError(f"Could not parse LLM output as JSON:\n{raw}")
                
        # Validate with Pydantic
        if "decision" in parsed_dict:
            return FinalResolution.model_validate(parsed_dict).model_dump()
        else:
            return ToolCall.model_validate(parsed_dict).model_dump()

    async def _execute_tool(self, tool_name: str, tool_input: dict, step_log: list) -> Any:
        """Execute a tool with exponential backoff retry and deterministic guardrails."""
        tool_fn = TOOLS.get(tool_name)
        if not tool_fn:
            return {"error": f"Unknown tool '{tool_name}'"}

        # ── DETERMINISTIC GUARDRAILS ──
        if tool_name == "issue_refund":
            order_id = tool_input.get("order_id")
            amount = tool_input.get("amount", 0.0)
            
            if order_id not in self.state["eligibility_checked"]:
                result = {"error": "SYSTEM BLOCK: You must call check_refund_eligibility first AND it must be eligible."}
                step_log.append({"tool": tool_name, "input": tool_input, "result": result, "attempt": 1, "success": False, "blocked": True})
                return result
                
            try:
                if float(amount) > 200.0:
                    result = {"error": "SYSTEM BLOCK: Refund exceeds $200 threshold. You MUST escalate."}
                    step_log.append({"tool": tool_name, "input": tool_input, "result": result, "attempt": 1, "success": False, "blocked": True})
                    return result
            except (ValueError, TypeError):
                pass

        for attempt in range(self.MAX_RETRIES):
            try:
                result = await tool_fn(**tool_input)
                
                # ── STATE TRACKING ──
                if tool_name == "check_refund_eligibility" and result.get("eligible"):
                    self.state["eligibility_checked"].add(tool_input.get("order_id"))
                    
                step_log.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                    "attempt": attempt + 1,
                    "success": True
                })
                return result
            except (TimeoutError, ConnectionError, Exception) as e:
                wait = 2 ** attempt   # 1s, 2s, 4s
                step_log.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "error": str(e),
                    "attempt": attempt + 1,
                    "success": False,
                    "retry_wait_s": wait
                })
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
                else:
                    return {
                        "error": f"Tool '{tool_name}' failed after {self.MAX_RETRIES} attempts: {e}"
                    }

    async def solve(self, ticket: dict) -> dict:
        """
        Run the ReAct loop for a single ticket.
        Returns a full audit record for this ticket.
        """
        ticket_id = ticket.get("ticket_id", "UNKNOWN")
        start_time = datetime.utcnow()

        # Build initial user message
        user_message = (
            f"TICKET ID: {ticket_id}\n"
            f"FROM: {ticket.get('customer_email', 'unknown')}\n"
            f"SUBJECT: {ticket.get('subject', '')}\n"
            f"MESSAGE:\n{ticket.get('body', '')}\n\n"
            "Please resolve this support ticket. Start by identifying the customer and their order."
        )

        messages = [{"role": "user", "content": user_message}]
        steps = []
        tool_calls_made = []
        confidence = 0.5
        escalated = False
        final_summary = ""

        for step_num in range(self.MAX_STEPS):
            # ── LLM decides what to do ─────────────────────────────────────
            try:
                raw_output = await self._call_llm(messages)
                parsed = self._parse_llm_output(raw_output)
            except Exception as e:
                steps.append({"step": step_num, "error": f"LLM parse error: {e}", "raw": raw_output if 'raw_output' in dir() else ""})
                break

            # Try to map new "final output" format format to the old expected fields
            action = parsed.get("action")
            if not action and "decision" in parsed:
                action = "finish"
                parsed["action"] = "finish"
                
                reasoning = parsed.get("reasoning", [])
                if isinstance(reasoning, list):
                    parsed["thought"] = "\n".join(reasoning)
                else:
                    parsed["thought"] = str(reasoning)
                    
                parsed["final_summary"] = parsed.get("final_action", "")
            elif not action:
                action = "finish"

            action_input = parsed.get("action_input", {})
            thought = parsed.get("thought", "")
            confidence = float(parsed.get("confidence", 0.5))
            needs_escalation = parsed.get("needs_escalation", False)
            final_summary = parsed.get("final_summary", "")

            step_record = {
                "step": step_num + 1,
                "thought": thought,
                "action": action,
                "action_input": action_input,
                "confidence": confidence,
                "tool_results": []
            }

            # Append LLM's thought to conversation
            messages.append({"role": "assistant", "content": raw_output})

            # ── Auto-escalate if confidence is too low ─────────────────────
            if confidence < self.CONFIDENCE_ESCALATION_THRESHOLD and action != "finish":
                needs_escalation = True

            # ── Check if done ──────────────────────────────────────────────
            if action == "finish":
                steps.append(step_record)
                break

            # ── Execute the tool ───────────────────────────────────────────
            if action in TOOLS:
                tool_result = await self._execute_tool(action, action_input, step_record["tool_results"])
                tool_calls_made.append(action)

                # Feed result back to LLM
                observation = json.dumps(tool_result, default=str, indent=2)
                messages.append({
                    "role": "user",
                    "content": f"[TOOL RESULT: {action}]\n{observation}\n\nContinue resolving the ticket."
                })
            else:
                messages.append({
                    "role": "user",
                    "content": f"[ERROR] Unknown action '{action}'. Use only the listed tools or 'finish'."
                })
            # ── DYNAMIC ESCALATION RULES ──
            if not needs_escalation and step_record["tool_results"]:
                for res in step_record["tool_results"]:
                    if res.get("blocked", False) or "SYSTEM BLOCK" in str(res.get("error", "")):
                        needs_escalation = True
                    result_data = res.get("result")
                    if isinstance(result_data, dict) and "warranty" in str(result_data).lower():
                        if res.get("tool") != "search_knowledge_base":
                            needs_escalation = True

            steps.append(step_record)

            # ── If agent is forced to escalate, execute it then finish ─────────
            if needs_escalation and "escalate" not in tool_calls_made:
                await self._execute_tool("escalate", {
                    "ticket_id": ticket_id,
                    "summary": f"{thought[:300]} [AUTO-ESCALATED BY SYSTEM SAFEGUARDS]",
                    "priority": "high" if confidence < 0.4 else "medium"
                }, [])
                tool_calls_made.append("escalate")
                escalated = True
                break
        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return {
            "ticket_id": ticket_id,
            "metadata": {
                "customer_email": ticket.get("customer_email"),
                "subject": ticket.get("subject"),
                "received_at": start_time.isoformat() + "Z"
            },
            "resolution": {
                "status": "escalated" if escalated else "resolved",
                "final_action": final_summary or (f"Escalated to human team" if escalated else "Processed"),
                "confidence": confidence,
                "escalated": escalated,
            },
            "trace": steps,
            "system_telemetry": {
                "total_tool_calls": len(tool_calls_made),
                "tool_calls": tool_calls_made,
                "duration_ms": duration_ms
            }
        }
