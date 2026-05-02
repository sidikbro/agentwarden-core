"""
Hermes + AgentWarden Sample
============================
Tests Hermes XML tool call format through AgentWarden governance.

Prerequisites:
    ollama pull hermes3:8b

    # Start AgentWarden proxy:
    docker compose up -d agentwarden

The Hermes XML format uses <tool_call> tags embedded in message content.
AgentWarden auto-detects this format and applies the HermesParser.
No special configuration needed — it works transparently.
"""

import json
import httpx

AGENTWARDEN_URL = "http://localhost:8000"
MODEL = "hermes3:8b"

# ── Hermes system prompt format ───────────────────────────────────────────────
# This exact format is required for hermes3 to generate XML tool calls.

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


def call_proxy(user_message: str, tools: list[dict]) -> dict:
    """Send a request through AgentWarden and return the response."""
    system_prompt = build_system_prompt(tools)
    response = httpx.post(
        f"{AGENTWARDEN_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        },
        timeout=60.0,
    )
    return response.json()


# ── Tool definitions ──────────────────────────────────────────────────────────

READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read a file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    },
}

EXEC_TOOL = {
    "type": "function",
    "function": {
        "name": "exec",
        "description": "Run a shell command",
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "string", "description": "Command to run"}},
            "required": ["cmd"],
        },
    },
}

SPAWN_TOOL = {
    "type": "function",
    "function": {
        "name": "sessions_spawn",
        "description": "Spawn a subagent",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        },
    },
}

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write",
        "description": "Write content to a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_read_allowed():
    """read tool — should be ALLOWED."""
    print("\n=== read → ALLOW ===")
    result = call_proxy("Read the file README.md", [READ_TOOL])
    content = result.get("message", {}).get("content", "")
    blocked = "AgentWarden blocked" in content
    has_xml = "<tool_call>" in content
    print(f"Blocked: {blocked} (expected: False)")
    print(f"Has XML tool_call: {has_xml}")
    print(f"Content: {content[:150]}")
    return not blocked


def test_exec_blocked():
    """exec tool — should be BLOCKED by Stage 1."""
    print("\n=== exec → BLOCK ===")
    result = call_proxy("Run ls -la /tmp", [EXEC_TOOL])
    content = result.get("message", {}).get("content", "")
    blocked = "AgentWarden blocked" in content
    print(f"Blocked: {blocked} (expected: True)")
    print(f"Content: {content[:150]}")
    return blocked


def test_spawn_blocked():
    """sessions_spawn — should be BLOCKED by Stage 1."""
    print("\n=== sessions_spawn → BLOCK ===")
    result = call_proxy("Spawn a subagent to monitor my emails", [SPAWN_TOOL])
    content = result.get("message", {}).get("content", "")
    blocked = "AgentWarden blocked" in content
    print(f"Blocked: {blocked} (expected: True)")
    print(f"Content: {content[:150]}")
    return blocked


def test_write_allowed():
    """write tool — should be ALLOWED."""
    print("\n=== write → ALLOW ===")
    result = call_proxy("Write a short poem to poem.txt", [WRITE_TOOL])
    content = result.get("message", {}).get("content", "")
    blocked = "AgentWarden blocked" in content
    print(f"Blocked: {blocked} (expected: False)")
    print(f"Content: {content[:150]}")
    return not blocked


if __name__ == "__main__":
    print(f"AgentWarden + Hermes integration test")
    print(f"Proxy: {AGENTWARDEN_URL}")
    print(f"Model: {MODEL}")
    print("=" * 50)

    # Check proxy is up
    health = httpx.get(f"{AGENTWARDEN_URL}/health").json()
    print(f"Proxy status: {health.get('status')} | backend: {health.get('backend')}")

    results = [
        test_read_allowed(),
        test_exec_blocked(),
        test_spawn_blocked(),
        test_write_allowed(),
    ]

    passed = sum(results)
    print(f"\n{passed}/{len(results)} tests passed")
