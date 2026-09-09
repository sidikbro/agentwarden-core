"""Structured view over config/tools.yaml + config/rules.yaml — the
independently-authored ground truth every training label ultimately
traces back to (docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md §1's standing
rule). Reuses agentwarden.policies.rules's existing YAML loaders rather
than re-implementing them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentwarden.policies.rules import _load_rules_yaml, _load_tools_yaml, _RULES_YAML, _TOOLS_YAML


@dataclass
class ToolEntry:
    name: str
    description: str
    risk_level: int
    categories: list[str]
    always_block: bool
    classifier_skip: bool


def load_tool_registry(tools_file=None, rules_file=None) -> dict[str, ToolEntry]:
    tools_data = _load_tools_yaml(tools_file or _TOOLS_YAML)
    rules_data = _load_rules_yaml(rules_file or _RULES_YAML)

    always_block_names = {n.lower() for n in (rules_data.get("always_block") or [])}
    classifier_skip_names = {n.lower() for n in (rules_data.get("classifier_skip") or [])}

    registry: dict[str, ToolEntry] = {}
    for name, cfg in (tools_data.get("tools") or {}).items():
        registry[name] = ToolEntry(
            name=name,
            description=cfg.get("description", ""),
            risk_level=int(cfg.get("risk_level", 2)),
            categories=list(cfg.get("categories") or []),
            always_block=bool(cfg.get("always_block")) or name.lower() in always_block_names,
            classifier_skip=bool(cfg.get("classifier_skip")) or name.lower() in classifier_skip_names,
        )
    return registry


def load_arg_patterns(rules_file=None) -> list[dict[str, Any]]:
    """rules.yaml's global arg_patterns — [{pattern, description, severity}]."""
    rules_data = _load_rules_yaml(rules_file or _RULES_YAML)
    return list(rules_data.get("arg_patterns") or [])


def by_risk_level(registry: dict[str, ToolEntry]) -> dict[int, list[ToolEntry]]:
    out: dict[int, list[ToolEntry]] = {}
    for entry in registry.values():
        out.setdefault(entry.risk_level, []).append(entry)
    return out
