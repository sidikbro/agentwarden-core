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


def build_stac_matched_s0_pairs(data_path: str | Path) -> tuple[list[S0Pair], dict[str, int]]:
    """Matched-negative variant of `build_stac_s0_pairs`, for gate 3 only
    (docs/v2/A4_MULTITURN_SPEC_v0.2.md §13 step 3, the follow-up re-run
    requested after the first, unmatched gate-3 result). Matching
    requirement: same task, same tool, and the matched tool's use must
    sit at the position directly compared against the final step (i.e.
    the benign candidate is still "the last executed call," and this
    construction only keeps cases where that last executed call happens
    to share the final malicious step's own tool name).

    Confirmed directly against the real 483-case file before writing
    this: the final malicious tool reappears among a case's own
    already-executed calls in only 30 of 471 cases with history (6.4%),
    and in 29 of those 30 it is specifically the LAST executed call (so
    "same tool" and "same compared position" coincide without forcing
    anything); the remaining 1 case has the matching tool earlier in the
    history but not last, so same-tool and same-position can't both be
    satisfied there and it is excluded rather than relaxed. For the
    other 441 cases with history, STAC's own construction simply never
    revisits the final step's tool earlier in that same case -- there is
    no within-task, same-tool matched negative for them in the
    benchmark's own data, and none is approximated. Returns (pairs,
    counts) where `counts` breaks down exactly where every one of the
    483 cases went.
    """
    cases = load_stac_cases(data_path)
    pairs: list[S0Pair] = []
    counts = {
        "total_cases": len(cases),
        "no_executed_tool_calls": 0,
        "no_same_tool_match": 0,
        "same_tool_but_not_last_position": 0,
        "matched": 0,
    }
    for case in cases:
        tool_calls = [t.tool_call for t in case.turns if t.tool_call is not None]
        if not tool_calls:
            counts["no_executed_tool_calls"] += 1
            continue

        final_step = case.label["malicious_tool_chain"][-1]
        final_tool = final_step["tool_name"]
        executed_tool_names = [c.name for c in tool_calls]

        if final_tool not in executed_tool_names:
            counts["no_same_tool_match"] += 1
            continue
        if tool_calls[-1].name != final_tool:
            counts["same_tool_but_not_last_position"] += 1
            continue

        counts["matched"] += 1
        prefix = tool_calls[:-1]
        benign_call = tool_calls[-1]
        attack_call = ToolCall(name=final_tool, arguments=final_step.get("parameters", {}))
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
    return pairs, counts


def build_stac_length_matched_s0_pairs(data_path: str | Path) -> tuple[list[S0Pair], dict[str, int]]:
    """Length-matched (not tool-matched) negative construction for STAC,
    addressing the index-from-end confound directly at the pair-construction
    level rather than only in arm 0's own feature encoding
    (`benchmark/a4/arms.py::arm0_scores`'s `position_feature` correction).

    The unmatched/tool-matched constructions above both fix `benign_call`
    to "the last executed call in the case's full `interaction_history`,"
    whatever that history's own length happens to be. `attack_call` is
    always `malicious_tool_chain[-1]` -- the final step of a chain of
    length `k = len(malicious_tool_chain)`. These two calls are therefore
    never guaranteed to sit at the same chain position: the attack
    candidate is always "step k of a k-step chain" by construction, while
    the benign candidate's position depends only on how long that
    particular case's executed history happened to be, which has no
    relationship to k.

    This function instead truncates each case's executed history to its
    *own* attack chain's length k and takes the k-th (final) call of that
    truncation as `benign_call`, with the first k-1 calls as the shared
    prefix -- i.e. both `benign_call` and `attack_call` are now "the final
    step of a k-step sequence," matching chain position directly, with no
    claim about matching tool identity (that is the separate, already-
    answered question `build_stac_matched_s0_pairs` tests).

    Returns (pairs, counts). `counts["no_executed_tool_calls"]` and
    `counts["insufficient_history_for_chain_length"]` partition the cases
    that cannot support a length-matched pair at all (zero executed calls,
    or an executed history shorter than its own attack chain's length);
    `counts["matched"]` is how many of the 471 cases with any executed
    history (`build_stac_s0_pairs`'s own pool) support one.
    """
    cases = load_stac_cases(data_path)
    pairs: list[S0Pair] = []
    counts = {
        "total_cases": len(cases),
        "no_executed_tool_calls": 0,
        "insufficient_history_for_chain_length": 0,
        "matched": 0,
    }
    for case in cases:
        tool_calls = [t.tool_call for t in case.turns if t.tool_call is not None]
        if not tool_calls:
            counts["no_executed_tool_calls"] += 1
            continue

        chain = case.label["malicious_tool_chain"]
        k = len(chain)
        if len(tool_calls) < k:
            counts["insufficient_history_for_chain_length"] += 1
            continue

        counts["matched"] += 1
        prefix = tool_calls[: k - 1]
        benign_call = tool_calls[k - 1]
        final_step = chain[-1]
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
    return pairs, counts


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


def build_agentdojo_matched_s0_pairs(
    suite_version: str = DEFAULT_SUITE_VERSION,
    suite_names: list[str] | None = None,
) -> tuple[list[S0Pair], dict[str, int]]:
    """Matched-negative variant of `build_agentdojo_s0_pairs`, for gate 3
    only. Matching requirement: same task (the UserTask's own session),
    same position (final call vs. final call -- already true of both
    `build_agentdojo_s0_pairs` and this function), and -- the actual
    change here -- the SAME TOOL for both the benign and attack call,
    rather than whichever injection task round-robin happened to assign.

    Confirmed directly against the installed package: of the 97
    UserTasks with a non-empty ground truth, 38 (39.2%) have at least
    one same-suite InjectionTask whose own final call uses the identical
    tool. The other 59 have no same-tool injection anywhere in their
    suite and are excluded -- not paired with a different tool and
    called "matched" anyway. Where more than one same-tool injection
    exists for a task, the first by sorted injection id is used,
    deterministically, not round-robin (round-robin was the source of
    the tool mismatch this function exists to remove).
    """
    cases = load_agentdojo_cases(suite_version=suite_version, suite_names=suite_names)
    pairs: list[S0Pair] = []
    counts = {"total_user_tasks": 0, "no_ground_truth": 0, "no_same_tool_injection": 0, "matched": 0}

    injections_by_suite: dict[str, list[dict]] = {}
    for case in cases:
        injections_by_suite.setdefault(case.label["suite"], case.label["injection_goals"])

    for case in cases:
        counts["total_user_tasks"] += 1
        tool_calls = [t.tool_call for t in case.turns]
        if not tool_calls:
            counts["no_ground_truth"] += 1
            continue
        prefix = tool_calls[:-1]
        benign_call = tool_calls[-1]
        final_tool = benign_call.name

        suite_injections = injections_by_suite[case.label["suite"]]
        same_tool_injections = sorted(
            (
                g
                for g in suite_injections
                if g["ground_truth_calls"] and g["ground_truth_calls"][-1]["function"] == final_tool
            ),
            key=lambda g: g["injection_task_id"],
        )
        if not same_tool_injections:
            counts["no_same_tool_injection"] += 1
            continue

        counts["matched"] += 1
        last_gt = same_tool_injections[0]["ground_truth_calls"][-1]
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
    return pairs, counts
