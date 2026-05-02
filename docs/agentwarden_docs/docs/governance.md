# AgentWarden — Governance Customisation Guide

How to tune what gets blocked, what gets allowed, and how the pipeline
makes decisions. All customisation happens in YAML files — no code changes,
no rebuild required.

---

## The governance stack

```
config/rules.yaml      ← what is always blocked (Stage 1)
config/tools.yaml      ← tool definitions and risk levels
config/openclaw.yaml   ← which tools are exposed per task type
agentwarden.yaml        ← pipeline stages and thresholds
```

Edit → save → restart proxy. That's it.

```bash
# Apply config changes
docker compose restart agentwarden

# Verify changes loaded
docker exec agentwarden_proxy python3 -c "
from agentwarden.policies.rules import RuleBasedPolicy
p = RuleBasedPolicy()
print('always_block:', sorted(p.always_block))
print('arg_patterns:', len(p._arg_pats))
print('classifier_skip:', sorted(p.classifier_skip))
"
```

---

## Stage 1 — Customising rules

### Add a tool to always-block

Edit `config/rules.yaml`:

```yaml
always_block:
  - exec          # already there
  - my_tool       # ← add your tool here
```

Any tool call with name `my_tool` is blocked immediately, 0.1ms, no LLM needed.

### Block a tool only when its arguments match a pattern

Use `arg_patterns` to block based on what the tool is doing, not just its name:

```yaml
arg_patterns:
  # Block web_fetch when fetching internal IPs
  - pattern: "192\\.168\\."
    description: "Private network access attempt"
    severity: high

  # Block write when path targets sensitive locations
  - pattern: "/etc/|/root/|/home/.*/.ssh"
    description: "Sensitive path write attempt"
    severity: critical

  # Block any tool when arguments contain base64-encoded payloads
  - pattern: "base64\\s+-d\\s*\\|"
    description: "Base64 decode pipe — shellcode delivery pattern"
    severity: critical
```

Patterns are Python regex, case-insensitive, matched against all argument values concatenated.

### Add a custom injection pattern

Inject patterns apply to the system prompt content:

```yaml
injection_patterns:
  - pattern: "you are now in developer mode"
    description: "Developer mode jailbreak"

  - pattern: "print your (system )?prompt"
    description: "System prompt extraction attempt"

  - pattern: "output everything (above|before) this"
    description: "Context extraction attempt"
```

### Allow a tool to skip Stage 2 (speed it up)

If a tool is always safe regardless of arguments, add it to `classifier_skip`:

```yaml
classifier_skip:
  - read
  - web_search
  - my_safe_readonly_tool    # ← add here to skip LLM classification
```

**Only add genuinely safe tools here.** The classifier catches semantic misuse — `write` with an HTTP server payload, for example. Safe tools are reads, searches, memory operations.

---

## Stage 2 — Tuning the classifier

### Change the confidence threshold

Lower threshold = block more aggressively (more false positives).
Higher threshold = block less (may miss some dangerous calls).

```yaml
# agentwarden.yaml
stages:
  classifier:
    threshold: 0.85    # default — balanced
    # threshold: 0.70  # aggressive — more false positives
    # threshold: 0.95  # conservative — fewer false positives
```

### Swap the classifier model

```yaml
stages:
  classifier:
    model: gemma4:e4b      # stronger, slower (~2s)
    # model: qwen2.5:1.5b  # faster, weaker (~800ms)
    # model: agentwarden-router  # fine-tuned, fastest (~200ms)
```

Or use a fine-tuned GGUF model:
```yaml
stages:
  classifier:
    model_path: /path/to/your-fine-tuned-model.gguf
```

### Disable Stage 2 entirely (rules only)

```yaml
stages:
  classifier:
    enabled: false
```

Or via env var: `AGENTWARDEN_DISABLE_CLASSIFIER=true`

Stage 1 (rules) still runs. Use this if you need maximum speed and your rules are comprehensive.

---

## Stage 3 — Semantic filter

Stage 3 is disabled by default. Enable it when you need to catch dangerous content in natural language responses — not just tool calls.

### Enable

```yaml
# agentwarden.yaml
stages:
  semantic_filter:
    enabled: true
    model: llama-guard3      # pull: ollama pull llama-guard3
    threshold: 0.7
    timeout_ms: 30000
```

Or via env var: `AGENTWARDEN_SEMANTIC_FILTER=true`

### Llama Guard 3 categories

Llama Guard 3 classifies responses into safety categories:

| Code | Category | Example |
|------|----------|---------|
| S1 | Violent Crimes | Instructions for physical violence |
| S2 | Non-Violent Crimes | Fraud, theft instructions |
| S3 | Sex-Related Crimes | — |
| S4 | Child Sexual Exploitation | — |
| S5 | Defamation | — |
| S6 | Specialised Advice | Unsafe medical/legal/financial advice |
| S7 | Privacy | PII extraction, doxxing |
| S8 | Intellectual Property | — |
| S9 | Indiscriminate Weapons | WMD instructions |
| S10 | Hate | — |
| S11 | Suicide/Self-Harm | — |
| S12 | Sexual Content | — |
| S13 | Elections | — |
| S14 | Code Interpreter Abuse | Reverse shells, malware |

For agent governance, S14 (Code Interpreter Abuse) is the most relevant.
A bind shell prompt triggering S14 at 0.95 confidence was caught in our evaluation.

### Use a different model for Stage 3

```yaml
stages:
  semantic_filter:
    model: gemma4:e4b        # general model with safety training
    backend: ollama
```

---

## Stage 4 — RL Policy

The RL policy is the capability governor — it decides which tools the agent is allowed to use per session, based on task type and trust level.

