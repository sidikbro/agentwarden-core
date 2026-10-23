"""Tests for scripts/a4_aseval_representation_ablation.py's text
extraction -- the real model/data are not needed here."""
from __future__ import annotations

import json

from benchmark.a4.shortcut_audit import AuditRecord, action_text
from scripts.a4_aseval_representation_ablation import response_only_text


def test_response_only_text_excludes_tool_name():
    record = AuditRecord("ASEval", "t1", "exec", {"tool_response": "some output"}, "benign")
    full = action_text(record)
    resp = response_only_text(record)
    assert "exec" in full
    assert "exec" not in resp
    assert json.loads(resp) == {"tool_response": "some output"}
