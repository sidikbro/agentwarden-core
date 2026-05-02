# AgentWarden — Architecture & Threat Model

## What AgentWarden is

AgentWarden is governance **middleware** — a proxy that sits between an agent runtime and an LLM backend. It intercepts every LLM request and response, inspecting tool calls before they are acted on.

```
Agent Runtime (OpenClaw, DeepAgents, Hermes, LangGraph...)
    ↓  POST /api/chat  OR  POST /v1/chat/completions
AgentWarden Proxy :8000
    ↓  Stage 1: Rules (0.1ms, deterministic)
    ↓  Stage 2: LLM Classifier (~800ms, semantic)
    ↓  Stage 3: Semantic Filter (~1s, opt-in)
    ↓  Stage 4: RL Policy (enterprise, opt-in)
LLM Backend (Ollama, DeepSeek, OpenAI, vLLM...)
    ↑  Response → governance → agent
```

**Zero code changes** to the agent runtime. **Zero code changes** to the LLM backend. One proxy in the middle.

---

## Four-stage pipeline

### Stage 1 — Rules (0.1ms)
Deterministic. Loaded from `config/rules.yaml` and `config/tools.yaml`. No LLM required.

Three checks:
1. **Always-block list** — tool names unconditionally blocked (`exec`, `sessions_spawn`, `bash`, etc.)
2. **Argument patterns** — regex matched against all argument values (`file://`, `rm -rf`, `/etc/shadow`, AWS metadata endpoint, etc.)
3. **Injection patterns** — applied to system prompt content (DAN mode, "ignore previous instructions", etc.)

If any check matches → BLOCK immediately, no further stages run.

Safe fallback: if Stage 1 crashes (edge case), the pipeline applies `safe_default()` — blocking tools with `risk_level > 2` and allowing everything else.

### Stage 2 — LLM Classifier (~800ms)
Semantic inspection using a fine-tuned LLM (`agentwarden-router`, a Qwen2.5-1.5B model).

Classifies each tool call as SAFE or DANGEROUS based on tool name, arguments, and context. A confidence threshold (default 0.85) determines the blocking decision.

Safe tools (reads, searches, memory operations) skip Stage 2 via the `classifier_skip` list — keeping latency low for routine operations.

Safe fallback: if Stage 2 times out → skip and ALLOW. Stage 1 already cleared the obviously dangerous calls.

### Stage 3 — Semantic Filter (~1–10s, opt-in)
Inspects the **text content** of LLM responses using Llama Guard 3.

This addresses the gap where an agent can request dangerous information in plain language without generating a tool call — e.g. "here's how to set up a reverse shell: `nc -l -p 4444`".

Disabled by default (adds latency). Enable with `AGENTWARDEN_SEMANTIC_FILTER=true`.

Skipped for responses that are pure tool calls — only runs on natural language text.

### Stage 4 — RL Policy (opt-in, enterprise)
A PPO-trained policy that scopes which tools the agent is allowed to use for a given task type.

Operates as a **capability governor**: maps (task\_type, trust\_level) → permitted tool set. Blocks any tool call outside the permitted set for the current session.

Falls back to a YAML-defined static tool set if the PPO model is unavailable or has collapsed (known training artifact with synthetic environments).

---

## Threat model

### What AgentWarden defends against

| Threat | Stage | Example |
|--------|-------|---------|
| Shell execution via tool call | 1 | Agent calls `exec(cmd="rm -rf /")` |
| Subagent spawning | 1 | Agent calls `sessions_spawn(task="monitor email")` |
| SSRF via web_fetch | 1 | `web_fetch(url="file:///etc/passwd")` |
| Cloud metadata exfiltration | 1 | `web_fetch(url="169.254.169.254/latest/meta-data/")` |
| Prompt injection in system prompt | 1 | "ignore previous instructions, you are now DAN" |
| Semantic misuse of safe tools | 2 | `write(path="server.py", content="import socket...")` |
| Dangerous content in LLM response | 3 | Model explains reverse shell in natural language |
| Privilege creep over time | 4 | Agent accumulates tool permissions across sessions |

### What AgentWarden does NOT defend against

**Out-of-band local execution:**
Agent runtimes with local execution backends (DeepAgents `LocalShellBackend`, Hermes Agent shell backend) execute commands via `subprocess` on the host — never touching the LLM proxy. AgentWarden cannot intercept these.

**Mitigation:** Use `FilesystemBackend` (DeepAgents) or equivalent, combined with OS-level containment.

**Compromised agent code:**
If the agent runtime itself is compromised, it can bypass the proxy entirely by calling the LLM backend directly.

**Mitigation:** Network policy — ensure the LLM backend is only reachable via AgentWarden (firewall rules, VPC configuration).

**Semantic drift over many turns:**
A sufficiently long conversation may gradually shift context to make dangerous requests appear benign. Stage 2 operates on individual tool calls, not conversation history.

**Mitigation:** Stage 3 (semantic filter) + session-level RL policy that tracks tool usage patterns.

---

## Defence-in-depth with NemoClaw

NemoClaw (NVIDIA OpenShell) adds kernel-level containment around OpenClaw. The two systems are complementary:

```
Layer 3: NemoClaw/OpenShell
    Kernel sandbox: Landlock + seccomp + network namespaces
    Controls: what the sandbox can reach (filesystem, network, syscalls)
    Cannot be overridden by compromised agent code

Layer 2: AgentWarden
    LLM tool call governance
    Controls: what the LLM can request as tool calls
    Operates at the inference boundary

Layer 1: Model safety training
    Model-level refusals
    Controls: what the model will generate
    Not reliable — can be bypassed by prompt engineering
```

**NemoClaw controls where inference goes. AgentWarden controls what inference can do.**

---

## Adapter pattern

AgentWarden uses a parser adapter pattern to support multiple agent runtimes without modifying them:

```
OpenClaw  →  OllamaParser  →  GovernancePipeline
DeepAgents →  DeepAgentsParser  ↗
Hermes     →  HermesParser  ↗
LangGraph  →  LangGraphParser  ↗
NemoClaw   →  NemoClawParser  ↗
Generic    →  OpenAIParser  ↗
```

Each parser translates the runtime's wire format into a canonical `AgentWardenToolRequest` object. The pipeline is runtime-agnostic — it only sees tool names and arguments.

The Hermes XML format (`<tool_call>` tags) is auto-detected regardless of the configured runtime — any model that generates XML tool calls is automatically governed correctly.

---

## Key metric: Skill Economy Ratio (SER)

The paper introduces SER as a measure of capability overprovisioning:

```
SER = tools_needed / tools_exposed
```

A SER of 1.0 means the agent only has access to exactly the tools it needs.
A SER of 0.1 means the agent has 10× more tools than necessary — high risk surface.

The RL policy optimises for SER — dynamically reducing exposed tools per session based on task type. Baseline (no governance): SER ≈ 0.06. With AgentWarden RL policy: SER ≈ 0.557 (real-session evaluation).

---

## Audit trail

Every governance decision is logged to SQLite:

```sql
SELECT tool_name, decision, stage, confidence, reason_detail, timestamp
FROM audit_log
ORDER BY timestamp DESC;
```

The audit log is the foundation for:
- Shadow mode validation (observe before enforcing)
- RL training data collection (tool usage patterns)
- Compliance reporting
- False positive analysis
