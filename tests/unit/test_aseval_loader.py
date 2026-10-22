"""Tests for the ASEval loader (benchmark/a4/audit_loaders/aseval.py).
Only the env-var-gated real-data test exists here (no synthetic fixture
mirroring ASEval's own JSON shape has been built) -- skips cleanly when
ASEVAL_DATA_PATH is unset, exercisable against a real clone of
https://github.com/antgroup/Agent3Sigma-Stage when it is set.
"""
from __future__ import annotations

import os

import pytest

from benchmark.a4.audit_loaders.aseval import load_aseval
from benchmark.a4.shortcut_audit import BenchmarkNotObtainedError


def test_raises_not_obtained_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("ASEVAL_DATA_PATH", raising=False)
    with pytest.raises(BenchmarkNotObtainedError):
        load_aseval()


@pytest.mark.skipif(
    not os.environ.get("ASEVAL_DATA_PATH"),
    reason="set ASEVAL_DATA_PATH to a clone of antgroup/Agent3Sigma-Stage to run this",
)
def test_load_aseval_against_real_data():
    records = load_aseval()
    assert len(records) > 100
    labels = {r.label for r in records}
    assert labels == {"benign", "attack"}
    assert sum(1 for r in records if r.label == "attack") > 5
    assert sum(1 for r in records if r.label == "benign") > 5
