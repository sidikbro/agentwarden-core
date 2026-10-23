#!/usr/bin/env python3
"""ASEval confound demonstration (docs/v2/RECONCILED_STATE_v0.2.md §14a):
how much of arm 1's (the per-step D2 classifier's) full-set performance
survives on the 233-task tool-matched subset, where tool identity cannot
trivially carry the label by construction
(`benchmark/a4/shortcut_audit.py::tool_matched_subset`). Arm 0 (tool
identity alone) is reported on both sets too, for comparison -- it
should collapse toward chance on the subset if the subset construction
is doing its job; this is checked empirically, not assumed.

Arm 1 is scored ONCE, on the full set (2,183 ASEval records); the
subset's arm-1 scores are the matching full-set scores filtered down by
object identity, not a second independent run -- generation is
deterministic (greedy decode, temperature 0) so this is equivalent to,
and half the cost of, scoring the subset a second time.

Arm 0 IS fit independently on each set (full vs. subset), since its CV
logistic regression's one-hot feature space depends on which tool names
are present -- reusing one fit across both would not be the same
question as "what can tool identity alone do on this specific set."

Also reports both sets' own attack/benign balance, since a balance
shift between them would confound a before/after comparison (checked,
not assumed, per instruction).

Per standing instruction (2026-10-22): run via the `agentwarden-gpu`
conda env for arm 1's local-model inference.

No symbolic baseline, no arms, no training beyond arm 0's own trivial,
already-established logistic regression.

Usage:
    conda run -n agentwarden-gpu python3 -m scripts.a4_aseval_confound_demo \
        --json-out results.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmark.a4.audit_loaders.aseval import load_aseval
from benchmark.a4.d2_runner import DEFAULT_ADAPTER_DIR, run_d2_classifier_batched, score_from_decision
from benchmark.a4.shortcut_audit import TARGET_FAR, AuditRecord, tool_identity_scores, tool_matched_subset, tpr_at_far


def _balance(records: list[AuditRecord]) -> dict[str, Any]:
    n = len(records)
    n_attack = sum(1 for r in records if r.label == "attack")
    return {
        "n": n,
        "n_benign": n - n_attack,
        "n_attack": n_attack,
        "attack_fraction": (n_attack / n) if n else float("nan"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER_DIR)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    full = load_aseval()
    subset = tool_matched_subset(full)

    full_balance = _balance(full)
    subset_balance = _balance(subset)
    print(f"Full set:            {full_balance}")
    print(f"Tool-matched subset: {subset_balance}")
    print(f"Distinct tool-matched tasks in subset: {len({r.task_id for r in subset})}\n")

    print("=== Arm 0 (tool identity alone, fit independently on each set) ===")
    full_labels0, full_scores0 = tool_identity_scores(full)
    full_r0 = tpr_at_far(full_labels0, full_scores0, TARGET_FAR)
    print(f"  full set:       AUC={full_r0['auc']:.3f}  TPR@FAR={full_r0['tpr_at_target_far']:.3f}")

    subset_labels0, subset_scores0 = tool_identity_scores(subset)
    subset_r0 = tpr_at_far(subset_labels0, subset_scores0, TARGET_FAR)
    print(f"  matched subset: AUC={subset_r0['auc']:.3f}  TPR@FAR={subset_r0['tpr_at_target_far']:.3f}\n")

    print("=== Arm 1 (per-step D2 classifier, zero-shot, scored once on the full set) ===")
    items = [(r.tool_name, r.arguments) for r in full]
    raw = run_d2_classifier_batched(items, adapter_dir=args.adapter_dir, batch_size=args.batch_size)
    n_parse_fail = sum(1 for r in raw if r["decision"] not in ("BLOCK", "ALLOW"))
    print(f"  n parse failures (scored at chance, 0.5): {n_parse_fail} / {len(raw)}")

    full_scores1 = [score_from_decision(r["decision"], r["confidence"]) for r in raw]
    full_labels1 = [1 if r.label == "attack" else 0 for r in full]
    full_r1 = tpr_at_far(full_labels1, full_scores1, TARGET_FAR)
    print(f"  full set:       AUC={full_r1['auc']:.3f}  TPR@FAR={full_r1['tpr_at_target_far']:.3f}")

    id_to_score = {id(r): s for r, s in zip(full, full_scores1)}
    subset_scores1 = [id_to_score[id(r)] for r in subset]
    subset_labels1 = [1 if r.label == "attack" else 0 for r in subset]
    subset_r1 = tpr_at_far(subset_labels1, subset_scores1, TARGET_FAR)
    print(f"  matched subset: AUC={subset_r1['auc']:.3f}  TPR@FAR={subset_r1['tpr_at_target_far']:.3f}\n")

    print("=== Survival: full-set arm-1 performance minus matched-subset arm-1 performance ===")
    auc_drop = full_r1["auc"] - subset_r1["auc"]
    tpr_drop = full_r1["tpr_at_target_far"] - subset_r1["tpr_at_target_far"]
    print(f"  AUC drop:     {auc_drop:+.3f}")
    print(f"  TPR@FAR drop: {tpr_drop:+.3f}")

    out = {
        "full_balance": full_balance,
        "subset_balance": subset_balance,
        "n_subset_tasks": len({r.task_id for r in subset}),
        "arm0": {"full": full_r0, "subset": subset_r0},
        "arm1": {"full": full_r1, "subset": subset_r1, "n_parse_failures": n_parse_fail},
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(out, indent=2))
        print(f"\nWrote results to {args.json_out}")


if __name__ == "__main__":
    main()
