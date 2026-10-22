"""STAC loader for the shortcut audit -- the already-measured reference
point (`docs/v2/RECONCILED_STATE_v0.2.md` §12/§12a/§13/§13a).

**Attack/benign definition and extraction, stated explicitly:** `attack`
is one record per case, the chain's held-out final step
(`malicious_tool_chain[-1]` -- planned but, per STAC's own construction,
never actually executed in the recorded trajectory). `benign` is EVERY
already-executed tool call in that case's `interaction_history` (not just
the last one, unlike the strict 1:1 minimal pair
`s0_inputs.py::build_stac_s0_pairs` uses for the validity gates/arm 0/arm
1) -- this broader pool is what lets the harness's generic tool-matched-
negative search ask "does the attack's tool reappear ANYWHERE in this
case's executed history," the same question
`build_stac_matched_s0_pairs` already answered (30/471 cases have ANY
reuse; 29/471 at the matching position specifically). `task_id` is the
case id. 12 of 483 cases have no executed tool call and are skipped.

This is a deliberately different, broader construction than the 1:1
minimal pair used for the earlier gate/arm measurements -- reported
alongside, not instead of, those numbers in the write-up, since "n" and
the exact tool-identity AUC/TPR differ by construction.

Requires `STAC_DATA_PATH` (the real `STAC_benchmark_data.json`, obtained
by cloning `github.com/amazon-science/MultiTurnAgentAttack`) -- the same
environment-variable convention `tests/unit/test_stac_adapter.py` already
uses.
"""
from __future__ import annotations

import os

from ..shortcut_audit import AuditRecord, BenchmarkNotObtainedError
from ..stac_adapter import load_stac_cases


def load_stac() -> list[AuditRecord]:
    path = os.environ.get("STAC_DATA_PATH")
    if not path:
        raise BenchmarkNotObtainedError(
            "STAC_DATA_PATH not set. Obtain via: "
            "git clone https://github.com/amazon-science/MultiTurnAgentAttack.git, "
            "then set STAC_DATA_PATH=<clone>/data/STAC_benchmark_data.json"
        )
    cases = load_stac_cases(path)
    records = []
    for case in cases:
        tool_calls = [t.tool_call for t in case.turns if t.tool_call is not None]
        if not tool_calls:
            continue
        for call in tool_calls:
            records.append(AuditRecord("STAC", case.case_id, call.name, call.arguments, "benign"))
        final_step = case.label["malicious_tool_chain"][-1]
        records.append(
            AuditRecord("STAC", case.case_id, final_step["tool_name"], final_step.get("parameters", {}), "attack")
        )
    return records
