# The ATBench-Claw "274/279 tools blocked" result is NOT driven by tool-name priors — it's ~99.8% content-sensitive

**Status:** confirmed via direct measurement against the actual replay artifacts.
**Found:** 2026-09, while producing the "route high-risk tools to Stage 2/3"
design report and re-examining the ATBench attribution question requested
in that review.
**Action needed:** this contradicts a claim in the NeurIPS rebuttal draft
(see below) — the rebuttal text needs to be corrected, not the other way
around.

## The rebuttal claim this contradicts

The current rebuttal draft states that AgentWarden's blocking was "highly
concentrated by tool identity" and that the governance layer "relies too
heavily on tool-name priors." Direct measurement of the actual evaluation
artifacts shows the opposite.

## What was measured

Source artifacts (a real 500-trajectory replay of ATBench-Claw through
`agentwarden.core.pipeline.build_pipeline()` — Stage 1 rules + Stage 2
classifier, not a mock):

- `~/atbench-claw-eval/replay_results.jsonl` (per-trajectory results)
- `~/atbench-claw-eval/tool_vocabulary.json` (per-tool aggregate counts,
  including `agentwarden_blocked` and `n_unique_tools: 279`)
- `~/atbench-claw-eval/replay_summary.json` (confusion matrix)

**"274/279" is real and reproducible**: 279 is the count of distinct tool
names in the ATBench-Claw vocabulary used across the 500 trajectories; 274
of those 279 were blocked at least once somewhere in the run. The 5 never
blocked are exactly the read-only / `classifier_skip` tools (`read`,
`read_file`, `memory_search`, `grep`, plus one incidental script name).

**Attribution to the Stage-1 `always_block` tool-name list, computed by
exact name match against `config/rules.yaml`'s list** (`exec, execute,
bash, shell, run_command, terminal, system, process, kill, sudo, su,
chmod, chown, sessions_spawn, subagent, subagents, spawn, create_agent,
delegate, task`):

| | count |
|---|---|
| Total blocked tool invocations (across all 500 trajectories) | 1,090 |
| ...whose tool name exactly matches an `always_block` entry | **2** (both `bash`) |
| Distinct blocked tools (of 274) that are in `always_block` | **1** (`bash`) |

**`always_block` accounts for 0.18% of the blocking in this result
(2/1090).** The remaining 99.8% came from Stage 1 `arg_patterns` (content
regex on argument values) and/or Stage 2 LLM classifier judgment — not
from a static per-tool-name denylist.

This is structurally expected, not a fluke: `always_block` is a fixed list
of ~20 generic execution/privilege verbs, and ATBench-Claw's real-world
MCP tool vocabulary (`himalaya envelope list`, `gog sheets get`,
`obsidian-cli move`, `tmux send-keys`, Slack-shaped `sendMessage` /
`pinMessage`, etc.) essentially never collides with those generic names —
`bash` is the one coincidental exception.

## What this means for the paper

1. **"274/279 tools blocked" should not be read as "a static denylist
   blocks almost the whole vocabulary."** The evidence says the opposite:
   the governance layer is inspecting call content/context on a
   near-universal basis, not gatekeeping by name. If the rebuttal's point
   was that governance is too coarse, tool-name-based blocking is not the
   mechanism to cite — cite the arg_pattern/classifier precision problem
   instead (see next point).
2. **The real, measured problem in this data is over-blocking precision,
   not tool-name coarseness**: `replay_summary.json` shows `fp=195` of
   500 — 39% of trajectories ATBench labels *safe* still had something
   blocked. That's a content-rule/classifier false-positive problem, and
   it is not what "relies too heavily on tool-name priors" describes.
3. We cannot currently split the 99.8% between Stage 1 `arg_patterns` and
   Stage 2 classifier — the historical `replay_results.jsonl` on disk only
   persisted aggregate block counts per trajectory, not the per-decision
   `stage` field. (`~/atbench-claw-eval/replay.py`'s current on-disk
   version already computes and would write per-decision `stage` for a
   fresh run — it just wasn't exercised for the run that produced the
   artifacts analyzed here.) If the paper needs the exact split, re-run
   the replay and use the persisted `stage` field.

## Recommendation

Change the rebuttal wording away from "concentrated by tool identity" /
"relies on tool-name priors" to something the data actually supports,
e.g.: governance blocked content/context-dependently across nearly the
entire tool vocabulary (274/279 tools, driven >99% by argument-pattern and
classifier judgment rather than a static per-tool list), with a
substantial false-positive rate (39% of safe trajectories still triggered
a block) that argues for improving Stage 1/2 precision rather than for
tool-name-based governance being the failure mode.
