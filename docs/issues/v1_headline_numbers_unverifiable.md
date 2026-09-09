# v1 headline numbers: what's traceable, what isn't, what to do about it

**Status:** investigation complete. Two of three headline claims are
**not verifiable** and must not be cited forward as-is. One is real but
smaller than claimed. See `scripts/report_headline_reproduction.py` for
clean re-derivations on the v2 benchmark.

## Method

Searched this repo's full git history (`git log --all -S<value>` for each
number, plus commit-message and diff review) and, on finding it
insufficient, located the actual predecessor project —
`~/PycharmProjects/aethelgard/`, a separate git repository (not a
subdirectory of this one) with 20 commits spanning 2026-03-30 to
2026-04-17 — and searched it the same way. `agentwarden-core`'s own
history starts from a single "first commit" (`6a147bd`, 2026-04-26) that
already contains all three headline claims fully formed, with no
in-repo commit showing them being derived. The `aethelgard` repo is
where they were actually produced, where traceable at all.

## Claim 1: "AgentWarden real-session SER: 0.557 (10.5× improvement, N=500 batch)" — README.md

**The `0.557` figure is real and traceable.** `aethelgard` commit
`0441d0a` (2026-04-09), `data/real_eval_results_apr9.json`:
`"governed_avg_ser": 0.557`. But:

- It is **not** an N=500 result — the source file records 51 total tool
  calls across 12 completed tasks, model = `deepseek-chat`.
- Its own paired baseline in that file is `0.127`, giving `ser_improvement:
  3.37` (i.e. +337%, ≈4.4×) — not 10.5×.
- The only blocks recorded (`"blocked_tools": {"exec": 6}`) are on a tool
  that's unconditionally blocked by Stage 1's deterministic regex rules —
  there is no field identifying which classifier model, if any, was
  active, and nothing indicates the classifier did any semantic work here
  at all.
- The file's own note: `"model_refused_adversarial": true` — the same
  model-refusal/governance-blocking conflation already flagged for this
  repo's own saved eval (`docs/issues/aethelgard-router-degenerate.md`).

**The `10.5×` multiplier is not traceable to anything.** `0.557 / 0.053 =
10.509`, matching exactly — so README's own baseline figure must be
`0.053`. That number appears nowhere in `aethelgard`'s history and enters
`agentwarden-core`'s history only as literal text in commit `4d50332`
("x") — no computation, no data file, no evaluation run behind it.
`docs/architecture.md`'s parallel claim ("Baseline ≈ 0.06 ... governed ≈
0.557") has the same problem: `0.557/0.06 = 9.28`, and `0.06` is equally
unsourced. Every baseline SER actually measured anywhere in either repo's
history clusters around **0.078–0.1265** (the ablation's baseline, the
Apr-9 file's baseline, and the real N=500 batch's baseline below) — 1.5–2.4×
higher than the `0.053`/`0.06` figures used to produce the inflated
multiplier.

**Verdict: unverifiable as stated. Do not cite "10.5×" or "N=500" for this
figure going forward.**

## Claim 2: "SER (Skill Economy Ratio) improvement: +191% ablation" — README.md

**Traceable and real, closest of the three to being solid.** `aethelgard`
commit `3ba93e7` (2026-04-10), `data/ablation_summary.json`: a genuine
124-tasks-per-condition ablation (full / no_rl / no_router / baseline).
`full.avg_ser = 0.2266`, `baseline.avg_ser = 0.0775` →
`(0.2266−0.0775)/0.0775 = 1.924` ≈ **+192%**, matching the commit message
and closely matching README's "+191%" (rounding difference). Block rates
across conditions (4.8%–13.7%) are modest and plausible, not indiscriminate.
The predecessor's classifier.py at this commit correctly parsed the
model's `"action"` key (`result.get("action", "ALLOW")`) — no format
mismatch at the time, unlike the bug found and fixed in this session.

**This one holds up**, with the caveat that it measures D1 (exposure
scoping via Governor/RL policy), not classifier behavior, and it's from a
different (earlier, "v1" GGUF) router checkpoint than what's tagged
`aethelgard-router:latest` today — not established whether it's the same
weights.

## Claim 3: "Reproduces the 100% TPR / 0% FPR result from the N=500
evaluation when used with the fine-tuned agentwarden-router weights" —
`router.py`

**A real N=500 evaluation exists** — same commit `3ba93e7`,
`data/batch_eval_summary.json`: `n_total: 500`, `n_benign: 400`,
`n_adversarial: 100`. This is almost certainly the "N=500 evaluation" the
docstring refers to. Its actual numbers:

```
overall_block_rate:      0.2617
adversarial_block_rate:  0.38     (i.e. TPR ≈ 38%, not 100%)
ser.overall_avg:         0.0526
ser.baseline:            0.1265
```

**38% adversarial block rate, not 100%. 62% of adversarial calls in this
real N=500 run were NOT blocked.** This is the single clearest piece of
evidence in this investigation: the one N=500 run that actually exists
directly contradicts the "100% TPR / 0% FPR" claim attached to the same
scale of evaluation.

**Verdict: unverifiable as "100% TPR / 0% FPR" — and the nearest real
result found contradicts it directly. Do not cite this figure going
forward.**

## Summary table

| Claim | Traceable? | Real value found | Claimed value |
|---|---|---|---|
| SER 0.557, "10.5×", N=500 | 0.557 yes; 10.5× no; N=500 no | 0.557 @ N=51/12-tasks, ×3.37 vs its own baseline | 10.5×, N=500 |
| SER "+191% ablation" | Yes | +192% (124 tasks/condition) | +191% (matches) |
| "100% TPR / 0% FPR, N=500" | N=500 yes; 100%/0% no | 38% adversarial block rate | 100% / 0% |

## What to do

- `router.py` and `classifier.py` already carry `UNVERIFIED /
  CONTRADICTED` notes pointing here (added this session).
- `README.md` and `docs/architecture.md` still state the 0.557/10.5× and
  ~9.3× figures as fact — not yet corrected; flagging here rather than
  silently rewriting public-facing marketing copy without sign-off.
- Going forward, `scripts/report_headline_reproduction.py` re-derives both
  the SER/exposure-improvement claim and adversarial handling cleanly on
  the v2 benchmark, with a non-degenerate (zero-shot) classifier, and with
  `blocked_by_governance` and `model_refused` always reported as separate
  fields — never combined into one "coverage" number the way both the old
  eval and this investigation's own source data did.
