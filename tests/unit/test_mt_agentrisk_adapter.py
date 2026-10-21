"""Tests for the MT-AgentRisk adapter (docs/v2/A4_MULTITURN_SPEC_v0.2.md
§13 step 1), against the synthetic fixture in
tests/fixtures/mt_agentrisk_sample/ (schema confirmed from
github.com/CHATS-lab/MT-AgentRisk_ToolShield, NOT real MT-AgentRisk
data -- the real dataset is gated on HuggingFace behind a terms-of-use
form; see benchmark/a4/mt_agentrisk_adapter.py's module docstring and
MTAgentRiskDatasetNotAvailableError for exactly why and what obtaining
it for real requires).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentwarden.core.models import TaskType
from benchmark.a4.common import ALL_EFFECTS
from benchmark.a4.mt_agentrisk_adapter import (
    MTAgentRiskDatasetError,
    MTAgentRiskDatasetNotAvailableError,
    load_mt_agentrisk_cases,
)

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "mt_agentrisk_sample"


def test_load_cases_from_fixture():
    cases = load_mt_agentrisk_cases(FIXTURE_ROOT)
    assert len(cases) == 1
    case = cases[0]
    assert case.source == "mt_agentrisk"
    assert case.case_id == "sample_task"


def test_anchor_uses_task_intro_and_inferred_tool_category():
    case = load_mt_agentrisk_cases(FIXTURE_ROOT)[0]
    assert case.anchor.authorized_task.startswith("You are helping organize")
    assert case.anchor.scope == frozenset({"filesystem"})
    assert case.anchor.task_type == TaskType.UNKNOWN
    assert case.anchor.allowed_effects == ALL_EFFECTS


def test_turns_are_user_role_only():
    case = load_mt_agentrisk_cases(FIXTURE_ROOT)[0]
    assert len(case.turns) == 2
    assert all(t.role == "user" for t in case.turns)
    assert all(t.tool_call is None for t in case.turns)
    assert "List the files" in case.turns[0].content
    assert "Move the file" in case.turns[1].content


def test_label_carries_turn_manifest_untouched():
    case = load_mt_agentrisk_cases(FIXTURE_ROOT)[0]
    manifest = case.label["turn_manifest"]
    assert manifest[0]["checkpoint_id"] == "list_files"
    assert manifest[1]["success_patterns"] == ["moved"]


def test_missing_root_raises_with_gated_access_instructions():
    with pytest.raises(MTAgentRiskDatasetNotAvailableError, match="huggingface-cli"):
        load_mt_agentrisk_cases("/nonexistent/mt-agentrisk-root")


def test_root_with_no_turns_yml_raises(tmp_path):
    empty = tmp_path / "empty_root"
    empty.mkdir()
    with pytest.raises(MTAgentRiskDatasetError, match="no turns.yml"):
        load_mt_agentrisk_cases(empty)
