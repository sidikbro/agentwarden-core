"""Track C degeneracy gate (benchmark/degeneracy_gate.py) — regression
tests. The most important case here is test_placeholder_fails_the_gate:
it locks in that the gate actually catches the known, documented
over-exposure confound (docs/v2/EXPERIMENTAL_PLAN_v0.2.md §3b) rather than
being an aspirational check nobody ever ran against real behavior. Uses
the real cross-family catalog/contexts (not a toy 2-3 tool example) —
the confound only shows up at realistic registry scale, where a
raw-looking "moderate" exposure fraction still means near-100% of what's
exposed is unnecessary relative to any single phase's actual needs.
"""
from __future__ import annotations

from agentwarden.core.base import GovernanceProfile
from agentwarden.core.models import SessionState
from agentwarden.profiles.placeholder_learned_governor import PlaceholderLearnedGovernor
from benchmark.degeneracy_gate import run_track_c_gate
from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth
from benchmark.tool_metadata import TOOL_DESCRIPTIONS

FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]


def _real_catalog() -> dict[str, str]:
    catalog: dict[str, str] = {}
    for family in FAMILIES:
        for tool in family.FULL_TOOL_REGISTRY:
            catalog[tool] = TOOL_DESCRIPTIONS[tool]
    return catalog


def _real_contexts(catalog: dict[str, str]) -> list:
    contexts = []
    for family in FAMILIES:
        history: list[str] = []
        for phase in family.phases_for("v1"):
            history.append(phase.name)
            contexts.append((
                family.make_task("v1").family, phase.name,
                SessionState(phase_history=list(history)), set(phase.required_tools),
            ))
    return contexts


REAL_CATALOG = _real_catalog()
REAL_CONTEXTS = _real_contexts(REAL_CATALOG)

# A synthetic 10-tool catalog for the fabricated degenerate-governor
# tests below — large enough that a fixed-seed shuffle reliably
# decorrelates alias index from original alphabetical rank.
SYNTH_CATALOG = {f"tool_name_{c}": f"description for {c}" for c in "abcdefghij"}
SYNTH_CONTEXT = ("some_task", "phase1", SessionState(), {"tool_name_a"})


class _ExposeEverything(GovernanceProfile):
    name = "expose_everything"

    def __init__(self, catalog):
        self._catalog = catalog

    def expose(self, task_type, phase, session_state):
        return set(self._catalog)

    def get_always_block(self, context):
        return set()


class _ExposeNothing(GovernanceProfile):
    name = "expose_nothing"

    def __init__(self, catalog):
        self._catalog = catalog

    def expose(self, task_type, phase, session_state):
        return set()

    def get_always_block(self, context):
        return set()


class _KeysOnAlphabeticalRank(GovernanceProfile):
    """Deliberately violates the G3 property in a subtle way: exposes
    based on the tool's ALPHABETICAL POSITION among the catalog's names,
    not its description. A naive rename scheme that assigns aliases in
    sorted order would preserve rank and incorrectly pass this — the gate
    must shuffle before assigning aliases to catch it."""
    name = "keys_on_alphabetical_rank"

    def __init__(self, catalog):
        self._catalog = catalog

    def expose(self, task_type, phase, session_state):
        if not self._catalog:
            return set()
        return {sorted(self._catalog)[0]}

    def get_always_block(self, context):
        return set()


def test_placeholder_fails_the_gate():
    """Locks in the documented finding: PlaceholderLearnedGovernor is not
    task-scoped enough to pass not_expose_everything at realistic
    registry scale. It is NOT expected to fail g3_rename_invariant (it
    was built to avoid that specific failure mode, and does — it never
    reads tool_call.name) — only the breadth check should fail."""
    result = run_track_c_gate(
        lambda catalog: PlaceholderLearnedGovernor(tool_catalog=catalog),
        REAL_CATALOG,
        REAL_CONTEXTS,
    )
    assert result.passed is False
    assert result.checks["not_expose_everything"] is False
    assert result.checks["not_expose_nothing"] is True
    assert result.checks["g3_rename_invariant"] is True


def test_expose_everything_fails_that_check():
    result = run_track_c_gate(_ExposeEverything, SYNTH_CATALOG, [SYNTH_CONTEXT])
    assert result.passed is False
    assert result.checks["not_expose_everything"] is False


def test_expose_nothing_fails_that_check():
    result = run_track_c_gate(_ExposeNothing, SYNTH_CATALOG, [SYNTH_CONTEXT])
    assert result.passed is False
    assert result.checks["not_expose_nothing"] is False


def test_rank_keyed_governor_fails_g3():
    result = run_track_c_gate(_KeysOnAlphabeticalRank, SYNTH_CATALOG, [SYNTH_CONTEXT])
    assert result.checks["g3_rename_invariant"] is False
