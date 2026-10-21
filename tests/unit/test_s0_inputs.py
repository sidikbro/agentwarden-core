"""Tests for S0 pair construction (docs/v2/A4_MULTITURN_SPEC_v0.2.md
§13 step 3) -- benchmark/a4/s0_inputs.py -- against the synthetic STAC
fixture and the real, locally-installed AgentDojo package.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentwarden.core.decision_input import S0_FIELDS, anchor_only_json, build_s0_input, call_only_json
from benchmark.a4.common import ALL_EFFECTS
from benchmark.a4.s0_inputs import build_agentdojo_s0_pairs, build_stac_s0_pairs

STAC_FIXTURE = Path(__file__).parent.parent / "fixtures" / "stac_sample.json"


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
