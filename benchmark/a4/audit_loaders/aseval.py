"""ASEval loader for the shortcut audit.

**Real source, confirmed by fetching the paper, not inferred from this
project's own related-work summary.** "ASEval" as cited in arXiv:2610.00400
("Representation Transitions") is Ma et al. 2026, *ASEval: Automated
Trajectory-Level Security Testing for Autonomous Agents*, arXiv:2605.22321.
Code and data: https://github.com/antgroup/Agent3Sigma-Stage (stated in the
arXiv listing's own Comments field). No credentials, login, or terms-of-use
form -- a public `git clone`.

**What's actually in the repo, confirmed by reading the real files, not
the paper text.** `data/advance/seeds.json` (424 items) holds purely benign
synthetic multi-turn trajectories (each turn: `user`, `tool_response`,
`tool_name` -- no injection fields at all). `data/advance/injected.json`
(726 items) holds the perturbed versions of those seeds: each turn adds
`injection_in_user`, `injection_in_tool`, `injection_type`. This loader
uses only `injected.json`, since it is the one file with BOTH labels
present within the same scenario (needed for the tool-matched-negative
question) -- 657 turns with an injection flag set and a non-null
`tool_name`, 1526 without, across the 726 scenarios' 2844 total turns (661
turns have `tool_name: null` and are skipped, e.g. turns that are pure
narration with no tool call).

**Attack/benign definition, stated explicitly:** a turn is `attack` if
`injection_in_user` or `injection_in_tool` is `true` -- i.e. the turn where
ASEval's own perturbation operator placed (or is still actively exploiting)
the injected harmful instruction, per the construction described in
2605.22321 ("injects instructions into otherwise benign tool-using
trajectories"). A turn is `benign` otherwise. `task_id` is the scenario's
own `id` field (one per synthetic run, e.g. `"syn-0251"`) -- turns from
different scenarios never share an id.

**Stated limitation, not glossed over:** this static export records only
`tool_name` and the tool's (pre-computed/mocked) response text for each
turn -- it does NOT record the actual arguments the mocked call was made
with. `arguments` is populated as `{"tool_response": <first 500 chars of
tool_response>}` as the best available substitute for "action content";
the content-leakage gate run against this is therefore measuring whether
the tool's *response* text leaks the label, not the call's own arguments
the way STAC/AgentDojo's gate-3 numbers do. This is disclosed here, not
silently treated as equivalent.

Requires `ASEVAL_DATA_PATH` pointing at a clone of
https://github.com/antgroup/Agent3Sigma-Stage (the directory containing
`data/advance/injected.json`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..shortcut_audit import AuditRecord, BenchmarkNotObtainedError


def load_aseval() -> list[AuditRecord]:
    repo_dir = os.environ.get("ASEVAL_DATA_PATH")
    if not repo_dir:
        raise BenchmarkNotObtainedError(
            "ASEVAL_DATA_PATH not set. Obtain via: "
            "git clone https://github.com/antgroup/Agent3Sigma-Stage.git, "
            "then set ASEVAL_DATA_PATH=<clone dir> (the directory containing data/advance/injected.json)"
        )
    injected_path = Path(repo_dir) / "data" / "advance" / "injected.json"
    if not injected_path.exists():
        raise BenchmarkNotObtainedError(f"ASEVAL_DATA_PATH set but {injected_path} does not exist")

    items = json.loads(injected_path.read_text())
    records = []
    for item in items:
        task_id = item["id"]
        for turn in item["turns"]:
            tool_name = turn.get("tool_name")
            if not tool_name:
                continue
            is_attack = bool(turn.get("injection_in_user")) or bool(turn.get("injection_in_tool"))
            arguments = {"tool_response": str(turn.get("tool_response"))[:500]}
            records.append(
                AuditRecord("ASEval", task_id, tool_name, arguments, "attack" if is_attack else "benign")
            )
    return records
