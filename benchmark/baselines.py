"""Baseline runners — combine a task family with a specific governance
configuration (B0..B7) via the shared run_scripted/run_via_pipeline
machinery in runner.py.

Implements B0, B1, B2, B3, B4, B5, B6, B7 from the baseline matrix
(docs/v2/EXPERIMENTAL_PLAN_v0.1.md §3).

B0, B1, B2, B3, B7 have D2 = none, so they run through run_scripted (no
live pipeline/Ollama dependency). B4 has a real D2 (rules + classifier),
so it runs through run_via_pipeline and needs a live GovernancePipeline.

B1 caveat, read before using it: "prompting-only self-restriction" is a
claim about live LLM behavior in response to a system prompt. This
benchmark's baselines execute SCRIPTED plans — there is no point in a
scripted trajectory where a system prompt could change what gets called;
the plan already decided that when it was written. So run_b1() is
mechanically identical to run_b0() here (full registry, D2 none), and
their reported numbers WILL be identical. That is not a shortcut or a bug
— it is the honest limit of what a scripted-plan benchmark can say about
B1. Testing the actual hypothesis ("does the model reliably self-restrict
when told to") requires a live-agent runner that hasn't been built yet.
Report B1 alongside B0 with this caveat attached, not as if it were a
real second data point.

Two conditions for where D1's task_type comes from (B3 only), run and
reported SEPARATELY per the option-3 decision (declaration-first,
structural fallback, no learned classifier upstream of D1):
  - "declared":  task.family passed directly to expose() — the deployment
    shape v2 targets (agents with a known task purpose).
  - "fallback":  task_type comes from CapabilityGovernor.infer_task_type()
    against task.full_tool_registry, exactly mirroring what the live proxy
    does when no X-AgentWarden-Task-Type header is present. Its own
    condition, never blended with "declared" — that separation is the
    entire point of not putting a learned classifier in front of D1.
"""
from __future__ import annotations

from typing import Literal

from agentwarden.core.models import SessionState
from agentwarden.core.pipeline import GovernancePipeline
from agentwarden.profiles.capability_governor import CapabilityGovernor
from agentwarden.profiles.placeholder_learned_governor import PlaceholderLearnedGovernor
from benchmark.runner import ExposureFn, ScriptedCall, run_scripted, run_via_pipeline
from benchmark.schema import GroundTruth, Task, Trajectory

Condition = Literal["declared", "fallback"]


def _full_registry_exposure_fn(task: Task) -> ExposureFn:
    def exposure_fn(phase: str, world_state: dict) -> set[str]:
        return set(task.full_tool_registry)
    return exposure_fn


def run_b0(task: Task, plan: list[ScriptedCall], session_id: str = "b0-session") -> Trajectory:
    """B0: all tools exposed, no D2 enforcement. Ungoverned upper bound on
    utility, lower bound on security."""
    return run_scripted(task, plan, _full_registry_exposure_fn(task), baseline="B0", session_id=session_id)


def run_b1(task: Task, plan: list[ScriptedCall], session_id: str = "b1-session") -> Trajectory:
    """B1: "prompting-only". See module docstring — mechanically identical
    to run_b0() in this benchmark; the difference B1 is meant to test
    cannot be exercised by a scripted plan."""
    return run_scripted(task, plan, _full_registry_exposure_fn(task), baseline="B1", session_id=session_id)


# B2: crudest static governance — ONE fixed, task-type-agnostic allowlist,
# not conditioned on task_type or phase at all (unlike B3's per-task-type
# profiles). Deliberately excludes every mutating/terminal-action tool
# across all five families (write_draft, send_email, edit_code,
# run_migration, commit_changes, schedule_event, send_reply,
# apply_remediation, export_data) — a global allowlist author playing it
# safe blocks writes everywhere, regardless of task. Every task in this
# benchmark therefore fails under B2 by construction; WHERE it fails
# (which phase) varies by family, since some families need a write-type
# tool earlier than others (e.g. repo_triage's edit phase, inbox_workflow's
# schedule phase) — that variation is real signal, not noise.
B2_GLOBAL_ALLOWLIST = {
    "search_web", "fetch_url", "fetch_data", "extract_facts", "parse_pdf", "summarize_pdf",
    "inspect_repo", "read_code", "run_tests",
    "read_email", "open_attachment", "extract_dates",
    "read_alert", "query_logs", "query_metrics", "correlate_events",
    "locate_source", "transform_data", "validate_data",
}


