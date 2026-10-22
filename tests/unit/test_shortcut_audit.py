"""Tests for benchmark/a4/shortcut_audit.py's core measurement functions,
on small synthetic AuditRecord lists -- no real benchmark data needed."""
from __future__ import annotations

import pytest

from benchmark.a4.shortcut_audit import (
    AuditRecord,
    run_audit,
    tool_identity_scores,
    tool_matched_negative_fraction,
)


def _records():
    # 6 benign (tool "read"), 6 attack (tool "exec") -- tool identity
    # should separate these perfectly.
    recs = []
    for i in range(6):
        recs.append(AuditRecord("TEST", f"task{i}", "read", {"path": f"f{i}"}, "benign"))
        recs.append(AuditRecord("TEST", f"task{i}", "exec", {"cmd": f"c{i}"}, "attack"))
    return recs


def test_audit_record_rejects_invalid_label():
    with pytest.raises(ValueError):
        AuditRecord("TEST", "t1", "read", {}, "RISKY")


def test_tool_identity_scores_separates_perfectly_distinct_tools():
    labels, scores = tool_identity_scores(_records())
    assert len(labels) == len(scores) == 12
    # perfect tool/label correlation -- out-of-fold scores should cleanly
    # separate the two classes.
    benign_scores = [s for l, s in zip(labels, scores) if l == 0]
    attack_scores = [s for l, s in zip(labels, scores) if l == 1]
    assert max(benign_scores) < min(attack_scores)


def test_tool_matched_negative_fraction_finds_shared_tool_per_task():
    # task A: benign and attack share tool "x" -- matched.
    # task B: benign "x", attack "y" -- not matched.
    # task C: only benign -- not eligible (no attack side to match against).
    records = [
        AuditRecord("TEST", "A", "x", {}, "benign"),
        AuditRecord("TEST", "A", "x", {}, "attack"),
        AuditRecord("TEST", "B", "x", {}, "benign"),
        AuditRecord("TEST", "B", "y", {}, "attack"),
        AuditRecord("TEST", "C", "x", {}, "benign"),
    ]
    result = tool_matched_negative_fraction(records)
    assert result == {"n_tasks_total": 3, "n_tasks_eligible": 2, "n_tasks_matched": 1}


def test_run_audit_skips_when_below_min_rows_per_class():
    records = [
        AuditRecord("TEST", "t1", "read", {}, "benign"),
        AuditRecord("TEST", "t2", "exec", {}, "attack"),
    ]
    result = run_audit("TEST", records)
    assert result["skipped"] is True
    assert "min class count" in result["reason"]


def test_run_audit_returns_auc_and_tpr_for_separable_records():
    result = run_audit("TEST", _records())
    assert not result.get("skipped")
    assert result["n"] == 12
    assert 0.0 <= result["tool_identity_auc"] <= 1.0
    assert 0.0 <= result["tool_identity_tpr_at_far"] <= 1.0
    assert "content_leakage" in result
    assert "tool_matched_negative" in result
