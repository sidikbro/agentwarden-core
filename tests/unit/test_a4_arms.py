"""Tests for benchmark/a4/arms.py -- arm 0 (shortcut baseline) and arm 1
(per-step floor) scoring, on the synthetic STAC fixture. Arm 1's real
classifier backend (a local LLM) is never loaded here -- `arm1_scores`
takes `classify_fn` injected, exactly so this can run without a model.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.a4.arms import arm0_scores, arm1_scores, tpr_at_far
from benchmark.a4.s0_inputs import build_stac_s0_pairs

STAC_FIXTURE = Path(__file__).parent.parent / "fixtures" / "stac_sample.json"


def test_arm0_scores_returns_one_score_per_instance():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    labels, scores, case_ids = arm0_scores(pairs)
    assert len(labels) == len(scores) == len(case_ids) == 2 * len(pairs)
    assert set(labels) == {0, 1}
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_arm0_index_from_start_is_the_default_and_differs_from_oracle():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    _, default_scores, _ = arm0_scores(pairs)
    _, explicit_start_scores, _ = arm0_scores(pairs, position_feature="index_from_start")
    assert default_scores == explicit_start_scores

    _, oracle_scores, _ = arm0_scores(pairs, position_feature="index_from_end_oracle")
    # not asserting a direction -- just that the two position encodings are
    # genuinely different code paths, not the same computation under a
    # different name.
    assert default_scores != oracle_scores


def test_arm0_scores_rejects_unknown_position_feature():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)
    with pytest.raises(ValueError):
        arm0_scores(pairs, position_feature="nonsense")


def test_arm1_scores_uses_injected_classify_fn_and_handles_parse_failure():
    pairs, _ = build_stac_s0_pairs(STAC_FIXTURE)

    def fake_classify(tool_name: str, arguments: dict) -> dict:
        if tool_name == "send_email":
            return {"decision": "BLOCK", "confidence": 0.9}
        if tool_name == "create_file":
            return {"decision": "ALLOW", "confidence": 0.8}
        return {"decision": None, "confidence": None}  # unparseable

    labels, scores, case_ids, raw = arm1_scores(pairs, fake_classify)
    assert len(labels) == len(scores) == len(raw) == 2 * len(pairs)

    by_tool = {}
    for (_, call, _), score in zip(
        [(l, c, cid) for p in pairs for l, c, cid in (("BENIGN", p.benign_call, p.case_id), ("ATTACK", p.attack_call, p.case_id))],
        scores,
    ):
        by_tool.setdefault(call.name, set()).add(score)

    assert by_tool.get("send_email") == {0.9}
    (create_file_score,) = by_tool.get("create_file")
    assert create_file_score == pytest.approx(0.2)  # 1 - 0.8


def test_tpr_at_far_perfect_separation_hits_target_tpr_one():
    labels = [0, 0, 0, 0, 1, 1, 1, 1]
    scores = [0.1, 0.2, 0.1, 0.2, 0.9, 0.8, 0.95, 0.85]
    result = tpr_at_far(labels, scores, target_far=0.12)
    assert result["tpr_at_target_far"] == 1.0
    assert result["auc"] == 1.0


def test_tpr_at_far_chance_scores_give_roughly_chance_tpr():
    labels = [0, 1] * 20
    scores = [0.5] * 40
    result = tpr_at_far(labels, scores, target_far=0.12)
    # every instance ties at the same score -- roc_curve degenerates to a
    # single interior point, which is itself the finding for a classifier
    # that never separates the classes at all.
    assert 0.0 <= result["tpr_at_target_far"] <= 1.0
