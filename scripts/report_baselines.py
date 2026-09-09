"""Static/ungoverned/learned-placeholder baseline spread — B0, B1, B2, B3
(declared), B4 (zero-shot AND fine-tuned), B5, B6, B7 — across all ten task
instances (5 families x 2 variants).

B4/B5/B6 need a live GovernancePipeline (real classifier backend via
Ollama) — skipped automatically with a note if Ollama isn't reachable,
same convention as the rest of the integration suite.

B4/B5 fine-tuned classifier caveat, read before trusting those rows: the
"aethelgard-router:latest" Ollama tag available in this environment is
CONFIRMED DEGENERATE — see docs/issues/aethelgard-router-degenerate.md.
It returns BLOCK for every tool call tested (12/12 in a targeted diverse
sample), including obviously benign ones, with fabricated justifications
(e.g. "locate_source ... attempts to execute arbitrary code", false).

A real "action" vs "decision" JSON-key mismatch between the model's own
Modelfile system prompt and classifier.py's CLASSIFY_PROMPT/parser WAS
found and fixed (evaluate() now accepts either key) — Ollama's
/api/generate auto-prepends a model's system prompt, so the model was
receiving two conflicting format instructions on every call. Re-tested
after the fix: still 12/12 blocked, identical fabricated reasons. The
degeneracy is in the model weights, not the invocation — do not treat the
fix as having resolved this; it ruled out one candidate cause and the
model is still unusable. "aethelgard-router-q4:latest" 500s on every
request and can't be used at all. Both "...:finetuned" rows below reflect
a broken model artifact, not the real capability of a properly fine-tuned
classifier.

B1's numbers are IDENTICAL to B0's by construction — see
benchmark/baselines.py's module docstring and
docs/v2/B1_prompting_only_limitation.md for why that's the honest result
of a scripted-plan benchmark, not a shortcut.

B6 uses PlaceholderLearnedGovernor — NOT a trained policy. See
agentwarden/profiles/placeholder_learned_governor.py's module docstring.

Usage: python3 -m scripts.report_baselines
"""
from __future__ import annotations

import httpx

from agentwarden.core.pipeline import GovernancePipeline
from agentwarden.parsers.openai import OpenAIParser
from agentwarden.policies.classifier import LLMClassifierPolicy
from agentwarden.policies.rules import RuleBasedPolicy
from agentwarden.profiles.capability_governor import CapabilityGovernor
from agentwarden.profiles.placeholder_learned_governor import PlaceholderLearnedGovernor
from agentwarden.providers.ollama import OllamaProvider
from benchmark import metrics
from benchmark.baselines import run_b0, run_b1, run_b2, run_b3, run_b4, run_b5, run_b6, run_b7
from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth
from benchmark.tool_metadata import TOOL_DESCRIPTIONS

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]
INSTANCES = [(family, variant) for family in FAMILIES for variant in family.VARIANTS]

OLLAMA_URL = "http://localhost:11434"


def _ollama_up() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0).status_code == 200
    except Exception:
        return False


def _row(baseline: str, task, gt, traj) -> dict:
    precision, recall = metrics.exposure_precision_recall(traj, gt)
    return {
        "family": task.family,
        "variant": task.task_id.rsplit("_", 1)[-1],
        "baseline": baseline,
        "success": metrics.task_success(traj, gt),
        "denial": metrics.required_tool_denial_rate(traj, gt),
        "unnec_exp": metrics.unnecessary_exposure_ratio(traj, gt),
        "precision": precision,
        "recall": recall,
        "invocation_fpr": metrics.invocation_fpr(traj, gt),
    }


