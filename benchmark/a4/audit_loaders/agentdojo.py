"""AgentDojo loader for the shortcut audit -- the already-measured
reference point (`docs/v2/RECONCILED_STATE_v0.2.md` §12/§12a).

**Attack/benign definition and extraction, stated explicitly:** `benign`
is EVERY call in every UserTask's own `ground_truth` sequence (not just
the final call, unlike the strict 1:1 minimal pair
`s0_inputs.py::build_agentdojo_s0_pairs` uses for the validity gates/arm
0/arm 1). `attack` is, per suite, the final ground-truth call of every
InjectionTask registered for that suite with a non-empty ground truth.
`task_id` is the **suite name**, not the individual UserTask id -- the
matched-negative question this benchmark already answered
(`build_agentdojo_matched_s0_pairs`: "38 of 97 UserTasks have at least
one SAME-SUITE InjectionTask whose own final call uses the identical
tool") is inherently suite-scoped, since the real threat model pairs any
UserTask in a suite with any of that suite's own injections, not a fixed
1:1 assignment.

This is a deliberately different, broader construction than the 1:1
minimal pair used for the earlier gate/arm measurements -- reported
alongside, not instead of, those numbers in the write-up.

Requires the `agentdojo` package (`pip install agentdojo>=0.1.35`,
already in this project's `benchmarks` extra) -- no credentials, no
terms-of-use form.
"""
from __future__ import annotations

from ..agentdojo_adapter import load_agentdojo_cases
from ..shortcut_audit import AuditRecord, BenchmarkNotObtainedError


def load_agentdojo() -> list[AuditRecord]:
    try:
        cases = load_agentdojo_cases()
    except ImportError as e:
        raise BenchmarkNotObtainedError(f"agentdojo package not installed ({e}); pip install agentdojo>=0.1.35") from e

    records = []
    injections_by_suite: dict[str, list[dict]] = {}
    for case in cases:
        injections_by_suite.setdefault(case.label["suite"], case.label["injection_goals"])

    for case in cases:
        suite = case.label["suite"]
        tool_calls = [t.tool_call for t in case.turns]
        for call in tool_calls:
            records.append(AuditRecord("AgentDojo", suite, call.name, call.arguments, "benign"))

    for suite, injections in injections_by_suite.items():
        for injection in injections:
            if not injection["ground_truth_calls"]:
                continue
            last = injection["ground_truth_calls"][-1]
            records.append(AuditRecord("AgentDojo", suite, last["function"], last["args"], "attack"))

    return records
