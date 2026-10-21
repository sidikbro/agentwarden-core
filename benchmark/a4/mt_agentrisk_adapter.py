"""MT-AgentRisk adapter (docs/v2/A4_MULTITURN_SPEC_v0.2.md §13 step 1).

MT-AgentRisk ("Unsafer in Many Turns," arXiv:2602.13379, PMLR v306) is
gated on HuggingFace (`CHATS-Lab/MT-AgentRisk`) behind a terms-of-use
form collecting the requester's own name, affiliation, country, and
email -- confirmed directly this session by fetching the dataset repo's
own README over HTTP, which declares `extra_gated_fields: Full Name /
Affiliation / Country / Academic or Work Email Address / I agree to
follow the terms of use`. That is real identifying information tied to
a real HuggingFace account; this adapter cannot and does not submit
that form on anyone's behalf. **As a direct consequence, this adapter
has not been run against real MT-AgentRisk data in this session** --
only against the synthetic fixture in
`tests/fixtures/mt_agentrisk_sample/`, built to match the schema below.
Running it for real requires the steps in
`MTAgentRiskDatasetNotAvailableError`'s message.

The schema below is confirmed from the companion GitHub repo
(github.com/CHATS-lab/MT-AgentRisk_ToolShield -- cloned and read this
session), specifically `agentrisk/run_eval.py`'s `load_turn_manager()`
and `docs/benchmark.md`'s example path, NOT from the gated data itself.
Every task is a directory:

    <task_path>/
      task.md              -- task statement (present for single-turn tasks)
      task-intro.md         -- optional multi-turn preamble
      turns.yml              -- {"turns": [{"id", "instruction_file",
                                 "checkpoint_id", "max_steps",
                                 "success_patterns"}, ...]}
      <instruction files named by each turn's instruction_file>
      utils/dependencies.yml, utils/seed.sql, utils/init.sh
      mcp_fs/, workspace/, scenarios.json

`load_turn_manager()` treats the presence of `turns.yml` as the test
for "this is a multi-turn task" -- this adapter uses the same test, so
it only ever emits cases for multi-turn tasks, which is what A4 needs.

A structural consequence worth stating plainly: MT-AgentRisk is a
LIVE-execution benchmark. Its real evaluation drives an OpenHands-
controlled agent, turn by turn, against a sandboxed MCP server
(filesystem / postgresql / terminal / playwright / notion) -- there is
no pre-recorded `interaction_history` to parse the way STAC has one,
because none exists until an agent actually runs. This adapter can
therefore only emit the STATIC task description: `turns` below holds
one `user`-role `AdapterTurn` per `turns.yml` entry (the staged
instruction text), with no `assistant`/`tool` turns at all. That is a
real difference in what this adapter can produce, not an omission to
fix later -- producing assistant/tool turns would require actually
running the live harness (OpenHands + MCP servers + possibly Postgres),
which is out of scope for an adapter and is, in any case, blocked here
by the lack of SSH/cluster access in this environment as well as by the
gated data.

Anchor derivation (mechanical, same spirit as the STAC adapter):
  - `authorized_task` := `task-intro.md` if present, else the first
    turn's instruction text -- in that fixed order, identical for every
    task directory.
  - `scope` := `frozenset({tool_category})`, where `tool_category` is
    inferred from the task directory's own path against the
    benchmark's fixed 5-tool vocabulary (filesystem / postgresql /
    terminal / playwright / notion) -- confirmed from
    `docs/benchmark.md`'s own example path
    (`workspaces/terminal/multi_turn_tasks/...`), not from per-task
    judgment.
  - `allowed_effects` := `ALL_EFFECTS`, for the same reason as STAC's
    adapter: no verified "benign-only" call sequence is available
    without actually running the task against a live sandbox, and this
    adapter does not run agents.

`label` carries whatever `checkpoint_id` / `success_patterns` each
task's own `turns.yml` declares, untouched. There is no `attack_goal`
text field in this benchmark's own schema the way STAC has one --
MT-AgentRisk's harm criterion is "the sandboxed environment ends up in
the attacker's target state," checked by the live sandbox at
evaluation time, not stated as text in the task package.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .common import ALL_EFFECTS, AdapterCase, AdapterTurn, build_anchor

SOURCE = "mt_agentrisk"

_KNOWN_TOOL_CATEGORIES = {"filesystem", "postgresql", "terminal", "playwright", "notion"}

HF_DATASET_URL = "https://huggingface.co/datasets/CHATS-Lab/MT-AgentRisk"


class MTAgentRiskDatasetError(RuntimeError):
    """Raised when a task directory doesn't match the documented schema
    -- never silently skipped."""


class MTAgentRiskDatasetNotAvailableError(MTAgentRiskDatasetError):
    def __init__(self, root: Path):
        super().__init__(
            f"MT-AgentRisk dataset not found at {root}. This dataset is "
            "gated on HuggingFace and cannot be fetched automatically. "
            "To obtain it:\n"
            f"  1. Request access at {HF_DATASET_URL} (the gate form "
            "asks for your own name/affiliation/email -- this step must "
            "be done by you, not on your behalf).\n"
            "  2. pip install huggingface-hub\n"
            "  3. huggingface-cli login\n"
            "  4. huggingface-cli download CHATS-lab/MT-AgentRisk "
            "--repo-type dataset --local-dir MT-AgentRisk\n"
            f"  5. Pass root_dir=<...>/MT-AgentRisk/workspaces to "
            "load_mt_agentrisk_cases().\n"
            "Note: MT-AgentRisk's full evaluation protocol drives a live "
            "OpenHands-controlled agent against sandboxed MCP servers "
            "(see github.com/CHATS-lab/MT-AgentRisk_ToolShield); this "
            "adapter only parses the static task description (turns.yml "
            "+ instruction files), not an executed trajectory -- see "
            "this module's docstring."
        )


def _infer_tool_category(task_path: Path) -> str:
    for part in task_path.parts:
        if part.lower() in _KNOWN_TOOL_CATEGORIES:
            return part.lower()
    return "unknown"


def _read_text(path: Path) -> str:
    return path.read_text().strip()


def _case_from_task_dir(task_path: Path) -> AdapterCase:
    manifest_path = task_path / "turns.yml"
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    raw_turns = manifest.get("turns", [])
    if not raw_turns:
        raise MTAgentRiskDatasetError(f"{task_path}: turns.yml has no turns")

    turn_texts: list[tuple[dict[str, Any], str]] = []
    for entry in raw_turns:
        instruction_file = entry.get("instruction_file")
        if not instruction_file:
            raise MTAgentRiskDatasetError(
                f"{task_path}: turn {entry.get('id')} missing instruction_file"
            )
        instruction_path = task_path / instruction_file
        if not instruction_path.exists():
            raise MTAgentRiskDatasetError(
                f"{task_path}: instruction file {instruction_path} not found"
            )
        turn_texts.append((entry, _read_text(instruction_path)))

    intro_path = task_path / "task-intro.md"
    authorized_task = _read_text(intro_path) if intro_path.exists() else turn_texts[0][1]

    tool_category = _infer_tool_category(task_path)

    anchor = build_anchor(
        authorized_task=authorized_task,
        scope=frozenset({tool_category}),
        allowed_effects=ALL_EFFECTS,
        issued_by="benchmark_adapter:mt_agentrisk",
    )

    turns = tuple(AdapterTurn(role="user", content=text) for _, text in turn_texts)

    label = {
        "turn_manifest": [
            {
                "id": entry.get("id"),
                "checkpoint_id": entry.get("checkpoint_id"),
                "max_steps": entry.get("max_steps", 10),
                "success_patterns": entry.get("success_patterns", []) or [],
            }
            for entry, _ in turn_texts
        ],
        "tool_category": tool_category,
        "task_dir": str(task_path),
    }

    return AdapterCase(
        source=SOURCE,
        case_id=task_path.name,
        anchor=anchor,
        turns=turns,
        label=label,
        raw={"manifest": manifest},
    )


def load_mt_agentrisk_cases(root_dir: str | Path) -> list[AdapterCase]:
    """Load every multi-turn task found under `root_dir` (recursively,
    identified by the presence of a `turns.yml`). `root_dir` is the
    dataset's own `workspaces/` directory after the gated download --
    see `MTAgentRiskDatasetNotAvailableError` for exact commands.
    """
    root = Path(root_dir)
    if not root.exists():
        raise MTAgentRiskDatasetNotAvailableError(root)
    task_dirs = sorted({p.parent for p in root.rglob("turns.yml")})
    if not task_dirs:
        raise MTAgentRiskDatasetError(
            f"no turns.yml found under {root} -- is this the dataset's "
            "workspaces/ directory?"
        )
    return [_case_from_task_dir(d) for d in task_dirs]
