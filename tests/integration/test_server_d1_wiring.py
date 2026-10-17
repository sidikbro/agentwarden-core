"""D1 wiring in the live proxy (agentwarden/server/app.py).

Before this, the proxy only ever filtered blocked tool_calls out of the
LLM's RESPONSE (D2) — nothing shaped what tools the model was even offered
in the request. These tests exercise that request-shaping path directly
via FastAPI's TestClient, with the LLM backend call itself mocked out (no
network dependency, no live Ollama/DeepSeek required) so they're fast and
deterministic.

D1 is declaration-first (X-AgentWarden-Task-Type / X-AgentWarden-Phase
headers) with a structural fallback when no header is present: infer
task_type from the offered tools=[...] set against capability_profiles.yaml
(NOT a learned classifier — see structural_task_type.py). The fallback only
activates on a confident match; an unconfident/no match means "don't apply
D1," identical to today's real runtimes (OpenClaw/DeepAgents/Hermes use
tools.yaml's canonical names, which don't confidently match any of today's
benchmark-family profiles) — that's what keeps this backward compatible.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from agentwarden.server.app import create_app


def _client():
    app = create_app(runtime="generic", backend="ollama")
    return TestClient(app)


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


def test_d1_filters_outgoing_tools_when_task_type_header_present():
    captured = {}

    async def fake_forward(self, body, headers=None, timeout=120.0):
        captured["body"] = body
        return {"message": {"role": "assistant", "content": "ok", "tool_calls": []}, "done": True, "done_reason": "stop"}

    with patch("agentwarden.providers.ollama.OllamaProvider.forward", new=fake_forward):
        resp = _client().post(
            "/api/chat",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [_tool("search_web"), _tool("exec_shell"), _tool("send_email")],
            },
            headers={"X-AgentWarden-Task-Type": "research_synth", "X-AgentWarden-Phase": "search"},
        )

    assert resp.status_code == 200
    forwarded_names = [t["function"]["name"] for t in captured["body"].get("tools", [])]
    assert forwarded_names == ["search_web"]


def test_d1_blocks_hallucinated_call_to_unexposed_tool():
    """Even a tool the request-side filter stripped from tools=[...] must
    still be blocked if the model calls it anyway — hiding it from the
    schema alone isn't enforcement."""
    async def fake_forward(self, body, headers=None, timeout=120.0):
        return {
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "call_1", "type": "function",
                                 "function": {"name": "exec_shell", "arguments": {"cmd": "ls"}}}],
            },
            "done": True, "done_reason": "tool_calls",
        }

    with patch("agentwarden.providers.ollama.OllamaProvider.forward", new=fake_forward):
        resp = _client().post(
            "/api/chat",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [_tool("search_web"), _tool("exec_shell")],
            },
            headers={"X-AgentWarden-Task-Type": "research_synth", "X-AgentWarden-Phase": "search"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["message"]["tool_calls"] == []
    assert "exec_shell" in body["message"]["content"]


def test_no_task_type_header_means_unchanged_passthrough():
    """Backward compatibility: omitting the opt-in header must reproduce
    exactly the pre-D1 behavior — full tools array forwarded, no
    exposure-based blocking of the response."""
    captured = {}

    async def fake_forward(self, body, headers=None, timeout=120.0):
        captured["body"] = body
        return {
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "call_1", "type": "function",
                                 "function": {"name": "exec_shell", "arguments": {"cmd": "ls"}}}],
            },
            "done": True, "done_reason": "tool_calls",
        }

    with patch("agentwarden.providers.ollama.OllamaProvider.forward", new=fake_forward):
        resp = _client().post(
            "/api/chat",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [_tool("search_web"), _tool("exec_shell")],
            },
        )

    assert resp.status_code == 200
    forwarded_names = [t["function"]["name"] for t in captured["body"].get("tools", [])]
    assert forwarded_names == ["search_web", "exec_shell"]   # untouched
    # exec_shell isn't in always_block/arg_patterns for these (safe) args,
    # so with no D1 opt-in it passes straight through, exactly as before.
    body = resp.json()
    assert body["message"]["tool_calls"][0]["function"]["name"] == "exec_shell"


def test_d1_unknown_task_type_exposes_nothing():
    """Fail-closed applies here too: an unrecognized task_type falls back
    to capability_profiles.yaml's empty "unknown" profile, so ALL tools
    are stripped from the outgoing request rather than defaulting open."""
    captured = {}

    async def fake_forward(self, body, headers=None, timeout=120.0):
        captured["body"] = body
        return {"message": {"role": "assistant", "content": "ok", "tool_calls": []}, "done": True, "done_reason": "stop"}

    with patch("agentwarden.providers.ollama.OllamaProvider.forward", new=fake_forward):
        resp = _client().post(
            "/api/chat",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [_tool("search_web"), _tool("send_email")],
            },
            headers={"X-AgentWarden-Task-Type": "some_task_type_not_in_yaml"},
        )

    assert resp.status_code == 200
    assert captured["body"].get("tools") == []


def test_structural_fallback_applies_d1_on_confident_match_with_no_header():
    """No header, but the offered tools=[...] confidently match
    research_synth's known vocabulary -- D1 applies via inference alone."""
    captured = {}

    async def fake_forward(self, body, headers=None, timeout=120.0):
        captured["body"] = body
        return {"message": {"role": "assistant", "content": "ok", "tool_calls": []}, "done": True, "done_reason": "stop"}

    with patch("agentwarden.providers.ollama.OllamaProvider.forward", new=fake_forward):
        resp = _client().post(
            "/api/chat",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [
                    _tool("search_web"), _tool("fetch_url"), _tool("extract_facts"),
                    _tool("write_draft"), _tool("send_email"),
                ],
            },
            headers={"X-AgentWarden-Phase": "search"},   # phase declared, task_type not
        )

    assert resp.status_code == 200
    forwarded_names = [t["function"]["name"] for t in captured["body"].get("tools", [])]
    assert forwarded_names == ["search_web"]   # research_synth's "search" phase, inferred


def test_structural_fallback_declines_low_confidence_and_passes_through():
    """No header, offered tools don't confidently match any profile
    (mirrors real runtimes using tools.yaml's canonical names) -- full
    passthrough, exactly like before D1 existed. This is the property that
    keeps existing runtimes working without a profile written for them."""
    captured = {}

    async def fake_forward(self, body, headers=None, timeout=120.0):
        captured["body"] = body
        return {"message": {"role": "assistant", "content": "ok", "tool_calls": []}, "done": True, "done_reason": "stop"}

    with patch("agentwarden.providers.ollama.OllamaProvider.forward", new=fake_forward):
        resp = _client().post(
            "/api/chat",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [_tool("read"), _tool("write"), _tool("web_fetch")],   # real tools.yaml names
            },
        )

    assert resp.status_code == 200
    forwarded_names = [t["function"]["name"] for t in captured["body"].get("tools", [])]
    assert forwarded_names == ["read", "write", "web_fetch"]   # unchanged
