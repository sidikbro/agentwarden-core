# Minimal-pair context-use probe — spec

Status: **spec only. Nothing in this document is implemented.** No items
exist yet, no generation has run. This is a design for a held-out
diagnostic, written so the eventual 30-50 items are built to a stated
contract instead of to whatever's easiest to write first.

## Why this exists

`docs/v2/RECONCILED_STATE_v0.2.md` §11b found that gate 3a
(`defensively_framed_but_unsafe`, zero-tolerance BLOCK) is not a valid
probe of whether the classifier can use `context` to disambiguate a
call: gate 3a's own category, and its sibling `safe_but_defended`, are
each decision-homogeneous in the full 2,370-row dataset (652/652 ALLOW,
106/106 BLOCK) and share zero `(tool_name, arguments)` pairs with each
other. No row in either category needs `context` to be decided
correctly — `arguments` alone (plus, in some rows, reputation
information baked into argument content, e.g. a domain name) already
determines the label. So a gate-3a result from the ceiling experiment
(`router_training/train_pilot_ceiling.py`), in either direction, answers
nothing about context-use specifically.

This spec is for the diagnostic that would actually answer that
question: a small, held-out set where the *only* thing that
distinguishes a BLOCK item from its paired ALLOW item is the `context`
string, with `tool_name` and `arguments` held identical across the pair.

## What this is not

- Not training data. Every item is held out, permanently. If it is ever
  used to retrain anything, it stops being a valid diagnostic for that
  checkpoint and a new set is needed.
- Not an instruction to generate it now. Writing this spec is the
  deliverable; building the 30-50 items is a separate, later decision.
- Not a replacement for `docs/v2/provenance_representation.md`'s
  constraint on where a real verification-status signal could
  legitimately come from in production. This diagnostic only asks
  "can the model use `context` as given," the same narrow ceiling
  question the existing ceiling experiment asks — it just asks it on
  data actually built to test it, instead of on data that happens not
  to need an answer either way.

## Structure

Each probe item is a pair: `(id, tool_name, arguments, context_allow,
context_block)` — one `tool_name`/`arguments` pair, two context strings,
two labels. Expanding a pair into two scored rows gives
`{tool_name, arguments, context, decision}` in the same shape
`TrainingExample` already uses, so the existing canary-check tooling
(`scripts/classifier_canary_check.py`, run with `--with-context`) can
score it without new scoring code. Target size: **15-25 pairs (30-50
rows)**, matching the existing canary set's order of magnitude.

## Requirements the eventual items must satisfy

**(a) The discriminating fact must be carried structurally, not by a
keyword that correlates with the label.** A pair fails this if there is
any single word or fixed phrase that, across the full set, appears
disproportionately in `context_allow` vs. `context_block` — the classic
failure being something like "already verified" or "no prior step"
showing up only on the ALLOW side. The fact that must differ between
`context_allow` and `context_block` is *whether a specific, falsifiable
prior event happened* (a named read, a named audit entry, a cited
source) — not the presence of a stock phrase asserting that it
happened. Two context strings can both contain the words "verified" and
"prior step" and still correctly belong to opposite labels, if what's
being verified or who's asserting it differs. Before any set is
considered built, check this directly: run every fixed word/phrase that
appears in more than one `context_allow` string against its rate in
`context_block` strings, and vice versa, and reject any set where a
single token's presence predicts the label with the kind of skew the
template-shortcut probe (`scripts/template_shortcut_probe.py`) was
built to catch for the main dataset.

**(b) Lexical surface must vary across both labels.** No two
`context_allow` strings should share a sentence-level template with
each other, and likewise for `context_block` — the set should look like
15-25 independently-worded scenarios, not 2-3 templates instantiated
repeatedly. This is the same discipline the main dataset's `reason`
field violated (57% of its rows draw from five fixed skeletons,
per the template-shortcut probe) and should not be repeated here on a
set whose whole purpose is ruling that failure mode out.

**(c) A stated leakage test, run and reported before the probe is
trusted for anything.** Before using this set's result as evidence
about context-use, run a context-only baseline: feed the classifier (or
a simpler baseline model) *only* the `context` string for each row, with
`tool_name` and `arguments` withheld or replaced with a constant
placeholder, and score it against the same labels. If that baseline
scores meaningfully above chance (50% on a balanced binary set), the
probe has leaked the label into `context`'s surface form somewhere — a
word, a sentence structure, even punctuation — and (a)/(b) above failed
in practice even if they looked satisfied by inspection. A near-chance
result on this baseline is the thing that licenses treating a
full-context score on the real probe as evidence about context-use
specifically, rather than about some other leaked cue.

