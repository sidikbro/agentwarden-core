#!/usr/bin/env python3
"""Reports how many of STAC's 471 (of 483) cases with executed history
support a length-matched, benign-final negative -- `benchmark/a4/
s0_inputs.py::build_stac_length_matched_s0_pairs`, see that function's
docstring for the construction. A length-matched negative sits at the same
chain position as the attack candidate (both "step k of a k-step chain"),
addressing the index-from-end confound directly at pair-construction level,
distinct from gate 3's tool-identity matching
(`benchmark/a4/s0_inputs.py::build_stac_matched_s0_pairs`,
`docs/v2/RECONCILED_STATE_v0.2.md` §12a).

Per instruction: if fewer than ~150 of 471 cases support one, STAC is unfit
for A4's central claim -- a benchmark-fitness finding, reported here, not
routed around. This script does not build the symbolic baseline or any
arm; it only reports feasibility counts and the raw (executed-length,
chain-length) distribution behind them.

Usage:
    python3 -m scripts.a4_stac_length_matched_feasibility --stac-data /path/to/STAC_benchmark_data.json
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from benchmark.a4.s0_inputs import build_stac_length_matched_s0_pairs
from benchmark.a4.stac_adapter import load_stac_cases

NEAR_FITNESS_THRESHOLD = 150  # this project's own instructed bar, stated plainly, not derived


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stac-data", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    cases = load_stac_cases(args.stac_data)
    dist: collections.Counter = collections.Counter()
    diffs = []
    for case in cases:
        tool_calls = [t.tool_call for t in case.turns if t.tool_call is not None]
        k = len(case.label["malicious_tool_chain"])
        L = len(tool_calls)
        dist[(L, k)] += 1
        if tool_calls:
            diffs.append(k - L)

    pairs, counts = build_stac_length_matched_s0_pairs(args.stac_data)

    print(f"=== STAC length-matched, benign-final negative: feasibility over {counts['total_cases']} cases ===\n")
    print(f"counts: {counts}")
    print(f"length-matched pairs built: {len(pairs)}\n")

    print("(executed_length L, chain_length k) -> n_cases, most common first:")
    for (L, k), n in dist.most_common(15):
        print(f"    L={L:3d}  k={k:3d}  (k-L={k - L:+d})  n={n}")

    if diffs:
        print(
            f"\nk-L over the {len(diffs)} cases with any executed history: "
            f"min={min(diffs)}, median={sorted(diffs)[len(diffs) // 2]}, max={max(diffs)}"
        )

    n_supporting = counts["matched"]
    pool = counts["total_cases"] - counts["no_executed_tool_calls"]
    print(f"\n=== VERDICT: {n_supporting} of {pool} cases support a length-matched negative ===")
    if n_supporting < NEAR_FITNESS_THRESHOLD:
        print(
            f"Below the instructed ~{NEAR_FITNESS_THRESHOLD}-case threshold. Per instruction: "
            "STAC is unfit for A4's central claim via this construction -- a benchmark-fitness "
            "finding, reported here, not routed around with a relaxed matching rule."
        )
    else:
        print(f"At or above the instructed ~{NEAR_FITNESS_THRESHOLD}-case threshold.")

    if args.json_out:
        out = {
            "counts": counts,
            "n_length_matched_pairs": len(pairs),
            "distribution": [{"L": L, "k": k, "n": n} for (L, k), n in dist.most_common()],
            "k_minus_L_stats": (
                {"min": min(diffs), "median": sorted(diffs)[len(diffs) // 2], "max": max(diffs)} if diffs else None
            ),
            "near_fitness_threshold": NEAR_FITNESS_THRESHOLD,
        }
        args.json_out.write_text(json.dumps(out, indent=2))
        print(f"\nWrote results to {args.json_out}")


if __name__ == "__main__":
    main()
