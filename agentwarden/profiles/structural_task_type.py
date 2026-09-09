"""Structural task-type fallback — deliberately NOT a learned/LLM classifier.

Matches the set of tools a session was offered against each capability
profile's own known vocabulary (from capability_profiles.yaml), by Jaccard
similarity. Returns a task_type only when the best match clears a
conservative confidence threshold; otherwise returns None.

Why not a learned classifier: a learned classifier upstream of D1 would
turn every D1 metric (unnecessary_exposure_ratio, required_tool_denial_rate,
...) into an unattributable mix of classifier error and Governor behavior —
a bad number couldn't be traced to either source. That's a second
experimental axis the project deliberately does not measure through before
the January deadline. This function stays a pure, deterministic mapping
from (offered_tools, profiles) with no learned component, so its own
behavior can be evaluated as a single, well-defined condition rather than
adding a confound to every other condition.

None must be treated by callers as "not enough structural signal to govern
this session via D1" — not as "apply D1 with a low-confidence guess." A
wrong confident guess costs more than an honest "I don't know" (see
CapabilityGovernor's own fail-closed philosophy — over-exposure from a bad
guess is worse than temporarily not gating a session at all).
"""
from __future__ import annotations

from typing import Any

MIN_CONFIDENCE = 0.5   # Jaccard similarity threshold — conservative on purpose


def _profile_vocabulary(profile: dict[str, Any]) -> set[str]:
    vocab: set[str] = set(profile.get("default", []))
    for tools in profile.get("phases", {}).values():
        vocab |= set(tools)
    return vocab


def infer_task_type_structural(
    offered_tools: set[str],
    profiles: dict[str, dict[str, Any]],
    min_confidence: float = MIN_CONFIDENCE,
) -> str | None:
    """(offered_tools, profiles) -> best-matching task_type, or None.

    `profiles` is capability_profiles.yaml's top-level "profiles" mapping
    (task_type -> {phases, default}). The "unknown" fallback profile is
    excluded from matching — its vocabulary is empty by design, so matching
    against it is meaningless.
    """
    if not offered_tools:
        return None

    best_type: str | None = None
    best_score = 0.0

    for task_type, profile in profiles.items():
        if task_type == "unknown":
            continue
        vocab = _profile_vocabulary(profile)
        union = vocab | offered_tools
        if not union:
            continue
        score = len(vocab & offered_tools) / len(union)
        if score > best_score:
            best_score = score
            best_type = task_type

    return best_type if best_score >= min_confidence else None
