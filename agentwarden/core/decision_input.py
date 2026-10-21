"""A4 step 2 (docs/v2/A4_MULTITURN_SPEC_v0.1.md §13): the single shared
serialization function producing the `(anchor, bounded summary, call)`
decision input, used by both the symbolic baseline and the learned arm
(§9: "Same ... input as the baseline -- identical serialization, no extra
fields. Any input advantage invalidates the comparison.").

Modeled directly on `agentwarden/policies/classifier.py::build_classify_prompt`
-- the ONE place that string is built, called by both training and every
serving backend, after two separate train/serve format bugs at that exact
boundary (see that function's docstring). The risk here is the same shape:
if the symbolic baseline and the learned arm each grew their own
"serialize the anchor+summary+call" code, they could silently diverge the
same way, and a result built on top of that divergence would be comparing
two different inputs while reporting it as one. One function, called by
both arms, makes that structurally impossible instead of relying on
convention to keep two copies in sync.

`tests/unit/test_decision_input_format.py` asserts byte-identical output
across two independent call sites, standing in for "the symbolic baseline"
and "the learned arm" until those are built (out of scope for this step).
"""
from __future__ import annotations

import json
from typing import Any

from agentwarden.core.models import ToolCall
from agentwarden.core.session_authorization import BoundedSessionSummary, SessionAuthorization


def _authorization_to_jsonable(authorization: SessionAuthorization) -> dict[str, Any]:
    return {
        "authorized_task": authorization.authorized_task,
        "task_type": authorization.task_type.value,
        "scope": sorted(authorization.scope),
        "allowed_effects": sorted(e.value for e in authorization.allowed_effects),
        "max_sensitivity": authorization.max_sensitivity,
        "issued_by": authorization.issued_by,
        "issued_at": authorization.issued_at,
        "expires_at": authorization.expires_at,
    }


def _summary_to_jsonable(summary: BoundedSessionSummary) -> dict[str, Any]:
    return {
        "scopes_opened": sorted(summary.scopes_opened),
        "verifications": [
            {
                "source": v.source,
                "verifier": v.verifier,
                "check": v.check,
                "result": v.result,
                "timestamp": v.timestamp,
            }
            # verifications is an ordered tuple (arrival order in the audit
            # log, not a set) -- not re-sorted, unlike the frozenset fields
            # above, since arrival order is itself part of the record.
            for v in summary.verifications
        ],
        "effect_classes_used": sorted(e.value for e in summary.effect_classes_used),
        "trust_levels_touched": sorted(summary.trust_levels_touched),
        "out_of_scope_resource_count": summary.out_of_scope_resource_count,
        "call_counts": dict(sorted(summary.call_counts.items())),
        "elapsed_turns": summary.elapsed_turns,
    }


def _call_to_jsonable(call: ToolCall) -> dict[str, Any]:
    return {
        "tool_name": call.name,
        "arguments": call.arguments,
    }


def build_decision_input(
    authorization: SessionAuthorization,
    summary: BoundedSessionSummary,
    call: ToolCall,
) -> str:
    """The ONE place the `(anchor, bounded summary, call)` decision input
    is serialized. Both the symbolic baseline (§8) and the learned arm
    (§9) must call this, never re-derive the format themselves.

    Deterministic JSON: `sort_keys=True` plus every set-typed field
    pre-sorted into a list before serialization (`json.dumps`'s
    `sort_keys` only orders dict keys, not set contents, and `frozenset`/
    `MappingProxyType` aren't JSON-serializable at all) -- the same input
    must produce the same string on every call, on every machine, which a
    hash-randomized set iteration order would silently break.
    """
    payload = {
        "authorization": _authorization_to_jsonable(authorization),
        "session_summary": _summary_to_jsonable(summary),
        "call": _call_to_jsonable(call),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
