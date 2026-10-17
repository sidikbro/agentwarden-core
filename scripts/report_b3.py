"""Thin end-to-end B3 (task-conditioned YAML) run across all ten task
instances (5 families x 2 variants each), both task-type conditions
(declared / structural fallback), reporting real metric numbers.

B3 = D1: CapabilityGovernor (real, YAML-driven), D2: none — matches the
baseline matrix definition exactly, so this runs run_scripted (not
run_via_pipeline; B3 has no D2 by design).

config/capability_profiles.yaml is a hand-authored, realistic-but-imperfect
static policy (NOT derived from ground truth) — see its own comments for
the specific mistakes per family. This run is expected to show nonzero
unnecessary_exposure_ratio and required_tool_denial_rate on at least some
instances; if it doesn't, the benchmark is too easy again.

Usage: python3 -m scripts.report_b3
"""
from __future__ import annotations

from agentwarden.profiles.capability_governor import CapabilityGovernor
from benchmark import metrics
from benchmark.baselines import resolve_task_type, run_b3
from benchmark.tasks import cluster_summary, data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]
INSTANCES = [(family, variant) for family in FAMILIES for variant in family.VARIANTS]
CONDITIONS = ["declared", "fallback"]


def main() -> None:
    governor = CapabilityGovernor()

    rows = []
    for family, variant in INSTANCES:
        task = family.make_task(variant)
        gt = family.make_ground_truth(variant)
        plan = family.build_oracle_plan(variant)

        for condition in CONDITIONS:
            task_type_used = resolve_task_type(task, governor, condition)
            traj = run_b3(task, plan, governor, condition)

            precision, recall = metrics.exposure_precision_recall(traj, gt)
            row = {
                "family": task.family,
                "variant": variant,
                "condition": condition,
                "task_type_used": task_type_used,
                "task_success": metrics.task_success(traj, gt),
                "required_tool_denial_rate": metrics.required_tool_denial_rate(traj, gt),
                "unnecessary_exposure_ratio": metrics.unnecessary_exposure_ratio(traj, gt),
                "exposure_precision": precision,
                "exposure_recall": recall,
                "revocation_lag": metrics.revocation_lag(traj, gt),
                "invocation_fpr": metrics.invocation_fpr(traj, gt),
                "invocation_fnr": metrics.invocation_fnr(traj, gt),
                "approval_request_rate": metrics.approval_request_rate(traj),
                "classifier_routing_fraction": metrics.classifier_routing_fraction(traj),
                "added_latency_ms": metrics.added_latency_ms(traj),
            }
            rows.append(row)

    cols = ["family", "variant", "condition", "task_type_used", "success", "denial",
            "unnec_exp", "precision", "recall", "fpr", "fnr"]
    widths = [18, 8, 10, 18, 8, 8, 10, 10, 8, 6, 6]

    def fmt_row(values: list) -> str:
        return "  ".join(str(v).ljust(w) for v, w in zip(values, widths))

    print(fmt_row(cols))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        print(fmt_row([
            r["family"], r["variant"], r["condition"], r["task_type_used"], r["task_success"],
            f"{r['required_tool_denial_rate']:.3f}", f"{r['unnecessary_exposure_ratio']:.3f}",
            f"{r['exposure_precision']:.3f}", f"{r['exposure_recall']:.3f}",
            f"{r['invocation_fpr']:.3f}", f"{r['invocation_fnr']:.3f}",
        ]))

    n_denied = sum(1 for r in rows if r["required_tool_denial_rate"] > 0)
    n_overexposed = sum(1 for r in rows if r["unnecessary_exposure_ratio"] > 0)
    n_failed = sum(1 for r in rows if r["task_success"] is False)
    print()
    print(f"Summary across {len(rows)} rows ({len(INSTANCES)} instances x {len(CONDITIONS)} conditions):")
    print(f"  {cluster_summary(FAMILIES)}")
    print(f"  rows with required_tool_denial_rate > 0: {n_denied}")
    print(f"  rows with unnecessary_exposure_ratio  > 0: {n_overexposed}")
    print(f"  rows with task_success == False:           {n_failed}")

    print()
    print("Per-instance revocation_lag (turns; -1 = never revoked before trajectory end):")
    for r in rows:
        print(f"  {r['family']:<18} {r['variant']:<4} {r['condition']:<10} {r['revocation_lag']}")

    print()
    print("approval_request_rate and classifier_routing_fraction are 0.0 for every row by")
    print("construction: B3 has no D2 (run_scripted never emits REVIEW or routes to a classifier).")
    print("added_latency_ms is 0.0 for every row by construction: run_scripted's exposure-gate")
    print("decisions never set latency_ms; there is no real governance-stage timing to sum under B3.")


if __name__ == "__main__":
    main()
