"""Task, Phase, GroundTruth, and Trajectory record formats.

Reuses AgentWarden's existing canonical types (ToolCall, GovernanceDecision,
Decision) from agentwarden.core.models rather than redefining them — the
Router already emits GovernanceDecision with stage/latency/reason, and its
ALLOW/BLOCK/REVIEW enum maps directly onto the paper's D2 (allow) / D3
(approve) decisions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from agentwarden.core.models import GovernanceDecision, ToolCall

# ---------------------------------------------------------------------------
# Task definition
# ---------------------------------------------------------------------------


@dataclass
class Phase:
    name: str                                          # e.g. "fetch"
    required_tools: set[str]                            # minimum viable set for THIS phase
    revocable_after: set[str]                            # withdraw once phase completes
    success_predicate: Callable[["Trajectory"], bool]    # programmatic check, not LLM-judged


@dataclass
class Task:
    task_id: str
    family: str
    phases: list[Phase]                  # ordered; requirements change across them
    full_tool_registry: set[str]         # everything the runtime could expose
    initial_prompt: str
    adversarial_variant: str | None = None    # None | "a1".."a5"


@dataclass
class GroundTruth:
    minimum_required_tools: dict[str, set[str]]     # phase name -> tools
    phase_boundaries: list[int]                       # turn indices where phase changes
    task_success_criteria: Callable[["Trajectory"], bool]
    expected_attack_blocked: bool | None = None       # for adversarial variants

    # --- extensions beyond the literal spec snippet, both needed to keep
    #     metrics.py pure functions of (traj, gt) alone --------------------

    revocable_after: dict[str, set[str]] = field(default_factory=dict)
        # phase name -> tools to withdraw once that phase ends. Mirrors
        # Phase.revocable_after; duplicated here because revocation_lag(traj, gt)
        # must not reach into Task to find out what *should* have been revoked.

    is_attack_invocation: Callable[[ToolCall], bool] | None = None
        # None for benign tasks. For adversarial variants, identifies which
        # ToolCall in the trajectory IS the attack action, so invocation_fpr/fnr
        # can label each InvocationAttempt as attack-vs-legitimate without a
        # metric ever reading anything but (traj, gt).


# ---------------------------------------------------------------------------
# Trajectory record format
# ---------------------------------------------------------------------------
#
# `turn` is a monotonically non-decreasing step counter over the whole
# session (one model action = one turn; a turn may contain several tool
# calls). GroundTruth.phase_boundaries and every event below are indexed
# against this same counter, so a metric can always ask "what was true at
# turn N" without re-deriving session structure.


@dataclass
class ExposureEvent:
    """A D1 (expose) event: a tool entering or leaving the model's registry.

    `exposed_tools` is the FULL exposed set immediately after this event,
    not a delta — a metric needing "what was exposed at turn N" takes the
    last event with turn <= N and reads this field directly. No session
    replay required anywhere downstream. `tool_name`/`action` are kept
    alongside purely for human-readable audit (which single tool changed,
    and how) and for revocation_lag, which needs the specific withdrawal
    event for a specific tool, not just the resulting set.
    """

    turn: int
    phase: str
    tool_name: str
    action: str                        # "expose" | "revoke"
    exposed_tools: frozenset[str]      # full exposed set after this event
    reason: str | None = None          # e.g. "phase_start", "phase_end_revocation", "escalation_grant"


@dataclass
class InvocationAttempt:
    """A D2/D3 event: the model attempted to call a tool.

    One of these is recorded for EVERY attempt regardless of outcome —
    ALLOW, BLOCK, and REVIEW alike. A blocked attempt is not dropped: it
    carries the GovernanceDecision that blocked it, which is the only
    place invocation_fpr's numerator (blocked legitimate calls) can come
    from. `result`/`error` are populated only when decision.decision is
    ALLOW and the call actually executed; they stay None for BLOCK/REVIEW.
    """

    turn: int
    phase: str
    tool_call: ToolCall
    was_exposed: bool                    # was tool_call.name in the exposed set at this turn?
    decision: GovernanceDecision          # ALLOW/BLOCK/REVIEW + stage + latency + reason, reused as-is
    routed_to_classifier: bool = False
        # Whether Stage 2 was actually consulted for this call, independent of
        # which stage produced the *final* decision (a stage1 BLOCK never reaches
        # stage2; a stage1 pass-through that stage2 also allows still shows
        # decision.stage == "router"). This is the field v1 never reported.
    invocation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
        # Stable id for this attempt, independent of decision.request_id, so a
        # later attempt's `derived_from` can point at it even across baselines
        # where the underlying request pipeline differs.
    derived_from: list[str] = field(default_factory=list)
        # invocation_ids of prior attempts whose `result` fed this call's
        # arguments — the provenance link A2 (indirect injection via tool
        # output) needs: was this escalation's argument traceable back to a
        # fetch result? Populated by the runner/task harness when it can show
        # dataflow (e.g. the injected string reappears in these arguments);
        # left empty when provenance isn't tracked for a given task.
    result: Any | None = None            # tool's return value; set only if the call executed
    error: str | None = None             # execution error, if any


@dataclass
class PhaseTransition:
    turn: int
    phase_from: str | None    # None for the first phase
    phase_to: str


@dataclass
class Trajectory:
    task_id: str
    baseline: str              # which config produced this run: "B0".."B7"
    session_id: str

    exposure_events: list[ExposureEvent] = field(default_factory=list)
    invocations: list[InvocationAttempt] = field(default_factory=list)
    phase_transitions: list[PhaseTransition] = field(default_factory=list)

    final_state: dict[str, Any] = field(default_factory=dict)
        # Oracle-checkable end state (files written, values returned, APIs
        # called...) — whatever task_success_criteria / success_predicate need.

    started_at: float = 0.0
    ended_at: float = 0.0


def exposed_tools_at(traj: Trajectory, turn: int) -> frozenset[str]:
    """The full exposed-tool set as of `turn` (last event with event.turn <= turn).

    Convenience lookup over ExposureEvent.exposed_tools snapshots — reads
    traj only, no ground truth, so calling this from inside a metric doesn't
    touch anything a metric isn't supposed to see.
    """
    current: frozenset[str] = frozenset()
    for ev in sorted(traj.exposure_events, key=lambda e: e.turn):
        if ev.turn > turn:
            break
        current = ev.exposed_tools
    return current
