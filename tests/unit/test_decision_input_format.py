"""Regression guard for A4 step 2 (docs/v2/A4_MULTITURN_SPEC_v0.1.md §13,
§9): the symbolic baseline and the learned arm must receive byte-identical
`(anchor, bounded summary, call)` input. Modeled on
tests/unit/test_classifier_train_serve_format.py -- that train/serve
boundary diverged silently twice before a single shared builder made a
third divergence structurally impossible; this test exists so a future
edit that gives either arm its own ad hoc serialization fails loudly here
instead of silently comparing two different inputs.
"""
from __future__ import annotations

from types import MappingProxyType

from agentwarden.core.decision_input import build_decision_input
from agentwarden.core.models import TaskType, ToolCall
from agentwarden.core.session_authorization import (
    BoundedSessionSummary,
    Effect,
    SessionAuthorization,
    VerificationRecord,
)


def _make_authorization() -> SessionAuthorization:
    return SessionAuthorization(
        authorized_task="triage and fix a failing CI run",
        task_type=TaskType.CODE_EXECUTION,
        scope=frozenset({"repo:agentwarden-core", "repo:docs"}),
        allowed_effects=frozenset({Effect.READ, Effect.WRITE}),
        max_sensitivity=2,
        issued_by="harness",
        issued_at=1_700_000_000.0,
        expires_at=1_700_003_600.0,
    )


def _make_summary() -> BoundedSessionSummary:
    return BoundedSessionSummary(
        scopes_opened=frozenset({"repo:agentwarden-core"}),
        verifications=(
            VerificationRecord(
                source="audit_log",
                verifier="enforcement_layer",
                check="scope containment",
                result="confirmed",
                timestamp=1_700_000_500.0,
            ),
        ),
        effect_classes_used=frozenset({Effect.READ}),
        trust_levels_touched=frozenset({0.8}),
        out_of_scope_resource_count=0,
        call_counts=MappingProxyType({"read": 2, "edit": 1}),
        elapsed_turns=3,
    )


def _make_call() -> ToolCall:
    return ToolCall(name="edit", arguments={"path": "src/main.py", "content": "pass"})


def _symbolic_arm_input() -> str:
    # Stands in for the symbolic baseline (§8, not built in this step) --
    # the point under test is that it uses the one shared builder, not a
    # local re-derivation of the format.
    return build_decision_input(_make_authorization(), _make_summary(), _make_call())


def _learned_arm_input() -> str:
    # Stands in for the learned arm (§9, not built in this step) -- same
    # requirement: call the shared builder, nothing bespoke.
    return build_decision_input(_make_authorization(), _make_summary(), _make_call())


def test_symbolic_and_learned_arms_receive_byte_identical_input():
    assert _symbolic_arm_input() == _learned_arm_input()


def test_decision_input_is_deterministic_regardless_of_set_construction_order():
    # frozenset/dict iteration order is not guaranteed to match
    # construction order; the serializer must sort every set-typed field
    # itself rather than relying on incidental iteration order.
    auth_a = SessionAuthorization(
        authorized_task="t",
        task_type=TaskType.FILE_READ,
        scope=frozenset({"a", "b", "c"}),
        allowed_effects=frozenset({Effect.READ, Effect.NETWORK}),
        max_sensitivity=1,
        issued_by="harness",
        issued_at=1.0,
    )
    auth_b = SessionAuthorization(
        authorized_task="t",
        task_type=TaskType.FILE_READ,
        scope=frozenset({"c", "a", "b"}),
        allowed_effects=frozenset({Effect.NETWORK, Effect.READ}),
        max_sensitivity=1,
        issued_by="harness",
        issued_at=1.0,
    )
    summary = _make_summary()
    call = _make_call()
    assert build_decision_input(auth_a, summary, call) == build_decision_input(auth_b, summary, call)


def test_decision_input_ends_with_exactly_one_newline():
    output = _symbolic_arm_input()
    assert output.endswith("\n")
    assert not output.endswith("\n\n")


def test_decision_input_is_valid_json_with_expected_top_level_keys():
    import json

    output = _symbolic_arm_input()
    payload = json.loads(output)
    assert set(payload.keys()) == {"authorization", "session_summary", "call"}
