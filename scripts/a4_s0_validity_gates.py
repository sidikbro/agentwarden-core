#!/usr/bin/env python3
"""A4 §13 step 3: run docs/v2/A4_MULTITURN_SPEC_v0.2.md §9's four
validity gates on S0 inputs. Nothing else -- no symbolic baseline, no
arms, no training; a gate failure is recorded as a result, not iterated
against until it passes.

Benchmarks: STAC (primary) and AgentDojo (secondary, coarse anchor per
§7's requirement) -- MT-AgentRisk is excluded, consistent with §7: its
dataset is gated and was not obtained this session.

Construction: `benchmark/a4/s0_inputs.py` builds, for each case, a
minimal pair of S0 decision inputs (same anchor, same session prefix,
differing only in the call under judgment) labeled BENIGN/ATTACK. See
that module's docstring for exactly how STAC's and AgentDojo's pairs
are built and what gets skipped.

Gates (docs/v2/A4_MULTITURN_SPEC_v0.2.md §9), each run independently
per benchmark:

1. Serialized-input leakage -- the full S0 JSON (`build_s0_input()`
   output) as the text field, run through `scripts/semantic_leakage_gate`'s
   AMI / nearest-centroid / TF-IDF+LR signals. Same thresholds as that
   script (AMI < 0.10, balanced accuracy < 0.65 to PASS) -- reused
   directly, not re-derived, so there is one definition of "leaks" across
   every leakage check in this project.
2. Anchor-only leakage -- the anchor alone (`anchor_only_json()`), same
   signals, same thresholds. PASS means the derivation isn't smuggling
   the label into the anchor.
3. Call-only leakage -- the call under judgment alone (`call_only_json()`),
   same signals, same thresholds. STAC reports ~0.5% prompt harmfulness,
   which predicts this should pass; this gate verifies that rather than
   assuming it.
4. No fabricated fields -- an automated, structural assertion (not a
   statistical signal) that every S0 instance's top-level keys are
   exactly {"authorization", "call_counts", "invocations_observed",
   "call"} and that none of the six fields `session_authorization.py`
   names as blocked (scopes_opened, verifications, effect_classes_used,
   trust_levels_touched, out_of_scope_resource_count, elapsed_turns)
   appears anywhere in the serialized output.

Also runs a MATCHED re-run of gate 3 alone (same task, same position --
final vs. final -- and, additionally, the same tool where the benchmark
allows it), alongside the original unmatched numbers, which are kept as
the historical record rather than overwritten. See
`benchmark/a4/s0_inputs.py::build_stac_matched_s0_pairs` and
`build_agentdojo_matched_s0_pairs` for exactly how each benchmark's
matched set is constructed and how much of it had no match at all.

Usage:
    python3 -m scripts.a4_s0_validity_gates --stac-data /path/to/STAC_benchmark_data.json
    python3 -m scripts.a4_s0_validity_gates --stac-data ... --json-out results.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentwarden.core.decision_input import S0_FIELDS, anchor_only_json, call_only_json
from benchmark.a4.s0_inputs import (
    S0Pair,
    build_agentdojo_matched_s0_pairs,
    build_agentdojo_s0_pairs,
    build_stac_matched_s0_pairs,
    build_stac_s0_pairs,
)
from scripts.semantic_leakage_gate import (
    AMI_FAIL_THRESHOLD,
    BAL_ACC_FAIL_THRESHOLD,
    _check_deps,
    run_pair,
)

_BLOCKED_FIELD_NAMES = frozenset(
    {
        "scopes_opened",
        "verifications",
        "effect_classes_used",
        "trust_levels_touched",
        "out_of_scope_resource_count",
        "elapsed_turns",
    }
)


def _rows_by_label(pairs: list[S0Pair], text_of) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {"BENIGN": [], "ATTACK": []}
    for pair in pairs:
        for label, s0_json in pair.instances():
            rows[label].append({"text": text_of(pair, s0_json), "case_id": pair.case_id})
    return rows


def _gate1_rows(pairs: list[S0Pair]) -> dict[str, list[dict[str, Any]]]:
    return _rows_by_label(pairs, lambda pair, s0_json: s0_json)


def _gate2_rows(pairs: list[S0Pair]) -> dict[str, list[dict[str, Any]]]:
    return _rows_by_label(pairs, lambda pair, s0_json: anchor_only_json(pair.anchor))


def _gate3_rows(pairs: list[S0Pair]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {"BENIGN": [], "ATTACK": []}
    for pair in pairs:
        rows["BENIGN"].append({"text": call_only_json(pair.benign_call), "case_id": pair.case_id})
        rows["ATTACK"].append({"text": call_only_json(pair.attack_call), "case_id": pair.case_id})
    return rows


def run_gate123(name: str, pairs: list[S0Pair], builder) -> dict[str, Any]:
    rows_by_label = builder(pairs)
    cache: dict[int, Any] = {}
    result = run_pair(rows_by_label, "BENIGN", "ATTACK", text_field="text", embedding_cache=cache)
    result["gate"] = name
    return result


def run_gate4(name: str, pairs: list[S0Pair]) -> dict[str, Any]:
    violations = []
    checked = 0
    for pair in pairs:
        for label, s0_json in pair.instances():
            checked += 1
            payload = json.loads(s0_json)
            if set(payload.keys()) != S0_FIELDS:
                violations.append(f"{pair.case_id}/{label}: top-level keys {set(payload.keys())} != {S0_FIELDS}")
                continue
            serialized_flat = json.dumps(payload)
            for blocked in _BLOCKED_FIELD_NAMES:
                if f'"{blocked}"' in serialized_flat:
                    violations.append(f"{pair.case_id}/{label}: blocked field {blocked!r} present")
    return {
        "gate": name,
        "n_checked": checked,
        "violations": violations,
        "verdict": "FAIL (fabricated/blocked field present)" if violations else "PASS (no fabricated fields)",
    }


def print_gate123(result: dict[str, Any], benchmark: str) -> None:
    print(f"[{benchmark}] Gate: {result['gate']}")
    if result.get("skipped"):
        print(f"    SKIPPED ({result['reason']})")
        return
    print(f"    n BENIGN={result['n_a']}, n ATTACK={result['n_b']}  [majority baseline {result['majority_baseline']:.1%}]")
    print(f"    AMI (clustering):                   {result['ami']:.3f}  (fail >= {AMI_FAIL_THRESHOLD})")
    print(f"    nearest-centroid balanced accuracy:  {result['centroid_balanced_accuracy']:.3f}  (fail >= {BAL_ACC_FAIL_THRESHOLD})")
    print(f"    TF-IDF+LR balanced accuracy:         {result['tfidf_lr_balanced_accuracy']:.3f}  (fail >= {BAL_ACC_FAIL_THRESHOLD})")
    print(f"    VERDICT: {result['verdict']}")
    for r in result["fail_reasons"]:
        print(f"        - {r}")
    print()


def print_gate4(result: dict[str, Any], benchmark: str) -> None:
    print(f"[{benchmark}] Gate: {result['gate']}")
    print(f"    n checked={result['n_checked']}, violations={len(result['violations'])}")
    print(f"    VERDICT: {result['verdict']}")
    for v in result["violations"][:10]:
        print(f"        - {v}")
    if len(result["violations"]) > 10:
        print(f"        ... and {len(result['violations']) - 10} more")
    print()


def run_all_gates(benchmark: str, pairs: list[S0Pair], skipped: int) -> list[dict[str, Any]]:
    print(f"=== {benchmark}: {len(pairs)} pairs ({2 * len(pairs)} S0 instances), {skipped} cases skipped ===\n")
    results = []

    g1 = run_gate123("1_serialized_input_leakage", pairs, _gate1_rows)
    print_gate123(g1, benchmark)
    results.append(g1)

    g2 = run_gate123("2_anchor_only_leakage", pairs, _gate2_rows)
    print_gate123(g2, benchmark)
    results.append(g2)

    g3 = run_gate123("3_call_only_leakage", pairs, _gate3_rows)
    print_gate123(g3, benchmark)
    results.append(g3)

    g4 = run_gate4("4_no_fabricated_fields", pairs)
    print_gate4(g4, benchmark)
    results.append(g4)

    return results


def run_matched_gate3(benchmark: str, pairs: list[S0Pair], counts: dict[str, int]) -> dict[str, Any]:
    print(f"=== {benchmark}: MATCHED gate 3 re-run -- {len(pairs)} matched pairs ({2 * len(pairs)} S0 instances) ===")
    print(f"    match breakdown: {counts}\n")
    if len(pairs) < 5:
        result = {
            "gate": "3_call_only_leakage_MATCHED",
            "skipped": True,
            "reason": f"only {len(pairs)} matched pairs -- below MIN_ROWS_PER_CLASS, CV not meaningful",
            "match_counts": counts,
        }
        print(f"[{benchmark}] Gate: {result['gate']}\n    SKIPPED ({result['reason']})\n")
        return result
    result = run_gate123("3_call_only_leakage_MATCHED", pairs, _gate3_rows)
    result["match_counts"] = counts
    print_gate123(result, benchmark)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stac-data", type=Path, required=True, help="path to STAC_benchmark_data.json")
    parser.add_argument("--agentdojo-suite-version", default="v1.2.1")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    _check_deps()

    stac_pairs, stac_skipped = build_stac_s0_pairs(args.stac_data)
    agentdojo_pairs, agentdojo_skipped = build_agentdojo_s0_pairs(suite_version=args.agentdojo_suite_version)

    all_results = {
        "stac": run_all_gates("STAC (primary)", stac_pairs, stac_skipped),
        "agentdojo": run_all_gates("AgentDojo (secondary, coarse anchor)", agentdojo_pairs, agentdojo_skipped),
    }

    stac_matched_pairs, stac_matched_counts = build_stac_matched_s0_pairs(args.stac_data)
    agentdojo_matched_pairs, agentdojo_matched_counts = build_agentdojo_matched_s0_pairs(
        suite_version=args.agentdojo_suite_version
    )
    matched_results = {
        "stac": run_matched_gate3("STAC (primary)", stac_matched_pairs, stac_matched_counts),
        "agentdojo": run_matched_gate3("AgentDojo (secondary, coarse anchor)", agentdojo_matched_pairs, agentdojo_matched_counts),
    }

    print("=== SUMMARY (unmatched, kept as record) ===")
    for benchmark, results in all_results.items():
        for r in results:
            verdict = r["verdict"] if not r.get("skipped") else "SKIPPED"
            print(f"{benchmark:10s} {r['gate']:30s} {verdict}")

    print("\n=== SUMMARY (matched gate 3 re-run) ===")
    for benchmark, r in matched_results.items():
        verdict = r["verdict"] if not r.get("skipped") else f"SKIPPED ({r.get('reason')})"
        print(f"{benchmark:10s} {r['gate']:30s} {verdict}")

    all_results["matched_gate3"] = matched_results

    if args.json_out:
        args.json_out.write_text(json.dumps(all_results, indent=2))
        print(f"\nWrote machine-readable results to {args.json_out}")


if __name__ == "__main__":
    main()
