# DeepAgents + AgentWarden Sample

Governs DeepAgents tool calls. Blocks `task` (subagent spawn) and `execute` (shell).

## Prerequisites

```bash
pip install deepagents langchain-openai
```

AgentWarden proxy must be running (see project root `docker-compose.yml`).

## Run

```bash
# With DeepSeek backend
export DEEPSEEK_API_KEY=sk-your-key
python governed_agent.py

# With Ollama backend (no API key needed)
# Edit governed_agent.py — change model to "openai:gemma4:e4b"
python governed_agent.py
```

## Expected output

```
=== Benign: Write a poem ===
Blocked: False (expected: False)
Response: I've written a short poem...

=== Adversarial: Spawn subagent ===
Blocked: True (expected: True)
Response: ⚠️ AgentWarden blocked this tool call...

=== Benign: Read a file ===
Blocked: False (expected: False)
Response: The README.md file...

3/3 tests passed
```

## Key point: FilesystemBackend is required

```python
# WRONG — LocalShellBackend bypasses the proxy
agent = create_deep_agent(model=...)

# CORRECT — FilesystemBackend routes through AgentWarden
from deepagents.backends.filesystem import FilesystemBackend
agent = create_deep_agent(model=..., backend=FilesystemBackend())
```

DeepAgents' default `LocalShellBackend` runs shell commands via `subprocess` locally,
completely bypassing the LLM proxy. AgentWarden cannot govern those calls.
Use `FilesystemBackend` to disable local shell and route everything through the proxy.

## Tool name mapping

| DeepAgents sends | AgentWarden sees | Decision |
|-----------------|-----------------|----------|
| `task` | `sessions_spawn` | BLOCK |
| `execute` | `exec` | BLOCK |
| `write_file` | `write_file` | ALLOW |
| `read_file` | `read` | ALLOW |
| `edit_file` | `edit` | ALLOW |
