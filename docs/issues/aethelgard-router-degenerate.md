# The fine-tuned router (aethelgard-router) is degenerate — blocks everything

**Status:** confirmed, not fixed. Weights need retraining or replacement;
this is not a code bug to work around.
**Found:** 2026-09, while re-running B4/B5 baselines with the fine-tuned
classifier instead of the zero-shot stand-in.

## Summary

Both `aethelgard-router:latest` and `aethelgard-router-q4:latest` (the
Ollama tags present in this environment) are unusable as governance
classifiers:

- `aethelgard-router:latest` returns `BLOCK` for **every** tool call
  tested — 12/12 in a targeted diverse sample (safe reads, benign writes,
  and genuinely dangerous calls alike) — each with a distinct but
  fabricated justification (e.g. `read_email` → "violates Aethelgard
  policy"; `extract_facts` → "attempts to execute arbitrary code"; neither
  claim is true of what those tools do).
- `aethelgard-router-q4:latest` returns HTTP 500 on every request and
  cannot be used at all.

## What was ruled out first

A real bug WAS found and fixed alongside this: the model's own Modelfile
system prompt asks for JSON key `"action"`, while `agentwarden/policies/
classifier.py`'s prompt and parser expected `"decision"` — and since
Ollama's `/api/generate` auto-prepends a model's baked-in system prompt,
`aethelgard-router` was receiving two conflicting format instructions on
every real call through this pipeline. Fixed in `classifier.py`'s
`evaluate()`: `result.get("decision") or result.get("action") or "ALLOW"`.

**This fix changed nothing.** Re-tested the same 12 calls through the
fixed code path: still 12/12 blocked, same fabricated reasons. Also
confirmed directly (bypassing classifier.py entirely, querying Ollama with
only the model's own system prompt, no conflicting instructions at all):
still blocks everything. The degeneracy is in the model itself, not in how
it's invoked.

## What this means

The model has collapsed into an always-block policy with plausible-sounding
but fabricated per-call justifications — structurally the same failure
mode already documented elsewhere in this project as a known risk for
learned policies (`EXPERIMENTAL_PLAN_v0.1.md` §8, L1: "unconstrained PPO
reproduces v1's collapse; included as a documented failure mode"). Whether
this specific artifact came from that collapse, a bad quantization, a
mismatched Modelfile paired with unrelated weights, or something else
wasn't determined — any of those would produce this behavior, and
distinguishing them requires access to the training run, which is out of
scope here. What's established is only that the deployed artifact is
unusable, not why.

## Where results in this repo depend on this model

- `agentwarden/policies/router.py` (`SafetyRouter` docstring) and
  `agentwarden/policies/classifier.py` (module docstring) both carried
  unverified performance claims tied to "the fine-tuned agentwarden-router
  weights" (100% TPR / 0% FPR; ~95%+ accuracy). Both now carry an explicit
  "UNVERIFIED / CONTRADICTED" note pointing here, rather than being
  silently left as if validated. Neither claim is disproven for some other,
  possibly-authoritative checkpoint — only for the artifact actually
  tagged with this name in this environment.

- **The SER headline numbers deserve a specific look, not just a general
  caveat.** `scripts/eval_runner.py`'s own comment on its SER
  approximation: `"SER improves when more dangerous calls are blocked"`
  (`compute_metrics()`). If the classifier active during whatever run
  produced `README.md`'s "+191% ablation / 10.5× real sessions" or
  `docs/architecture.md`'s "SER ≈ 0.557 (real-session evaluation)" was
  over-blocking indiscriminately, that would inflate SER exactly the way
  this project's own benchmark work just demonstrated for B4/B5: blocking
  everything makes "efficiency" metrics look great while task utility
  collapses (B4 zero-shot: task success 0.100 with only a *moderate*
  false-positive rate; a model blocking 100% of calls would show even more
  dramatic SER "improvement" while succeeding at nothing). **This is not
  confirmed** — the one saved evaluation in `data/eval_results/`
  (`eval_gemma4_e4b_n20_20260502_123506.json`) shows `block_rate: 0.0` for
  its 20 tasks, i.e. a run where the classifier blocked nothing, which
  doesn't match a degenerate always-block model — but that file is N=20
  against `gemma4:e4b`, not the N=500 run the headline figures cite, and
  it doesn't record which classifier model/config was active. **Before
  citing the SER headline numbers anywhere the fine-tuned router's state
  now matters, check what classifier configuration actually produced
  them.**

- That same N=20 saved eval surfaces an unrelated but real methodology
  gap while it was open: `adversarial_coverage: 1.0` for that run is
  computed from `blocked OR model_refused`, and all 8 adversarial tasks in
  it were `model_refusal` — `adversarial_blocked_agentwarden: 0`. The
  reported 100% adversarial coverage there is entirely the backend LLM
  refusing on its own, not AgentWarden's rules/classifier catching
  anything. Worth separating "the model declined" from "governance
  blocked it" in any report that cites adversarial coverage from this
  script.

- Docs referencing `agentwarden-router`/`aethelgard-router` as a
  configuration option (`README.md`, `TESTING.md`,
  `docs/architecture.md`, `docs/governance.md`, `docs/debugging.md`,
  `docs/troubleshooting.md`, and their `docs/agentwarden_docs/` mirrors)
  were not individually edited — describing it as an available backend
  choice isn't itself a false claim. The two places that stated a
  *specific validated performance number* for it are the two fixed above.

- `benchmark/`'s own B4/B5 baseline runs (this project's new work, not
  legacy code) already treat this correctly: `scripts/report_baselines.py`
  labels the fine-tuned row explicitly as reflecting a degenerate artifact
  and reports it separately from the zero-shot number, never averaged in.

## What would actually fix this

Retraining or re-obtaining known-good weights, then re-validating against
a diverse benign/dangerous test set before trusting any performance claim
about them again — not a code change. Re-running B4/B5 with a corrected
model is a five-minute check once one exists; producing one is not in
scope here.