def main() -> None:
    governor = CapabilityGovernor()
    learned_governor = PlaceholderLearnedGovernor(TOOL_DESCRIPTIONS)
    ollama_up = _ollama_up()

    pipeline_zero_shot = pipeline_finetuned = pipeline_b6 = None
    if ollama_up:
        pipeline_zero_shot = GovernancePipeline(
            parser=OpenAIParser(),
            policies=[RuleBasedPolicy(), LLMClassifierPolicy(ollama_model="qwen2.5:3b")],
            provider=OllamaProvider(),
        )
        try:
            pipeline_finetuned = GovernancePipeline(
                parser=OpenAIParser(),
                policies=[RuleBasedPolicy(), LLMClassifierPolicy(ollama_model="aethelgard-router:latest")],
                provider=OllamaProvider(),
            )
        except Exception as e:
            print(f"Fine-tuned router pipeline could not be constructed: {e}\n")
        pipeline_b6 = pipeline_zero_shot
    else:
        print("Ollama not reachable — B4/B5/B6 skipped (need a live classifier backend).\n")

    rows: list[dict] = []
    for family, variant in INSTANCES:
        task = family.make_task(variant)
        gt = family.make_ground_truth(variant)
        plan = family.build_oracle_plan(variant)

        rows.append(_row("B0", task, gt, run_b0(task, plan)))
        rows.append(_row("B1", task, gt, run_b1(task, plan)))
        rows.append(_row("B2", task, gt, run_b2(task, plan)))
        rows.append(_row("B3", task, gt, run_b3(task, plan, governor, "declared")))
        if pipeline_zero_shot is not None:
            rows.append(_row("B4:zero-shot", task, gt, run_b4(task, plan, pipeline_zero_shot)))
            rows.append(_row("B5:zero-shot", task, gt, run_b5(task, plan, governor, pipeline_zero_shot, "declared")))
        if pipeline_finetuned is not None:
            rows.append(_row("B4:finetuned", task, gt, run_b4(task, plan, pipeline_finetuned)))
            rows.append(_row("B5:finetuned", task, gt, run_b5(task, plan, governor, pipeline_finetuned, "declared")))
        if pipeline_b6 is not None:
            rows.append(_row("B6", task, gt, run_b6(task, plan, learned_governor, pipeline_b6)))
        rows.append(_row("B7", task, gt, run_b7(task, gt, plan)))

    cols = ["family", "variant", "baseline", "success", "denial", "unnec_exp", "precision", "recall", "fpr"]
    widths = [18, 8, 13, 8, 8, 10, 10, 8, 6]

    def fmt(values: list) -> str:
        return "  ".join(str(v).ljust(w) for v, w in zip(values, widths))

    print(fmt(cols))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        print(fmt([
            r["family"], r["variant"], r["baseline"], r["success"],
            f"{r['denial']:.3f}", f"{r['unnec_exp']:.3f}", f"{r['precision']:.3f}", f"{r['recall']:.3f}",
            f"{r['invocation_fpr']:.3f}",
        ]))

    print()
    print("Per-baseline summary, averaged across all instances that ran:")
    baseline_order = ["B0", "B1", "B2", "B3", "B4:zero-shot", "B4:finetuned", "B5:zero-shot", "B5:finetuned", "B6", "B7"]
    baselines_seen = [b for b in baseline_order if any(r["baseline"] == b for r in rows)]
    print(fmt(["baseline", "n", "success_rate", "avg_denial", "avg_unnec_exp", "avg_precision", "avg_recall", "avg_fpr"]))
    for b in baselines_seen:
        subset = [r for r in rows if r["baseline"] == b]
        n = len(subset)
        success_rate = sum(1 for r in subset if r["success"]) / n
        avg = lambda k: sum(r[k] for r in subset) / n
        print(fmt([
            b, str(n), f"{success_rate:.3f}", f"{avg('denial'):.3f}",
            f"{avg('unnec_exp'):.3f}", f"{avg('precision'):.3f}", f"{avg('recall'):.3f}", f"{avg('invocation_fpr'):.3f}",
        ]))

    print()
    print("B1 rows are identical to B0's by construction (see baselines.py docstring +")
    print("docs/v2/B1_prompting_only_limitation.md) -- not a second data point.")
    print("B4:finetuned uses a DEGENERATE model artifact (always blocks, fabricated reasons) --")
    print("see this script's module docstring. Not representative of real fine-tuned performance.")
    print("B6 uses PlaceholderLearnedGovernor -- NOT a trained policy, see its module docstring.")


if __name__ == "__main__":
    main()
