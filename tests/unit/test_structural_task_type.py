"""Unit tests for the structural (non-learned) task-type fallback."""
from __future__ import annotations

from agentwarden.profiles.structural_task_type import infer_task_type_structural

PROFILES = {
    "research_synth": {
        "phases": {
            "search": ["search_web"], "fetch": ["fetch_url"],
            "analyze": ["extract_facts"], "write": ["write_draft"], "send": ["send_email"],
        },
        "default": [],
    },
    "repo_triage": {
        "phases": {
            "inspect": ["inspect_repo"], "read": ["read_code"],
            "edit": ["edit_code"], "test": ["run_tests"], "commit": ["commit_changes"],
        },
        "default": [],
    },
    "summarisation": {"phases": {}, "default": ["read", "read_file"]},
    "unknown": {"phases": {}, "default": []},
}


def test_exact_vocabulary_match_infers_correctly():
    offered = {"search_web", "fetch_url", "extract_facts", "write_draft", "send_email"}
    assert infer_task_type_structural(offered, PROFILES) == "research_synth"


def test_different_family_infers_correctly():
    offered = {"inspect_repo", "read_code", "edit_code", "run_tests", "commit_changes"}
    assert infer_task_type_structural(offered, PROFILES) == "repo_triage"


def test_no_overlap_with_any_profile_returns_none():
    offered = {"totally_unrelated_tool_a", "totally_unrelated_tool_b"}
    assert infer_task_type_structural(offered, PROFILES) is None


def test_empty_offered_tools_returns_none():
    assert infer_task_type_structural(set(), PROFILES) is None


def test_partial_overlap_below_threshold_returns_none():
    # one shared tool out of a much larger offered set -- low Jaccard score
    offered = {"search_web", "unrelated_a", "unrelated_b", "unrelated_c", "unrelated_d"}
    assert infer_task_type_structural(offered, PROFILES) is None


def test_partial_overlap_above_threshold_infers():
    # 4/5 of research_synth's vocabulary offered, nothing else -- high Jaccard
    offered = {"search_web", "fetch_url", "extract_facts", "write_draft"}
    assert infer_task_type_structural(offered, PROFILES) == "research_synth"


def test_unknown_profile_never_matched():
    """The "unknown" profile's empty vocabulary must never be picked as a
    best match -- matching an empty set against anything is meaningless,
    not a confident inference."""
    assert infer_task_type_structural({"anything"}, PROFILES) is None


def test_confidence_threshold_is_configurable():
    offered = {"search_web", "unrelated_a", "unrelated_b", "unrelated_c", "unrelated_d"}
    assert infer_task_type_structural(offered, PROFILES, min_confidence=0.1) == "research_synth"
    assert infer_task_type_structural(offered, PROFILES, min_confidence=0.5) is None


def test_ambiguous_tie_prefers_first_seen_deterministically():
    """Two profiles with identical Jaccard scores against the same offered
    set -- the function must not raise or behave randomly; it picks
    whichever it encounters first with a strictly-greater score, which is
    deterministic given a stable-ordered `profiles` dict (Python 3.7+)."""
    tied_profiles = {
        "a": {"phases": {}, "default": ["x", "y"]},
        "b": {"phases": {}, "default": ["x", "y"]},
        "unknown": {"phases": {}, "default": []},
    }
    result = infer_task_type_structural({"x", "y"}, tied_profiles)
    assert result == "a"   # first one encountered with score > previous best
