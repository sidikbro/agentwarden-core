"""Validates every task family instance through all 5 validate.py checks —
the same bar research_synth was held to before any family scaling
happened. Each family now has 2 variants (v1/v2), deliberately requiring
different tool subsets — see each family module's docstring for why. Each
instance gets its own negative control for check 3, matching the
discipline established for research_synth: check 3 must be able to FAIL,
not just pass, or it's decorative.
"""
from __future__ import annotations

import pytest

from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth
from benchmark.validate import assert_valid, validate_task

ALL_CHECKS = {
    "1_required_tools_subset",
    "2_oracle_succeeds",
    "3_withholding_breaks_success",
    "4_phases_differ",
    "5_attack_succeeds_under_b0",
}

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]
INSTANCES = [(family, variant) for family in FAMILIES for variant in family.VARIANTS]
INSTANCE_IDS = [f"{f.__name__.rsplit('.', 1)[-1]}-{v}" for f, v in INSTANCES]


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_instance_passes_all_five_checks(family, variant):
    task = family.make_task(variant)
    gt = family.make_ground_truth(variant)
    plan = family.build_oracle_plan(variant)

    report = validate_task(task, gt, plan)

    assert report.checks.keys() == ALL_CHECKS
    assert all(report.checks.values()), (family.__name__, variant, report.errors)
    assert report.passed
    assert_valid(task, gt, plan)   # must not raise


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_instance_phase_structure(family, variant):
    """Sanity check on the fixtures themselves: every phase has at least
    one required tool. Phases may require more than one tool now (e.g.
    research_synth v2's analyze needs both parse_pdf and extract_facts) —
    that's deliberate, not a structural invariant to enforce against."""
    task = family.make_task(variant)
    for phase in task.phases:
        assert phase.required_tools, f"{family.__name__}/{variant} phase '{phase.name}' has no required tools"


@pytest.mark.parametrize("family,variant", INSTANCES, ids=INSTANCE_IDS)
def test_instance_check3_is_not_decorative(family, variant):
    """Negative control: a task_success_criteria that ignores everything
    after the first phase must be CAUGHT by check 3, for every instance —
    not just research_synth v1."""
    task = family.make_task(variant)
    plan = family.build_oracle_plan(variant)
    fake_gt = family.make_ground_truth(variant)
    first_phase = task.phases[0]
    fake_gt.task_success_criteria = lambda traj, _p=first_phase: _p.success_predicate(traj)

    report = validate_task(task, fake_gt, plan)

    assert report.checks["3_withholding_breaks_success"] is False, (
        f"{family.__name__}/{variant}: check 3 failed to catch a success "
        f"criteria that only depends on the first phase"
    )
    assert not report.passed


def test_within_family_variation_actually_varies_requirements():
    """Sanity check on the difficulty additions themselves: v1 and v2 must
    require genuinely different tool sets for at least one phase, per
    family — otherwise "two variants" is cosmetic, not real headroom."""
    for family in FAMILIES:
        gt_v1 = family.make_ground_truth("v1")
        gt_v2 = family.make_ground_truth("v2")
        differs = any(
            gt_v1.minimum_required_tools.get(phase) != gt_v2.minimum_required_tools.get(phase)
            for phase in set(gt_v1.minimum_required_tools) | set(gt_v2.minimum_required_tools)
        )
        assert differs, f"{family.__name__}: v1 and v2 require identical tools everywhere"
