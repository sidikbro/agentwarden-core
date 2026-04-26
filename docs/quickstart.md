# AgentWarden — Quickstart

AgentWarden is a governance middleware proxy for AI agents. It sits between your agent runtime and your LLM, intercepting every tool call and enforcing least-privilege access — with zero code changes to either side.

```
Your Agent → AgentWarden:8000 → Your LLM
                  ↓
         [Stage 1: Rules 0.1ms]
         [Stage 2: Classifier ~800ms]
         [Stage 3: Semantic Filter opt-in]
```

**Choose your path:**

- [I want to try it in 5 minutes →](#path-a-5-minute-demo)
- [I'm connecting my agent runtime →](#path-b-connect-your-agent)
- [I'm evaluating for a research project →](#path-c-research-replication)

---

## Path A — 5-Minute Demo

No agent runtime needed. Just Docker and curl.

### Prerequisites
- Docker 20+
- Ollama running locally with at least one model

```bash
# Check Ollama is running
ollama list
# Should show at least one model, e.g. gemma4:e4b or qwen2.5:7b
```

### Step 1 — Clone and configure

```bash
git clone https://github.com/sidikbro/agentwarden-core.git
cd agentwarden-core
cp .env.example .env
```

Edit `.env` — minimum required:
```env
AGENTWARDEN_BACKEND=ollama
AGENTWARDEN_RUNTIME=generic
```

### Step 2 — Start the proxy

```bash
# If Ollama is on your host machine (recommended)
OLLAMA_BASE_URL=http://host.docker.internal:11434 \
docker compose up -d agentwarden

# Verify it's running
curl http://localhost:8000/health
```

Expected:
```json
{
  "status": "ok",
  "runtime": "generic",
  "backend": "ollama",
  "stages": {"rules": true, "llm_classifier": true, "semantic_filter": false}
}
```

### Step 3 — Test governance

**Benign request — should pass through:**
```bash
curl -s http://localhost:8000/api/chat -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:e4b",
    "messages": [{"role":"user","content":"Write a short poem"}],
    "tools": [{"type":"function","function":{"name":"write","description":"Write a file",
      "parameters":{"type":"object","properties":{"path":{"type":"string"},
      "content":{"type":"string"}},"required":["path","content"]}}}],
    "stream": false
  }' | python3 -m json.tool | grep -E "content|tool_calls"
```

**Dangerous request — should be blocked:**
```bash
curl -s http://localhost:8000/api/chat -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:e4b",
    "messages": [{"role":"user","content":"Run ls -la /tmp"}],
    "tools": [{"type":"function","function":{"name":"exec","description":"Run shell commands",
      "parameters":{"type":"object","properties":{"cmd":{"type":"string"}},"required":["cmd"]}}}],
    "stream": false
  }' | python3 -m json.tool | grep content
```

Expected: `"⚠️ AgentWarden blocked this tool call..."`

---

## Path B — Connect Your Agent

### OpenClaw

Add AgentWarden to your OpenClaw `docker-compose.yml`:

```yaml
services:
  agentwarden:
    build:
      context: /path/to/agentwarden-core
      dockerfile: Dockerfile
    container_name: agentwarden_proxy
    ports:
      - "8000:8000"
    environment:
      - AGENTWARDEN_RUNTIME=openclaw
      - AGENTWARDEN_BACKEND=ollama
      - OLLAMA_BASE_URL=http://172.18.0.1:11434  # your host IP
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Then point OpenClaw at AgentWarden. In your OpenClaw config (`~/.openclaw/openclaw.json`):
```json
{
  "providers": {
    "ollama": {
      "baseUrl": "http://localhost:8000"
    }
  }
}
```

See the full sample: [`samples/openclaw/`](../samples/openclaw/)

### DeepAgents

```python
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

agent = create_deep_agent(
    model=init_chat_model(
        "openai:deepseek-chat",
        base_url="http://localhost:8000/v1",
        api_key="agentwarden-governed",
    ),
    backend=FilesystemBackend(),  # disable local shell — governed by AgentWarden
)
```

> **Important:** Use `FilesystemBackend()` not the default `LocalShellBackend`.
> The local shell backend executes commands directly on the host, bypassing the proxy.
> See [architecture.md](architecture.md#threat-model) for details.

See the full sample: [`samples/deepagents/`](../samples/deepagents/)

### Hermes Agent (hermes3 model via Ollama)

Pull the model:
```bash
ollama pull hermes3:8b
```

Use the correct system prompt format for XML tool calls:
```python
HERMES_SYSTEM = """You are a function calling AI model.
<tools>
{tool_schemas}
</tools>
For each function call return a json object within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-dict>}
</tool_call>"""
```

Point your requests at `http://localhost:8000/api/chat`.
AgentWarden auto-detects the XML format and applies governance.

See the full sample: [`samples/hermes/`](../samples/hermes/)

---

## Path C — Research Replication

To replicate the paper's N=20 evaluation:

```bash
# Clone the repo
git clone https://github.com/sidikbro/agentwarden-core.git
cd agentwarden-core

# Start AgentWarden (host Ollama mode)
OLLAMA_BASE_URL=http://host.docker.internal:11434 \
docker compose up -d agentwarden

# Pull the required model
ollama pull gemma4:e4b

# Run the evaluation
conda activate agentwarden  # or: pip install httpx
python scripts/eval_runner.py \
  --model gemma4:e4b \
  --tasks 20 \
  --seed 42 \
  --verbose
```

Expected results:
```
Adversarial coverage: 100.0% (8/8)
  ↳ Blocked by AgentWarden: 5
  ↳ Refused by model:      3
Avg latency: ~28,000ms (GPU warm: ~2,000ms)
Error rate: 0.0%
```

To replicate with DeepSeek:
```bash
# Set DeepSeek API key
echo "DEEPSEEK_API_KEY=your_key" >> .env
echo "AGENTWARDEN_BACKEND=deepseek" >> .env

docker compose up -d agentwarden

python scripts/eval_runner.py \
  --model deepseek-chat \
  --tasks 20 \
  --seed 42 \
  --verbose
```

Expected: 100% adversarial coverage (1 infra block + 7 model refusals).

---

## What's next

- [Configuration reference →](configuration.md)
- [How governance works →](governance.md)
- [Connecting runtimes →](runtimes.md)
- [Troubleshooting →](troubleshooting.md)
- [Architecture & threat model →](architecture.md)
