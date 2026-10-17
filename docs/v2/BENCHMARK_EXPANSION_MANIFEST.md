# Benchmark expansion manifest — Track A

Tracks progress toward the benchmark-expansion target (`EXPERIMENTAL_PLAN_v0.2.md` §4a — see §4b for why that target's shape is now under review). Each instance is listed with its `validate.py` result, review status, and review note — mirroring `router_training/schema.py::TrainingExample`'s `review_status` field, which the benchmark's `Task`/`GroundTruth` dataclasses don't carry natively, so this file is the tracking mechanism for benchmark instances instead.

**Standing rule, same as §4a: no instance below is usable in any *reported* baseline run until its `review_status` is `approved`.** All five `validate.py` checks passing is necessary, not sufficient — a human reading the actual task/ground-truth/oracle-plan content, not just the check output, is required for `approved`.

---

## Human review verdict — 2026-09-10 (reviewer: slavik)

**Finding: 5 genuinely distinct task structures, 8 within-family perturbations — not 13 independent data points.** Every `v1` is a distinct workflow. Every `v2`/`v3` varies a file format, a transport, or an inserted side-effect step within that same workflow — none of them changes the workflow's structure. The programmatic predicates are sound and the `v3` hard dependencies genuinely detect a skipped tool (confirmed: that establishes the instances are *valid*, which is a separate question from whether they are *independent*).

**Consequence, binding on all future reporting:** report family-clustered. Never report a bare "N=13" (or whatever the count grows to) as if it were 13 independent samples for any claim that needs to hold *across* task structures — e.g. "B6 beats B3 in general." Per-family/per-structure breakdowns, or an explicit "N=5 structures" framing, are required alongside any flat instance count. `benchmark.tasks.cluster_summary()` is the enforced mechanism — every report script that prints a top-line instance count now also prints this.

Per-instance verdict:

| Instance | Verdict | `review_status` | `review_note` |
|---|---|---|---|
| `research_synth_v1` | **distinct structure** | `approved` | Distinct workflow: research → synthesize → publish. Baseline for its cluster. |
| `research_synth_v2` | within-family perturbation | `approved` | PDF parsing — file-format variation, same workflow as v1. |
| `research_synth_v3` | within-family perturbation | `approved` | Long-PDF summarization — inserted step (`summarize_pdf`) before `extract_facts`, same workflow as v1. |
| `repo_triage_v1` | **distinct structure** | `approved` | Distinct workflow: inspect → fix → test → commit. Baseline for its cluster. |
| `repo_triage_v2` | within-family perturbation | `approved` | Inserted migration side effect — same workflow as v1, one extra step. |
| `repo_triage_v3` | within-family perturbation | `approved` | Lint-before-test CI policy — inserted step (`run_linter`), same workflow as v1. |
| `inbox_workflow_v1` | **distinct structure** | `approved` | Distinct workflow: read → extract → schedule → reply. Baseline for its cluster. |
| `inbox_workflow_v2` | within-family perturbation | `approved` | PDF attachment — file-format variation, same workflow as v1. |
| `incident_response_v1` | **distinct structure** | `approved` | Distinct workflow: alert → investigate → correlate → remediate. Baseline for its cluster. |
| `incident_response_v2` | within-family perturbation | `approved` | Metrics instead of logs — data-source transport variation, same workflow as v1. |
| `incident_response_v3` | within-family perturbation | `approved` | Traces as extra evidence tool — inserted step (`query_traces`), same workflow as v1. |
| `data_pipeline_v1` | **distinct structure** | `approved` | Distinct workflow: locate → fetch → transform → validate → export. Baseline for its cluster. |
| `data_pipeline_v2` | within-family perturbation | `approved` | URL fetch instead of direct fetch — transport variation, same workflow as v1. |

All 13 are `approved` — the content and predicates are sound (this was reviewed, not assumed). What changed is *how they count*: none of the `v2`/`v3` rows count as an independent structure for a cross-task claim, regardless of their `approved` status. "Batch 1" (the three `v3` instances) is no longer `PENDING` as of this review — it is `approved`, with the same within-family-perturbation caveat as every other non-`v1` instance, existing or new.

---

## §4b scoping issue — raised for the plan, not resolved here

If the ~100-instance target is reached by adding more perturbations to these same 5 structures (e.g. "5 structures × 20 perturbations = 100"), **the effective N for any cross-task-structure claim stays at 5, no matter how large the perturbation count gets.** Perturbations are still worth having — they test format/transport robustness and the task-evolution/staleness question directly (see the `v3` design rationale below) — but they cannot substitute for structural diversity, and the central comparison this paper needs to hold up (B3 vs. B6, static vs. learned) is exactly the kind of claim that needs to hold *across* task structures, not within one.

See `EXPERIMENTAL_PLAN_v0.2.md` §4b for the proposal and cost estimate to add 5-10 genuinely distinct workflow families. Not decided yet — flagged for review alongside this manifest.

---

## Design rationale (why the perturbations exist, unchanged from before review)

Three of the `v2`/`v3` perturbations make a pre-existing "plausible distractor, never required" tool (`summarize_pdf`, `run_linter`, `query_traces`) genuinely load-bearing for the first time — `config/capability_profiles.yaml` includes each defensively but no `v1`/`v2` variant needed it. This directly exercises the paper's task-evolution question (`EXPERIMENTAL_PLAN_v0.2.md` §1) *within* a structure: a static profile authored against `v1`/`v2` has no way to know `v3` needs the tool it correctly excluded before. That is real and worth keeping — it is just not, on its own, evidence about whether learned governance generalizes *across* structures, which is the separate, larger question §4b raises.

| Instance | What's new | Real dependency (not cosmetic) |
|---|---|---|
| `research_synth` v3 | `summarize_pdf` required before `extract_facts` | `extract_facts_v3` raises if content isn't marked summarized; verified by check 3 |
| `repo_triage` v3 | `run_linter` required before `run_tests` | `run_tests_v3` reads `ws["lint_passed"]` by bracket access; verified by check 3 |
| `incident_response` v3 | `query_traces` required before `correlate_events` | `correlate_events_v3` reads `ws["trace_evidence"]` by bracket access; verified by check 3 |

**Validation** (`python3 -m pytest tests/test_task_families.py -v`, and directly via `benchmark.validate.validate_task`): all 13 instances pass all 5 checks, including check 3 (the load-bearing one).

---

## Not yet started

- `inbox_workflow` and `data_pipeline` v3 (or equivalent): deprioritized pending the §4b decision — adding a third perturbation to two more structures doesn't address the effective-N problem the review just raised, and may not be the right next move at all depending on how §4b is resolved.
- New, genuinely distinct workflow families (§4b): not started, cost estimate in `EXPERIMENTAL_PLAN_v0.2.md` §4b, decision pending.
