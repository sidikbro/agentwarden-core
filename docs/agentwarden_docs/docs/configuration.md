# AgentWarden — Configuration Reference

All configuration is YAML-driven. Nothing is hardcoded in Python.
Edit config files and restart the proxy — no rebuild required.

## Configuration files

| File | Purpose |
|------|---------|
| `agentwarden.yaml` | Master config — stages, providers, server |
| `config/rules.yaml` | Always-block lists, arg patterns, injection patterns |
| `config/tools.yaml` | Tool registry — risk levels, metadata |
| `config/openclaw.yaml` | OpenClaw-specific task profiles |

## Priority order

Highest to lowest:
1. Environment variables
2. `agentwarden.yaml`
3. Built-in defaults

---

## agentwarden.yaml — Full Reference

```yaml
# ── Identity ──────────────────────────────────────────────────────────────────
# Which agent runtime is sending requests
runtime: openclaw
# Options: openclaw | nemoclaw | hermes | deepagents | langgraph | generic

# Which LLM backend to forward to
backend: ollama
# Options: ollama | openai | deepseek | vllm

# ── Governance mode ───────────────────────────────────────────────────────────
# Shadow mode: log decisions but never block (safe for onboarding)
shadow_mode: false

# Named governance policy from the hub (optional)
policy: null
# Example: policy: customer-support-v1

# ── Pipeline stages ───────────────────────────────────────────────────────────
stages:

  # Stage 1: Rule-based (always on, 0.1ms, deterministic)
  rules:
    enabled: true

  # Stage 2: LLM classifier (semantic tool call inspection, ~800ms)
  classifier:
    enabled: true
    model: qwen2.5:1.5b       # Ollama model for classification
    backend: ollama            # ollama | gguf | openai
    model_path: null           # path to fine-tuned GGUF (overrides model)
    threshold: 0.85            # confidence threshold for blocking
    timeout_ms: 2000           # timeout in milliseconds

  # Stage 3: Semantic output filter (response text inspection, ~1s)
  # Catches dangerous content in natural language (not tool calls)
  # e.g. "here's how to set up a reverse shell: nc -l -p 4444"
  semantic_filter:
    enabled: false             # opt-in — adds latency
    model: llama-guard3        # pull: ollama pull llama-guard3
    backend: ollama
    threshold: 0.7
    timeout_ms: 30000          # 30s — Llama Guard cold start is slow

  # Stage 4: RL Policy (enterprise — requires trained weights)
  rl_policy:
    enabled: false
    model_path: null           # path to best_model.zip

# ── LLM Providers ─────────────────────────────────────────────────────────────
providers:
  ollama:
    base_url: http://localhost:11434
    keep_alive: -1             # keep model loaded forever

  openai:
    base_url: https://api.openai.com/v1
    api_key: null              # reads OPENAI_API_KEY env var

  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key: null              # reads DEEPSEEK_API_KEY env var
    model: deepseek-chat

  vllm:
    base_url: http://localhost:8080/v1

# ── Audit log ─────────────────────────────────────────────────────────────────
audit:
  enabled: true
  db_path: ~/.agentwarden/audit/agentwarden_audit.db
  log_allowed: true
  log_blocked: true

# ── Server ────────────────────────────────────────────────────────────────────
server:
  host: 0.0.0.0
  port: 8000
  workers: 1
  log_level: INFO
```

---

## Environment Variables — Full Reference

All env vars override the corresponding `agentwarden.yaml` values.

### Runtime and backend

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTWARDEN_RUNTIME` | `generic` | Agent runtime: `openclaw`, `nemoclaw`, `hermes`, `deepagents`, `langgraph`, `generic` |
| `AGENTWARDEN_BACKEND` | `ollama` | LLM backend: `ollama`, `openai`, `deepseek`, `vllm` |
| `AGENTWARDEN_CONFIG` | `./agentwarden.yaml` | Path to config file |

### Governance mode

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTWARDEN_SHADOW_MODE` | `false` | `true` = log only, never block |
| `AGENTWARDEN_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Stage 2 — Classifier

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTWARDEN_CLASSIFIER_MODEL` | `qwen2.5:1.5b` | Ollama model for Stage 2 |
| `AGENTWARDEN_DISABLE_CLASSIFIER` | `false` | `true` = skip Stage 2 entirely |

### Stage 3 — Semantic filter

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTWARDEN_SEMANTIC_FILTER` | `false` | `true` = enable Stage 3 |
| `AGENTWARDEN_SEMANTIC_MODEL` | `llama-guard3` | Model for Stage 3 |

### Stage 4 — RL policy

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTWARDEN_ENABLE_RL_POLICY` | `false` | `true` = enable Stage 4 |
| `AGENTWARDEN_RL_MODEL_PATH` | `null` | Path to `best_model.zip` |

