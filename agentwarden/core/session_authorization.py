"""A4 step 1 (docs/v2/A4_MULTITURN_SPEC_v0.1.md §13): `SessionAuthorization`
(§3) and the bounded-summary builder (§4(b)). Nothing else from the spec --
no symbolic baseline, no pair authoring, no training.

`SessionAuthorization` has no audit-log dependency: it is set once, at
session start, by a trusted producer (§3), so it is implemented in full.

The bounded-summary builder is a different story. §4(b) requires it to read
*only* "the enforcement layer's audit log" -- never tool output, never
conversation text, never agent reasoning -- and the spec is explicit that
if the audit log can't currently supply a field, the right move is to say
so and stop, not to source it from somewhere else (e.g. the in-memory
`GovernanceContext`/`SessionState` objects that happen to be nearby).

Checked directly before writing this: `agentwarden/core/audit.py`'s
`AuditLogger.log_pipeline_result()` is a single `logger.info(...)` call per
decision, logging only `session_id`, `tool_name`, `decision`, and
`latency_ms`. It is not a persisted, queryable, session-keyed store --
there is nothing in this codebase a builder could query by `session_id`.
This is the exact gap `docs/v2/provenance_representation.md` already
documented ("Building a real queryable audit store is therefore a
prerequisite ... not a detail inside it") in the context of a single
verification field; A4's bounded summary needs six more fields on top of
that, and inherits the same blocker.

`AuditRecord` below is deliberately NOT a wishful schema -- it mirrors
exactly what `AuditLogger.log_pipeline_result()` actually logs today, so
that whatever `build_bounded_summary()` can or can't compute is a direct,
checkable consequence of that one function's real content, not a guess.
`AuditLogReader` is the queryable interface `provenance_representation.md`
says is a prerequisite; no concrete implementation of it exists in this
codebase, so `build_bounded_summary()` cannot be exercised against real
production data yet (tests use a stub).

Result: of the seven §4(b) fields, `call_counts` is the one this function
can genuinely compute from what `AuditRecord` carries -- implemented for
real below, not stubbed -- once something actually implements
`AuditLogReader` against a real store. The other six are blocked, each
for a stated reason, and `build_bounded_summary()` raises
`AuditLogInsufficientError` rather than returning a `BoundedSessionSummary`
with fabricated or silently-redefined fields. See that exception's
message for the itemized report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from agentwarden.core.models import Decision, TaskType


class Effect(str, Enum):
    """§3's `allowed_effects` vocabulary and §4(b)'s `effect_classes_used`
    vocabulary -- the same five values, deliberately kept as one enum so
    the two fields can never drift to different vocabularies."""

    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    EXEC = "exec"
    DELEGATE = "delegate"


@dataclass(frozen=True)
class SessionAuthorization:
    """§3. Set once, at session start, by a trusted producer -- the
    operator, the harness, or an authenticated task dispatcher. Never
    inferred from conversation, never written by the agent or by tool
    output. `frozen=True` enforces "immutable for the session's lifetime"
    at the type level: any attempt to reassign a field raises
    `dataclasses.FrozenInstanceError`. `scope` and `allowed_effects` are
    `frozenset`, not `set` -- a frozen dataclass only blocks reassigning an
    attribute, not mutating a mutable value already in it, so a plain
    `set` would leave a hole in the immutability this type exists to
    guarantee.

    A change to any field requires a **new** `SessionAuthorization`
    instance, emitted by the enforcement layer as a logged authorization
    event (§3) -- not an edit to this one. Constructing that event is out
    of scope for this step.
    """

    authorized_task: str
    task_type: TaskType
    scope: frozenset[str]
    allowed_effects: frozenset[Effect]
    max_sensitivity: int
    issued_by: str
    issued_at: float
    expires_at: float | None = None


@dataclass(frozen=True)
class VerificationRecord:
    """Structured provenance record, per `docs/v2/minimal_pair_probe_spec.md`'s
    revised design and `docs/v2/provenance_representation.md`'s constraint:
    populated only from the enforcement layer's own audit log, never from
    tool output or model-generated text. Not populated by this step --
    `verifications` is one of the six blocked §4(b) fields -- defined here
    only so the target shape exists for later use."""

    source: str
    verifier: str
    check: str
    result: str
    timestamp: float


@dataclass(frozen=True)
class BoundedSessionSummary:
    """§4(b). Fixed-size regardless of session length: every field is
    either a count, a bounded set of *distinct* values seen so far, or a
    fixed-arity mapping keyed by a bounded vocabulary (tool names) --
    never a growing list of raw events. `call_counts` is a
    `MappingProxyType` rather than a plain `dict` for the same reason the
    two fields above are `frozenset`: this is a derived snapshot, not
    something a caller should be able to mutate in place.
    """

    scopes_opened: frozenset[str]
    verifications: tuple[VerificationRecord, ...]
    effect_classes_used: frozenset[Effect]
    trust_levels_touched: frozenset[float]
    out_of_scope_resource_count: int
    call_counts: Mapping[str, int]
    elapsed_turns: int


@dataclass(frozen=True)
class AuditRecord:
    """Exactly what `AuditLogger.log_pipeline_result()` (agentwarden/core/
    audit.py) actually logs per decision today: `session_id`, `tool_name`,
    `decision`, `latency_ms`. Nothing more -- adding fields here that
    aren't actually written by that function would be the "source it from
    elsewhere" move the spec says not to make."""

    session_id: str
    tool_name: str
    decision: Decision
    latency_ms: float | None


