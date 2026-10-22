"""InjecAgent loader for the shortcut audit (arXiv:2403.02691, "InjecAgent:
Benchmarking Indirect Prompt Injections in Tool-Integrated Large Language
Model Agents", github.com/uiuc-kang-lab/InjecAgent). No credentials, no
terms-of-use form -- a plain public clone.

**Attack/benign definition and extraction, stated explicitly, confirmed
against the real `data/test_cases_{dh,ds}_base.json` files (1,054 cases
total: 510 "direct harm" + 544 "data stealing", matching the paper's own
reported scale exactly):**

- `benign` is the case's own **User Tool** call: `(User Tool, Tool
  Parameters)`. `Tool Parameters` ships as a Python-dict-repr string
  (single-quoted, not JSON) and is parsed with `ast.literal_eval`, not
  `json.loads`.
- `attack` is, for each name in the case's **Attacker Tools** list (one
  record per name -- the "data stealing" cases often name two, e.g. a
  read tool followed by an exfiltration tool), that tool name **with an
  empty arguments dict**. InjecAgent's static test cases specify only the
  attacker's intended TARGET tool and the injected instruction text
  (`Attacker Instruction`) -- not concrete call arguments. Concrete
  arguments only exist once a live agent is actually run against the
  injected prompt and chooses to comply (the paper's own evaluation
  method); this loader does not run that evaluation and does not
  approximate those arguments, since InjecAgent's benchmark itself does
  not specify them. The empty dict is therefore the honest value, not an
  approximation.
- `task_id` is `f"{source_file}_{index}"` (no case-id field exists in the
  raw data; row index within its source file is stable and unique).

The two "_enhanced" files are NOT used -- they are the same 1,054 cases
with a synthetic "Tool Response" field added for simulated execution, not
a different case set (confirmed by identical length and identical
Attacker/User Tool fields against the "_base" files).

Requires `INJECAGENT_DATA_DIR` pointing at a clone's `data/` directory:
`git clone https://github.com/uiuc-kang-lab/InjecAgent.git`, then
`INJECAGENT_DATA_DIR=<clone>/data`.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

from ..shortcut_audit import AuditRecord, BenchmarkNotObtainedError

_SOURCE_FILES = ("test_cases_dh_base.json", "test_cases_ds_base.json")


def load_injecagent() -> list[AuditRecord]:
    data_dir = os.environ.get("INJECAGENT_DATA_DIR")
    if not data_dir:
        raise BenchmarkNotObtainedError(
            "INJECAGENT_DATA_DIR not set. Obtain via: "
            "git clone https://github.com/uiuc-kang-lab/InjecAgent.git, "
            "then set INJECAGENT_DATA_DIR=<clone>/data"
        )
    data_path = Path(data_dir)

    records: list[AuditRecord] = []
    for source_file in _SOURCE_FILES:
        path = data_path / source_file
        if not path.exists():
            raise BenchmarkNotObtainedError(f"expected file not found: {path}")
        cases = json.loads(path.read_text())
        for i, case in enumerate(cases):
            task_id = f"{source_file}_{i}"
            params = ast.literal_eval(case["Tool Parameters"])
            records.append(AuditRecord("InjecAgent", task_id, case["User Tool"], params, "benign"))
            for attacker_tool in case["Attacker Tools"]:
                records.append(AuditRecord("InjecAgent", task_id, attacker_tool, {}, "attack"))
    return records
