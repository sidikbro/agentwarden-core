"""Tests for benchmark/a4/d2_runner.py's response parsing -- moved here
from tests/unit/test_a4_arm0_arm1_stac.py when the shared runner was
extracted out of scripts/a4_arm0_arm1_stac.py. The local model is never
loaded here."""
from __future__ import annotations

import pytest

from benchmark.a4.d2_runner import parse_classifier_text, score_from_decision


def test_parses_well_formed_json():
    text = '{"decision": "BLOCK", "confidence": 0.9, "reason": "dangerous"}'
    result = parse_classifier_text(text)
    assert result == {"decision": "BLOCK", "confidence": 0.9, "raw": text}


def test_recovers_decision_and_confidence_from_truncated_reason():
    # max_new_tokens can cut generation off mid-"reason" string, before the
    # closing brace -- decision/confidence come first in the field order
    # and must still be recovered.
    text = '{"decision": "ALLOW", "confidence": 0.9, "reason": "Ordinary use of send_email, no risk indicators pre'
    result = parse_classifier_text(text)
    assert result["decision"] == "ALLOW"
    assert result["confidence"] == 0.9


def test_unparseable_text_returns_none_decision_and_confidence():
    result = parse_classifier_text("not json at all")
    assert result["decision"] is None
    assert result["confidence"] is None


def test_score_from_decision_block_allow_and_unparseable():
    assert score_from_decision("BLOCK", 0.9) == 0.9
    assert score_from_decision("ALLOW", 0.8) == pytest.approx(0.2)
    assert score_from_decision(None, None) == 0.5
