"""Sanity checks for B0, B1, B2, B7 across all 10 task instances — these
don't need Ollama (no D2), so they run in the default suite. B4 (real D2)
is covered separately in tests/integration (requires_ollama).
"""
from __future__ import annotations

import pytest

from benchmark import metrics
from benchmark.baselines import B2_GLOBAL_ALLOWLIST, run_b0, run_b1, run_b2, run_b7
from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]
INSTANCES = [(family, variant) for family in FAMILIES for variant in family.VARIANTS]
INSTANCE_IDS = [f"{f.__name__.rsplit('.', 1)[-1]}-{v}" for f, v in INSTANCES]


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_b0_succeeds_on_every_instance(family, variant):
    """Full registry exposed, no D2 -- the oracle plan only ever calls
    tools it needs, and everything it needs is (trivially) exposed."""
    task = family.make_task(variant)
    gt = family.make_ground_truth(variant)
    plan = family.build_oracle_plan(variant)
    traj = run_b0(task, plan)
    assert metrics.task_success(traj, gt) is True
    assert metrics.required_tool_denial_rate(traj, gt) == 0.0


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_b1_is_mechanically_identical_to_b0(family, variant):
    """See baselines.py's module docstring: this identity is the honest
    result of a scripted-plan benchmark, not a shortcut."""
    task = family.make_task(variant)
    gt = family.make_ground_truth(variant)
    plan = family.build_oracle_plan(variant)
    traj_b0 = run_b0(task, plan)
    traj_b1 = run_b1(task, plan)
    assert metrics.task_success(traj_b0, gt) == metrics.task_success(traj_b1, gt)
    assert metrics.required_tool_denial_rate(traj_b0, gt) == metrics.required_tool_denial_rate(traj_b1, gt)
    assert metrics.unnecessary_exposure_ratio(traj_b0, gt) == metrics.unnecessary_exposure_ratio(traj_b1, gt)


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_b7_oracle_is_perfect_on_every_instance(family, variant):
    """Ground-truth exposure -- must succeed, zero denial, zero
    unnecessary exposure, perfect precision/recall, on every instance.
    This is the upper bound every other baseline is measured against."""
    task = family.make_task(variant)
    gt = family.make_ground_truth(variant)
    plan = family.build_oracle_plan(variant)
    traj = run_b7(task, gt, plan)
    assert metrics.task_success(traj, gt) is True
    assert metrics.required_tool_denial_rate(traj, gt) == 0.0
    assert metrics.unnecessary_exposure_ratio(traj, gt) == 0.0
    precision, recall = metrics.exposure_precision_recall(traj, gt)
    assert precision == 1.0
    assert recall == 1.0


def test_b2_allowlist_excludes_every_terminal_mutating_tool():
    """Sanity check on the fixture itself: none of the tools every
    family's task_success_criteria ultimately depends on for its final
    mutating action are in the global allowlist."""
    mutating_tools = {
        "write_draft", "send_email", "edit_code", "run_migration", "commit_changes",
        "schedule_event", "send_reply", "apply_remediation", "export_data",
    }
    assert mutating_tools.isdisjoint(B2_GLOBAL_ALLOWLIST)


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_b2_fails_on_every_instance(family, variant):
    """The crudest static governance can't complete any task in this
    benchmark, by construction (every family's success criteria requires
    at least one write-type action B2's global allowlist never grants)."""
    task = family.make_task(variant)
    gt = family.make_ground_truth(variant)
    plan = family.build_oracle_plan(variant)
    traj = run_b2(task, plan)
    assert metrics.task_success(traj, gt) is False
    assert metrics.required_tool_denial_rate(traj, gt) > 0.0
