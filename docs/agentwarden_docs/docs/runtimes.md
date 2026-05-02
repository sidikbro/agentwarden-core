# AgentWarden — Runtime Integration Guide

How to connect AgentWarden to each supported agent runtime.

## OpenClaw

**Wire format:** Ollama `/api/chat`
**Tool call format:** Standard Ollama `message.tool_calls` JSON

### Integration

OpenClaw reads its LLM endpoint from `~/.openclaw/openclaw.json`.
Point the `baseUrl` at AgentWarden:

```json
{
  "providers": {
    "ollama": {
      "baseUrl": "http://localhost:8000",
      "apiKey": "agentwarden-governed"
    }
  },
  "models": {
    "primary": "ollama/gemma4:e4b"
  }
}
```

### Docker compose integration

Add AgentWarden to your OpenClaw `docker-compose.yml`:

```yaml
services:
  agentwarden:
    build:
      context: /path/to/agentwarden-core
    container_name: agentwarden_proxy
    ports: ["8000:8000"]
    environment:
      - AGENTWARDEN_RUNTIME=openclaw
      - AGENTWARDEN_BACKEND=ollama
      - OLLAMA_BASE_URL=http://172.18.0.1:11434  # host bridge IP
    restart: unless-stopped
```

### Env var: `AGENTWARDEN_RUNTIME=openclaw`

---

## NemoClaw (NVIDIA OpenShell)

**Wire format:** Ollama `/api/chat` (OpenClaw inside OpenShell sandbox)
**Tool call format:** Same as OpenClaw — standard Ollama JSON
**Default model:** `nvidia/nemotron-3-super-120b-a12b` via NVIDIA NIM

### Architecture

NemoClaw = OpenClaw + NVIDIA OpenShell kernel-level sandbox.
AgentWarden intercepts at the LLM inference layer — complementary to NemoClaw's OS-level controls:

```
NemoClaw OpenShell:  kernel sandbox, network egress, credential isolation
AgentWarden:          LLM tool call governance, semantic classification
Combined:            defence-in-depth from OS to LLM token
```

### Integration

```bash
# Set inference endpoint to AgentWarden
openshell inference set \
  --provider openai-compatible \
  --base-url http://localhost:8000/v1 \
  --api-key agentwarden-governed
```

Or via environment variable:
```bash
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=agentwarden-governed
```

### NIM API key

Required for cloud inference. Get it at `https://build.nvidia.com/settings/api-key`.

### Env var: `AGENTWARDEN_RUNTIME=nemoclaw`

---

## DeepAgents (LangChain, v0.5.x)

**Wire format:** OpenAI `/v1/chat/completions`
**Tool call format:** OpenAI JSON (`choices[0].message.tool_calls`)
**Built-in tools:** `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`, `task`, `compact_conversation`, `write_todos`, `read_todos`

### Critical: LocalShellBackend bypass

DeepAgents' default `LocalShellBackend` executes shell commands via `subprocess` directly on the host — bypassing the LLM proxy entirely. AgentWarden cannot intercept these.

**Always use `FilesystemBackend` when deploying with AgentWarden:**

```python
from deepagents.backends.filesystem import FilesystemBackend

agent = create_deep_agent(
    model=init_chat_model(
        "openai:deepseek-chat",
        base_url="http://localhost:8000/v1",
        api_key="agentwarden-governed",
    ),
    backend=FilesystemBackend(),  # ← required
)
```

For shell execution containment, combine with NemoClaw or Docker isolation.

### Tool name mapping

AgentWarden normalises DeepAgents tool names to canonical names:

| DeepAgents name | AgentWarden name | Action |
|----------------|-----------------|--------|
| `read_file` | `read` | safe |
| `write_file` | `write_file` | medium |
| `edit_file` | `edit` | medium |
| `execute` | `exec` | **BLOCK** |
| `task` | `sessions_spawn` | **BLOCK** |

### Env var: `AGENTWARDEN_RUNTIME=deepagents`

---

## Hermes Agent (NousResearch)

