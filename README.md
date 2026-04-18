# ShopWave Autonomous Support Agent 🚀

**An enterprise-grade, production-ready AI Support Agent built for the Agentic AI Hackathon 2026.**

ShopWave is a fully autonomous, fault-tolerant support agent powered by a **Hybrid Deterministic ReAct Architecture**. It utilizes Gemini 2.5 Flash to understand natural language customer requests while relying on strict deterministic Python guardrails to enforce absolute policy compliance, validate outputs effortlessly, and generate secure audit records.

---

## ✨ Cutting-Edge Architectural Features

### 1. Hybrid Deterministic Agent (The "Gateway" Pattern)
Instead of trusting the LLM blindly via prompting (e.g. *"Never refund without checking eligibility"*), we actuate a **Python-layer Guardrail Gateway** that intercepts the ReAct loop:
- **Eligibility Checking State Tracker:** If the LLM tries to execute a refund without validating eligibility first, it is strictly blocked, and the system forces the LLM to execute the correct prerequisite sequence.
- **Refund Thresholds Enforced:** Refunds above $200 are hard-stopped by the gateway and auto-escalated, regardless of the LLM's opinion.

### 2. Strict Pydantic Output Validation
Regex JSON parsing is dead. ShopWave securely filters all LLM decisions through strictly typed `Pydantic` schemas (`ToolCall` and `FinalResolution`).
- **Self-Healing Execution:** If Gemini hallucinates unsupported fields, `ValidationError`s are seamlessly caught, logged as internal system warnings, and the prompt is re-fed allowing the AI to naturally correct its format.

### 3. Smart Escalation Engine 
Escalations are decoupled from simplistic "LLM Confidence" rules. Our python engine reads the responses at the observation layer:
- Force-triggers an escalation immediately if the word `"warranty"` appears in knowledge searches.
- Force-triggers an escalation when systemic blocks flag suspicious sequential behavior.

### 4. Enterprise Audit Logging (JSONL)
The agent features a completely structured diagnostic footprint. Every completed ticket guarantees metadata mapping into a `output/audit_log.jsonl` append-only database, categorized by:
- `metadata` (email, timestamp, source)
- `resolution` (status, confidence, decision)
- `trace` (complete execution mapping of tool usages)
- `system_telemetry` (latency footprints, LLM tool iterations)

### 5. Multi-Channel Interactive State Machine
The CLI doesn't just evaluate sample tickets—it's a persistent conversational pipeline. Run `python main.py --ask` to interact natively as a customer. The heuristic-router intelligently identifies context:
- Automatically handles new user registration if no account is found.
- Detects exact navigation shortcuts for shopping vs natural language.
- Generates dynamic product tables for direct shopping checkout.
- Intelligently differentiates typos like `"I want to cacle my order"` and bypasses shopping sub-routines straight into complex Agent processing.

---

## 🛠️ Installation & Setup

1. **Clone the repository.**
2. **Install requirements:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure your API keys:**
   Create a `.env` file in the root directory and add your key:
   ```env
   GOOGLE_API_KEY="your-gemini-key-here"
   ```

---

## 🚀 How to Run

The central execution orchestrator supports four distinct modes:

**1. Interactive Conversational Mode** 
Have a native, persistent chat with the agent where you can register, shop, or open cases.
```bash
python main.py --ask
```

**2. Fast API Server** 
Expose the agent to external clients over standard network interfaces. Connects natively with our comprehensive `/audit` dashboards.
```bash
python main.py --serve
```

**3. Test a Single Ticket** 
Immediately test the structural execution format step-by-step from the testing matrix.
```bash
python main.py --ticket TKT-001
```

**4. Full Batch Processing**
Process all sample mock tickets at max concurrency simulating production loads.
```bash
python main.py
```

---

**Built with resilience in mind. Zero hallucinations. Maximum safety.**