### Enable with trained weights

```yaml
stages:
  rl_policy:
    enabled: true
    model_path: /path/to/best_model.zip    # from PPO training
```

Or via env var: `AGENTWARDEN_ENABLE_RL_POLICY=true` and `AGENTWARDEN_RL_MODEL_PATH=/path/to/model`.

### YAML fallback (no weights needed)

If the PPO model is unavailable or collapsed, the policy uses static YAML defaults:

```python
# Default tool sets per task type (from rl_policy.py)
YAML_FALLBACK = {
    TaskType.SUMMARISATION: {"read", "memory_get", "memory_search", "web_search"},
    TaskType.FILE_READ:     {"read", "memory_get", "memory_search"},
    TaskType.WEB_RESEARCH:  {"web_search", "web_fetch", "read", "memory_get"},
    TaskType.CODE_EXECUTION:{"read", "write", "edit", "web_search"},
    TaskType.EMAIL:         {"read", "web_search", "sessions_send"},
    TaskType.UNKNOWN:       {"read", "web_search", "memory_get", "memory_search"},
}
```

Customise the fallback by editing `agentwarden/policies/rl_policy.py` — no rebuild needed if the file is mounted as a volume.

---

## Shadow mode — safe onboarding

Before enforcing governance, run in shadow mode to understand what would be blocked:

```bash
# Start in observe-only mode
AGENTWARDEN_SHADOW_MODE=true docker compose up -d agentwarden

# Run your agent normally for a few days
# Then review what would have been blocked
docker exec agentwarden_proxy sqlite3 /app/audit/agentwarden_audit.db \
  "SELECT tool_name, decision, reason_detail, COUNT(*) as count
   FROM audit_log
   WHERE decision = 'BLOCK'
   GROUP BY tool_name, reason_detail
   ORDER BY count DESC;"
```

If legitimate tool calls would be blocked (false positives):
1. Add the tool to `classifier_skip` in `config/rules.yaml`
2. Or raise the classifier `threshold` in `agentwarden.yaml`
3. Or remove the tool from `always_block` if it's been added incorrectly

Then switch to enforcement:
```bash
AGENTWARDEN_SHADOW_MODE=false docker compose up -d agentwarden
```

---

## Task profiles (OpenClaw)

For OpenClaw, you can define which tools are exposed per task type.
This is a semantic-level control that complements the pipeline blocks.

Edit `config/openclaw.yaml`:

```yaml
task_profiles:
  my_custom_task:
    description: "Custom task type for my use case"
    allowed_tools:
      - read
      - web_search
      - memory_get
      - my_custom_tool
    blocked_tools:
      - exec
      - sessions_spawn
```

The profile injects an AGENTS.md preamble into the OpenClaw workspace telling the agent which tools it has access to — semantic governance on top of the infrastructure-level blocks.

---

## Per-environment configurations

### Development — permissive, detailed logging

```yaml
# agentwarden.yaml
shadow_mode: true        # observe only, never block
stages:
  classifier:
    threshold: 0.95      # conservative — fewer false positives
server:
  log_level: DEBUG
```

### Staging — enforce with detailed audit

```yaml
shadow_mode: false
stages:
  classifier:
    threshold: 0.85
  semantic_filter:
    enabled: true        # catch response-level issues
server:
  log_level: INFO
audit:
  log_allowed: true      # log everything for analysis
  log_blocked: true
```

### Production — strict, minimal logging overhead

```yaml
shadow_mode: false
stages:
  rules:
    enabled: true
  classifier:
    enabled: true
    model: agentwarden-router    # fastest model
    threshold: 0.85
  semantic_filter:
    enabled: false              # disable unless needed — saves latency
server:
  log_level: WARNING            # only errors and blocks
audit:
  log_allowed: false            # only log blocks
  log_blocked: true
```

---

## Governance customisation checklist

Before going to production:

- [ ] Review `config/rules.yaml` — are the always-block tool names correct for your agent?
- [ ] Test with `shadow_mode: true` for at least a day — review false positives
- [ ] Check `classifier_skip` — are you skipping too many tools? Too few?
- [ ] Verify `arg_patterns` cover your threat model (SSRF, credential paths, injection)
- [ ] If using Stage 3, confirm `ollama pull llama-guard3` is done
- [ ] Set `AGENTWARDEN_LOG_LEVEL=INFO` — you need visibility into blocks
- [ ] Check the audit DB is being written: `ls -la /app/audit/`
- [ ] Run `scripts/eval_runner.py` with your model to confirm 0% error rate

---

## Testing your customisations

Always test governance changes before deploying:

```bash
# Test rules in isolation (no Docker rebuild)
docker exec agentwarden_proxy python3 -c "
from agentwarden.policies.rules import RuleBasedPolicy
from agentwarden.core.models import AgentWardenToolRequest, ToolCall, GovernanceContext, Runtime

p = RuleBasedPolicy()

# Test your new always_block tool
from agentwarden.core.models import GovernanceContext, Runtime
ctx = GovernanceContext(runtime=Runtime.OPENCLAW)

for tool, args in [
    ('my_tool', {'param': 'value'}),           # should be blocked
    ('read', {'path': 'README.md'}),           # should be allowed
    ('web_fetch', {'url': 'file:///etc/passwd'}), # should be blocked (arg pattern)
]:
    req = AgentWardenToolRequest(
        tool_call=ToolCall(name=tool, arguments=args),
        context=ctx, raw_response_body={}
    )
    d = p.evaluate(req)
    print(f'{tool:20} → {d.decision.value:5} | {d.reason_detail or \"ok\"}')
"
```
