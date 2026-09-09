"""Unit tests for PlaceholderLearnedGovernor (B6's non-trained stand-in).

The property under test throughout: decisions come from tool_description
and SessionState.phase_history, NEVER from tool name. That's the one thing
this placeholder exists to prove is structurally true — see the class's
own module docstring for why (v1's policy learned identity because name
was the only signal available to it).
"""
from __future__ import annotations

from agentwarden.core.models import SessionState
from agentwarden.profiles.placeholder_learned_governor import PlaceholderLearnedGovernor
from benchmark.tool_metadata import TOOL_DESCRIPTIONS


def _governor(min_phases: int = 2) -> PlaceholderLearnedGovernor:
    return PlaceholderLearnedGovernor(TOOL_DESCRIPTIONS, min_phases_for_mutation_trust=min_phases)


class TestNameIndependence:

    def test_two_tools_with_identical_descriptions_get_identical_treatment(self):
        """Directly tests the core property: scoring is a function of
        description text, not the name string attached to it."""
        governor = _governor()
        catalog = {
            "totally_different_name_a": "Read the contents of a source code file.",
            "totally_different_name_b": "Read the contents of a source code file.",
        }
        g = PlaceholderLearnedGovernor(catalog)
        exposed = g.expose("anything", None, SessionState())
        assert ("totally_different_name_a" in exposed) == ("totally_different_name_b" in exposed)

    def test_renaming_a_dangerous_tool_does_not_expose_it(self):
        """The identity-memorization failure mode this class exists to
        avoid: renaming exec_shell to something innocuous-sounding must
        NOT change the outcome, because the description (still dangerous)
        is what's scored, not the name."""
        governor = _governor()
        catalog = {"totally_safe_sounding_name": "Execute an arbitrary shell command with no restrictions."}
        g = PlaceholderLearnedGovernor(catalog)
        assert g.expose("anything", None, SessionState()) == set()

    def test_expose_never_reads_task_type_or_phase_string_content(self):
        """task_type/phase are accepted (interface conformance) but the
        heuristic doesn't string-match against them — passing nonsense
        values must not change anything description/session_state didn't
        already determine."""
        governor = _governor()
        s = SessionState(phase_history=["a", "b"])
        result_1 = governor.expose("research_synth", "search", s)
        result_2 = governor.expose("some_nonsense_type_xyz", "some_nonsense_phase_xyz", s)
        assert result_1 == result_2


class TestDescriptionRiskCategories:

    def test_safe_tools_always_exposed_regardless_of_session_state(self):
        governor = _governor()
        empty_session = SessionState()
        assert "search_web" in governor.expose("research_synth", None, empty_session)
        assert "read_code" in governor.expose("repo_triage", None, empty_session)

    def test_dangerous_tools_never_exposed_regardless_of_session_state(self):
        governor = _governor()
        long_session = SessionState(phase_history=["a", "b", "c", "d", "e"])
        exposed = governor.expose("anything", None, long_session)
        assert "exec_shell" not in exposed
        assert "delete_file" not in exposed

    def test_mutating_tools_denied_early_in_session(self):
        governor = _governor(min_phases=2)
        early_session = SessionState(phase_history=["search"])   # only 1 phase so far
        exposed = governor.expose("research_synth", "send", early_session)
        assert "send_email" not in exposed

    def test_mutating_tools_exposed_once_trust_threshold_reached(self):
        governor = _governor(min_phases=2)
        late_session = SessionState(phase_history=["search", "fetch", "analyze"])   # 3 phases
        exposed = governor.expose("research_synth", "send", late_session)
        assert "send_email" in exposed

    def test_get_always_block_returns_dangerous_category(self):
        governor = _governor()
        always_block = governor.get_always_block(None)
        assert "exec_shell" in always_block
        assert "delete_file" in always_block
        assert "search_web" not in always_block


class TestSessionStatePurity:

    def test_expose_is_pure_given_identical_session_state(self):
        governor = _governor()
        s = SessionState(phase_history=["a", "b"])
        assert governor.expose("research_synth", "send", s) == governor.expose("research_synth", "send", s)

    def test_phase_history_length_is_what_matters_not_content(self):
        """The placeholder's heuristic reads len(phase_history), not
        which phases specifically occurred -- documented simplification,
        tested so it doesn't silently change."""
        governor = _governor(min_phases=2)
        s1 = SessionState(phase_history=["a", "b"])
        s2 = SessionState(phase_history=["totally", "different"])
        assert governor.expose("x", "send", s1) == governor.expose("x", "send", s2)
