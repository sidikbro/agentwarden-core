"""Tests for scripts/a4_arm0_arm1_stac.py's response parsing -- the local
model is never loaded here."""
from __future__ import annotations

from scripts.a4_arm0_arm1_stac import _parse_classifier_text


def test_parses_well_formed_json():
    text = '{"decision": "BLOCK", "confidence": 0.9, "reason": "dangerous"}'
    result = _parse_classifier_text(text)
    assert result == {"decision": "BLOCK", "confidence": 0.9, "raw": text}


def test_recovers_decision_and_confidence_from_truncated_reason():
    # max_new_tokens can cut generation off mid-"reason" string, before the
    # closing brace -- decision/confidence come first in the field order
    # and must still be recovered.
    text = '{"decision": "ALLOW", "confidence": 0.9, "reason": "Ordinary use of send_email, no risk indicators pre'
    result = _parse_classifier_text(text)
    assert result["decision"] == "ALLOW"
    assert result["confidence"] == 0.9


def test_unparseable_text_returns_none_decision_and_confidence():
    result = _parse_classifier_text("not json at all")
    assert result["decision"] is None
    assert result["confidence"] is None
