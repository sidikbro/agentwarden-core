"""Human-readable printout of every benchmark instance, for review.

Prints, per instance: task_id, family, initial_prompt, each phase's
required_tools/revocable_after/success_predicate (source, not just a
description -- a reviewer should see the actual check, not my paraphrase
of it), and the overall task_success_criteria.

Marks each instance NEW/PENDING or existing, per
docs/v2/BENCHMARK_EXPANSION_MANIFEST.md, so a reviewer isn't re-reading
already-settled instances by accident.

Usage: python3 -m scripts.print_benchmark_instances [family_name]
"""
from __future__ import annotations

import inspect
import re
import sys

from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]

# Per docs/v2/BENCHMARK_EXPANSION_MANIFEST.md batch 1 -- everything else
# is pre-existing (already part of the original 10-instance benchmark).
NEW_PENDING_REVIEW = {
    ("research_synth", "v3"),
    ("repo_triage", "v3"),
    ("incident_response", "v3"),
}


def _clean_lambda_source(fn) -> str:
    src = inspect.getsource(fn)
    src = re.sub(r"^\s*\w+\s*=\s*", "", src, count=1)   # strip "success_predicate="
    src = src.strip().rstrip(",")
    src = re.sub(r"\s+", " ", src)   # collapse multi-line lambdas to one line
    return src


def print_instance(family, variant: str) -> None:
    task = family.make_task(variant)
    gt = family.make_ground_truth(variant)
    tag = "*** NEW, PENDING REVIEW ***" if (family.__name__.rsplit(".", 1)[-1], variant) in NEW_PENDING_REVIEW else "(existing)"

    print("=" * 90)
    print(f"{task.task_id}  {tag}")
    print("=" * 90)
    print(f"family:         {task.family}")
    print(f"full_registry:  {sorted(task.full_tool_registry)}")
    print(f"initial_prompt: {task.initial_prompt!r}")
    print()
    print("phases:")
    for phase in task.phases:
        print(f"  - {phase.name}")
        print(f"      required_tools:   {sorted(phase.required_tools)}")
        print(f"      revocable_after:  {sorted(phase.revocable_after)}")
        print(f"      success_predicate: {_clean_lambda_source(phase.success_predicate)}")
    print()
    print(f"task_success_criteria: {_clean_lambda_source(gt.task_success_criteria)}")
    print()


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    families = [f for f in FAMILIES if only is None or f.__name__.rsplit(".", 1)[-1] == only]
    if not families:
        print(f"No family named {only!r}. Choices: {[f.__name__.rsplit('.', 1)[-1] for f in FAMILIES]}")
        return

    total = 0
    for family in families:
        for variant in family.VARIANTS:
            print_instance(family, variant)
            total += 1
    print(f"Printed {total} instance(s).")


if __name__ == "__main__":
    main()
