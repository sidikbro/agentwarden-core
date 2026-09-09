"""Attribution computation behind
docs/issues/atbench_274_279_not_toolname_driven.md — reads the ATBench-Claw
replay artifacts (produced entirely outside this repo, under AMARE; this
script only reads them read-only to check a factual claim, per
EXPERIMENTAL_PLAN_v0.2.md §0's clarification) and reports how much of the
observed blocking is attributable to the Stage-1 always_block tool-name
list vs. everything else.

Saved as a script (rather than left as an ad hoc one-off computation) per
docs/v2/RECONCILED_STATE_v0.2.md §7's own gap note: a number is not
reproducible-from-a-recorded-command if the command was never recorded.

Usage: python3 -m scripts.report_atbench_attribution
"""
from __future__ import annotations

import json
from pathlib import Path

REPLAY_RESULTS = Path.home() / "atbench-claw-eval" / "replay_results.jsonl"
TOOL_VOCABULARY = Path.home() / "atbench-claw-eval" / "tool_vocabulary.json"

# config/rules.yaml's always_block list, current as of the D3/approval-gate
# change (agentwarden/policies/approval_gate.py) — process, kill, chmod,
# chown, sessions_spawn, subagent, subagents, delegate, task moved OUT of
# this set and into route_to_review since the historical replay ran, but
# the historical replay predates that change, so this is the list as it
# stood when replay_results.jsonl was produced (the full pre-split list),
# not today's smaller irreducible set — the attribution question is about
# what actually drove THAT run's numbers.
ALWAYS_BLOCK_AT_REPLAY_TIME = {
    "exec", "execute", "bash", "shell", "run_command", "terminal", "system",
    "process", "kill", "sudo", "su", "chmod", "chown",
    "sessions_spawn", "subagent", "subagents", "spawn", "create_agent",
    "delegate", "task",
}


def main() -> None:
    if not REPLAY_RESULTS.exists() or not TOOL_VOCABULARY.exists():
        print(f"Artifacts not found ({REPLAY_RESULTS}, {TOOL_VOCABULARY}) — "
              f"nothing to compute. These live outside this repo (AMARE-side).")
        return

    total_blocked_invocations = 0
    blocked_name_exact_matches = 0

    with REPLAY_RESULTS.open() as f:
        for line in f:
            row = json.loads(line)
            total_blocked_invocations += row["aw_block_count"]
            for name in row["blocked_tools"]:
                if name.lower() in ALWAYS_BLOCK_AT_REPLAY_TIME:
                    blocked_name_exact_matches += 1

    vocab = json.loads(TOOL_VOCABULARY.read_text())
    all_tools = set(vocab["all_tools"])
    blocked_tools = set(vocab["agentwarden_blocked"])
    n_unique_tools = vocab["n_unique_tools"]

    exact_match_distinct_tools = {t for t in blocked_tools if t.lower() in ALWAYS_BLOCK_AT_REPLAY_TIME}

    print("=" * 70)
    print("ATBench-Claw replay attribution: always_block vs. everything else")
    print("=" * 70)
    print(f"n_unique_tools in vocabulary:        {n_unique_tools}")
    print(f"distinct tools blocked at least once: {len(blocked_tools)}")
    print(f"  -> of which exactly match always_block: {len(exact_match_distinct_tools)} {sorted(exact_match_distinct_tools)}")
    print()
    print(f"total blocked invocations (all trajectories): {total_blocked_invocations}")
    print(f"  -> of which tool name exactly matches always_block: {blocked_name_exact_matches}")
    if total_blocked_invocations:
        pct = 100 * blocked_name_exact_matches / total_blocked_invocations
        print(f"  -> {pct:.2f}% of blocked invocations attributable to the tool-name list")
        print(f"  -> {100 - pct:.2f}% attributable to arg_patterns and/or the LLM classifier")


if __name__ == "__main__":
    main()
