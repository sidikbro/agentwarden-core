"""Ground-truth validation — the five checks a task must pass before it is
allowed into the benchmark.

All five are hard, benchmark-blocking failures via assert_valid(); none are
advisory. Checks 3 and 5 in particular are what make the benchmark
trustworthy rather than decorative:

  - check 3: success must FAIL when any required tool is withheld
    (otherwise the "required" tool wasn't actually required — the ground
    truth is fiction).
  - check 5: the attack must SUCCEED under B0 (ungoverned) for adversarial
    variants (otherwise the adversarial test can't fail either — there's
    nothing for governance to have prevented, so a pass is meaningless).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agentwarden.core.models import Decision
from benchmark.runner import ExposureFn, ScriptedCall, run_scripted
from benchmark.schema import GroundTruth, Task


class BenchmarkValidationError(Exception):
    """Raised by assert_valid when a task fails one or more of the five checks."""


@dataclass
class ValidationReport:
    task_id: str
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values()) and not self.errors


def _required_by_phase(task: Task) -> dict[str, set[str]]:
    return {p.name: set(p.required_tools) for p in task.phases}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_required_tools_subset(task: Task) -> tuple[bool, str | None]:
    """1. Every phase's required_tools is a subset of full_tool_registry."""
    for p in task.phases:
        missing = p.required_tools - task.full_tool_registry
        if missing:
            return False, f"phase '{p.name}' required_tools {missing} not in full_tool_registry"
    return True, None


def check_oracle_succeeds(
    task: Task, gt: GroundTruth, oracle_plan: list[ScriptedCall]
) -> tuple[bool, str | None]:
    """2. success_predicate passes when run with an oracle agent given
    exactly required_tools (nothing more, nothing less, per phase)."""
    required = _required_by_phase(task)
    exposure: ExposureFn = lambda phase, ws: required.get(phase, set())
    traj = run_scripted(task, oracle_plan, exposure, baseline="ORACLE")

    if not gt.task_success_criteria(traj):
        return False, "task_success_criteria failed for oracle agent given exactly required_tools"
    for p in task.phases:
        if not p.success_predicate(traj):
            return False, (
                f"phase '{p.name}' success_predicate failed for oracle agent "
                f"given exactly required_tools"
            )
    return True, None


def check_withholding_breaks_success(
    task: Task, gt: GroundTruth, oracle_plan: list[ScriptedCall]
) -> tuple[bool, str | None]:
    """3. success_predicate FAILS when any required tool is withheld.
    Hard failure — the check that proves the ground truth is real."""
    required = _required_by_phase(task)
    for p in task.phases:
        for tool in sorted(p.required_tools):
            def exposure(phase: str, ws: dict, _phase=p.name, _tool=tool) -> set[str]:
                base = required.get(phase, set())
                return (base - {_tool}) if phase == _phase else base

            traj = run_scripted(task, oracle_plan, exposure, baseline=f"WITHHOLD:{p.name}:{tool}")
            if gt.task_success_criteria(traj):
                return False, (
                    f"task_success_criteria still passed with '{tool}' withheld from "
                    f"phase '{p.name}' — ground truth is not real"
                )
    return True, None


def check_phases_differ(task: Task) -> tuple[bool, str | None]:
    """4. Phases genuinely differ: required_tools is not identical across
    all phases."""
    distinct = {frozenset(p.required_tools) for p in task.phases}
    if len(distinct) <= 1:
        return False, "required_tools is identical across all phases"
    return True, None


def check_attack_succeeds_under_b0(
    task: Task, gt: GroundTruth, attack_plan: list[ScriptedCall] | None
) -> tuple[bool, str | None]:
    """5. For adversarial variants: the attack succeeds under B0
    (ungoverned), else the test is vacuous. Hard failure. Vacuously
    satisfied (True) for non-adversarial tasks — there is no attack to
    check, so this check does not apply."""
    if task.adversarial_variant is None:
        return True, None

    if attack_plan is None or gt.is_attack_invocation is None:
        return False, "adversarial task has no attack_plan / is_attack_invocation to verify against"

    exposure: ExposureFn = lambda phase, ws: set(task.full_tool_registry)   # B0: full registry, D2 none
    traj = run_scripted(task, attack_plan, exposure, baseline="B0")

    attack_calls = [inv for inv in traj.invocations if gt.is_attack_invocation(inv.tool_call)]
    if not attack_calls:
        return False, "attack_plan contains no invocation gt.is_attack_invocation recognizes"
    if not all(inv.decision.decision == Decision.ALLOW and inv.error is None for inv in attack_calls):
        return False, "attack did not succeed under B0 (ungoverned) — adversarial test would be vacuous"
    return True, None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def validate_task(
    task: Task,
    gt: GroundTruth,
    oracle_plan: list[ScriptedCall],
    attack_plan: list[ScriptedCall] | None = None,
) -> ValidationReport:
    report = ValidationReport(task_id=task.task_id)

    for key, fn, args in [
        ("1_required_tools_subset", check_required_tools_subset, (task,)),
        ("2_oracle_succeeds", check_oracle_succeeds, (task, gt, oracle_plan)),
        ("3_withholding_breaks_success", check_withholding_breaks_success, (task, gt, oracle_plan)),
        ("4_phases_differ", check_phases_differ, (task,)),
        ("5_attack_succeeds_under_b0", check_attack_succeeds_under_b0, (task, gt, attack_plan)),
    ]:
        ok, err = fn(*args)
        report.checks[key] = ok
        if err:
            report.errors.append(f"[{key}] {err}")

    return report


def assert_valid(
    task: Task,
    gt: GroundTruth,
    oracle_plan: list[ScriptedCall],
    attack_plan: list[ScriptedCall] | None = None,
) -> ValidationReport:
    """Raises BenchmarkValidationError if any of the five checks fail.
    This is the gate: a task that doesn't pass this must not enter the
    benchmark's task registry."""
    report = validate_task(task, gt, oracle_plan, attack_plan)
    if not report.passed:
        raise BenchmarkValidationError(
            f"task '{task.task_id}' failed validation: {'; '.join(report.errors)}"
        )
    return report
