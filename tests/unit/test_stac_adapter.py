"""Tests for the STAC adapter (docs/v2/A4_MULTITURN_SPEC_v0.2.md §13
step 1), against the synthetic fixture in tests/fixtures/stac_sample.json
(schema-faithful, not real STAC data -- see that file's own content and
benchmark/a4/stac_adapter.py's module docstring for the confirmed real
schema this mirrors).

A second, skip-if-absent test runs the same adapter against the REAL
STAC benchmark file when a path to it is supplied via the
STAC_DATA_PATH environment variable, so this suite stays green in any
environment without the external dataset while still being exercisable
against real data (`git clone
https://github.com/amazon-science/MultiTurnAgentAttack` and point
STAC_DATA_PATH at its data/STAC_benchmark_data.json).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentwarden.core.models import TaskType
from agentwarden.core.session_authorization import Effect
from benchmark.a4.common import ALL_EFFECTS
from benchmark.a4.stac_adapter import StacDatasetError, load_stac_cases

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "stac_sample.json"


def test_load_stac_cases_from_fixture():
    cases = load_stac_cases(FIXTURE_PATH)
    assert len(cases) == 2
    assert {c.case_id for c in cases} == {"0", "1"}


def test_anchor_derivation_is_mechanical_and_uniform():
    cases = load_stac_cases(FIXTURE_PATH)
    case0 = next(c for c in cases if c.case_id == "0")
    assert case0.anchor.authorized_task == "Hi, could you check your contacts for B?"
    assert case0.anchor.scope == frozenset({"travel"})
    assert case0.anchor.task_type == TaskType.UNKNOWN
    assert case0.anchor.allowed_effects == ALL_EFFECTS

    case1 = next(c for c in cases if c.case_id == "1")
    assert case1.anchor.scope == frozenset({"banking"})
    # Same rule applied to a different case -- task_type and
    # allowed_effects are identical regardless of content, by design.
    assert case1.anchor.task_type == TaskType.UNKNOWN
    assert case1.anchor.allowed_effects == ALL_EFFECTS


def test_double_encoded_tool_call_arguments_are_decoded():
    cases = load_stac_cases(FIXTURE_PATH)
    case0 = next(c for c in cases if c.case_id == "0")
    tool_turns = [t for t in case0.turns if t.tool_call is not None]
    assert tool_turns[0].tool_call.name == "search_contacts_by_name"
    assert tool_turns[0].tool_call.arguments == {"inbox": "a@example.com", "query": "B"}


def test_interaction_history_stops_before_the_malicious_step():
    cases = load_stac_cases(FIXTURE_PATH)
    case0 = next(c for c in cases if c.case_id == "0")
    tool_names_in_history = {t.tool_call.name for t in case0.turns if t.tool_call is not None}
    # send_email is the chain's final (malicious) step but is never
    # actually invoked in interaction_history -- it only appears via
    # planner_history's predicted_attack_prompt / the label's chain.
    assert "send_email" not in tool_names_in_history
    assert case0.label["malicious_tool_chain"][-1]["tool_name"] == "send_email"
    assert "email" in case0.label["predicted_attack_prompt"].lower()


def test_label_carries_ground_truth_untouched():
    cases = load_stac_cases(FIXTURE_PATH)
    case1 = next(c for c in cases if c.case_id == "1")
    assert case1.label["attack_goal"].startswith("Synthetic fixture attack goal 2")
    assert case1.label["dataset_source"] == "Agent_SafetyBench"
    assert case1.label["predicted_attack_prompt"] is None  # empty planner_history


def test_missing_file_raises_with_clone_instructions():
    with pytest.raises(StacDatasetError, match="MultiTurnAgentAttack"):
        load_stac_cases("/nonexistent/path/STAC_benchmark_data.json")


@pytest.mark.skipif(
    not os.environ.get("STAC_DATA_PATH"),
    reason="set STAC_DATA_PATH to the real STAC_benchmark_data.json to run this",
)
def test_load_stac_cases_from_real_dataset():
    cases = load_stac_cases(os.environ["STAC_DATA_PATH"])
    assert len(cases) == 483
    for case in cases:
        assert case.anchor.allowed_effects == ALL_EFFECTS
        assert isinstance(case.anchor.authorized_task, str) and case.anchor.authorized_task
