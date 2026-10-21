"""Shared types and the mechanical anchor-derivation rule for every A4
benchmark adapter (docs/v2/A4_MULTITURN_SPEC_v0.2.md §13 steps 1-2, §7's
"must be mechanical and stated... must not be hand-tuned per case"
requirement).

The rule, stated once here and applied identically by every adapter:

  - `authorized_task` -- the benchmark's OWN earliest declared
    natural-language statement of the task, verbatim. Never derived from
    an attack-goal field, a predicted-attack field, or anything else
    that carries the label. Each adapter's module docstring says
    exactly which field this is for its benchmark, and whether that
    field is genuinely trusted-producer-written (AgentDojo's PROMPT) or
    only the nearest available stand-in (STAC's/MT-AgentRisk's opening
    turn, itself benchmark-synthesized) -- that distinction matters for
    how the resulting anchor may be interpreted and is not papered over.

  - `task_type` -- always `TaskType.UNKNOWN`, for every case of every
    benchmark. Deliberately not classified: AgentWarden's existing
    TaskType enum (SUMMARISATION/FILE_READ/WEB_RESEARCH/CODE_EXECUTION/
    EMAIL/UNKNOWN) doesn't fit these benchmarks' domains, and picking a
    value per case would be exactly the kind of per-case judgment this
    rule exists to avoid.

  - `scope` -- a single-element frozenset holding the domain/category
    tag the benchmark ITSELF declares (STAC: `generation_config
    ["environment"]`; MT-AgentRisk: the MCP tool category implied by
    the task directory's own path; AgentDojo: the suite name). Never a
    tag inferred by reading the case's content.

  - `allowed_effects` -- derived via `effect_for_tool_name`/
    `effects_for_tool_calls` below from a tool-name set, OR left at
    `ALL_EFFECTS` when no such set is available without risking
    label-correlation through the benchmark's own construction (see
    stac_adapter.py's docstring for the specific confound that rules
    this out for STAC and, by the same argument, for MT-AgentRisk).
    AgentDojo is the one benchmark where a genuinely unconfounded call
    set exists (`ground_truth`, which exists independent of any
    attack), so it is used there.

  - `max_sensitivity` -- a fixed constant (`UNINFORMATIVE_MAX_SENSITIVITY`),
    uniform across every case of every benchmark. Picking a real value
    per case would require the same kind of domain judgment §9's
    anchor-only-leakage gate exists to test for, not something to
    pre-empt here.

None of this is validated yet -- that is exactly what
docs/v2/A4_MULTITURN_SPEC_v0.2.md §9's validity gates (build-order step
3, not built here) are for. A gate failure on these anchors would be a
reportable result, not a reason to go back and hand-tune this rule
per-case after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentwarden.core.models import TaskType, ToolCall
from agentwarden.core.session_authorization import Effect, SessionAuthorization

ALL_EFFECTS: frozenset[Effect] = frozenset(Effect)

UNINFORMATIVE_MAX_SENSITIVITY = 2
"""Fixed, uninformative-by-design placeholder -- see module docstring."""

# Static, authored once, never adjusted per case or per benchmark. Checked
# in this fixed order; a tool name may match more than one effect (e.g. a
# tool whose name contains both "send" and "update" is WRITE and NETWORK).
_EFFECT_KEYWORDS: dict[Effect, tuple[str, ...]] = {
    Effect.EXEC: ("exec", "run_", "cmd", "execute", "shell"),
    Effect.DELEGATE: ("delegate", "spawn", "subagent", "assign_"),
    Effect.NETWORK: (
        "send_", "email", "fetch", "http", "post_", "browse", "navigate",
        "request_", "message",
    ),
    Effect.WRITE: (
        "write", "create_", "update_", "append_", "delete_", "remove_",
        "set_", "schedule_",
    ),
    Effect.READ: ("read", "get_", "search_", "list_", "query", "lookup"),
}


def effect_for_tool_name(tool_name: str) -> frozenset[Effect]:
    """Classify a tool name into zero or more Effect categories by
    keyword match against `_EFFECT_KEYWORDS`. A tool matching no keyword
    contributes no effect -- conservative under-claiming rather than
    guessing."""
    name = tool_name.lower()
    hits = {effect for effect, keywords in _EFFECT_KEYWORDS.items() if any(k in name for k in keywords)}
    return frozenset(hits)


def effects_for_tool_calls(tool_names: list[str]) -> frozenset[Effect]:
    result: set[Effect] = set()
    for name in tool_names:
        result |= effect_for_tool_name(name)
    return frozenset(result)


@dataclass(frozen=True)
class AdapterTurn:
    """One step of a benchmark trajectory, kept close to each
    benchmark's own native shape rather than forced into one format
    across adapters -- see each adapter's module docstring for what
    `role` values it actually produces."""

    role: str
    content: str | None = None
    tool_call: ToolCall | None = None


@dataclass(frozen=True)
class AdapterCase:
    """What every A4 benchmark adapter emits: a mechanically-derived
    anchor plus the benchmark's own trajectory and label. Nothing else --
    no `BoundedSessionSummary`, no `build_decision_input()` call, no gate
    evaluation. Those belong to later build-order steps, which decide how
    to turn this into a governance decision input; this type is
    deliberately upstream of that decision.
    """

    source: str
    case_id: str
    anchor: SessionAuthorization
    turns: tuple[AdapterTurn, ...]
    label: dict[str, Any]
    raw: Any = None


def build_anchor(
    *,
    authorized_task: str,
    scope: frozenset[str],
    allowed_effects: frozenset[Effect],
    issued_by: str,
) -> SessionAuthorization:
    """The one call site every adapter uses to construct its anchor --
    see this module's docstring for the rule and its stated limits."""
    return SessionAuthorization(
        authorized_task=authorized_task,
        task_type=TaskType.UNKNOWN,
        scope=scope,
        allowed_effects=allowed_effects,
        max_sensitivity=UNINFORMATIVE_MAX_SENSITIVITY,
        issued_by=issued_by,
        issued_at=0.0,
        expires_at=None,
    )
