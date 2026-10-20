# Minimal-pair context-use probe — spec

Status: **spec only, revised 2026-10-20. Nothing in this document is
implemented.** The original prose-sentence design (below, "Original
design: prose context") is superseded — its stage-1 item set leaked and
is not being re-authored; see "Why the prose design is superseded" for
why iterating on it further isn't the right move. The current design is
"Revised design: structured provenance records," for which no items
have been generated yet either. This is still a design document, not
an implementation.

## Original design: prose context (superseded — kept for the record, not a current spec)

### Why this exists

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

### What this is not

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

### Structure

Each probe item is a pair: `(id, tool_name, arguments, context_allow,
context_block)` — one `tool_name`/`arguments` pair, two context strings,
two labels. Expanding a pair into two scored rows gives
`{tool_name, arguments, context, decision}` in the same shape
`TrainingExample` already uses, so the existing canary-check tooling
(`scripts/classifier_canary_check.py`, run with `--with-context`) can
score it without new scoring code. Target size: **15-25 pairs (30-50
rows)**, matching the existing canary set's order of magnitude.

### Requirements the eventual items must satisfy

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

### Stage 1 result (2026-10-19): leakage detected, stopped per protocol

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

## Why the prose design is superseded, not re-authored

The stage-1 result above (68.8% leave-one-pair-out accuracy from
`context` text alone) could, in principle, be treated as "these
particular 16 pairs still have a fixable tell — rewrite them and
re-check." That is deliberately not what's happening here, and not
only because of budget. Two further facts, both from 2026-10-20, make
re-authoring the wrong move rather than just an unappealing one:

1. **The leak isn't specific to these 16 hand-written pairs — it's
   present at near-total strength across the entire real dataset.**
   `scripts/context_category_leakage_check.py` ran the identical
   TF-IDF + logistic-regression setup against all 758
   `safe_but_defended`/`defensively_framed_but_unsafe` rows in
   `full_dataset.jsonl`, context string only, and got **99.5% balanced
   accuracy** (one misclassified row out of 758) separating the two
   categories by register alone. If the dataset's own 758
   professionally-authored rows carry a near-total register tell, 16
   pairs written to deliberately avoid one are not an easier case —
   they're a harder one, being far smaller and single-authored.
2. **Prose carries register irreducibly.** Any sentence written by a
   human to convey "this was verified" vs. "this was not" will differ
   in more than its truth-bearing content — word choice, sentence
   length, hedging, which clause comes first, how specific the cited
   detail is. That's not a drafting mistake to iron out; it's what
   natural-language register *is*. Each revision pass that rewrote a
   pair specifically to beat `scripts/minimal_pair_leakage_check.py`
   would be training the author (a human, or an LLM if one were used
   instead) against that one detector — removing whatever the detector
   currently flags while very plausibly introducing or leaving some
   other register tell the same detector, or a stronger one, would
   catch next. That is overfitting the items to the test, not removing
   the thing the test exists to catch. A probe built this way would
   eventually "pass" by construction, not by actually being clean.

The 68.8% result is therefore being read as confirmation that prose
`context` is the wrong representation for this diagnostic, not as a
bug in sixteen specific sentences. The structured-record design below
replaces it rather than iterating on it.

## Revised design: structured provenance records (current spec — no items generated)

Instead of a free-text `context` sentence, each probe item's `context`
is a **structured record**, shaped after the verification-history
concept `docs/v2/provenance_representation.md` describes (a prior
governance decision this system itself logged — never tool output,
never model-generated text, never the current call's own claim).
Concretely, each half of a pair carries a record with these fields,
not a sentence:

```
{
  "source": "<what produced this record, e.g. 'audit_log'>",
  "verifier": "<which prior decision or actor confirmed the fact,
                e.g. 'session sess_main, decision d_117'>",
  "check": "<what was checked, e.g. 'domain reputation lookup'>",
  "result": "<the check's outcome, e.g. 'confirmed malicious' |
              'no record found' | 'confirmed legitimate'>",
  "timestamp": "<when the check happened, e.g. '2026-10-18T09:14:00Z'>"
}
```

`tool_name` and `arguments` stay identical within a pair, exactly as
in the original design; only this structured record varies, and it is
what flips the label (a `result` of "confirmed malicious"/"no record
found" → BLOCK is unverified or adverse; "confirmed legitimate" →
ALLOW). `build_classify_prompt`'s `include_context` path would need to
render this as a block of key-value lines rather than a sentence for
this to reach the model in the same place `context` currently does —
not implemented here, noted as the integration point for whenever
items are actually built.

**This makes label-discrimination near-trivial for any consumer of the
field — and that is the finding, not a flaw to design around.** A
record with a `result` field has one answer: read it. There is no
register to launder, no sentence-construction tell to leak or to
clean up, because there is no sentence — the field states the outcome
directly, by construction, *if and only if the field is populated from
a trustworthy source* (which is exactly `provenance_representation.md`'s
unresolved prerequisite — a real audit store, not the single
`logger.info()` call that exists today). A structured field that is
actually trustworthy is naturally read by a symbolic rule (`if
result == "confirmed malicious": BLOCK`), not inferred by a learned
classifier weighing lexical cues. That reframes where gate 3a's
decision belongs in a system that actually has this field available:
**on the symbolic side of a hybrid architecture, keyed directly off
the verification record, with the learned classifier's job narrowed to
residual ambiguity the record doesn't resolve** (e.g. no record exists
yet, or the record's own `check` type doesn't cover the claim being
made) — not "train the classifier harder on more examples with context
included," which is the path the original ceiling experiment was
implicitly testing.

**No items are being generated for this design yet.** This section is
the spec for what a future minimal-pair set under this representation
would look like, so that whenever that set is built, it's built as a
structured record from the start rather than as a sentence that
happens to describe one.

## What this document does not do

It does not write any items under either design. For the superseded
prose design, the 16 pairs that were written are historical record,
not a template to extend. For the current structured-record design,
it does not pick which of the 16 eligible tools gets which record
content, does not implement the `build_classify_prompt` rendering
change a structured `context` would need, does not design a leakage
check for this representation (the point of the design is that one
shouldn't be necessary if the field is genuinely structured and
trustworthy — that claim itself would still need checking once items
exist, just not against lexical register), and does not schedule when
any of this gets built or whether a hybrid symbolic/learned
architecture gets implemented. Those are all separate, later
decisions.
