"""Capability Governor — D1, the real component.

Decides which tools the model gets to SEE, as a function of task_type and
phase, loaded from config/capability_profiles.yaml. Multi-turn expansion
and revocation is not tracked here: expose() is stateless and pure — the
caller re-invokes it at each phase transition and diffs the returned set
against what was exposed before. This mirrors how GovernancePipeline's own
policies are pure (they decide, they don't execute), and it's what makes a
future learned Governor (B6) a drop-in replacement: same expose() signature,
same caller-diffs-the-set contract, different internals.

Fail-closed, not fail-open — deliberate asymmetry from RuleBasedPolicy.
RuleBasedPolicy fails open on a missing/broken config because Stage 1 is
defense-in-depth on top of Stage 2/3; under-blocking is the risk it guards
against. D1's entire purpose is preventing over-exposure, so a missing or
broken capability_profiles.yaml must never silently expose everything (or,
worse, look like a legitimate "exposed nothing" data point in an experiment
run). Two modes:
  - strict=False (default, production): log a warning, expose nothing.
  - strict=True  (benchmark/experiment callers must opt in explicitly):
    raise CapabilityProfileError. A benchmark run with a broken profile
    config must abort, not produce a silently-empty trajectory that looks
    like real data.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agentwarden.core.base import GovernanceProfile
from agentwarden.core.models import GovernanceContext, SessionState
from agentwarden.core.registry import register_profile
from agentwarden.policies.rules import _load_rules_yaml, _load_tools_yaml, _RULES_YAML, _TOOLS_YAML
from agentwarden.profiles.structural_task_type import MIN_CONFIDENCE, infer_task_type_structural

logger = logging.getLogger("agentwarden.profiles.capability_governor")

_HERE          = Path(__file__).parent.parent.parent   # repo root
_PROFILES_YAML = _HERE / "config" / "capability_profiles.yaml"

_EMPTY_PROFILE: dict[str, Any] = {"phases": {}, "default": []}


class CapabilityProfileError(RuntimeError):
    """Raised when capability_profiles.yaml is missing/unparseable and the
    Governor was constructed with strict=True."""


def _load_profiles_yaml(path: Path) -> tuple[dict, str | None]:
    """Returns (data, error). error is None on success."""
    if not path.exists():
        return {}, f"file not found: {path}"
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
        return data, None
    except Exception as e:
        return {}, f"parse error: {e}"


def _load_always_block(tools_file: Path | str | None, rules_file: Path | str | None) -> set[str]:
    """Same aggregation RuleBasedPolicy uses, reusing its loaders so the two
    stay in sync rather than maintaining a second copy of this logic."""
    tools_data = _load_tools_yaml(Path(tools_file) if tools_file else _TOOLS_YAML)
    rules_data = _load_rules_yaml(Path(rules_file) if rules_file else _RULES_YAML)

    always_block: set[str] = set()
    for tool_name, tool_cfg in (tools_data.get("tools") or {}).items():
        if tool_cfg.get("always_block"):
            always_block.add(tool_name.lower())
    for name in (rules_data.get("always_block") or []):
        always_block.add(name.lower())
    return always_block


@register_profile
class CapabilityGovernor(GovernanceProfile):
    """D1: task_type/phase -> minimum tool set, loaded from
    config/capability_profiles.yaml, with tools.yaml's always_block set
    subtracted unconditionally — a YAML authoring error in a phase profile
    can never expose an always-blocked tool.
    """

    name = "capability_governor"
    description = "Task-type/phase -> tool-set exposure profiles (D1), loaded from YAML."

    def __init__(
        self,
        profiles_file: Path | str | None = None,
        tools_file:    Path | str | None = None,
        rules_file:    Path | str | None = None,
        strict:        bool = False,
    ):
        self.strict = strict
        path = Path(profiles_file) if profiles_file else _PROFILES_YAML
        data, error = _load_profiles_yaml(path)

        if error:
            msg = f"CapabilityGovernor: failed to load {path}: {error} — failing closed (exposing nothing)."
            if strict:
                raise CapabilityProfileError(msg)
            logger.warning(msg)

        self._profiles: dict[str, Any] = data.get("profiles", {}) if not error else {}
        self._unknown:  dict[str, Any] = data.get("unknown", _EMPTY_PROFILE) if not error else _EMPTY_PROFILE
        self._always_block = _load_always_block(tools_file, rules_file)

        logger.info(
            "[CapabilityGovernor] Loaded %d profiles from %s | %d always_block tools subtracted | strict=%s",
            len(self._profiles), path, len(self._always_block), strict,
        )

    def expose(self, task_type: str, phase: str | None, session_state: SessionState) -> set[str]:
        profile = self._profiles.get(task_type, self._unknown)
        phases  = profile.get("phases", {})

        if phase is not None and phase in phases:
            candidate = set(phases[phase])
        else:
            candidate = set(profile.get("default", []))

        return candidate - self._always_block

    def get_always_block(self, context: GovernanceContext) -> set[str]:
        return set(self._always_block)

    def infer_task_type(self, offered_tools: set[str], min_confidence: float = MIN_CONFIDENCE) -> str | None:
        """Declaration-first, structural fallback: when no task_type was
        declared, guess from the shape of what was offered rather than not
        governing the session at all. Returns None when no profile's
        vocabulary clears `min_confidence` against `offered_tools` — callers
        must treat None as "don't apply D1," never as "apply D1 with a
        guess." See structural_task_type.py for the full rationale.
        """
        return infer_task_type_structural(offered_tools, self._profiles, min_confidence)