**Wire format:** Ollama `/api/chat` OR OpenAI `/v1/chat/completions`
(Hermes Agent v0.4+ has an OpenAI-compatible API server)
**Tool call format:** XML `<tool_call>` embedded in message content

### Model setup

The Hermes XML tool call format requires the correct system prompt.
Hermes-3 and Hermes-4.x models support this natively.

```bash
# Pull a supported model
ollama pull hermes3:8b      # 8B — fits on 6GB VRAM
# ollama pull hermes3:70b  # 70B — requires 40GB+ VRAM
```

### System prompt format

Hermes models require a specific system prompt to generate XML tool calls:

```python
HERMES_SYSTEM_PROMPT = """You are a function calling AI model. \
You are provided with function signatures within <tools></tools> XML tags. \
You may call one or more functions to assist with the user query.
<tools>
{tool_schemas_json}
</tools>
For each function call return a json object with function name and arguments \
within <tool_call></tool_call> XML tags as follows:
<tool_call>
{"name": <function-name>, "arguments": <args-dict>}
</tool_call>"""
```

### Auto-detection

AgentWarden automatically detects `<tool_call>` XML in responses and switches to the Hermes parser, regardless of the configured runtime. You do not need to set `AGENTWARDEN_RUNTIME=hermes` — it works transparently.

### Connecting Hermes Agent framework

Hermes Agent (the framework at github.com/NousResearch/hermes-agent) also has a local shell backend. Same mitigation applies as DeepAgents.

Point the inference endpoint at AgentWarden in `~/.hermes/config.yaml`:
```yaml
provider: openai-compatible
base_url: http://localhost:8000/v1
api_key: agentwarden-governed
model: hermes3:8b
```

### Env var: `AGENTWARDEN_RUNTIME=hermes`

---

## LangGraph

**Wire format:** OpenAI `/v1/chat/completions`
**Tool call format:** Standard OpenAI JSON

LangGraph agents use standard LangChain model interfaces.
Point the model at AgentWarden:

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model="gpt-4o",
    base_url="http://localhost:8000/v1",
    api_key="agentwarden-governed",
)
```

Or with Ollama-backed models:
```python
from langchain_ollama import ChatOllama

model = ChatOllama(
    model="gemma4:e4b",
    base_url="http://localhost:8000",
)
```

LangGraph tool names are user-defined. AgentWarden normalises common patterns:

| LangGraph pattern | AgentWarden name | Action |
|------------------|-----------------|--------|
| `bash_tool`, `run_bash`, `shell_exec` | `exec` | **BLOCK** |
| `python_repl`, `python_exec` | `exec` | **BLOCK** |
| `create_agent`, `spawn_agent` | `sessions_spawn` | **BLOCK** |

For custom tool names that should be blocked, add them to `config/rules.yaml`:
```yaml
always_block:
  - my_custom_shell_tool
  - my_custom_spawn_tool
```

### Env var: `AGENTWARDEN_RUNTIME=langgraph`

---

## Generic / Any OpenAI-compatible agent

For any agent that sends standard OpenAI `/v1/chat/completions` requests:

```bash
# Set your agent's LLM endpoint to:
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=agentwarden-governed  # any non-empty string
```

AgentWarden passes the model name through to the backend unchanged.
Tool call governance applies regardless of which model is used.

### Env var: `AGENTWARDEN_RUNTIME=generic`

---

## Switching backends

AgentWarden supports multiple LLM backends. Switch without rebuilding:

### Ollama (local GPU)
```env
AGENTWARDEN_BACKEND=ollama
OLLAMA_BASE_URL=http://172.18.0.1:11434
```

### DeepSeek (cloud API)
```env
AGENTWARDEN_BACKEND=deepseek
DEEPSEEK_API_KEY=sk-your-key-here
```

### OpenAI
```env
AGENTWARDEN_BACKEND=openai
OPENAI_API_KEY=sk-your-key-here
```

### vLLM (self-hosted)
```env
AGENTWARDEN_BACKEND=vllm
VLLM_BASE_URL=http://your-vllm-server:8080/v1
```

Restart the container after changing backend:
```bash
docker compose up -d agentwarden
curl http://localhost:8000/health | python3 -m json.tool | grep backend
```
