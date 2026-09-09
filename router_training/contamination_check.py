"""Automated enforcement of docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md §1's
contamination boundary. Every generated/authored example must pass this
before entering any split — not a documentation-only rule.
"""
from __future__ import annotations

from dataclasses import dataclass

from benchmark.tool_metadata import TOOL_DESCRIPTIONS as V2_BENCHMARK_TOOLS
from router_training.schema import TrainingExample

# Names/phrases that must never appear anywhere in a training example —
# catches accidental ATBench-Claw references even though that dataset was
# never pulled into this repo (contribution_boundary.md: off-limits
# entirely, no exceptions).
_FORBIDDEN_SUBSTRINGS = ["atbench", "atbench-claw", "at-bench"]


@dataclass
class ContaminationResult:
    ok: bool
    violations: list[str]


def check_example(ex: TrainingExample) -> ContaminationResult:
    violations: list[str] = []

    # Rule: no (tool_name, description) pair reused from the v2 benchmark's
    # own vocabulary (benchmark/tool_metadata.py).
    v2_desc = V2_BENCHMARK_TOOLS.get(ex.tool_name)
    if v2_desc is not None and v2_desc.strip().lower() == ex.tool_description.strip().lower():
        violations.append(
            f"tool_name={ex.tool_name!r} reuses a v2 benchmark (name, description) pair verbatim"
        )

    # Rule: no ATBench-Claw content anywhere in the text fields.
    haystacks = [ex.tool_name, ex.tool_description, ex.context, ex.reason]
    haystacks += [str(v) for v in ex.arguments.values()]
    blob = " ".join(haystacks).lower()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in blob:
            violations.append(f"forbidden substring {forbidden!r} found in example text")

    # Rule: no label sourced from a model's runtime decision — enforced at
    # the schema level (drafted_by must not name a classifier-lineage
    # model, review_status must not be "pending" for anything claimed as
    # training-ready). Checked structurally, not content-sniffed.
    if ex.source == "hand_authored" and ex.review_status == "pending":
        violations.append("hand_authored example has review_status=pending -- not training-eligible yet")

    return ContaminationResult(ok=not violations, violations=violations)


def check_dataset(examples: list[TrainingExample]) -> ContaminationResult:
    all_violations: list[str] = []
    for i, ex in enumerate(examples):
        result = check_example(ex)
        if not result.ok:
            all_violations.extend(f"[{i}] {v}" for v in result.violations)
    return ContaminationResult(ok=not all_violations, violations=all_violations)
