# Benchmark expansion manifest — Track A

Tracks progress toward the ~100-instance target (`EXPERIMENTAL_PLAN_v0.2.md` §4a). Each batch is listed with what it adds, its difficulty category, its `validate.py` result, and its review status — mirroring `router_training/schema.py::TrainingExample`'s `review_status` field, which the benchmark's `Task`/`GroundTruth` dataclasses don't carry natively, so this file is the tracking mechanism for benchmark instances instead.

**Standing rule, same as §4a: no batch below is usable in any *reported* baseline run until its `review_status` moves past `pending`.** All five `validate.py` checks passing is necessary, not sufficient — per §4a, a human reading the actual task/ground-truth/oracle-plan content, not just the check output, is required for `approved`.

---

## Batch 1 — 2026-09 (3 new instances: 10 → 13)

**Difficulty category:** content-dependent phase requirements / task evolution — specifically, a fourth pattern not yet exercised: **a pre-existing "plausible distractor, never required" tool becomes genuinely required in a new variant.** Three families already had a named, documented distractor sitting unused in `FULL_TOOL_REGISTRY` (`summarize_pdf`, `run_linter`, `query_traces`) — each flagged in that family's own module docstring as something `config/capability_profiles.yaml` includes defensively but no existing variant needs. Batch 1 adds one `v3` per family that makes exactly that distractor load-bearing.

This is not cosmetic difficulty — it's the paper's actual scientific question (`EXPERIMENTAL_PLAN_v0.2.md` §1) in miniature: a static profile authored against v1/v2 has no way to know v3 needs the tool it correctly excluded before. It directly tests whether a learned policy handles task evolution better than a static one, once Track C's gate (§3b) is passed by a real trained policy.

| Instance | What's new | Real dependency (not cosmetic) |
|---|---|---|
| `research_synth` v3 | `summarize_pdf` required before `extract_facts` | `extract_facts_v3` raises if content isn't marked summarized; verified by check 3 |
| `repo_triage` v3 | `run_linter` required before `run_tests` | `run_tests_v3` reads `ws["lint_passed"]` by bracket access; verified by check 3 |
| `incident_response` v3 | `query_traces` required before `correlate_events` | `correlate_events_v3` reads `ws["trace_evidence"]` by bracket access; verified by check 3 |

**Validation** (`python3 -m pytest tests/test_task_families.py -v`, and directly via `benchmark.validate.validate_task`): all three pass all 5 checks, including check 3 (the load-bearing one). v1/v2 for all three families re-verified unaffected (no regression) — same command, same result as before this batch.

**Authorship:** drafted by Claude (Sonnet 5), following the existing difficulty-category pattern already established in the original 10 instances, reusing each family's own already-documented "distractor" tool rather than inventing a new one — kept deliberately close to the existing design to minimize the risk of introducing a new, unreviewed pattern on top of an already-large batch.

**Review status: PENDING.** Per §4a, `validate.py` passing is necessary but not sufficient — a human has not yet read these three instances' `initial_prompt`, `phases_for()`, `make_ground_truth()`, and `build_oracle_plan()` and confirmed by hand that the new required tool is genuinely minimal/necessary and that the oracle plan is what a competent human would actually do. Not included in any baseline run reported in `RECONCILED_STATE_v0.2.md` until that happens.

**Progress: 13/~100 instances (5 families × up to 3 variants each; 2 families — `inbox_workflow`, `data_pipeline` — still at 2 variants, no `v3` yet).**

---

## Not yet started

- `inbox_workflow` and `data_pipeline` v3 (or equivalent): neither family had a pre-existing named distractor lying around the way the other three did, so a batch-1-style extension needs a genuinely new distractor tool invented and threaded through `tool_metadata.py`/`capability_profiles.yaml`, not just an existing one flipped to required. Slightly more design work; deferred to batch 2 rather than rushed alongside batch 1.
- Batches 2+ toward ~100 instances: not started. Given the per-instance design and validation effort batch 1 took (three genuinely load-bearing dependencies, each independently checked against all 5 validation checks, not template-stamped), reaching ~100 instances at the same quality bar is many more batches, each needing the same review-before-use discipline — not a single mechanical expansion pass.
