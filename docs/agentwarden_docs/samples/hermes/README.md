# Hermes + AgentWarden Sample

Governs Hermes model XML tool calls through AgentWarden middleware.
Works with any model that generates `<tool_call>` XML format — hermes3, nous-hermes2pro, etc.

## Prerequisites

```bash
# Pull a supported model
ollama pull hermes3:8b        # 5GB — fits on 6GB VRAM
# ollama pull hermes3:70b     # 40GB — for high-end setups

# Install httpx for the test script
pip install httpx
```

AgentWarden proxy must be running (see project root `docker-compose.yml`).

## Run

```bash
python governed_hermes.py
```

## Expected output

```
AgentWarden + Hermes integration test
Proxy: http://localhost:8000
Model: hermes3:8b
==================================================
Proxy status: ok | backend: ollama

=== read → ALLOW ===
Blocked: False (expected: False)
Has XML tool_call: True
Content: <tool_call>
{"name": "read", "arguments": {"path": "README.md"}}
</tool_call>

=== exec → BLOCK ===
Blocked: True (expected: True)
Content:
⚠️ AgentWarden blocked one or more tool calls. The requested operations
are not permitted in this governed session.

=== sessions_spawn → BLOCK ===
Blocked: True (expected: True)
Content:
⚠️ AgentWarden blocked one or more tool calls. The requested operations
are not permitted in this governed session.

=== write → ALLOW ===
Blocked: False (expected: False)
Content: {"name": "write", "arguments": {"path": "poem.txt", "content": "..."}}

4/4 tests passed
```

## How it works

Hermes models embed tool calls as XML inside the message content field:

```
message.content = '<tool_call>\n{"name": "exec", "arguments": {"cmd": "ls"}}\n</tool_call>'
```

Standard Ollama parsers look for `message.tool_calls` (a JSON array) and miss this.

AgentWarden auto-detects `<tool_call>` in the response content and switches to the `HermesParser` automatically — regardless of the configured runtime. No special configuration needed.

## System prompt format

The exact system prompt format is required for hermes3 to generate XML tool calls reliably. Copy it from `governed_hermes.py`:

```python
def build_system_prompt(tools: list[dict]) -> str:
    tool_schemas = "\n".join(json.dumps(t) for t in tools)
    return f"""You are a function calling AI model. \
You are provided with function signatures within <tools></tools> XML tags. \
You may call one or more functions to assist with the user query.
<tools>
{tool_schemas}
</tools>
For each function call return a json object with function name and arguments \
within <tool_call></tool_call> XML tags as follows:
<tool_call>
{{"name": <function-name>, "arguments": <args-dict>}}
</tool_call>"""
```

Without this exact format, hermes3 may output raw JSON without XML tags —
which is still handled by the standard OpenAI parser path.

## Supported models

| Model | VRAM | XML tool calls | Notes |
|-------|------|---------------|-------|
| `hermes3:8b` | ~5GB | ✅ | Recommended for 6GB VRAM |
| `hermes3:70b` | ~40GB | ✅ | Better reasoning |
| `nous-hermes2` | ~4GB | ❌ | Does not support tools in Ollama |
| `nous-hermes2pro` | ~4GB | ✅ | Via HuggingFace/vLLM |

## Hermes Agent framework

If you are using the Hermes Agent framework (`github.com/NousResearch/hermes-agent`) rather than the Hermes model directly via Ollama, point its inference endpoint at AgentWarden:

```yaml
# ~/.hermes/config.yaml
provider: openai-compatible
base_url: http://localhost:8000/v1
api_key: agentwarden-governed
model: hermes3:8b
```

**Warning:** Hermes Agent has a local shell backend (similar to DeepAgents `LocalShellBackend`) that executes commands via `subprocess` on the host, bypassing the LLM proxy. Combine with Docker isolation or NemoClaw for full containment. See [architecture.md](../../docs/architecture.md#threat-model) for details.

## Governance summary

| Tool | Stage blocked | Reason |
|------|--------------|--------|
| `exec` | Stage 1 | always_block list |
| `bash` | Stage 1 | always_block list |
| `sessions_spawn` | Stage 1 | always_block list |
| `web_fetch(url="file://...")` | Stage 1 | arg pattern: Local file URI |
| `write` (benign) | — | ALLOW |
| `read` | — | ALLOW |
| `web_search` | — | ALLOW (classifier_skip) |
