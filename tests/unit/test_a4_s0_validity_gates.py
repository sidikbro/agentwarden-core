"""Tests for the gate-1 ablation (docs/v2/A4_MULTITURN_SPEC_v0.2.md §9
gate 1's ablated re-run) -- scripts/a4_s0_validity_gates.py's
_ablate_shortcut_features() must scrub exactly arm 0's two shortcut
features (tool identity, position) and leave everything else, including
the call's own arguments, byte-identical.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentwarden.core.decision_input import S0_FIELDS
from benchmark.a4.s0_inputs import build_stac_s0_pairs
from scripts.a4_s0_validity_gates import _ablate_shortcut_features

STAC_FIXTURE = Path(__file__).parent.parent / "fixtures" / "stac_sample.json"


def test_ablation_scrubs_tool_name_and_position_only():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    pair = pairs[0]
    _, s0_json = pair.instances()[0]  # BENIGN
    ablated = _ablate_shortcut_features(s0_json)

    original = json.loads(s0_json)
    scrubbed = json.loads(ablated)

    assert set(scrubbed.keys()) == S0_FIELDS
    assert scrubbed["call"]["tool_name"] != original["call"]["tool_name"]
    assert scrubbed["invocations_observed"] == 0
    # everything else is untouched
    assert scrubbed["call"]["arguments"] == original["call"]["arguments"]
    assert scrubbed["authorization"] == original["authorization"]
    assert scrubbed["call_counts"] == original["call_counts"]


def test_ablation_removes_tool_name_as_a_distinguishing_signal_within_a_pair():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    pair = pairs[0]
    benign_ablated = json.loads(_ablate_shortcut_features(pair.instances()[0][1]))
    attack_ablated = json.loads(_ablate_shortcut_features(pair.instances()[1][1]))
    assert benign_ablated["call"]["tool_name"] == attack_ablated["call"]["tool_name"]
    assert benign_ablated["invocations_observed"] == attack_ablated["invocations_observed"]
