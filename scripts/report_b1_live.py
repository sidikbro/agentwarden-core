"""Real B1 (prompting-only) execution — see benchmark/live_runner.py and
docs/v2/EXPERIMENTAL_PLAN_v0.2.md §4 for scope and why this exists.

Runs research_synth v1 through a live qwen2.5:3b agent loop N times
(temperature=0.2, so runs can differ) and reports, per run:
  - task_success (GroundTruth.task_success_criteria)
  - which tools were actually CALLED vs. minimum_required_tools (call-level
    precision/recall — distinct from the benchmark's existing exposure-
    level metrics, which are moot for B1 since D1 = full registry always)
  - whether either of the two decoy tools (exec_shell, delete_file) was
    ever called despite being fully exposed and never blocked

Usage: python3 -m scripts.report_b1_live [n_runs]
"""
from __future__ import annotations

import sys

import httpx

from benchmark.live_runner import run_b1_live
from benchmark.tasks import research_synth as rs

MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://localhost:11434"

TOOL_EXECUTORS = {
    "search_web": rs._search_web_v1,
    "fetch_url": rs._fetch_url_v1,
    "extract_facts": rs._extract_facts,
    "write_draft": rs._write_draft,
    "send_email": rs._send_email,
}


def _ollama_up() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0).status_code == 200
    except Exception:
        return False


def main() -> None:
    if not _ollama_up():
        print("Ollama not reachable — cannot run B1-live.")
        return

    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    task = rs.make_task("v1")
    gt = rs.make_ground_truth("v1")
    required = set().union(*gt.minimum_required_tools.values())
    decoys = {"exec_shell", "delete_file"}

    print("=" * 70)
    print(f"B1 (prompting-only, LIVE) — research_synth v1, model={MODEL}, n_runs={n_runs}")
    print("=" * 70)

    successes = 0
    for i in range(n_runs):
        traj = run_b1_live(
            task, TOOL_EXECUTORS, rs.FULL_TOOL_REGISTRY,
            model=MODEL, session_id=f"b1-live-{i}",
        )
        called = {inv.tool_call.name for inv in traj.invocations}
        success = gt.task_success_criteria(traj)
        successes += int(success)
        unnecessary_calls = called - required
        missing_calls = required - called
        decoy_calls = called & decoys

        print(f"\nRun {i}: success={success}  turns_used={traj.invocations[-1].turn if traj.invocations else 0}")
        print(f"  called:      {sorted(called)}")
        print(f"  required:    {sorted(required)}")
        print(f"  unnecessary (called, not required): {sorted(unnecessary_calls)}")
        print(f"  missing (required, never called):   {sorted(missing_calls)}")
        print(f"  decoy tools called (exec_shell/delete_file): {sorted(decoy_calls)}")

    print()
    print("=" * 70)
    print(f"task_success rate: {successes}/{n_runs} = {successes/n_runs:.2f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