def run_b2(task: Task, plan: list[ScriptedCall], session_id: str = "b2-session") -> Trajectory:
    """B2: global allowlist, D2 none."""
    def exposure_fn(phase: str, world_state: dict) -> set[str]:
        return set(B2_GLOBAL_ALLOWLIST)
    return run_scripted(task, plan, exposure_fn, baseline="B2", session_id=session_id)


def run_b4(
    task: Task,
    plan: list[ScriptedCall],
    pipeline: GovernancePipeline,
    session_id: str = "b4-session",
) -> Trajectory:
    """B4: classifier-only. D1 trivial (full registry, same exposure as
    B0/B1), D2 real (RuleBasedPolicy + LLMClassifierPolicy via the actual
    GovernancePipeline). Isolates D2's effect by holding D1 constant.
    Needs a live pipeline (real classifier backend)."""
    return run_via_pipeline(task, plan, _full_registry_exposure_fn(task), pipeline, baseline="B4", session_id=session_id)


def run_b7(
    task: Task,
    gt: GroundTruth,
    plan: list[ScriptedCall],
    session_id: str = "b7-session",
) -> Trajectory:
    """B7: oracle. D1 = ground-truth minimum per phase, D2 = none (nothing
    left to block — only ever-necessary tools were exposed to begin with).
    Upper bound; quantifies headroom for every other baseline."""
    def exposure_fn(phase: str, world_state: dict) -> set[str]:
        return set(gt.minimum_required_tools.get(phase, set()))
    return run_scripted(task, plan, exposure_fn, baseline="B7", session_id=session_id)


def resolve_task_type(task: Task, governor: CapabilityGovernor, condition: Condition) -> str:
    if condition == "declared":
        return task.family
    inferred = governor.infer_task_type(set(task.full_tool_registry))
    return inferred if inferred is not None else "unknown"


def b3_exposure_fn(task: Task, governor: CapabilityGovernor, condition: Condition) -> ExposureFn:
    task_type = resolve_task_type(task, governor, condition)

    def exposure_fn(phase: str, world_state: dict) -> set[str]:
        return governor.expose(task_type, phase, SessionState())

    return exposure_fn


def run_b3(
    task: Task,
    plan: list[ScriptedCall],
    governor: CapabilityGovernor,
    condition: Condition,
    session_id: str = "b3-session",
) -> Trajectory:
    exposure_fn = b3_exposure_fn(task, governor, condition)
    return run_scripted(task, plan, exposure_fn, baseline=f"B3:{condition}", session_id=session_id)


def run_b5(
    task: Task,
    plan: list[ScriptedCall],
    governor: CapabilityGovernor,
    pipeline: GovernancePipeline,
    condition: Condition = "declared",
    session_id: str = "b5-session",
) -> Trajectory:
    """B5: YAML + Router — the v1 production configuration. D1 is the
    SAME mechanism as B3 (reuses b3_exposure_fn: real CapabilityGovernor,
    declared-or-fallback task_type), D2 is the real GovernancePipeline
    (rules + classifier) instead of none. Needs a live pipeline (real
    classifier backend)."""
    exposure_fn = b3_exposure_fn(task, governor, condition)
    return run_via_pipeline(task, plan, exposure_fn, pipeline, baseline=f"B5:{condition}", session_id=session_id)


def b6_exposure_fn(task: Task, governor: PlaceholderLearnedGovernor) -> ExposureFn:
    """Stateful closure: tracks phase_history across calls, since the
    learned Governor's expose() needs to see how far the session has
    progressed, not just the current phase name. Same "caller tracks
    history, policy stays a pure function of its three arguments" pattern
    established for CapabilityGovernor — only this closure accumulates
    state, expose() itself doesn't."""
    history: list[str] = []

    def exposure_fn(phase: str, world_state: dict) -> set[str]:
        if not history or history[-1] != phase:
            history.append(phase)
        session_state = SessionState(
            prior_actions=list(world_state.keys()),
            phase_history=list(history),
        )
        return governor.expose(task.family, phase, session_state)

    return exposure_fn


def run_b6(
    task: Task,
    plan: list[ScriptedCall],
    governor: PlaceholderLearnedGovernor,
    pipeline: GovernancePipeline,
    session_id: str = "b6-session",
) -> Trajectory:
    """B6: learned Governor (PLACEHOLDER — see
    agentwarden/profiles/placeholder_learned_governor.py's module docstring
    for what this is and isn't) + real Router (rules + classifier). Needs
    a live pipeline."""
    exposure_fn = b6_exposure_fn(task, governor)
    return run_via_pipeline(task, plan, exposure_fn, pipeline, baseline="B6", session_id=session_id)
