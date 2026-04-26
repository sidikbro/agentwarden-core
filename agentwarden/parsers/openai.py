"""
OpenAI-format parser — covers Ollama, OpenClaw, vLLM, DeepSeek, generic agents.

Wire format (Ollama /api/chat and OpenAI /v1/chat/completions):
    {
      "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "read",
              "arguments": {"path": "README.md"}  # dict or JSON string
            }
          }
        ]
      }
    }

OpenClaw quirk: tool results use "tool_name" instead of "tool_call_id".
This is handled in the proxy bridge, not here — the parser only sees
the LLM *response*, not the tool result message.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agentwarden.core.base import ToolParser
from agentwarden.core.models import (
    AgentWardenToolRequest,
    GovernanceContext,
    Runtime,
    ToolCall,
)
from agentwarden.core.registry import register_parser

logger = logging.getLogger("agentwarden.parsers.openai")


@register_parser
class OpenAIParser(ToolParser):
    """
    Generic OpenAI-compatible parser.
    Handles both dict arguments (Ollama) and JSON-string arguments (OpenAI/DeepSeek).
    """
    runtime = Runtime.GENERIC

    def can_parse(self, raw: dict[str, Any]) -> bool:
        return bool(
            isinstance(raw.get("message"), dict)
            and raw["message"].get("tool_calls")
        )

    def parse(
        self, raw: dict[str, Any], ctx: GovernanceContext
    ) -> list[AgentWardenToolRequest]:
        tool_calls = raw.get("message", {}).get("tool_calls", [])
        requests = []
        for tc in tool_calls:
            fn   = tc.get("function", {})
            args = fn.get("arguments", {})
            # OpenAI sends arguments as JSON string; Ollama sends as dict
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            requests.append(
                AgentWardenToolRequest(
                    tool_call=ToolCall(
                        name=fn.get("name", "unknown"),
                        arguments=args,
                        raw_id=tc.get("id"),
                        raw_format="openai_json",
                    ),
                    context=ctx,
                    raw_response_body=raw,
                )
            )
        return requests

    def reconstruct(
        self, raw: dict[str, Any], allowed: list[AgentWardenToolRequest]
    ) -> dict[str, Any]:
        """Return raw response with blocked tool calls stripped."""
        msg = raw.get("message", {})
        if "tool_calls" not in msg:
            return raw

        allowed_ids = {r.tool_call.raw_id for r in allowed if r.tool_call.raw_id}
        filtered = [tc for tc in msg["tool_calls"] if tc.get("id") in allowed_ids]

        mutated = {**raw, "message": {**msg, "tool_calls": filtered}}
        if not filtered and msg.get("tool_calls"):
            mutated["message"]["content"] = (
                "⚠️ AgentWarden blocked this tool call. "
                "The requested operation is not permitted in this governed session."
            )
        return mutated


@register_parser
class OllamaParser(OpenAIParser):
    """
    Ollama native /api/chat format parser.
    Identical wire format to OpenAI — tool_calls live inside message{}.
    Registered separately so runtime detection is explicit.
    """
    runtime = Runtime.OPENCLAW


@register_parser
class OpenClawParser(OpenAIParser):
    """
    OpenClaw-specific parser.

    OpenClaw uses standard Ollama format for LLM responses.
    Key quirk: in multi-turn tool results, OpenClaw sends:
        {"role": "tool", "tool_name": "read", "content": "..."}
    instead of the standard:
        {"role": "tool", "tool_call_id": "call_abc", "content": "..."}

    The tool_name→tool_call_id mapping is handled by the proxy bridge
    (_ollama_via_deepseek / DeepSeek bridge). This parser only needs to
    handle the LLM *response* direction, which is standard.
    """
    runtime = Runtime.OPENCLAW

    def can_parse(self, raw: dict[str, Any]) -> bool:
        # OpenClaw responses are standard Ollama format
        return super().can_parse(raw)

    def reconstruct(
        self, raw: dict[str, Any], allowed: list[AgentWardenToolRequest]
    ) -> dict[str, Any]:
        """
        OpenClaw expects Ollama format back: message.tool_calls = []
        when blocked, not null.
        """
        result = super().reconstruct(raw, allowed)
        # Ensure tool_calls is always a list (never null) for OpenClaw compatibility
        if "message" in result and result["message"].get("tool_calls") is None:
            result["message"]["tool_calls"] = []
        return result


@register_parser
class NemoClawParser(OpenClawParser):
    """
    NVIDIA NemoClaw parser (alpha, March 2026).

    NemoClaw = OpenClaw + NVIDIA OpenShell security runtime.
    Announced at GTC 2026, open source (Apache 2.0).
    GitHub: NVIDIA/NemoClaw

    Architecture:
        User → NemoClaw CLI (TypeScript plugin)
             → NVIDIA OpenShell (kernel-level sandbox: Landlock + seccomp + netns)
             → OpenClaw agent process
             → [inference routing via Privacy Router]
             → NVIDIA NIM (Nemotron models) or local Ollama
             → [AgentWarden intercepts here] ← this parser
             → LLM response back through the stack

    Wire format: identical to OpenClaw (Ollama /api/chat format).
    NemoClaw does not modify the tool call wire format — OpenClaw inside
    the sandbox talks to the LLM backend exactly as it does standalone.

    Key differences from bare OpenClaw:
    1. Inference is routed through OpenShell's Privacy Router, which may
       add NIM-specific headers (X-NIM-Model, X-OpenShell-Session-ID).
       These appear in HTTP headers, not the JSON body — transparent to us.
    2. Default model is nvidia/nemotron-3-super-120b-a12b via NVIDIA NIM
       (OpenAI-compatible /v1/chat/completions endpoint).
    3. NemoClaw already enforces some egress policy via OpenShell (kernel level).
       AgentWarden adds LLM-layer governance on top — complementary, not redundant.
       NemoClaw controls what the sandbox can reach; AgentWarden controls what
       the LLM can invoke as tools.

    Positioning (paper §NemoClaw Integration):
        NemoClaw layer:   kernel sandbox, network egress policy, credential isolation
        AgentWarden layer: tool call governance, semantic classification, RL policy
        Combined:         defence-in-depth from OS to LLM token

    Tool names: same as OpenClaw (read, write, exec, sessions_spawn, etc.)
    Always-block rules: same as OpenClaw — exec and sessions_spawn are blocked
    even inside the NemoClaw sandbox (defence in depth).

    NIM inference endpoint:
        Default: https://integrate.api.nvidia.com/v1/chat/completions
        Local:   http://localhost:8000/v1/chat/completions (NIM container)
        The proxy intercepts whichever endpoint NemoClaw routes to.

    Status: alpha (APIs may change). Parser pinned to NemoClaw behaviour
    as of March–April 2026. Track NVIDIA/NemoClaw releases for changes.
    """
    runtime = Runtime.NEMOCLAW

    # NIM-specific fields that may appear in responses — log but don't block
    NIM_EXTRA_FIELDS = {"nim_request_id", "nvidia_usage", "x_nim_model"}

    def can_parse(self, raw: dict[str, Any]) -> bool:
        # NemoClaw uses Ollama format internally (OpenClaw agent inside sandbox)
        return super().can_parse(raw)

    def parse(
        self, raw: dict[str, Any], ctx: GovernanceContext
    ) -> list[AgentWardenToolRequest]:
        requests = super().parse(raw, ctx)
        for r in requests:
            r.tool_call.raw_format = "nemoclaw_ollama"
        return requests

    def reconstruct(
        self, raw: dict[str, Any], allowed: list[AgentWardenToolRequest]
    ) -> dict[str, Any]:
        """
        Reconstruct preserving any NIM-specific top-level fields
        that NemoClaw's Privacy Router may have added.
        """
        result = super().reconstruct(raw, allowed)
        # NIM may add extra top-level fields — preserve them transparently
        for field in self.NIM_EXTRA_FIELDS:
            if field in raw and field not in result:
                result[field] = raw[field]
        return result
