"""Deterministic scripted executors.

Runs a fixed, recorded plan of tool calls (a "scripted agent") against an
exposure policy and produces a Trajectory. This is the shared low-level
bookkeeping — turn counting, exposure snapshots, phase transitions,
invocation recording — that every caller builds on, so every baseline
produces records in exactly the same shape.

Two executors:
  - run_scripted:    B0 governance semantics only (exposed => ALLOW, not
                      exposed => BLOCK, nothing else in between). Used by
                      validate.py's ground-truth checks, which need to
                      isolate D1 (exposure) without any D2/D3 policy in
                      the loop. Never touches GovernancePipeline.
  - run_via_pipeline: D2/D3 decisions come from the REAL, registered
                      GovernancePipeline (RuleBasedPolicy +
                      LLMClassifierPolicy — real config/*.yaml, real
                      classifier backend). D1 (exposure) is supplied by the
                      caller's exposure_fn in both executors. A real D1
                      implementation now exists —
                      agentwarden.profiles.capability_governor.CapabilityGovernor
                      — wiring it in is a one-line exposure_fn:
                      `lambda phase, ws: governor.expose(task.family, phase, ws)`.
                      Neither executor calls it directly; that's the
                      caller's choice of baseline (B0/oracle/withhold use
                      scripted ground-truth sets instead, deliberately).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from agentwarden.core.models import (
    Decision,
    GovernanceContext,
    GovernanceDecision,
    ToolCall,
)
from agentwarden.core.pipeline import GovernancePipeline
from benchmark.schema import (
    ExposureEvent,
    InvocationAttempt,
    PhaseTransition,
    Task,
    Trajectory,
)


@dataclass
class ScriptedCall:
    """One step of a recorded/scripted agent plan."""

    phase: str
    tool_call: ToolCall
    execute: Callable[[dict[str, Any]], Any]
        # (world_state) -> result. Mutates world_state directly for whatever
        # keys later success predicates need; the return value is only used
        # for provenance bookkeeping. Only called if the tool is exposed.
    step_id: str | None = None
        # optional label other steps can reference via derived_from
    derived_from: list[str] = field(default_factory=list)
        # step_ids of prior steps this call's arguments were derived from


ExposureFn = Callable[[str, dict[str, Any]], set[str]]
# (current_phase, world_state) -> exposed tool set for that phase.


def run_scripted(
    task: Task,
    plan: list[ScriptedCall],
    exposure_fn: ExposureFn,
    baseline: str = "SCRIPTED",
    session_id: str = "scripted-session",
) -> Trajectory:
    traj = Trajectory(task_id=task.task_id, baseline=baseline, session_id=session_id)
    world_state: dict[str, Any] = {}
    step_ids: dict[str, str] = {}   # ScriptedCall.step_id -> assigned invocation_id
    current_phase: str | None = None
    exposed: set[str] = set()
    turn = 0

    for call in plan:
        turn += 1

        if call.phase != current_phase:
            traj.phase_transitions.append(
                PhaseTransition(turn=turn, phase_from=current_phase, phase_to=call.phase)
            )
            current_phase = call.phase

        new_exposed = exposure_fn(current_phase, world_state)
        if new_exposed != exposed:
            for added in sorted(new_exposed - exposed):
                traj.exposure_events.append(ExposureEvent(
                    turn=turn, phase=current_phase, tool_name=added,
                    action="expose", exposed_tools=frozenset(new_exposed),
                ))
            for removed in sorted(exposed - new_exposed):
                traj.exposure_events.append(ExposureEvent(
                    turn=turn, phase=current_phase, tool_name=removed,
                    action="revoke", exposed_tools=frozenset(new_exposed),
                ))
            exposed = new_exposed

        was_exposed = call.tool_call.name in exposed
        decision = GovernanceDecision(
            request_id=str(turn),
            tool_name=call.tool_call.name,
            decision=Decision.ALLOW if was_exposed else Decision.BLOCK,
            reason_detail=None if was_exposed else "tool not exposed",
            stage="exposure_gate",
        )
        inv = InvocationAttempt(
            turn=turn,
            phase=current_phase,
            tool_call=call.tool_call,
            was_exposed=was_exposed,
            decision=decision,
            routed_to_classifier=False,
            derived_from=[step_ids[r] for r in call.derived_from if r in step_ids],
        )
        if call.step_id:
            step_ids[call.step_id] = inv.invocation_id

        if was_exposed:
            try:
                inv.result = call.execute(world_state)
            except Exception as e:
                inv.error = str(e)

        traj.invocations.append(inv)

    traj.final_state = world_state
    return traj


def _to_openai_tool_call_response(tool_call: ToolCall, turn: int) -> dict[str, Any]:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"call_{turn}",
                "type": "function",
                "function": {"name": tool_call.name, "arguments": tool_call.arguments},
            }],
        }
    }


def run_via_pipeline(
    task: Task,
    plan: list[ScriptedCall],
    exposure_fn: ExposureFn,
    pipeline: GovernancePipeline,
    context: GovernanceContext | None = None,
    baseline: str = "B5",
    session_id: str = "pipeline-session",
) -> Trajectory:
    """Execute a scripted plan's D2/D3 decisions through the REAL
    GovernancePipeline.process() — parse -> chain -> reconstruct -> audit,
    the actual entry point a live deployment uses, not a re-implementation
    of its stage-walking logic. D1 (exposure) is still supplied by
    `exposure_fn`, same as run_scripted: agentwarden-core has no concrete
    GovernanceProfile implementation to wire against yet.

    Requires `pipeline` to be configured with an OpenAI/Ollama-wire-format
    parser (OpenAIParser/OllamaParser/OpenClawParser) — this function feeds
    it one tool call at a time in that wire format.

    routed_to_classifier is read directly off the returned decision's
    `.stage == "llm_classifier"`. That only became correct after fixing
    GovernancePipeline._run_chain() to return the real terminal stage's own
    decision instead of a synthetic stage="pipeline" one for ALLOWed calls
    that survive the whole chain — before that fix, this field required a
    separate stage-walking workaround here. No longer needed.
    """
    traj = Trajectory(task_id=task.task_id, baseline=baseline, session_id=session_id)
    ctx = context or GovernanceContext(session_id=session_id)
    world_state: dict[str, Any] = {}
    step_ids: dict[str, str] = {}
    current_phase: str | None = None
    exposed: set[str] = set()
    turn = 0

    for call in plan:
        turn += 1

        if call.phase != current_phase:
            traj.phase_transitions.append(
                PhaseTransition(turn=turn, phase_from=current_phase, phase_to=call.phase)
            )
            current_phase = call.phase

        new_exposed = exposure_fn(current_phase, world_state)
        if new_exposed != exposed:
            for added in sorted(new_exposed - exposed):
                traj.exposure_events.append(ExposureEvent(
                    turn=turn, phase=current_phase, tool_name=added,
                    action="expose", exposed_tools=frozenset(new_exposed),
                ))
            for removed in sorted(exposed - new_exposed):
                traj.exposure_events.append(ExposureEvent(
                    turn=turn, phase=current_phase, tool_name=removed,
                    action="revoke", exposed_tools=frozenset(new_exposed),
                ))
            exposed = new_exposed

        was_exposed = call.tool_call.name in exposed

        if was_exposed:
            raw = _to_openai_tool_call_response(call.tool_call, turn)
            result = asyncio.run(pipeline.process(raw, ctx))
            if result.decisions:
                decision = result.decisions[0]
            else:
                decision = GovernanceDecision(
                    request_id=str(turn), tool_name=call.tool_call.name,
                    decision=Decision.ALLOW, stage="no_requests_parsed",
                )
        else:
            decision = GovernanceDecision(
                request_id=str(turn), tool_name=call.tool_call.name,
                decision=Decision.BLOCK, reason_detail="tool not exposed",
                stage="exposure_gate",
            )

        inv = InvocationAttempt(
            turn=turn,
            phase=current_phase,
            tool_call=call.tool_call,
            was_exposed=was_exposed,
            decision=decision,
            routed_to_classifier=(decision.stage == "llm_classifier"),
            derived_from=[step_ids[r] for r in call.derived_from if r in step_ids],
        )
        if call.step_id:
            step_ids[call.step_id] = inv.invocation_id

        if was_exposed and decision.decision == Decision.ALLOW:
            try:
                inv.result = call.execute(world_state)
            except Exception as e:
                inv.error = str(e)

        traj.invocations.append(inv)

    traj.final_state = world_state
    return traj
