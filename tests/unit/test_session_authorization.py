"""Tests for A4 step 1 (docs/v2/A4_MULTITURN_SPEC_v0.1.md §13):
`SessionAuthorization`'s immutability and `build_bounded_summary()`'s
stop-rather-than-fabricate behavior.
"""
from __future__ import annotations

import dataclasses

import pytest

from agentwarden.core.models import Decision, TaskType
from agentwarden.core.session_authorization import (
    AuditLogInsufficientError,
    AuditRecord,
    Effect,
    SessionAuthorization,
    build_bounded_summary,
)


def _make_authorization(**overrides) -> SessionAuthorization:
    defaults = dict(
        authorized_task="triage and fix a failing CI run",
        task_type=TaskType.CODE_EXECUTION,
        scope=frozenset({"repo:agentwarden-core"}),
        allowed_effects=frozenset({Effect.READ, Effect.WRITE}),
        max_sensitivity=2,
        issued_by="harness",
        issued_at=1_700_000_000.0,
    )
    defaults.update(overrides)
    return SessionAuthorization(**defaults)


def test_session_authorization_is_frozen():
    auth = _make_authorization()
    with pytest.raises(dataclasses.FrozenInstanceError):
        auth.authorized_task = "something else"  # type: ignore[misc]


def test_session_authorization_scope_and_effects_are_frozensets():
    auth = _make_authorization()
    assert isinstance(auth.scope, frozenset)
    assert isinstance(auth.allowed_effects, frozenset)
    with pytest.raises(AttributeError):
        auth.scope.add("repo:other")  # type: ignore[attr-defined]


def test_session_authorization_expires_at_defaults_to_none():
    auth = _make_authorization()
    assert auth.expires_at is None


class _StubAuditLogReader:
    """Test double for AuditLogReader -- no concrete implementation exists
    in this codebase yet (see session_authorization.py's module docstring)."""

    def __init__(self, records):
        self._records = records

    def records_for_session(self, session_id):
        return [r for r in self._records if r.session_id == session_id]


def test_build_bounded_summary_raises_rather_than_fabricates():
    records = [
        AuditRecord(session_id="s1", tool_name="read", decision=Decision.ALLOW, latency_ms=12.0),
        AuditRecord(session_id="s1", tool_name="read", decision=Decision.ALLOW, latency_ms=9.0),
        AuditRecord(session_id="s1", tool_name="write_file", decision=Decision.BLOCK, latency_ms=5.0),
        AuditRecord(session_id="s2", tool_name="exec", decision=Decision.BLOCK, latency_ms=3.0),
    ]
    reader = _StubAuditLogReader(records)

    with pytest.raises(AuditLogInsufficientError) as excinfo:
        build_bounded_summary("s1", reader)

    error = excinfo.value
    for blocked_field in (
        "scopes_opened",
        "verifications",
        "effect_classes_used",
        "trust_levels_touched",
        "out_of_scope_resource_count",
        "elapsed_turns",
    ):
        assert blocked_field in str(error), f"{blocked_field} should be named as blocked"

    # call_counts is the one field build_bounded_summary can genuinely
    # compute from AuditRecord -- correctly isolated to session "s1".
    assert dict(error.partial_call_counts) == {"read": 2, "write_file": 1}


def test_build_bounded_summary_never_returns_a_summary():
    reader = _StubAuditLogReader([])
    with pytest.raises(AuditLogInsufficientError):
        build_bounded_summary("empty-session", reader)
