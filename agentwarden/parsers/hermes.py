"""
Hermes XML parser, DeepAgents parser, and LangGraph parser.

── Hermes (NousResearch) ────────────────────────────────────────────────────
Wire format: tool calls embedded in <tool_call> XML tags inside message content.
    {
      "message": {
        "role": "assistant",
        "content": "<tool_call>\n{\"name\": \"read\", \"arguments\": {\"path\": \"README.md\"}}\n</tool_call>"
      }
    }
Used by: Hermes-3, OpenHermes, Nous-Hermes models via Ollama.

── DeepAgents (LangChain, v0.5.0, April 2026) ───────────────────────────────
Wire format: standard OpenAI JSON /v1/chat/completions.
Uses LangChain's init_chat_model — emits standard tool_calls list.
Built-in tool names (from filesystem middleware):
    ls, read_file, write_file, edit_file, glob, grep, execute
    task (subagent delegation, CRITICAL — always block)
    compact_conversation (context management)
    write_todos, read_todos (planning/memory)
Ref: langchain-ai/deepagents middleware/filesystem.py

── LangGraph (standalone) ───────────────────────────────────────────────────
Wire format: standard OpenAI JSON.
Tool names depend on user-defined tools — no fixed name mapping.
Registered as a thin subclass that normalises common patterns.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from agentwarden.core.base import ToolParser
from agentwarden.core.models import (
    AgentWardenToolRequest,
    GovernanceContext,
    Runtime,
    ToolCall,
)
from agentwarden.core.registry import register_parser
from agentwarden.parsers.openai import OpenAIParser

logger = logging.getLogger("agentwarden.parsers.hermes")

# Matches <tool_call>...</tool_call> blocks (case-insensitive, multiline)
_TC_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)


@register_parser
class HermesParser(ToolParser):
    """
    NousResearch Hermes XML tool-call format.
    Falls back to OpenAI JSON format if no XML tool_call tags found.
    """
    runtime = Runtime.HERMES

    # Tool name normalisation — Hermes models sometimes use different casing/names
    EXEC_ALIASES  = {"execute", "bash", "shell", "run_command", "exec", "terminal",
                     "run", "cmd", "command"}
    SPAWN_ALIASES = {"task", "spawn", "subagent", "delegate", "sessions_spawn",
                     "create_agent", "create_subagent"}
    WRITE_ALIASES = {"write_file", "write", "save_file", "create_file", "edit_file",
                     "writefile", "savefile"}
    READ_ALIASES  = {"read_file", "readfile", "cat", "open", "load"}
    LS_ALIASES    = {"ls", "list_files", "listfiles", "dir"}

    def can_parse(self, raw: dict[str, Any]) -> bool:
        content = (raw.get("message") or {}).get("content", "")
        return bool(content and "<tool_call>" in content) or OpenAIParser().can_parse(raw)

    def parse(
        self, raw: dict[str, Any], ctx: GovernanceContext
    ) -> list[AgentWardenToolRequest]:
        content = (raw.get("message") or {}).get("content", "")

        # XML path
        if content and "<tool_call>" in content:
            requests = []
            for i, match in enumerate(_TC_RE.findall(content)):
                try:
                    parsed = json.loads(match.strip())
                    args   = parsed.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    name = self._normalise(parsed.get("name", ""))
                    requests.append(
                        AgentWardenToolRequest(
                            tool_call=ToolCall(
                                name=name,
                                arguments=args,
                                raw_id=f"hermes_xml_{i}",
                                raw_format="hermes_xml",
                            ),
                            context=ctx,
                            raw_response_body=raw,
                        )
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Hermes XML parse error at index %d: %s", i, e)
            return requests

        # Fallback to OpenAI JSON format
        return OpenAIParser().parse(raw, ctx)

    def reconstruct(
        self, raw: dict[str, Any], allowed: list[AgentWardenToolRequest]
    ) -> dict[str, Any]:
        content = (raw.get("message") or {}).get("content", "")

        # XML path — remove blocked tool_call blocks from content string
        if content and "<tool_call>" in content:
            allowed_indices = {
                int(r.tool_call.raw_id.split("_")[-1])
                for r in allowed
                if (r.tool_call.raw_id or "").startswith("hermes_xml_")
            }
            matches = list(_TC_RE.finditer(content))
            new_content = content
            for i, m in reversed(list(enumerate(matches))):
                if i not in allowed_indices:
                    new_content = new_content[:m.start()] + new_content[m.end():]

            if not allowed_indices and matches:
                new_content += (
                    "\n⚠️ AgentWarden blocked one or more tool calls. "
                    "The requested operations are not permitted in this governed session."
                )

            return {**raw, "message": {**(raw.get("message") or {}), "content": new_content}}

        # Fallback to OpenAI reconstruction
        return OpenAIParser().reconstruct(raw, allowed)

    def _normalise(self, name: str) -> str:
        """Normalise tool names to AgentWarden canonical names."""
        l = name.lower().strip()
        if l in self.EXEC_ALIASES:  return "exec"
        if l in self.SPAWN_ALIASES: return "sessions_spawn"
        if l in self.WRITE_ALIASES: return "write_file"
        if l in self.READ_ALIASES:  return "read"
        if l in self.LS_ALIASES:    return "ls"
        return name


@register_parser
class DeepAgentsParser(OpenAIParser):
    """
    LangChain DeepAgents (v0.5.0, April 2026) parser.

    DeepAgents uses standard OpenAI JSON wire format via LangChain's init_chat_model.
    This parser normalises DeepAgents' built-in tool names to AgentWarden canonical names.

    Built-in DeepAgents tools and their AgentWarden mappings:
    ┌─────────────────────┬──────────────────┬───────────────────┐
    │ DeepAgents name     │ AgentWarden name  │ Risk              │
    ├─────────────────────┼──────────────────┼───────────────────┤
    │ read_file           │ read             │ safe              │
    │ ls                  │ ls               │ safe              │
    │ glob                │ glob             │ safe              │
    │ grep                │ grep             │ safe              │
    │ read_todos          │ read_todos       │ safe              │
    │ compact_conversation│ (pass-through)   │ safe              │
    │ write_file          │ write_file       │ medium            │
    │ edit_file           │ edit             │ medium            │
    │ write_todos         │ write_todos      │ medium            │
    │ execute             │ exec             │ CRITICAL/block    │
    │ task                │ sessions_spawn   │ CRITICAL/block    │
    └─────────────────────┴──────────────────┴───────────────────┘

    Note: 'execute' maps to 'exec' (always-block).
          'task' maps to 'sessions_spawn' (always-block) — this is DeepAgents'
          subagent delegation tool, high governance priority.
    """
    runtime = Runtime.DEEPAGENTS

    # Confirmed from deepagents/middleware/filesystem.py (v0.5.0)
    NAME_MAP: dict[str, str] = {
        # Filesystem — safe reads
        "read_file":           "read",
        "ls":                  "ls",
        "glob":                "glob",
        "grep":                "grep",
        "read_todos":          "read_todos",

        # Filesystem — writes (medium risk)
        "write_file":          "write_file",
        "edit_file":           "edit",
        "write_todos":         "write_todos",

        # Context management (safe, pass-through)
        "compact_conversation": "compact_conversation",

        # CRITICAL — always blocked
        "execute":             "exec",           # shell execution
        "task":                "sessions_spawn", # subagent delegation
    }

    def parse(
        self, raw: dict[str, Any], ctx: GovernanceContext
    ) -> list[AgentWardenToolRequest]:
        requests = super().parse(raw, ctx)
        for r in requests:
            original_name       = r.tool_call.name
            r.tool_call.name    = self.NAME_MAP.get(original_name, original_name)
            r.tool_call.raw_format = "deepagents_json"
            if r.tool_call.name != original_name:
                logger.debug(
                    "DeepAgents name normalised: %s → %s", original_name, r.tool_call.name
                )
        return requests


@register_parser
class LangGraphParser(OpenAIParser):
    """
    LangGraph standalone agent parser.

    LangGraph agents use standard OpenAI JSON format.
    Tool names are user-defined — no fixed normalisation.
    This parser applies common alias normalisation for shell/spawn patterns
    and marks the runtime for logging/audit purposes.

    If you use LangGraph with custom tool names that conflict with
    AgentWarden's always-block list, add them to config/rules.yaml
    under extra_always_block.
    """
    runtime = Runtime.LANGGRAPH

    # Common patterns in LangGraph tool names worth normalising
    EXEC_PATTERNS  = {"bash_tool", "run_bash", "shell_exec", "execute_command",
                      "run_command", "terminal", "python_repl", "python_exec"}
    SPAWN_PATTERNS = {"create_agent", "spawn_agent", "delegate_task",
                      "create_subagent", "handoff"}

    def parse(
        self, raw: dict[str, Any], ctx: GovernanceContext
    ) -> list[AgentWardenToolRequest]:
        requests = super().parse(raw, ctx)
        for r in requests:
            name = r.tool_call.name.lower()
            if name in self.EXEC_PATTERNS:
                logger.debug("LangGraph exec alias normalised: %s → exec", r.tool_call.name)
                r.tool_call.name = "exec"
            elif name in self.SPAWN_PATTERNS:
                logger.debug("LangGraph spawn alias normalised: %s → sessions_spawn", r.tool_call.name)
                r.tool_call.name = "sessions_spawn"
            r.tool_call.raw_format = "langgraph_json"
        return requests
