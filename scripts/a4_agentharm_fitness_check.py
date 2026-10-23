#!/usr/bin/env python3
"""AgentHarm fitness check (docs/v2/RECONCILED_STATE_v0.2.md §14b): a
fitness check, not a substitution. Reports, against AgentHarm's real
harmful-behaviors data:

1. How many tasks involve more than one tool call (`len(target_functions)
   > 1`).
2. How many have no single call harmful in isolation, by a disclosed,
   literal tool-name heuristic (ALARM_KEYWORDS below) -- since no real
   call arguments exist in this static release (every record's
   `arguments` is `{}`, per `benchmark/a4/audit_loaders/agentharm.py`'s
   own stated limitation), this is necessarily an undercount of the true
   number: real arguments, if they existed, could reveal additional
   in-isolation harm this heuristic cannot see.
3. Whether harm is carried by the task request or the call sequence --
   checked directly against the harmful/benign behavior pairs that share
   an id: do they use the same tools in the same structure, differing
   only in the stated goal's content?

No baseline, no arms, no training. This script only counts and compares
real downloaded data.

Usage:
    python3 -m scripts.a4_agentharm_fitness_check --data-dir /path/to/agentharm/benchmark
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# A tool name is "inherently alarming" only if it contains one of these
# substrings -- a name that would read as a red flag with NO context at
# all, independent of any stated goal. Deliberately literal and narrow,
# not a judgment call made case by case.
ALARM_KEYWORDS = [
    "ransomware", "exploit", "malware", "stolen", "credit_card_details",
    "alpha_bay", "onion", "login_data", "trafficking", "csam", "child_",
    "bioweapon", "explosive", "poison", "hack",
]

_SPLITS = ("test_public", "validation")


def _load_behaviors(path: Path) -> list[dict]:
    return json.loads(path.read_text())["behaviors"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True, help="AgentHarm's benchmark/ directory")
    args = parser.parse_args()

    base = args.data_dir
    harmful_by_id: dict[str, dict] = {}
    benign_by_id: dict[str, dict] = {}
    for split in _SPLITS:
        for b in _load_behaviors(base / f"harmful_behaviors_{split}.json"):
            harmful_by_id[f"{split}_{b['id']}"] = b
        for b in _load_behaviors(base / f"benign_behaviors_{split}.json"):
            benign_by_id[f"{split}_{b['id']}"] = b

    all_harmful = list(harmful_by_id.values())
    n = len(all_harmful)
    print(f"Total harmful behaviors (both splits): {n}")

    n_multi = sum(1 for b in all_harmful if len(b["target_functions"]) > 1)
    print(f"\n1. Tasks with more than one tool call: {n_multi}/{n}")

    all_tools = set()
    for b in all_harmful:
        all_tools.update(b["target_functions"])
    alarming = sorted(t for t in all_tools if any(k in t.lower() for k in ALARM_KEYWORDS))
    print(f"\n2. Distinct tool names used by harmful behaviors: {len(all_tools)}")
    print(f"   Tool names matching an alarm keyword: {alarming}")
    n_all_generic = sum(1 for b in all_harmful if not any(t in alarming for t in b["target_functions"]))
    print(f"   Behaviors where EVERY tool name is generic/mundane (no single call harmful in isolation, by name): "
          f"{n_all_generic}/{n} ({n_all_generic / n:.1%})")
    print("   Caveat: by tool name alone -- no real call arguments exist in this static release; this is a lower bound.")

    print("\n3. Harm carried by the request vs. the sequence -- paired harmful/benign tool-sequence comparison:")
    n_pairs = 0
    n_identical_tools = 0
    for task_id, h in harmful_by_id.items():
        b = benign_by_id.get(task_id)
        if b is None:
            continue
        n_pairs += 1
        if h["target_functions"] == b["target_functions"]:
            n_identical_tools += 1
    print(f"   Harmful/benign pairs with IDENTICAL target_functions (same tools, same order): "
          f"{n_identical_tools}/{n_pairs} ({n_identical_tools / n_pairs:.1%})")
    print("   Where tools are identical, the only difference between the harmful and benign version")
    print("   is the stated goal's content in the prompt -- harm is carried by the request, not the sequence.")


if __name__ == "__main__":
    main()
