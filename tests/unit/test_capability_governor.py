"""Unit tests for CapabilityGovernor (D1: task-type/phase -> tool-set)."""
from __future__ import annotations

import pytest

from agentwarden.core.models import GovernanceContext, SessionState, TaskType
from agentwarden.core.registry import get_registry
from agentwarden.profiles.capability_governor import CapabilityGovernor, CapabilityProfileError
from benchmark.tasks import data_pipeline, incident_response, inbox_workflow, repo_triage, research_synth


@pytest.fixture
def governor() -> CapabilityGovernor:
    return CapabilityGovernor()


class TestExpose:

    def test_known_task_type_and_phase(self, governor):
        assert governor.expose("research_synth", "search", SessionState()) == {"search_web"}
        assert governor.expose("research_synth", "fetch", SessionState()) == {"fetch_url"}
        assert governor.expose("research_synth", "send", SessionState()) == {"send_email"}

    def test_unknown_phase_falls_back_to_default(self, governor):
        assert governor.expose("research_synth", "nonexistent_phase", SessionState()) == set()
        assert governor.expose("summarisation", "nonexistent_phase", SessionState()) == {"read", "read_file"}

    def test_none_phase_falls_back_to_default(self, governor):
        assert governor.expose("summarisation", None, SessionState()) == {"read", "read_file"}

    def test_unknown_task_type_falls_back_to_unknown_profile(self, governor):
        assert governor.expose("some_task_type_not_in_yaml", "search", SessionState()) == set()
        assert governor.expose("some_task_type_not_in_yaml", None, SessionState()) == set()

    def test_expose_is_pure_and_stateless(self, governor):
        """Calling expose() repeatedly with the same args gives the same
        result — no hidden state, no mid-session tracking inside the
        Governor itself. The caller is responsible for diffing across
        calls (see benchmark/runner.py's exposure_fn wiring)."""
        s = SessionState(prior_actions=["search_web"], phase_history=["search"], turn=1)
        first = governor.expose("research_synth", "fetch", s)
        second = governor.expose("research_synth", "fetch", s)
        assert first == second == {"fetch_url"}

    def test_multi_turn_expand_and_revoke_is_caller_diffed(self, governor):
        """Simulates what benchmark/runner.py does: call expose() at each
        phase transition and diff against the previous exposed set."""
        phases_in_order = ["search", "fetch", "analyze", "write", "send"]
        exposed: set[str] = set()
        history: list[tuple[str, set[str], set[str]]] = []   # (phase, added, removed)

        for phase in phases_in_order:
            new_exposed = governor.expose("research_synth", phase, SessionState())
            added = new_exposed - exposed
            removed = exposed - new_exposed
            history.append((phase, added, removed))
            exposed = new_exposed

        # analyze legitimately includes summarize_pdf here: it's the
        # profile's plausible distractor for research_synth (see
        # capability_profiles.yaml), not a bug in this test.
        assert history[0] == ("search", {"search_web"}, set())
        assert history[1] == ("fetch", {"fetch_url"}, {"search_web"})
        assert history[2] == ("analyze", {"extract_facts", "summarize_pdf"}, {"fetch_url"})
        assert history[3] == ("write", {"write_draft"}, {"extract_facts", "summarize_pdf"})
        assert history[4] == ("send", {"send_email"}, {"write_draft"})


