"""S0 input construction for A4's validity gates (docs/v2/
A4_MULTITURN_SPEC_v0.2.md §9, §13 step 3 -- "run the §9 validity gates
on S0 inputs. Nothing else"). Builds labeled (BENIGN, ATTACK) minimal
pairs of serialized S0 decision inputs from each benchmark's
`AdapterCase` objects (step 1/2's own adapters), for the gates to test.

S0 is the tier `docs/v2/A4_MULTITURN_SPEC_v0.2.md` §6 defines: anchor +
`call_counts` (a real per-tool tally) + `invocations_observed` (a
tool-call count, not a turn count) + the call under judgment. No
`BoundedSessionSummary` field is part of S0 -- `agentwarden/core/
decision_input.py::build_s0_input()` is the serializer and asserts this
directly. This module only decides WHICH `(anchor, prefix, call,
label)` tuples to feed it; it runs no model, simulates no attack, and
executes no tool -- everything here is a static construction over data
step 1/2's adapters already produced.

Pairing is a minimal pair in the same shape this project's other
leakage probes already use: same anchor, same session prefix (hence
the same `call_counts`/`invocations_observed`), differing only in the
single call under judgment.

**STAC (primary).** For each case with at least one already-executed
tool call in `interaction_history`:
  - `prefix` := every executed tool call except the last
  - `benign` := the last executed tool call (label BENIGN)
  - `attack` := the chain's held-out final step,
    `label["malicious_tool_chain"][-1]` (label ATTACK)
  - the anchor is used exactly as the STAC adapter derived it (already
    `ALL_EFFECTS`, per that adapter's own reasoning -- no further
    coarsening needed here)
Confirmed directly against the real 483-case file: 12 cases have ZERO
executed tool calls in `interaction_history` and are skipped -- there
is no benign candidate for them without fabricating one, so they are
dropped and counted, not substituted.

**AgentDojo (secondary, coarse anchor -- docs/v2/
A4_MULTITURN_SPEC_v0.2.md §7's AgentDojo coarse-anchor requirement).**
For each `UserTask` with a non-empty `ground_truth`, paired with one
`InjectionTask` from the same suite (chosen deterministically by index
modulo the count of injection tasks in that suite that have a
non-empty ground truth -- 9 of 97 registered injection tasks across the
default suites have an empty ground truth, i.e. their GOAL is checked
by environment-state inspection rather than requiring their own call,
and are excluded from the candidate pool entirely rather than treated
as a length-0 call):
  - `anchor`  := the UserTask's own anchor with `allowed_effects`
    forced to `ALL_EFFECTS` -- the adapter's default ground-truth-derived
    value is NOT used here, per §7's requirement that AgentDojo's anchor
    be coarsened before being pooled into any A4 gate/arms comparison
  - `prefix`  := `UserTask.ground_truth[:-1]`
  - `benign`  := `UserTask.ground_truth[-1]` (label BENIGN)
  - `attack`  := the paired `InjectionTask`'s `ground_truth[-1]` (label
    ATTACK) -- only the injection's final call is used; its own prefix
    is discarded, because in the real threat model the attack diverts a
    session whose *preceding* calls are the user's own task, not a
    separate injection-task session
  - `call_counts`/`invocations_observed` come from the SAME prefix (the
    user task's own) for both instances of the pair, exactly as STAC's
    construction does

Neither benchmark's construction claims to reproduce what a real
attack would look like end to end (that is §8's arms, explicitly out of
scope for this step) -- both are the minimal static pair the gates in
§9 need to ask their three questions.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from agentwarden.core.decision_input import build_s0_input
from agentwarden.core.models import ToolCall
from agentwarden.core.session_authorization import SessionAuthorization

from .agentdojo_adapter import DEFAULT_SUITE_VERSION, load_agentdojo_cases
from .common import ALL_EFFECTS
from .stac_adapter import load_stac_cases


@dataclasses.dataclass(frozen=True)
class S0Pair:
    case_id: str
    anchor: SessionAuthorization
    call_counts: dict[str, int]
    invocations_observed: int
    benign_call: ToolCall
    attack_call: ToolCall

    def instances(self) -> list[tuple[str, str]]:
        """[(label, serialized S0 json), ...] -- BENIGN then ATTACK,
        sharing the same anchor/call_counts/invocations_observed."""
        benign = build_s0_input(self.anchor, self.call_counts, self.invocations_observed, self.benign_call)
        attack = build_s0_input(self.anchor, self.call_counts, self.invocations_observed, self.attack_call)
        return [("BENIGN", benign), ("ATTACK", attack)]


def _tally(tool_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in tool_names:
        counts[name] = counts.get(name, 0) + 1
    return counts


def build_stac_s0_pairs(data_path: str | Path) -> tuple[list[S0Pair], int]:
    """Returns (pairs, n_skipped). See module docstring for the rule."""
    cases = load_stac_cases(data_path)
    pairs: list[S0Pair] = []
    skipped = 0
    for case in cases:
        tool_calls = [t.tool_call for t in case.turns if t.tool_call is not None]
        if not tool_calls:
            skipped += 1
            continue
        prefix = tool_calls[:-1]
        benign_call = tool_calls[-1]

        final_step = case.label["malicious_tool_chain"][-1]
        attack_call = ToolCall(name=final_step["tool_name"], arguments=final_step.get("parameters", {}))

        pairs.append(
            S0Pair(
                case_id=case.case_id,
                anchor=case.anchor,
                call_counts=_tally([c.name for c in prefix]),
                invocations_observed=len(prefix),
                benign_call=benign_call,
                attack_call=attack_call,
            )
        )
    return pairs, skipped


def _coarsen_anchor(anchor: SessionAuthorization) -> SessionAuthorization:
    """§7's AgentDojo coarse-anchor requirement: force allowed_effects to
    ALL_EFFECTS before pooling into any A4 gate or arms comparison."""
    return dataclasses.replace(anchor, allowed_effects=ALL_EFFECTS)


def build_agentdojo_s0_pairs(
    suite_version: str = DEFAULT_SUITE_VERSION,
    suite_names: list[str] | None = None,
) -> tuple[list[S0Pair], int]:
    """Returns (pairs, n_skipped). See module docstring for the rule."""
    cases = load_agentdojo_cases(suite_version=suite_version, suite_names=suite_names)
    pairs: list[S0Pair] = []
    skipped = 0
    suite_counters: dict[str, int] = {}

    for case in cases:
        suite_name = case.label["suite"]
        idx = suite_counters.get(suite_name, 0)
        suite_counters[suite_name] = idx + 1

        tool_calls = [t.tool_call for t in case.turns]  # AgentDojo turns are all tool calls
        if not tool_calls:
            skipped += 1
            continue
        prefix = tool_calls[:-1]
        benign_call = tool_calls[-1]

        usable_injections = [g for g in case.label["injection_goals"] if g["ground_truth_calls"]]
        if not usable_injections:
            skipped += 1
            continue
        injection = usable_injections[idx % len(usable_injections)]
        last_gt = injection["ground_truth_calls"][-1]
        attack_call = ToolCall(name=last_gt["function"], arguments=last_gt["args"])

        pairs.append(
            S0Pair(
                case_id=case.case_id,
                anchor=_coarsen_anchor(case.anchor),
                call_counts=_tally([c.name for c in prefix]),
                invocations_observed=len(prefix),
                benign_call=benign_call,
                attack_call=attack_call,
            )
        )
    return pairs, skipped