class AuditLogReader(Protocol):
    """The queryable interface `docs/v2/provenance_representation.md`
    describes as a prerequisite ("the audit log is the right *shape* of
    candidate source ... but it does not currently exist in a form that
    satisfies the constraint"). No concrete implementation of this
    protocol exists in this codebase -- `AuditLogger` writes to Python's
    `logging` module, which nothing here reads back from by `session_id`.
    """

    def records_for_session(self, session_id: str) -> Sequence[AuditRecord]: ...


class AuditLogInsufficientError(RuntimeError):
    """Raised by `build_bounded_summary()` instead of returning a
    `BoundedSessionSummary` with fabricated or silently-redefined fields.
    `partial_call_counts` carries the one computation this function could
    actually perform, for callers that want to inspect it, but the
    function does not return a `BoundedSessionSummary` -- "stop", per the
    spec's instruction, not "return something partial and call it done".
    """

    def __init__(self, message: str, partial_call_counts: Mapping[str, int]):
        super().__init__(message)
        self.partial_call_counts = partial_call_counts


_BLOCKED_FIELD_REASONS = """\
- scopes_opened: BLOCKED. No resource/scope concept exists anywhere in the
  current data model (GovernanceContext, GovernanceDecision, ToolCall) or
  audit trail -- AuditRecord has no field for which resource a call
  touched, and AuditLogger.log_pipeline_result() never logs one.
- verifications: BLOCKED. No structured provenance/verification record
  (source, verifier, check, result, timestamp) exists on GovernanceDecision
  or anywhere in the audit trail. This is the exact gap
  docs/v2/provenance_representation.md already documented: "Building a
  real queryable audit store is therefore a prerequisite for this
  feature, not a detail inside it."
- effect_classes_used: BLOCKED. No effect-class taxonomy ({read, write,
  network, exec, delegate}) is recorded anywhere in the audit trail;
  config/tools.yaml's risk_level (0-4) is a different, non-effect-class
  scale and is not a substitute.
- trust_levels_touched: BLOCKED. GovernanceContext.trust_level exists as a
  float, but AuditLogger.log_pipeline_result() never writes it to the
  audit log -- only session_id, tool_name, decision, and latency_ms are
  logged. Reading it from GovernanceContext directly would be "sourcing
  it from elsewhere", not from the audit log.
- out_of_scope_resource_count: BLOCKED. Depends on the scope concept
  above, which does not exist.
- elapsed_turns: BLOCKED. The audit log only records governed tool-call
  decisions, not conversational turns in general -- a turn with no tool
  call leaves no audit record. Approximating it as len(records) would
  silently redefine the field as "tool-call count", a smaller quantity
  already captured correctly by call_counts, under the name of a
  different field. Not done.

call_counts is the one field this function can genuinely compute from
what AuditRecord carries today (a tool_name tally) -- see
partial_call_counts on this exception. Even that requires a queryable,
session-keyed store to read records back from, and none exists:
AuditLogger.log_pipeline_result() (agentwarden/core/audit.py) is a single
logger.info() call, not a persisted store, so no concrete
AuditLogReader implementation exists in this codebase to pass here in
production. The `audit_log` argument above was a test double.

Root cause, stated once: there is no persisted, queryable audit store in
this codebase at all right now (confirmed by reading agentwarden/core/
audit.py directly) -- the exact prerequisite
docs/v2/provenance_representation.md already flagged before any
verification-history field could be designed. Five of the six blocked
fields above would stay blocked even if that store existed, because the
data they need (scope, effect class, verification record, sensitivity
touch) isn't captured by any object already flowing through the pipeline
(GovernanceContext, GovernanceDecision, ToolCall) for a store to persist
in the first place."""


def build_bounded_summary(session_id: str, audit_log: AuditLogReader) -> BoundedSessionSummary:
    """Attempt §4(b)'s bounded summary from `audit_log` alone. Always
    raises `AuditLogInsufficientError` -- see that exception's message,
    reproduced in `_BLOCKED_FIELD_REASONS`, for exactly which of the seven
    fields are blocked and why. Never falls back to
    `GovernanceContext`/`SessionState` or any other in-memory source: per
    §4(b), this function reads *only* the audit log, and when the audit
    log can't supply a field, the correct behavior is to stop, not to
    widen the source.
    """
    records = list(audit_log.records_for_session(session_id))

    call_counts: dict[str, int] = {}
    for record in records:
        call_counts[record.tool_name] = call_counts.get(record.tool_name, 0) + 1

    raise AuditLogInsufficientError(
        "build_bounded_summary: the enforcement layer's audit log cannot "
        "currently supply 6 of the 7 BoundedSessionSummary fields required "
        "by docs/v2/A4_MULTITURN_SPEC_v0.1.md §4(b):\n\n"
        + _BLOCKED_FIELD_REASONS,
        partial_call_counts=MappingProxyType(call_counts),
    )
