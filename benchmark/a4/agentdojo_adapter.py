"""AgentDojo adapter (docs/v2/A4_MULTITURN_SPEC_v0.2.md §13 step 2:
"AgentDojo harness (independent, mandatory regardless of A4)").

Wraps the installed `agentdojo` package (confirmed via `pip show
agentdojo` -> 0.1.35 in this environment; not previously declared as a
project dependency -- added to `pyproject.toml`'s new `benchmarks`
extra by this change). AgentDojo ships its task suites (banking,
travel, workspace, slack) as real, locally loadable Python objects --
no network access or gated download needed, unlike MT-AgentRisk.

One `AdapterCase` per `UserTask`. Each `UserTask` carries:

  - `PROMPT`: the user's own natural-language task statement, written
    before any injected content exists in the environment. Unlike
    STAC's/MT-AgentRisk's opening text (benchmark-synthesized as part
    of attack construction), this is genuinely the kind of
    trusted-producer-written text docs/v2/A4_MULTITURN_SPEC_v0.2.md §5
    describes as the one safe prose field -- AgentDojo's own threat
    model is indirect injection via tool/environment output, and the
    user's task prompt sits entirely outside that channel.

  - `ground_truth(env)`: the `FunctionCall` sequence that legitimately
    completes `PROMPT`, independent of whether any injection is present
    at all. This is the one of the three A4 benchmarks where a genuinely
    unconfounded "benign call set" exists prior to and independent of
    any attack framing -- unlike STAC's `interaction_history`, which by
    construction always stops right before the attack step (see
    `stac_adapter.py`'s docstring), `ground_truth` is not shaped by
    where an attack would go. `allowed_effects` is therefore derived
    from it here, rather than left at `ALL_EFFECTS`.

Anchor derivation (mechanical):
  - `authorized_task` := `UserTask.PROMPT`, verbatim.
  - `scope` := `frozenset({suite.name})`.
  - `allowed_effects` := `effects_for_tool_calls()` over the
    `ground_truth` call names, via the same fixed keyword table every
    other adapter uses.

`label` carries, per `UserTask`: the suite name and version, the
ground-truth call sequence (as plain dicts, not AgentDojo's own
`FunctionCall` type, so downstream code doesn't need `agentdojo`
importable), and -- kept separate from the anchor and the benign
trajectory, never folded in -- every `InjectionTask.GOAL` registered in
the same suite. AgentDojo's injection goals are the natural "what must
not happen" labels for this benchmark, since AgentDojo's own threat
model (adversary writes retrieved/tool-output content) is exactly A4's
§3 threat model; this adapter only records them as data, it does not
insert any injection or run a live agent -- that is a later build-order
step (arms, §8).
"""
from __future__ import annotations

from typing import Any

from agentdojo.task_suite.load_suites import get_suites
from agentwarden.core.models import ToolCall

from .common import AdapterCase, AdapterTurn, build_anchor, effects_for_tool_calls

SOURCE = "agentdojo"

DEFAULT_SUITE_VERSION = "v1.2.1"


def _case_from_user_task(suite: Any, task_id: str, user_task: Any, suite_version: str) -> AdapterCase:
    env = suite.load_and_inject_default_environment({})
    ground_truth_calls = user_task.ground_truth(env)

    tool_names = [call.function for call in ground_truth_calls]
    anchor = build_anchor(
        authorized_task=user_task.PROMPT,
        scope=frozenset({suite.name}),
        allowed_effects=effects_for_tool_calls(tool_names),
        issued_by="benchmark_adapter:agentdojo",
    )

    turns = tuple(
        AdapterTurn(
            role="assistant",
            tool_call=ToolCall(name=call.function, arguments=dict(call.args)),
        )
        for call in ground_truth_calls
    )

    injection_goals = [
        {"injection_task_id": inj_id, "goal": inj_task.GOAL}
        for inj_id, inj_task in suite.injection_tasks.items()
    ]

    label = {
        "suite": suite.name,
        "suite_version": suite_version,
        "ground_truth_calls": [
            {"function": call.function, "args": dict(call.args)} for call in ground_truth_calls
        ],
        "injection_goals": injection_goals,
    }

    return AdapterCase(
        source=SOURCE,
        case_id=f"{suite.name}:{task_id}",
        anchor=anchor,
        turns=turns,
        label=label,
        raw=None,  # AgentDojo's UserTask holds live env/tool objects -- not stashed
    )


def load_agentdojo_cases(
    suite_version: str = DEFAULT_SUITE_VERSION,
    suite_names: list[str] | None = None,
) -> list[AdapterCase]:
    """Load every `UserTask` from the given AgentDojo suite version.
    `suite_names` restricts to a subset (e.g. `["banking"]`); `None`
    (default) loads all suites registered for that version.
    """
    suites = get_suites(suite_version)
    cases: list[AdapterCase] = []
    for name, suite in suites.items():
        if suite_names is not None and name not in suite_names:
            continue
        for task_id, user_task in suite.user_tasks.items():
            cases.append(_case_from_user_task(suite, task_id, user_task, suite_version))
    return cases