class TestAlwaysBlockCrossCheck:

    def test_always_block_tools_are_never_exposed_even_if_profile_lists_them(self, tmp_path):
        """The defensible design property: a YAML authoring error in
        capability_profiles.yaml cannot expose an always-blocked tool."""
        bad_profiles = tmp_path / "capability_profiles.yaml"
        bad_profiles.write_text("""
profiles:
  buggy_task:
    phases:
      oops: [exec, read]   # author accidentally listed a dangerous tool
    default: []
unknown:
  phases: {}
  default: []
""")
        governor = CapabilityGovernor(profiles_file=bad_profiles)
        exposed = governor.expose("buggy_task", "oops", SessionState())
        assert exposed == {"read"}
        assert "exec" not in exposed

    def test_get_always_block_returns_the_cross_check_set(self, governor):
        always_block = governor.get_always_block(GovernanceContext(session_id="t"))
        assert "exec" in always_block
        assert "sudo" in always_block
        # sessions_spawn/subagent/subagents moved to route_to_review (D3
        # approval gate) — conditionally legitimate, no longer hard-blocked
        # at Stage 1. See agentwarden/policies/approval_gate.py.
        assert "sessions_spawn" not in always_block
        assert "subagent" not in always_block
        assert "subagents" not in always_block


class TestFailClosed:

    def test_missing_config_defaults_to_warning_and_empty_exposure(self, tmp_path, caplog):
        missing = tmp_path / "does_not_exist.yaml"
        governor = CapabilityGovernor(profiles_file=missing, strict=False)
        assert governor.expose("research_synth", "search", SessionState()) == set()
        assert governor.expose("anything", None, SessionState()) == set()

    def test_missing_config_raises_when_strict(self, tmp_path):
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(CapabilityProfileError):
            CapabilityGovernor(profiles_file=missing, strict=True)

    def test_unparseable_config_raises_when_strict(self, tmp_path):
        broken = tmp_path / "capability_profiles.yaml"
        broken.write_text("profiles:\n  - this is not: [valid, yaml, :::")
        with pytest.raises(CapabilityProfileError):
            CapabilityGovernor(profiles_file=broken, strict=True)


class TestGetAllowedToolsWrapper:

    def test_delegates_to_expose_via_context_metadata(self, governor):
        ctx = GovernanceContext(
            session_id="t",
            task_type=TaskType.UNKNOWN,
            metadata={"phase": "fetch"},
        )
        # UNKNOWN isn't a key in capability_profiles.yaml -> falls back to "unknown" -> empty.
        assert governor.get_allowed_tools(ctx) == set()

    def test_session_state_passed_through_metadata(self, governor):
        s = SessionState(prior_actions=["search_web"], phase_history=["search"])
        ctx = GovernanceContext(session_id="t", metadata={"phase": "fetch", "session_state": s})
        # Static YAML governor ignores session_state contents, but must not
        # error when one is supplied.
        assert governor.get_allowed_tools(ctx) == set()   # task_type defaults to UNKNOWN


class TestRegistryIntegration:

    def test_registered_and_resolvable_by_name(self):
        registry = get_registry()
        profile = registry.get_profile("capability_governor")
        assert isinstance(profile, CapabilityGovernor)


class TestInferTaskType:

    def test_infers_correct_family_from_full_tool_registry(self, governor):
        task = research_synth.make_task()
        assert governor.infer_task_type(task.full_tool_registry - {"exec_shell", "delete_file"}) == "research_synth"

    def test_no_match_returns_none(self, governor):
        assert governor.infer_task_type({"totally_unrelated_tool"}) is None

    def test_result_feeds_directly_into_expose(self, governor):
        task = repo_triage.make_task()
        inferred = governor.infer_task_type(task.full_tool_registry - {"exec_shell", "delete_file"})
        assert inferred == "repo_triage"
        assert governor.expose(inferred, "read", SessionState()) == {"read_code"}

    def test_overlapping_families_still_resolve_correctly_at_realistic_offer_size(self, governor):
        """fetch_url is shared between research_synth/data_pipeline;
        parse_pdf is shared between research_synth/inbox_workflow. At the
        overlap level actually present in these families' full
        full_tool_registry (each still carries plenty of family-unique
        tools alongside the shared ones), inference is robust — it does
        NOT misfire. This is the honest empirical result, not assumed."""
        for family, variant in [
            (research_synth, "v1"), (research_synth, "v2"),
            (data_pipeline, "v1"), (data_pipeline, "v2"),
            (inbox_workflow, "v1"), (inbox_workflow, "v2"),
        ]:
            task = family.make_task(variant)
            offered = task.full_tool_registry - {"exec_shell", "delete_file"}
            assert governor.infer_task_type(offered) == task.family, (
                f"{task.family}/{variant} misclassified despite realistic overlap"
            )

    def test_real_failure_mode_is_fail_closed_under_pure_overlap(self, governor):
        """The fallback's actual, measurable failure mode: offered ONLY the
        tools two+ families legitimately share, with no family-unique
        signal at all, inference correctly DECLINES (returns None) rather
        than guessing wrong. That's the safe direction — but under the
        benchmark's "fallback" condition (baselines.py), None resolves to
        task_type="unknown", which CapabilityGovernor.expose() maps to an
        empty profile: every tool denied, task fails. A session whose
        offered tools never reveal family-specific intent pays for that
        with total D1 denial under the fallback condition, even though the
        declared condition (same session, task_type known) would succeed."""
        assert governor.infer_task_type({"fetch_url"}) is None
        assert governor.infer_task_type({"fetch_url", "parse_pdf"}) is None


