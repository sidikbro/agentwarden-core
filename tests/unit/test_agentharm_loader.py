"""Tests for the AgentHarm shortcut-audit loader
(benchmark/a4/audit_loaders/agentharm.py). A synthetic fixture (schema-
faithful to the real harmful/benign_behaviors_{test_public,validation}.json
shape) exercises the parsing logic; a second, skip-if-absent test runs
against the real benchmark when AGENTHARM_DATA_DIR is supplied
(`huggingface_hub.snapshot_download(repo_id='ai-safety-institute/AgentHarm',
repo_type='dataset', local_dir=<dest>)`, then AGENTHARM_DATA_DIR=<dest>/benchmark).
"""
from __future__ import annotations

import json
import os

import pytest

from benchmark.a4.audit_loaders.agentharm import load_agentharm
from benchmark.a4.shortcut_audit import BenchmarkNotObtainedError

_HARMFUL = {
    "canary_guid": "fixture",
    "behaviors": [
        {
            "id": "1-1",
            "id_original": "1",
            "name": "fixture harmful",
            "category": "Fraud",
            "prompt": "fixture",
            "target_functions": ["send_email", "transfer_money"],
            "grading_function": "fixture",
        }
    ],
}

_BENIGN = {
    "canary_guid": "fixture",
    "behaviors": [
        {
            "id": "1-1",
            "id_original": "1",
            "name": "fixture harmful - Benign",
            "category": "Fraud",
            "prompt": "fixture",
            "target_functions": ["send_email", "transfer_money"],
            "grading_function": "fixture",
        }
    ],
}

_EMPTY = {"canary_guid": "fixture", "behaviors": []}


def test_load_agentharm_raises_without_env_var(monkeypatch):
    monkeypatch.delenv("AGENTHARM_DATA_DIR", raising=False)
    with pytest.raises(BenchmarkNotObtainedError):
        load_agentharm()


def test_load_agentharm_parses_fixture(tmp_path, monkeypatch):
    (tmp_path / "harmful_behaviors_test_public.json").write_text(json.dumps(_HARMFUL))
    (tmp_path / "benign_behaviors_test_public.json").write_text(json.dumps(_BENIGN))
    (tmp_path / "harmful_behaviors_validation.json").write_text(json.dumps(_EMPTY))
    (tmp_path / "benign_behaviors_validation.json").write_text(json.dumps(_EMPTY))
    monkeypatch.setenv("AGENTHARM_DATA_DIR", str(tmp_path))

    records = load_agentharm()
    assert len(records) == 4  # 2 tools x (1 harmful behavior + 1 benign behavior)

    attack = [r for r in records if r.label == "attack"]
    benign = [r for r in records if r.label == "benign"]
    assert len(attack) == 2
    assert len(benign) == 2
    assert {r.tool_name for r in attack} == {"send_email", "transfer_money"}
    assert all(r.arguments == {} for r in records)  # no concrete arguments in the static data
    # same task_id pairs the harmful/benign counterparts (shared id "1-1")
    assert {r.task_id for r in records} == {"test_public_1-1"}


@pytest.mark.skipif(
    not os.environ.get("AGENTHARM_DATA_DIR"),
    reason="set AGENTHARM_DATA_DIR to a real AgentHarm benchmark/ dir to run this",
)
def test_load_agentharm_against_real_data():
    records = load_agentharm()
    n_benign = sum(1 for r in records if r.label == "benign")
    n_attack = sum(1 for r in records if r.label == "attack")
    assert n_benign > 0 and n_attack > 0
    assert len(records) > 1000
