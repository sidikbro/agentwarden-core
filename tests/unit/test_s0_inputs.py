"""Tests for S0 pair construction (docs/v2/A4_MULTITURN_SPEC_v0.2.md
§13 step 3) -- benchmark/a4/s0_inputs.py -- against the synthetic STAC
fixture and the real, locally-installed AgentDojo package.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentwarden.core.decision_input import S0_FIELDS, anchor_only_json, build_s0_input, call_only_json
from benchmark.a4.common import ALL_EFFECTS
from benchmark.a4.s0_inputs import (
    build_agentdojo_matched_s0_pairs,
    build_agentdojo_s0_pairs,
    build_stac_length_matched_s0_pairs,
    build_stac_matched_s0_pairs,
    build_stac_s0_pairs,
)

STAC_FIXTURE = Path(__file__).parent.parent / "fixtures" / "stac_sample.json"
STAC_TOOL_REUSE_FIXTURE = Path(__file__).parent.parent / "fixtures" / "stac_sample_tool_reuse.json"
STAC_LENGTH_MATCHED_FIXTURE = Path(__file__).parent.parent / "fixtures" / "stac_sample_length_matched.json"


def test_build_s0_input_only_has_s0_fields():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    s0_json = build_s0_input(pairs[0].anchor, pairs[0].call_counts, pairs[0].invocations_observed, pairs[0].benign_call)
    import json

    payload = json.loads(s0_json)
    assert set(payload.keys()) == S0_FIELDS
    for blocked in (
        "scopes_opened", "verifications", "effect_classes_used",
        "trust_levels_touched", "out_of_scope_resource_count", "elapsed_turns",
    ):
        assert blocked not in s0_json


def test_anchor_only_and_call_only_json_are_substrings_of_full_input():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    pair = pairs[0]
    full = build_s0_input(pair.anchor, pair.call_counts, pair.invocations_observed, pair.benign_call)
    anchor_json = anchor_only_json(pair.anchor)
    call_json = call_only_json(pair.benign_call)
    assert json_fragment_present(anchor_json, full)
    assert json_fragment_present(call_json, full)


def json_fragment_present(fragment: str, full: str) -> bool:
    import json

    frag = json.loads(fragment)
    whole = json.loads(full)
    if frag == whole.get("authorization"):
        return True
    if frag == whole.get("call"):
        return True
    return False


def test_stac_pairs_share_anchor_and_prefix_differ_only_in_call():
    pairs, skipped = build_stac_s0_pairs(STAC_FIXTURE)
    assert len(pairs) == 2
    assert skipped == 0
    for pair in pairs:
        assert pair.benign_call.name != pair.attack_call.name
        assert pair.anchor.allowed_effects == ALL_EFFECTS


def test_stac_case0_pairing_matches_fixture_construction():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    case0 = next(p for p in pairs if p.case_id == "0")
    # fixture case 0 has 2 executed tool calls: search_contacts_by_name,
    # create_file -- prefix is the first, benign candidate is the second.
    assert case0.invocations_observed == 1
    assert case0.call_counts == {"search_contacts_by_name": 1}
    assert case0.benign_call.name == "create_file"
    assert case0.attack_call.name == "send_email"  # the chain's held-out final step


def test_stac_case_with_zero_tool_calls_is_skipped():
    # Build a minimal in-memory variant via a temp file to directly
    # exercise the skip path without relying on the real dataset.
    import json
    import tempfile

    record = {
        "id": 99,
        "generation_config": {"dataset": "fixture", "environment": "x"},
        "attack_plan": {"attack_goal": "g", "verified_tool_chain": [{"tool_name": "t", "parameters": {}}]},
        "interaction_history": [{"role": "user", "content": "hi"}],
        "planner_history": [],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([record], f)
        path = f.name

    pairs, skipped = build_stac_s0_pairs(path)
    assert pairs == []
    assert skipped == 1


def test_agentdojo_pairs_use_coarsened_anchor():
    pytest.importorskip("agentdojo")
    pairs, skipped = build_agentdojo_s0_pairs(suite_names=["banking"])
    assert len(pairs) >= 1
    for pair in pairs:
        assert pair.anchor.allowed_effects == ALL_EFFECTS
        assert pair.anchor.scope == frozenset({"banking"})
        # Benign and attack calls may share a tool name (e.g. banking's
        # injection also funnels through send_money, just to a different
        # recipient) -- only the full call (arguments included) is
        # guaranteed to differ, which is exactly what gate 3 tests.
        assert pair.benign_call != pair.attack_call


def test_agentdojo_injection_selection_is_deterministic_round_robin():
    pytest.importorskip("agentdojo")
    pairs_a, _ = build_agentdojo_s0_pairs(suite_names=["banking"])
    pairs_b, _ = build_agentdojo_s0_pairs(suite_names=["banking"])
    assert [p.attack_call for p in pairs_a] == [p.attack_call for p in pairs_b]


def test_stac_matched_pairs_finds_within_task_same_tool_match():
    pairs, counts = build_stac_matched_s0_pairs(STAC_TOOL_REUSE_FIXTURE)
    assert counts == {
        "total_cases": 2,
        "no_executed_tool_calls": 0,
        "no_same_tool_match": 1,  # case 101: get_hotels_in_city vs send_email, no reuse
        "same_tool_but_not_last_position": 0,
        "matched": 1,  # case 100: delete_file reused as both benign and attack tool
    }
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.benign_call.name == "delete_file"
    assert pair.attack_call.name == "delete_file"
    assert pair.benign_call.arguments != pair.attack_call.arguments


def test_stac_matched_pairs_on_original_fixture_has_no_matches():
    # Neither case in the original stac_sample.json fixture reuses its
    # final tool earlier in the same case -- confirms the "no match"
    # path is counted, not silently dropped, when none exists at all.
    pairs, counts = build_stac_matched_s0_pairs(STAC_FIXTURE)
    assert pairs == []
    assert counts["matched"] == 0
    assert counts["no_same_tool_match"] == 2


def test_agentdojo_matched_pairs_use_same_tool_for_both_calls():
    pytest.importorskip("agentdojo")
    pairs, counts = build_agentdojo_matched_s0_pairs(suite_names=["banking"])
    assert counts["total_user_tasks"] == 16
    assert counts["matched"] + counts["no_same_tool_injection"] + counts["no_ground_truth"] == 16
    assert len(pairs) == counts["matched"]
    for pair in pairs:
        assert pair.benign_call.name == pair.attack_call.name
        assert pair.anchor.allowed_effects == ALL_EFFECTS


def test_stac_length_matched_pairs_truncates_history_to_chain_length():
    pairs, counts = build_stac_length_matched_s0_pairs(STAC_LENGTH_MATCHED_FIXTURE)
    assert counts == {
        "total_cases": 2,
        "no_executed_tool_calls": 0,
        "insufficient_history_for_chain_length": 1,  # case 201: 1 executed call < chain length 3
        "matched": 1,  # case 200: 3 executed calls >= chain length 2
    }
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.invocations_observed == 1  # k - 1 = 2 - 1
    assert pair.call_counts == {"search_files_by_filename": 1}
    assert pair.benign_call.name == "read_file"  # tool_calls[k-1] = tool_calls[1]
    assert pair.attack_call.name == "send_email"  # chain[-1]


def test_agentdojo_matched_pairs_is_deterministic():
    pytest.importorskip("agentdojo")
    pairs_a, counts_a = build_agentdojo_matched_s0_pairs(suite_names=["banking"])
    pairs_b, counts_b = build_agentdojo_matched_s0_pairs(suite_names=["banking"])
    assert counts_a == counts_b
    assert [p.attack_call for p in pairs_a] == [p.attack_call for p in pairs_b]
