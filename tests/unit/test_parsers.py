"""
Unit tests for ToolParser implementations.
Tests normalisation, tool name mapping, and reconstruct() logic.
No network calls, no models, no Docker required.
"""
import pytest
from agentwarden.core.models import GovernanceContext, Runtime
from agentwarden.parsers.openai import OpenAIParser, OllamaParser
from agentwarden.parsers.hermes import HermesParser, DeepAgentsParser


# ── Fixtures ──────────────────────────────────────────────────────────────────

def ctx(runtime=Runtime.GENERIC) -> GovernanceContext:
    return GovernanceContext(runtime=runtime, session_id="test-session")


OPENAI_EXEC_RESPONSE = {
    "model": "deepseek-chat",
    "message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_001",
                "type": "function",
                "function": {
                    "name": "exec",
                    "arguments": '{"cmd": "ls -la /etc"}'
                }
            }
        ]
    }
}

OPENAI_SAFE_RESPONSE = {
    "model": "deepseek-chat",
    "message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_002",
                "type": "function",
                "function": {
                    "name": "read",
                    "arguments": '{"path": "/workspace/README.md"}'
                }
            }
        ]
    }
}

OPENAI_MULTI_RESPONSE = {
    "model": "deepseek-chat",
    "message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_001", "type": "function",
             "function": {"name": "read", "arguments": '{"path": "file.txt"}'}},
            {"id": "call_002", "type": "function",
             "function": {"name": "exec", "arguments": '{"cmd": "rm -rf /"}'}},
        ]
    }
}

HERMES_XML_RESPONSE = {
    "model": "hermes-3",
    "message": {
        "role": "assistant",
        "content": (
            "I'll help you with that.\n"
            '<tool_call>\n{"name": "execute", "arguments": {"cmd": "cat /etc/passwd"}}\n</tool_call>'
        )
    }
}

DEEPAGENTS_RESPONSE = {
    "model": "gpt-4o",
    "message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_da_001", "type": "function",
             "function": {"name": "execute", "arguments": '{"command": "ls"}'}},
            {"id": "call_da_002", "type": "function",
             "function": {"name": "task", "arguments": '{"description": "spawn sub"}'}},
        ]
    }
}

NO_TOOLS_RESPONSE = {
    "model": "deepseek-chat",
    "message": {"role": "assistant", "content": "Here is the summary you requested."}
}


# ── OpenAI Parser ─────────────────────────────────────────────────────────────

class TestOpenAIParser:

    def test_can_parse_tool_call(self):
        assert OpenAIParser().can_parse(OPENAI_EXEC_RESPONSE) is True

    def test_cannot_parse_no_tools(self):
        assert OpenAIParser().can_parse(NO_TOOLS_RESPONSE) is False

    def test_parse_exec_tool(self):
        reqs = OpenAIParser().parse(OPENAI_EXEC_RESPONSE, ctx())
        assert len(reqs) == 1
        assert reqs[0].tool_call.name == "exec"
        assert reqs[0].tool_call.arguments == {"cmd": "ls -la /etc"}
        assert reqs[0].tool_call.raw_id == "call_001"
        assert reqs[0].tool_call.raw_format == "openai_json"

    def test_parse_safe_tool(self):
        reqs = OpenAIParser().parse(OPENAI_SAFE_RESPONSE, ctx())
        assert len(reqs) == 1
        assert reqs[0].tool_call.name == "read"

    def test_parse_multiple_tools(self):
        reqs = OpenAIParser().parse(OPENAI_MULTI_RESPONSE, ctx())
        assert len(reqs) == 2
        names = {r.tool_call.name for r in reqs}
        assert names == {"read", "exec"}

    def test_parse_no_tools_returns_empty(self):
        reqs = OpenAIParser().parse(NO_TOOLS_RESPONSE, ctx())
        assert reqs == []

    def test_reconstruct_blocks_exec(self):
        """After blocking exec, only read should remain in response."""
        parser = OpenAIParser()
        reqs = parser.parse(OPENAI_MULTI_RESPONSE, ctx())
        allowed = [r for r in reqs if r.tool_call.name == "read"]
        mutated = parser.reconstruct(OPENAI_MULTI_RESPONSE, allowed)
        remaining = mutated["message"]["tool_calls"]
        assert len(remaining) == 1
        assert remaining[0]["id"] == "call_001"

    def test_reconstruct_all_blocked_adds_message(self):
        """If all calls blocked, response gets governance message as content."""
        parser = OpenAIParser()
        reqs = parser.parse(OPENAI_EXEC_RESPONSE, ctx())
        mutated = parser.reconstruct(OPENAI_EXEC_RESPONSE, [])  # block all
        assert mutated["message"]["tool_calls"] == []
        assert "AgentWarden blocked" in (mutated["message"].get("content") or "")

    def test_arguments_string_parsed_to_dict(self):
        reqs = OpenAIParser().parse(OPENAI_EXEC_RESPONSE, ctx())
        assert isinstance(reqs[0].tool_call.arguments, dict)


