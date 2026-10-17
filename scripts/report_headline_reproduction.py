"""Clean re-derivation of the two v1 headline claims (SER/exposure
improvement, adversarial coverage) on the v2 benchmark, with the
(non-degenerate) zero-shot classifier — see
docs/issues/v1_headline_numbers_unverifiable.md for why the original
numbers can't be cited forward and what this replaces them with.

SER re-derivation: docs/architecture.md defines SER = tools_needed /
tools_exposed. The benchmark's own exposure_precision_recall's precision
component is exactly this: |exposed ∩ required| / |exposed|. Governed
condition is B5:zero-shot (real D1 + real, non-degenerate D2) to mirror
v1's own ablation shape ("full" = Governor + Router + policy vs
"baseline" = ungoverned) — B0 (full registry, no D2) is the baseline.

Adversarial coverage: blocked_by_governance and model_refused are ALWAYS
reported as separate fields, never combined into one "coverage" number.
model_refused is structurally None/"N/A" for every row here: this
benchmark executes SCRIPTED plans (benchmark/runner.py) — there is no live
model in the loop that could choose to refuse a call. Every scripted
adversarial call is always attempted; only governance can be what stops
it. This is a genuine benchmark limitation (see
docs/v2/B1_prompting_only_limitation.md — the same "no live decision-maker"
gap), not a claim that model refusal doesn't matter, and it means 100% of
any "coverage" measured here is mechanically attributable to governance —
that attribution is real, but it does not generalize to what a live model
would do, and there is currently only ONE adversarial scenario built
(research_synth's a1), not the N=100-adversarial-task breadth v1's own
batch eval had. Report this as N=1, not as a coverage percentage.

Usage: python3 -m scripts.report_headline_reproduction
"""
from __future__ import annotations

import httpx

from agentwarden.core.pipeline import GovernancePipeline
from agentwarden.parsers.openai import OpenAIParser
from agentwarden.policies.classifier import LLMClassifierPolicy
from agentwarden.policies.rules import RuleBasedPolicy
from agentwarden.profiles.capability_governor import CapabilityGovernor
from agentwarden.providers.ollama import OllamaProvider
from benchmark import metrics
from benchmark.adversarial import a1_direct_dangerous as a1
from benchmark.baselines import run_b0, run_b5
from benchmark.tasks import cluster_summary, data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]
INSTANCES = [(family, variant) for family in FAMILIES for variant in family.VARIANTS]

OLLAMA_URL = "http://localhost:11434"


def _ollama_up() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0).status_code == 200
    except Exception:
        return False


def main() -> None:
    if not _ollama_up():
        print("Ollama not reachable — cannot re-derive (needs the real classifier).")
        return

    governor = CapabilityGovernor()
    pipeline = GovernancePipeline(
        parser=OpenAIParser(),
        policies=[RuleBasedPolicy(), LLMClassifierPolicy(ollama_model="qwen2.5:3b")],
        provider=OllamaProvider(),
    )

    # ── SER / exposure improvement ──────────────────────────────────────
    baseline_precisions, governed_precisions = [], []
    for family, variant in INSTANCES:
        task = family.make_task(variant)
        gt = family.make_ground_truth(variant)
        plan = family.build_oracle_plan(variant)

        traj_b0 = run_b0(task, plan)
        p_b0, _ = metrics.exposure_precision_recall(traj_b0, gt)
        baseline_precisions.append(p_b0)

        traj_b5 = run_b5(task, plan, governor, pipeline, "declared")
        p_b5, _ = metrics.exposure_precision_recall(traj_b5, gt)
        governed_precisions.append(p_b5)

    ser_baseline = sum(baseline_precisions) / len(baseline_precisions)
    ser_governed = sum(governed_precisions) / len(governed_precisions)
    ratio = ser_governed / ser_baseline if ser_baseline else float("inf")

    print("=" * 70)
    print("SER (tools_needed / tools_exposed) re-derivation")
    print("=" * 70)
    print(f"  n instances:         {len(INSTANCES)}  ({cluster_summary(FAMILIES)})")
    print(f"  baseline (B0, ungoverned): avg SER = {ser_baseline:.4f}")
    print(f"  governed (B5:zero-shot):   avg SER = {ser_governed:.4f}")
    print(f"  improvement:               {ratio:.3f}x ({(ratio - 1) * 100:+.1f}%)")
    print()
    print("  For comparison, the two OLD headline figures this replaces:")
    print("    README.md:            10.5x (SER 0.557 vs unsourced baseline 0.053)")
    print("    docs/architecture.md: ~9.3x (SER 0.557 vs unsourced baseline 0.06)")
    print("  Neither baseline figure is traceable to any evaluation run in this")
    print("  repo or its predecessor (aethelgard) — see the issue doc.")

    # ── Adversarial coverage (N=1 — see module docstring) ───────────────
    print()
    print("=" * 70)
    print("Adversarial coverage — research_synth a1 (the only scripted")
    print("adversarial scenario currently built; N=1, not a percentage)")
    print("=" * 70)

    a1_task = a1.make_task()
    a1_gt = a1.make_ground_truth()
    attack_plan = a1.build_attack_plan()

    for label, traj in [
        ("B0 (ungoverned)", run_b0(a1_task, attack_plan)),
        ("B5:zero-shot (governed)", run_b5(a1_task, attack_plan, governor, pipeline, "declared")),
    ]:
        attack_inv = next(inv for inv in traj.invocations if a1_gt.is_attack_invocation(inv.tool_call))
        blocked_by_governance = attack_inv.decision.decision.value == "BLOCK"
        model_refused = None   # structural: scripted plan, no live model to refuse — see module docstring
        print(f"  {label}:")
        print(f"    blocked_by_governance: {blocked_by_governance}  (stage={attack_inv.decision.stage})")
        print(f"    model_refused:         {model_refused}  (N/A — scripted plan, no live decision-maker)")


if __name__ == "__main__":
    main()
