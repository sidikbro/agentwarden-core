from __future__ import annotations

import pytest

from benchmark.adversarial import a1_direct_dangerous as a1
from benchmark.tasks import research_synth as rs
from benchmark.validate import BenchmarkValidationError, assert_valid, validate_task

ALL_CHECKS = {
    "1_required_tools_subset",
    "2_oracle_succeeds",
    "3_withholding_breaks_success",
    "4_phases_differ",
    "5_attack_succeeds_under_b0",
}


def test_research_synth_passes_all_five_checks():
    task = rs.make_task()
    gt = rs.make_ground_truth()
    plan = rs.build_oracle_plan()

    report = validate_task(task, gt, plan)

    assert report.checks.keys() == ALL_CHECKS
    assert all(report.checks.values()), report.errors
    assert report.passed
    assert_valid(task, gt, plan)   # must not raise


def test_research_synth_a1_passes_all_five_checks():
    task = a1.make_task()
    gt = a1.make_ground_truth()
    oracle_plan = a1.build_oracle_plan()
    attack_plan = a1.build_attack_plan()

    report = validate_task(task, gt, oracle_plan, attack_plan)

    assert report.checks.keys() == ALL_CHECKS
    assert all(report.checks.values()), report.errors
    assert report.passed
    assert_valid(task, gt, oracle_plan, attack_plan)   # must not raise


def test_check5_is_vacuous_pass_for_non_adversarial_task():
    """Non-adversarial tasks have nothing for check 5 to verify — it must
    pass vacuously, not silently skip in a way that looks like a real pass
    on an adversarial task."""
    task = rs.make_task()
    assert task.adversarial_variant is None
    gt = rs.make_ground_truth()
    plan = rs.build_oracle_plan()
    report = validate_task(task, gt, plan, attack_plan=None)
    assert report.checks["5_attack_succeeds_under_b0"] is True


# ---------------------------------------------------------------------------
# Negative controls: the checks must be able to FAIL on bad ground truth,
# not just pass on good ground truth. Without these, check 3 and check 5
# could be tautologies that pass no matter what.
# ---------------------------------------------------------------------------


def test_check3_catches_a_success_criteria_that_ignores_required_tools():
    task = rs.make_task()
    plan = rs.build_oracle_plan()
    fake_gt = rs.make_ground_truth()
    # "success" only depends on the search step -- fetch/analyze/write/send
    # tools are not actually required by this (bad) criteria.
    fake_gt.task_success_criteria = lambda traj: bool(traj.final_state.get("search_results"))

    report = validate_task(task, fake_gt, plan)

    assert report.checks["3_withholding_breaks_success"] is False
    assert not report.passed
    with pytest.raises(BenchmarkValidationError):
        assert_valid(task, fake_gt, plan)


def test_check5_catches_an_attack_plan_with_no_matching_attack_call():
    task = a1.make_task()
    gt = a1.make_ground_truth()
    gt.is_attack_invocation = lambda tc: tc.name == "nonexistent_tool"
    oracle_plan = a1.build_oracle_plan()
    attack_plan = a1.build_attack_plan()

    report = validate_task(task, gt, oracle_plan, attack_plan)

    assert report.checks["5_attack_succeeds_under_b0"] is False
    assert not report.passed
    with pytest.raises(BenchmarkValidationError):
        assert_valid(task, gt, oracle_plan, attack_plan)


def test_check1_catches_required_tool_outside_registry():
    task = rs.make_task()
    task.full_tool_registry = set(task.full_tool_registry) - {"send_email"}
    gt = rs.make_ground_truth()
    plan = rs.build_oracle_plan()

    report = validate_task(task, gt, plan)

    assert report.checks["1_required_tools_subset"] is False
    assert not report.passed


def test_check4_catches_identical_phases():
    task = rs.make_task()
    # collapse every phase to the same required_tools
    for p in task.phases:
        p.required_tools = {"search_web"}

    report = validate_task(task, rs.make_ground_truth(), rs.build_oracle_plan())

    assert report.checks["4_phases_differ"] is False
    assert not report.passed
