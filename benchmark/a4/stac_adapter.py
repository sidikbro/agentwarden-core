"""STAC adapter (docs/v2/A4_MULTITURN_SPEC_v0.2.md §13 step 1).

Loads the real STAC benchmark (Amazon Science / UC Berkeley,
arXiv:2509.25624, github.com/amazon-science/MultiTurnAgentAttack --
archived/read-only as of 2026-07-10 but still clonable) from its own
`data/STAC_benchmark_data.json`. Confirmed directly against that file
(cloned and inspected this session, not taken from the paper text): a
JSON list of 483 records, each with keys `id`, `generation_config`
(`dataset`, `environment`, `failure_mode`, ...), `attack_plan`
(`attack_goal`, `verified_tool_chain` -- the FULL chain, including the
malicious final step), `interaction_history` (user / assistant
[tool_calls] / tool turns), `planner_history` (the predicted final
attack prompt).

Two confirmed, non-obvious things about the real file that shape this
adapter:

1. `function.arguments` inside each `tool_calls` entry is JSON-encoded
   TWICE (a JSON string whose decoded value is itself a JSON string) --
   verified by loading a real record and checking the type at each
   decode step, not assumed from the schema's appearance.

2. `interaction_history` always stops immediately BEFORE the candidate
   malicious step is attempted; the held-out next turn is
   `planner_history[-1]["predicted_attack_prompt"]`, and the tool that
   turn would invoke is `attack_plan["verified_tool_chain"][-1]`. This
   is a structural property of how STAC stores every case, not
   something that varies per case.

That second fact is why this adapter's anchor uses `ALL_EFFECTS`
instead of deriving `allowed_effects` from the tool calls actually
present in `interaction_history` (which would otherwise be the more
informative, still-mechanical choice AgentDojo's adapter makes from its
own ground truth). Reasoning, stated once: because `interaction_history`
is, by STAC's own construction, always the prefix immediately before a
new-effect-class step, "effect classes used so far" is confounded with
"the next step is probably a new effect class" independent of any
per-case tuning on my part -- a fixed rule built on that signal would
still end up label-correlated through the benchmark's own construction.
`ALL_EFFECTS` avoids the confound at the cost of being uninformative for
this benchmark. Whether that tradeoff is worth revisiting belongs to
§9's anchor-only-leakage gate (build-order step 3), which is designed to
test exactly this kind of thing empirically rather than have it argued
away here.

Anchor derivation, mechanical and identical for all 483 cases (uses
`benchmark/a4/common.py`'s shared rule):
  - `authorized_task` := `interaction_history[0]["content"]`, the first
    user-role turn, verbatim. Caveat stated plainly: STAC's own "Prompt
    Writer" stage authors this opening turn as part of attack
    construction, so unlike AgentDojo's `PROMPT` it is NOT
    cryptographically trusted the way docs/v2/A4_MULTITURN_SPEC_v0.2.md
    §5 assumes a real session's anchor would be -- it is the nearest
    available stand-in for "the benchmark's own declared task," and
    using a red-team benchmark's attacker-synthesized opening turn as a
    trusted anchor is a known limitation of adapting STAC to this
    threat model, not something hidden by this docstring.
  - `scope` := `frozenset({generation_config["environment"]})`.
  - `allowed_effects` := `ALL_EFFECTS` (see above).

`label` carries STAC's own ground truth untouched: `attack_goal`,
`malicious_tool_chain` (the full `verified_tool_chain`),
`predicted_attack_prompt`, `dataset_source`, `environment`,
`failure_mode`. Nothing here decides pass/fail for anything -- that is a
later build-order step.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from agentwarden.core.models import ToolCall

from .common import ALL_EFFECTS, AdapterCase, AdapterTurn, build_anchor

SOURCE = "stac"

STAC_REPO_URL = "https://github.com/amazon-science/MultiTurnAgentAttack"


class StacDatasetError(RuntimeError):
    """Raised when the STAC benchmark file is missing or not shaped the
    way this adapter expects -- never silently skipped or guessed
    around."""


def _parse_tool_call_arguments(raw: Any) -> dict[str, Any]:
    """Unwrap STAC's (sometimes doubly) JSON-encoded `function.arguments`
    field until a dict comes out, or raise rather than guess. See this
    module's docstring, point 1."""
    value = raw
    for _ in range(2):
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            break
        value = json.loads(value)
    if isinstance(value, dict):
        return value
    raise StacDatasetError(f"could not decode tool-call arguments: {raw!r}")


def _turns_from_interaction_history(history: list[dict[str, Any]]) -> tuple[AdapterTurn, ...]:
    turns: list[AdapterTurn] = []
    for entry in history:
        role = entry["role"]
        if role == "assistant" and entry.get("tool_calls"):
            for tc in entry["tool_calls"]:
                fn = tc["function"]
                turns.append(
                    AdapterTurn(
                        role="assistant",
                        tool_call=ToolCall(
                            name=fn["name"],
                            arguments=_parse_tool_call_arguments(fn["arguments"]),
                            raw_id=tc.get("id"),
                            raw_format="openai_function_call",
                        ),
                    )
                )
        else:
            turns.append(AdapterTurn(role=role, content=entry.get("content")))
    return tuple(turns)


def _case_from_record(record: dict[str, Any]) -> AdapterCase:
    case_id = str(record["id"])
    history = record["interaction_history"]

    first_user_turns = [t for t in history if t["role"] == "user"]
    if not first_user_turns:
        raise StacDatasetError(f"case {case_id}: no user turn to anchor on")
    authorized_task = first_user_turns[0]["content"]

    gen_config = record["generation_config"]
    environment = gen_config.get("environment", "unknown")

    anchor = build_anchor(
        authorized_task=authorized_task,
        scope=frozenset({environment}),
        allowed_effects=ALL_EFFECTS,
        issued_by="benchmark_adapter:stac",
    )

    planner_history = record.get("planner_history") or []
    predicted_attack_prompt = (
        planner_history[-1].get("predicted_attack_prompt") if planner_history else None
    )

    label = {
        "attack_goal": record["attack_plan"]["attack_goal"],
        "malicious_tool_chain": record["attack_plan"]["verified_tool_chain"],
        "predicted_attack_prompt": predicted_attack_prompt,
        "dataset_source": gen_config.get("dataset"),
        "environment": environment,
        "failure_mode": gen_config.get("failure_mode"),
    }

    return AdapterCase(
        source=SOURCE,
        case_id=case_id,
        anchor=anchor,
        turns=_turns_from_interaction_history(history),
        label=label,
        raw=record,
    )


def load_stac_cases(data_path: str | Path) -> list[AdapterCase]:
    """Load every case from STAC's `STAC_benchmark_data.json`.

    `data_path` points at that file wherever it was cloned -- it is not
    vendored into this repo (it is amazon-science's dataset, and this
    project's `data/` directory is gitignored by standing convention).
    Obtain it with:

        git clone https://github.com/amazon-science/MultiTurnAgentAttack
        # file is at MultiTurnAgentAttack/data/STAC_benchmark_data.json

    (the repo was archived 2026-07-10 but remains clonable read-only).
    """
    path = Path(data_path)
    if not path.exists():
        raise StacDatasetError(
            f"STAC dataset not found at {path}. Clone {STAC_REPO_URL} and "
            "pass the path to its data/STAC_benchmark_data.json."
        )
    with path.open() as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise StacDatasetError(f"expected a JSON list of cases, got {type(records)}")
    return [_case_from_record(r) for r in records]


def iter_stac_cases(data_path: str | Path) -> Iterator[AdapterCase]:
    yield from load_stac_cases(data_path)