**(d) Tool names drawn from the current registry only, and specifically
from tools the classifier actually sees in production.**
`router_training.tool_registry.load_tool_registry()` currently reports
39 registered tools, of which 12 are excluded from the classifier
entirely: `classifier_skip` tools (`glob`, `grep`, `ls`, `memory_get`,
`memory_save`, `memory_search`, `read`, `read_file`, `session_status`,
`sessions_history`, `sessions_list`, `web_search` — never routed to the
classifier) and `always_block` tools (`bash`, `create_agent`, `exec`,
`execute`, `run_command`, `shell`, `spawn`, `su`, `sudo`, `system`,
`terminal` — blocked by Stage-1 rules before the classifier runs). This
matters concretely: the dataset-hygiene finding in §11b found the main
dataset's only other pocket of genuine context-discrimination used
`bash`/`shell`/`su`/`system` — four of exactly the `always_block` names
above — making half of that pocket irrelevant to classifier behavior by
construction. This probe's tool names must come from the 16 tools that
are neither: `chmod`, `chown`, `cron`, `delegate`, `edit`, `kill`,
`process`, `sessions_send`, `sessions_spawn`, `sessions_yield`,
`subagent`, `subagents`, `task`, `web_fetch`, `write`, `write_file`.

## Stage 1 result (2026-10-19): leakage detected, stopped per protocol

16 pairs (32 rows) were hand-authored to this spec and written to
`data/router_training/HELD_OUT_minimal_pair_probe.jsonl` — one pair per
eligible tool from requirement (d)'s 16-tool list. `router_training/
train_common.py::load_examples()` now rejects any path whose filename
starts with `HELD_OUT_`, so this file cannot reach `run_training()`
through any current or future training entrypoint that funnels through
it. `scripts/minimal_pair_leakage_check.py` implements requirements (a)
and (c):

- **Token-skew scan (a):** no unigram or bigram appearing at least twice
  across the set is skewed ≥0.8 between ALLOW and BLOCK contexts. No
  single stock phrase (the failure mode (a) specifically names) is
  present.
- **Context-only baseline (c):** TF-IDF + logistic regression, given
  only the `context` string (no `tool_name`/`arguments`), scored with
  leave-one-**pair**-out cross-validation (leave-one-*row*-out was tried
  first and rejected: it leaves a row's exact topical twin — its own
  pair partner, carrying the opposite label — in the training set on
  every fold, which pulls a topic-sensitive model toward the wrong
  label for a reason that has nothing to do with real leakage; see the
  script's docstring). Result: **22/32 = 68.8%** (one-sided binomial
  p=0.025 against chance; 90% CI 53%-82%). Errors split roughly evenly
  (5 ALLOW items misread as BLOCK, 5 BLOCK items misread as ALLOW) — not
  a degenerate "always predict BLOCK" baseline, and consistent with the
  token-skew scan finding no single dominant tell: whatever the leak
  is, it's diffuse across several pairs' phrasing rather than one
  repeated keyword.

**This is statistically meaningfully above chance.** Per the stage-1
protocol: stopping here. Stage 2 (scoring the probe against
`PILOT_UNREVIEWED_DATA_checkpoint` and `PILOT_CEILING_WITH_CONTEXT_checkpoint`)
was not run. This item set is not yet valid evidence about context-use
and should not be read as such until it's revised and re-checked. The
31-item canary set's own template-shortcut probe
(`scripts/template_shortcut_probe.py`) found no single-token leak either
in that case — the pattern here (clean token scan, leaky classifier) is
a reminder that a token-presence check alone is not sufficient to clear
a set; the held-out baseline classifier is doing real work the
token-skew scan can't substitute for.

## What this document does not do

It does not write any of the 30-50 items, does not pick which of the 16
eligible tools to use for which pair, does not design the leakage-test
baseline's exact implementation (only states what it must check and
what result licenses trusting the probe), and does not schedule when
this gets built. Those are the next decisions, each separate from
writing this spec.
