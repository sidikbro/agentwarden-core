"""Tests for the Agent Security Bench (ASB) shortcut-audit loader
(benchmark/a4/audit_loaders/agent_security_bench.py). A synthetic
fixture (built in-line, schema-faithful to the real `all_normal_tools
.jsonl` / `all_attack_tools.jsonl` shape) exercises the parsing logic; a
second, skip-if-absent test runs against the real benchmark when
ASB_DATA_DIR is supplied (`git clone https://github.com/agiresearch/ASB.git`,
then ASB_DATA_DIR=<clone>/data).
"""
from __future__ import annotations

import json
import os

import pytest

from benchmark.a4.audit_loaders.agent_security_bench import load_agent_security_bench
from benchmark.a4.shortcut_audit import BenchmarkNotObtainedError

_NORMAL = [
    {"Tool Name": "sys_monitor", "Description": "fixture", "Expected Achievements": "fixture", "Corresponding Agent": "system_admin_agent"},
    {"Tool Name": "update_manager", "Description": "fixture", "Expected Achievements": "fixture", "Corresponding Agent": "system_admin_agent"},
]

_ATTACK = [
    {"Attacker Tool": "CredentialHarvesting", "Attacker Instruction": "fixture", "Description": "fixture", "Attack goal": "fixture", "Attack Type": "Stealthy Attack", "Corresponding Agent": "system_admin_agent", "Aggressive": "True"},
    {"Attacker Tool": "AccessEscalation", "Attacker Instruction": "fixture", "Description": "fixture", "Attack goal": "fixture", "Attack Type": "Stealthy Attack", "Corresponding Agent": "system_admin_agent", "Aggressive": "True"},
    {"Attacker Tool": "ResourceAllocationHijack", "Attacker Instruction": "fixture", "Description": "fixture", "Attack goal": "fixture", "Attack Type": "Disruptive Attack", "Corresponding Agent": "financial_analyst_agent", "Aggressive": "False"},
]


def test_load_raises_without_env_var(monkeypatch):
    monkeypatch.delenv("ASB_DATA_DIR", raising=False)
    with pytest.raises(BenchmarkNotObtainedError):
        load_agent_security_bench()


def test_load_parses_fixture(tmp_path, monkeypatch):
    (tmp_path / "all_normal_tools.jsonl").write_text("\n".join(json.dumps(t) for t in _NORMAL))
    (tmp_path / "all_attack_tools.jsonl").write_text("\n".join(json.dumps(t) for t in _ATTACK))
    monkeypatch.setenv("ASB_DATA_DIR", str(tmp_path))

    records = load_agent_security_bench()
    assert len(records) == 2 + 3

    benign = [r for r in records if r.label == "benign"]
    attack = [r for r in records if r.label == "attack"]
    assert len(benign) == 2
    assert len(attack) == 3
    assert all(r.arguments == {} for r in records)  # no concrete call args in the static export, either label
    assert {r.tool_name for r in benign} == {"sys_monitor", "update_manager"}
    assert {r.tool_name for r in attack} == {"CredentialHarvesting", "AccessEscalation", "ResourceAllocationHijack"}
    # task_id groups by "Corresponding Agent"
    sysadmin_task_ids = {r.task_id for r in records if r.tool_name in ("sys_monitor", "update_manager", "CredentialHarvesting", "AccessEscalation")}
    assert sysadmin_task_ids == {"system_admin_agent"}


@pytest.mark.skipif(
    not os.environ.get("ASB_DATA_DIR"),
    reason="set ASB_DATA_DIR to a real ASB clone's data/ dir to run this",
)
def test_load_against_real_data():
    records = load_agent_security_bench()
    n_benign = sum(1 for r in records if r.label == "benign")
    n_attack = sum(1 for r in records if r.label == "attack")
    assert n_benign == 20
    assert n_attack == 400
    assert len({r.task_id for r in records}) == 10
