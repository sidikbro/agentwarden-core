# B1 (prompting-only self-restriction): what this benchmark can and cannot say

**Status:** known limitation, not yet resolved. Written in response to
Reviewer BNSs's request for this exact baseline — the paper needs a stated
answer here, not a silently-B0-equal row in a results table.

## What B1 is supposed to test

Per the baseline matrix (`EXPERIMENTAL_PLAN_v0.1.md` §3): D1 = full tool
registry, D2 = "LLM self-restriction via system prompt." The hypothesis
under test is *"just tell the model not to call dangerous tools"* — does a
system-prompt instruction alone produce safe behavior without any
enforcement layer, i.e. is a Capability Governor/Router even necessary?

## Why the current benchmark cannot test it

Every baseline in this benchmark executes a **scripted plan**: a fixed,
pre-written sequence of tool calls (`benchmark/runner.py`'s `ScriptedCall`
list), built once per task instance in `benchmark/tasks/*.py`. A scripted
plan has no point at which a system prompt could change what gets called —
the sequence of tool names was decided when the plan was authored, not
inferred live from a system prompt by a model reasoning at request time.

Concretely: `run_b1()` and `run_b0()` in `benchmark/baselines.py` differ
only in a `baseline=` label passed to `run_scripted()`. Both use the same
`_full_registry_exposure_fn` (D1 = full registry) and the same D2 = none.
There is no code path where a "please self-restrict" instruction is
represented at all, because there is no live decision-maker in the loop to
receive it. Running B1 today reproduces B0's numbers exactly, on every
metric, for every task instance — confirmed in
`tests/test_baselines.py::test_b1_is_mechanically_identical_to_b0`.

This is not a bug to fix in `run_b1()`. It is a structural property of a
scripted-plan benchmark: **B1's entire hypothesis lives in a part of the
pipeline (the model's live decision process) that this benchmark doesn't
execute.**

## What a real test would require

A **non-scripted variant**: a task execution mode where an actual LLM,
given the task's `initial_prompt` plus a system-prompt instruction
("only call tools relevant to this task; do not call X, Y, Z"), chooses
which tools to call at each turn, live. The resulting trajectory — which
tools it *chose* to call, whether it stayed within the intended set —
would then be the real B1 data point, compared against what the same task
does under B0 (no instruction) and B3/B5 (real enforcement).

This is a materially bigger piece of infrastructure than anything else in
the benchmark today:

- A live-agent runner: something that actually calls an LLM in a loop,
  parses its tool-call responses, feeds results back, and continues —
  distinct from `run_scripted`/`run_via_pipeline`, which both replay a
  fixed plan rather than generate one.
- A way to keep the comparison fair: the same task, same tool registry,
  same ground truth, but now with model non-determinism in the loop
  (multiple seeds/temperature considerations, matching the multi-seed
  requirement already flagged for the learned conditions in §8).
- A decision about which model(s) to run this against, and whether B1's
  result is meant to characterize "LLMs in general" or a specific model
  family — a single-model result would need that caveat explicitly.
- Extending `benchmark/schema.py`/`Trajectory` recording to a live
  execution path, if it doesn't already generalize (it should — the
  Trajectory record format was deliberately kept model/runner-agnostic —
  but this hasn't been exercised against a live decision-maker yet, only
  against `run_scripted` and `run_via_pipeline`'s replay of fixed plans).

None of this is exotic, but it is a genuinely separate execution mode, not
a parameter change to the existing scripted runner.

## Recommendation (for a later decision, not made here)

Two honest options for how the paper handles B1:

1. **Build the live-agent runner** and get a real B1 number. Strengthens
   the "enforcement is necessary" argument concretely (assuming B1
   underperforms B3/B5/B6, which is the expected but unverified outcome)
   and directly answers Reviewer BNSs. Costs real scope: a new execution
   mode, live-model calls (cost + latency + non-determinism to manage),
   and it only produces one baseline's worth of evidence.
2. **Report the limitation as-is**, with this document as the citation:
   state plainly that this benchmark's scripted-plan design cannot
   evaluate prompting-only self-restriction, explain why (above), and
   frame B0 as the honest ungoverned bound that stands in its place. This
   keeps scope contained but leaves Reviewer BNSs's specific ask formally
   unanswered rather than answered with real data.

Not deciding between these here — flagging the tradeoff so it can be
weighed against the January timeline alongside the task-type-classifier
scope decision already made (declaration-first + structural fallback, no
learned classifier upstream of D1).