### Providers

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | DeepSeek base URL |
| `NIM_API_KEY` | — | NVIDIA NIM API key (NemoClaw) |

### Audit

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTWARDEN_DB_PATH` | `~/.agentwarden/audit/agentwarden_audit.db` | SQLite audit DB path |

### OpenClaw

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENCLAW_TOKEN` | — | OpenClaw gateway auth token |
| `OPENCLAW_MODEL` | `gemma4:e4b` | Model OpenClaw uses |

---

## config/rules.yaml — Full Reference

```yaml
# ── Always-block tool names ──────────────────────────────────────────────────
# Blocked immediately at Stage 1, no LLM call needed.
always_block:
  - exec
  - execute
  - bash
  - shell
  - run_command
  - terminal
  - system
  - process
  - kill
  - sudo
  - su
  - chmod
  - chown
  - sessions_spawn
  - subagents
  - spawn
  - create_agent
  - delegate
  - task

# ── Argument patterns ────────────────────────────────────────────────────────
# Regex patterns matched against all argument values.
# Block the tool call if any pattern matches.
arg_patterns:
  - pattern: "rm\\s+-rf"
    description: "Recursive delete"
    severity: critical

  - pattern: "\\|\\s*bash"
    description: "Pipe to bash"
    severity: critical

  - pattern: "file://"
    description: "Local file URI — SSRF risk"
    severity: high

  - pattern: "169\\.254\\.169\\.254"
    description: "AWS metadata endpoint"
    severity: critical

  - pattern: "~/.ssh/"
    description: "SSH credential path"
    severity: high

  - pattern: "/etc/passwd"
    description: "Password file access"
    severity: high

  - pattern: "/etc/shadow"
    description: "Shadow file access"
    severity: critical

  - pattern: "\\.aws/credentials"
    description: "AWS credentials file"
    severity: critical

  - pattern: "nc\\s+-[el]"
    description: "Netcat listener"
    severity: critical

# ── Prompt injection patterns ────────────────────────────────────────────────
# Applied to the system prompt content.
injection_patterns:
  - pattern: "ignore\\s+(all\\s+)?previous\\s+instructions?"
    description: "Classic prompt injection"

  - pattern: "you\\s+are\\s+now\\s+(a\\s+)?DAN"
    description: "DAN jailbreak"

  - pattern: "jailbreak"
    description: "Jailbreak keyword"

# ── Classifier skip list ─────────────────────────────────────────────────────
# Tools that skip Stage 2 (LLM classifier) — low-risk, fast path.
classifier_skip:
  - read
  - read_file
  - memory_get
  - memory_search
  - memory_save
  - session_status
  - sessions_list
  - sessions_history
  - web_search
  - ls
  - glob
  - grep
  - write        # in classifier_skip due to known FP with current weights
  - edit
  - write_file
```

---

## config/tools.yaml — Tool Risk Levels

Each tool has a `risk_level` from 0 (safe) to 4 (critical):

| Level | Meaning | Examples |
|-------|---------|---------|
| 0 | Always safe | `read`, `ls`, `memory_get` |
| 1 | Low risk | `web_search`, `memory_save` |
| 2 | Medium risk | `write`, `edit`, `web_fetch` |
| 3 | High risk | `cron`, `sessions_send` |
| 4 | Critical — always block | `exec`, `sessions_spawn`, `bash` |

Tools with `always_block: true` are blocked at Stage 1 regardless of other settings.
Tools with `classifier_skip: true` skip Stage 2 for speed.

---

## After a restart

When the system restarts, this is what AgentWarden needs to come back:

```bash
# 1. Ensure Ollama is running
systemctl status ollama
# If not: sudo systemctl start ollama

# 2. Ensure Ollama is listening on all interfaces (required for Docker)
ss -tlnp | grep 11434
# Should show: *:11434 not 127.0.0.1:11434
# If wrong: sudo systemctl restart ollama
# (override.conf should have OLLAMA_HOST=0.0.0.0:11434)

# 3. Start AgentWarden
cd ~/PycharmProjects/openclaw    # or wherever your compose file is
docker compose up -d agentwarden

# 4. Verify
curl http://localhost:8000/health

# 5. If OpenClaw is separate, start it too
docker compose up -d openclaw-gateway
```

### Why Ollama needs 0.0.0.0

By default Ollama binds to `127.0.0.1` — only accepting local connections.
Docker containers have their own network namespace and cannot reach `127.0.0.1` on the host.
The override makes Ollama listen on all interfaces so containers can connect via the bridge gateway IP.

To make this permanent:
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d/
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```
