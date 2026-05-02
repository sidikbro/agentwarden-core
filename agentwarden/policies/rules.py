"""
Rule-based policy — Stage 1, deterministic, 0.1ms.

All rules are loaded from config/rules.yaml and config/tools.yaml.
Nothing is hardcoded in Python — operators tune governance by editing YAML.

Loading order (merged, later wins):
  1. config/tools.yaml     — per-tool always_block / arg_watch flags
  2. config/rules.yaml     — always_block list, arg_patterns, injection_patterns
  3. agentwarden.yaml       — stages.rules.extra_always_block (operator additions)
  4. Constructor arguments  — programmatic override (testing only)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from agentwarden.core.base import PolicyPlugin
from agentwarden.core.models import (
    AgentWardenToolRequest,
    BlockReason,
    Decision,
    GovernanceDecision,
)
from agentwarden.core.registry import register_policy

logger = logging.getLogger("agentwarden.policies.rules")

# ── Config file locations (resolved relative to package root) ─────────────────
_HERE        = Path(__file__).parent.parent.parent   # repo root
_RULES_YAML  = _HERE / "config" / "rules.yaml"
_TOOLS_YAML  = _HERE / "config" / "tools.yaml"


def _flatten(arguments: dict[str, Any]) -> str:
    """Flatten tool arguments to a single string for pattern matching."""
    return " ".join(
        str(v) for v in arguments.values()
        if isinstance(v, (str, int, float))
    )


def _load_rules_yaml(path: Path) -> dict:
    """Load rules.yaml — returns empty dict if file missing or parse fails."""
    if not path.exists():
        logger.warning("Rules YAML not found: %s — using empty ruleset", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        logger.debug("Loaded rules from %s", path)
        return data
    except Exception as e:
        logger.error("Rules YAML parse error (%s): %s — using empty ruleset", path, e)
        return {}


def _load_tools_yaml(path: Path) -> dict:
    """Load tools.yaml — returns empty dict if file missing or parse fails."""
    if not path.exists():
        logger.warning("Tools YAML not found: %s — no tool-level rules loaded", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        logger.debug("Loaded tool registry from %s", path)
        return data
    except Exception as e:
        logger.error("Tools YAML parse error (%s): %s", path, e)
        return {}


def _compile_patterns(entries: list[dict]) -> list[tuple[re.Pattern, str]]:
    """Compile a list of {pattern, description} dicts into (regex, desc) tuples."""
    compiled = []
    for entry in entries:
        pattern = entry.get("pattern", "")
        desc    = entry.get("description", pattern)
        if not pattern:
            continue
        try:
            compiled.append((re.compile(pattern, re.I), desc))
        except re.error as e:
            logger.error("Invalid regex pattern '%s': %s — skipping", pattern, e)
    return compiled


@register_policy
class RuleBasedPolicy(PolicyPlugin):
    """
    Stage 1: Deterministic rule-based governance.

    Loads all rules from YAML config files. No hardcoded lists in Python.
    Three rule types:
      1. always_block   — tool names that are unconditionally blocked
      2. arg_patterns   — regex patterns on argument values
      3. injection_patterns — regex patterns on context/system prompt

    Safe fallback: if config files are missing, the policy logs a warning
    and uses an empty ruleset (ALLOW everything). This is intentional —
    fail-open at Stage 1 means Stage 2 (classifier) still runs.
    Operators should ensure config files are present in production.
    """
    name        = "rules"
    priority    = 0
    is_terminal = False

    def __init__(
        self,
        rules_file:   Path | str | None = None,
        tools_file:   Path | str | None = None,
        extra_always_block: list[str]   = None,
    ):
        """
        Args:
            rules_file:         Path to rules.yaml. Defaults to config/rules.yaml.
            tools_file:         Path to tools.yaml. Defaults to config/tools.yaml.
            extra_always_block: Additional tool names to always-block (from
                                agentwarden.yaml stages.rules.extra_always_block).
        """
        rules_path = Path(rules_file) if rules_file else _RULES_YAML
        tools_path = Path(tools_file) if tools_file else _TOOLS_YAML

        rules_data = _load_rules_yaml(rules_path)
        tools_data = _load_tools_yaml(tools_path)

        # ── Build always_block set ────────────────────────────────────────────
        self.always_block: set[str] = set()

        # From tools.yaml: tools with always_block: true
        for tool_name, tool_cfg in (tools_data.get("tools") or {}).items():
            if tool_cfg.get("always_block"):
                self.always_block.add(tool_name.lower())

        # From rules.yaml: explicit always_block list
        for name in (rules_data.get("always_block") or []):
            self.always_block.add(name.lower())

        # From agentwarden.yaml stages.rules.extra_always_block (operator additions)
        for name in (extra_always_block or []):
            self.always_block.add(name.lower())

        # ── Build arg patterns ────────────────────────────────────────────────
        # From tools.yaml: per-tool arg_watch patterns with block: true
        tool_arg_patterns = []
        for tool_name, tool_cfg in (tools_data.get("tools") or {}).items():
            for watch in (tool_cfg.get("arg_watch") or []):
                if watch.get("block"):
                    tool_arg_patterns.append({
                        "pattern":     watch["pattern"],
                        "description": f"[{tool_name}] {watch.get('reason', watch['pattern'])}",
                    })

        # From rules.yaml: global arg_patterns list
        rules_arg_patterns = rules_data.get("arg_patterns") or []

        self._arg_pats = _compile_patterns(tool_arg_patterns + rules_arg_patterns)

        # ── Build injection patterns ──────────────────────────────────────────
        self._inj_pats = _compile_patterns(
            rules_data.get("injection_patterns") or []
        )

        # ── Build classifier skip set ─────────────────────────────────────────
        self.classifier_skip: set[str] = set()
        for name in (rules_data.get("classifier_skip") or []):
            self.classifier_skip.add(name.lower())
        # Also from tools.yaml: tools with classifier_skip: true
        for tool_name, tool_cfg in (tools_data.get("tools") or {}).items():
            if tool_cfg.get("classifier_skip"):
                self.classifier_skip.add(tool_name.lower())

        logger.info(
            "[RuleBasedPolicy] Loaded: %d always_block | %d arg_patterns | "
            "%d injection_patterns | %d classifier_skip",
            len(self.always_block), len(self._arg_pats),
            len(self._inj_pats), len(self.classifier_skip),
        )

    def evaluate(self, request: AgentWardenToolRequest) -> GovernanceDecision:
        name = request.tool_call.name.lower()

        # ── Check 1: always_block ─────────────────────────────────────────────
        if name in self.always_block:
            return GovernanceDecision(
                request_id   = request.request_id,
                tool_name    = request.tool_call.name,
                decision     = Decision.BLOCK,
                reason       = BlockReason.ALWAYS_BLOCK_TOOL,
                reason_detail= f"Tool '{request.tool_call.name}' is unconditionally blocked.",
                confidence   = 1.0,
                stage        = self.name,
                reward_signal= -1.0,
            )

        # ── Check 2: argument patterns ────────────────────────────────────────
        args_str = _flatten(request.tool_call.arguments)
        for pat, desc in self._arg_pats:
            if pat.search(args_str):
                return GovernanceDecision(
                    request_id   = request.request_id,
                    tool_name    = request.tool_call.name,
                    decision     = Decision.BLOCK,
                    reason       = BlockReason.DANGEROUS_ARGUMENT,
                    reason_detail= f"Argument matched dangerous pattern: {desc}",
                    confidence   = 1.0,
                    stage        = self.name,
                    reward_signal= -1.0,
                )

        # ── Check 3: injection patterns (on context/system prompt) ────────────
        context_str = getattr(request.context, "system_prompt", "") or ""
        for pat, desc in self._inj_pats:
            if pat.search(context_str):
                return GovernanceDecision(
                    request_id   = request.request_id,
                    tool_name    = request.tool_call.name,
                    decision     = Decision.BLOCK,
                    reason       = BlockReason.INJECTION_PATTERN,
                    reason_detail= f"Prompt injection detected: {desc}",
                    confidence   = 1.0,
                    stage        = self.name,
                    reward_signal= -1.0,
                )

        return GovernanceDecision(
            request_id= request.request_id,
            tool_name = request.tool_call.name,
            decision  = Decision.ALLOW,
            stage     = self.name,
        )

    def should_skip_classifier(self, tool_name: str) -> bool:
        """Return True if this tool should skip Stage 2 (LLM classifier)."""
        return tool_name.lower() in self.classifier_skip