# ── Hermes Parser ─────────────────────────────────────────────────────────────

class TestHermesParser:

    def test_can_parse_xml_format(self):
        assert HermesParser().can_parse(HERMES_XML_RESPONSE) is True

    def test_parse_xml_execute_normalised(self):
        """'execute' in Hermes XML should normalise to 'exec'."""
        reqs = HermesParser().parse(HERMES_XML_RESPONSE, ctx(Runtime.HERMES))
        assert len(reqs) == 1
        assert reqs[0].tool_call.name == "exec"
        assert reqs[0].tool_call.raw_format == "hermes_xml"
        assert reqs[0].tool_call.arguments == {"cmd": "cat /etc/passwd"}

    def test_hermes_xml_reconstruct_strips_blocked(self):
        parser = HermesParser()
        reqs = parser.parse(HERMES_XML_RESPONSE, ctx(Runtime.HERMES))
        # Block all
        mutated = parser.reconstruct(HERMES_XML_RESPONSE, [])
        assert "<tool_call>" not in mutated["message"]["content"]
        assert "AgentWarden blocked" in mutated["message"]["content"]

    def test_hermes_falls_back_to_openai_format(self):
        """Hermes with OpenAI tool_calls should fall back to OpenAI parser."""
        reqs = HermesParser().parse(OPENAI_EXEC_RESPONSE, ctx(Runtime.HERMES))
        assert len(reqs) == 1
        assert reqs[0].tool_call.name == "exec"

    @pytest.mark.parametrize("name,expected", [
        ("execute",       "exec"),
        ("bash",          "exec"),
        ("shell",         "exec"),
        ("task",          "sessions_spawn"),
        ("spawn",         "sessions_spawn"),
        ("write_file",    "write_file"),
        ("edit_file",     "write_file"),
        ("web_search",    "web_search"),   # unchanged
    ])
    def test_tool_name_normalisation(self, name, expected):
        parser = HermesParser()
        assert parser._norm(name) == expected


# ── DeepAgents Parser ─────────────────────────────────────────────────────────

class TestDeepAgentsParser:

    def test_execute_maps_to_exec(self):
        reqs = DeepAgentsParser().parse(DEEPAGENTS_RESPONSE, ctx(Runtime.DEEPAGENTS))
        names = [r.tool_call.name for r in reqs]
        assert "exec" in names

    def test_task_maps_to_sessions_spawn(self):
        reqs = DeepAgentsParser().parse(DEEPAGENTS_RESPONSE, ctx(Runtime.DEEPAGENTS))
        names = [r.tool_call.name for r in reqs]
        assert "sessions_spawn" in names

    def test_raw_format_set(self):
        reqs = DeepAgentsParser().parse(DEEPAGENTS_RESPONSE, ctx(Runtime.DEEPAGENTS))
        for r in reqs:
            assert r.tool_call.raw_format == "deepagents_json"