FAMILIES = [research_synth, repo_triage, inbox_workflow, incident_response, data_pipeline]
ALL_INSTANCES = [(family, variant) for family in FAMILIES for variant in family.VARIANTS]


class TestProfilesAreRealisticNotGroundTruthCopies:
    """Regression guard for the opposite property of what this suite used
    to assert. An earlier version of capability_profiles.yaml was a
    mechanical copy of each family's minimum_required_tools, which made B3
    (task-conditioned YAML) score a perfect unnecessary_exposure_ratio=0
    and required_tool_denial_rate=0 on every metric, every family — "B3
    running with the answer key," leaving zero headroom for a learned
    Governor (B6) to demonstrate anything. The rewrite hand-authored a
    realistic-but-imperfect policy instead (see capability_profiles.yaml's
    own comments for the specific mistakes). These tests assert that
    imperfection is still present and measurable — NOT that the profile
    matches ground truth, which is now the wrong thing to assert.
    """

    def test_mismatches_exist_between_profile_and_ground_truth(self, governor):
        mismatches = 0
        for family, variant in ALL_INSTANCES:
            task = family.make_task(variant)
            gt = family.make_ground_truth(variant)
            for phase_name, required in gt.minimum_required_tools.items():
                exposed = governor.expose(task.family, phase_name, SessionState())
                if exposed != required:
                    mismatches += 1
        assert mismatches > 0, (
            "capability_profiles.yaml matches ground truth everywhere again — "
            "this is a headroom regression, not an improvement; B3 would be "
            "running with the answer key. See this file's module docstring."
        )

    def test_some_instances_are_unnecessarily_over_exposed(self, governor):
        """At least one (family, variant, phase) exposes a tool ground
        truth never requires there — the "plausible distractor" direction."""
        found = False
        for family, variant in ALL_INSTANCES:
            task = family.make_task(variant)
            gt = family.make_ground_truth(variant)
            for phase_name, required in gt.minimum_required_tools.items():
                exposed = governor.expose(task.family, phase_name, SessionState())
                if exposed - required:
                    found = True
        assert found, "no instance shows unnecessary exposure — plausible-distractor coverage regressed"

    def test_some_instances_are_denied_a_required_tool(self, governor):
        """At least one (family, variant, phase) fails to expose a tool
        ground truth requires there — the "static author never saw this
        case" direction, matching within-family variation / content
        dependence (research_synth v2, inbox_workflow v2, incident_response
        v2, repo_triage v2)."""
        found = False
        for family, variant in ALL_INSTANCES:
            task = family.make_task(variant)
            gt = family.make_ground_truth(variant)
            for phase_name, required in gt.minimum_required_tools.items():
                exposed = governor.expose(task.family, phase_name, SessionState())
                if required - exposed:
                    found = True
        assert found, "no instance shows denial — within-family-variation coverage regressed"
