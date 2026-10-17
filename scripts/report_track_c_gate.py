"""Run the Track C degeneracy gate (benchmark/degeneracy_gate.py) against
PlaceholderLearnedGovernor, across every phase of every task family.

This is expected to FAIL — the placeholder is explicitly not a trained
policy (see its own module docstring) and this script exists to prove the
gate actually catches the specific confound
docs/v2/EXPERIMENTAL_PLAN_v0.2.md §3b calls out, not to certify B6.

Usage: python3 -m scripts.report_track_c_gate
"""
from __future__ import annotations

from agentwarden.core.models import SessionState
from agentwarden.profiles.placeholder_learned_governor import PlaceholderLearnedGovernor
from benchmark.degeneracy_gate import run_track_c_gate
from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth
from benchmark.tool_metadata import TOOL_DESCRIPTIONS

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]


def build_catalog() -> dict[str, str]:
    catalog: dict[str, str] = {}
    for family in FAMILIES:
        for tool in family.FULL_TOOL_REGISTRY:
            catalog[tool] = TOOL_DESCRIPTIONS[tool]
    return catalog


def build_contexts(catalog: dict[str, str]) -> list:
    """One context per (family, phase), with phase_history built up
    progressively — the shape PlaceholderLearnedGovernor actually
    conditions on (see benchmark/baselines.py::b6_exposure_fn)."""
    contexts = []
    for family in FAMILIES:
        history: list[str] = []
        for phase in family.phases_for("v1"):
            history.append(phase.name)
            contexts.append((
                family.make_task("v1").family,
                phase.name,
                SessionState(phase_history=list(history)),
                set(phase.required_tools),
            ))
    return contexts


def make_governor(catalog: dict[str, str]) -> PlaceholderLearnedGovernor:
    return PlaceholderLearnedGovernor(tool_catalog=catalog)


def main() -> None:
    catalog = build_catalog()
    contexts = build_contexts(catalog)

    print(f"Catalog: {len(catalog)} tools across {len(FAMILIES)} families")
    print(f"Contexts probed: {len(contexts)} (family, phase) pairs")
    print()

    result = run_track_c_gate(make_governor, catalog, contexts)
    print(result.report())
    print()
    print("Gate outcome:", "PASS -- B6 numbers may be reported" if result.passed
          else "FAIL -- B6 numbers must not be reported until this passes")


if __name__ == "__main__":
    main()
