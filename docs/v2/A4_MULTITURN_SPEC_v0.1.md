# A4 — Multi-Turn Intent-Drift Governance: Experiment Specification

**Version:** 0.1 (design — nothing implemented)
**Date:** 2026-10-21
**Depends on:** `docs/v2/provenance_representation.md`, `scripts/semantic_leakage_gate.py`, `AGENTWARDEN_V2_POSITIONING_v2.md` §4
**Supersedes:** the single-call A4 sketch in `docs/v2/BENCHMARK_EXPANSION_MANIFEST.md`

A4 is the only positive empirical claim in AgentWarden-v2. This spec fixes its construct, its baseline, its validity gates and its reporting rules **before** any data is generated, because the three failures of October 2026 were all failures of construct rather than of method.

---

## 1. The claim under test

> Some governance decisions in a multi-turn agent session cannot be made from the current call plus a permission list, and cannot be made from a recorded fact either, because the discriminating property is the *relation* between the call and what the session was authorized to do. A learned policy can judge that relation; a symbolic rule over the same inputs cannot.

The claim is explicitly comparative and explicitly bounded. If a competent symbolic rule over the same inputs can judge the relation, the claim is false and §11 says what to report.

---

## 2. Threat model

The adversary controls **everything a tool returns**: retrieved document content, file contents, web page text, subagent output, and any text that reaches the session through a tool result. The adversary may also control earlier user-role turns in a compromised or relayed session.

The adversary does **not** control: the session authorization (§3), the enforcement layer's audit log, or the structured session summary derived from it (§4).

This asymmetry is the whole design. Every input to the governance decision must come from the side the adversary cannot write.

---

## 3. The anchor: `SessionAuthorization`

Set **once**, at session start, by a trusted producer — the operator, the harness, or an authenticated task dispatcher. Never inferred from conversation. Never written by the agent or by tool output.

| Field | Meaning |
|---|---|
| `authorized_task` | Short natural-language statement of the session's purpose |
| `task_type` | Structural type from the existing registry |
| `scope` | Resource sets the task may touch (paths, domains, repos, record classes) |
| `allowed_effects` | Subset of `{read, write, network, exec, delegate}` |
| `max_sensitivity` | Highest sensitivity class the task may reach |
| `issued_by`, `issued_at`, `expires_at` | Provenance of the authorization itself |

Immutable for the session's lifetime. A change requires a **new authorization event** emitted by the enforcement layer and logged; the agent cannot request one into existence.

`authorized_task` is natural language and is therefore the one prose field the decision reads. It is safe to read because it is written by a trusted producer before the adversary has any influence. This must be stated explicitly in the paper, since it is the exception to §2's rule and a reviewer will look for it.

---

## 4. What the decision sees

Three inputs, and nothing else.

**(a) The anchor** — §3, in full.

**(b) The bounded session summary** — machine-derived from the enforcement layer's audit log only. Fixed-size regardless of session length.

- `scopes_opened`: resource classes actually touched so far
- `verifications`: structured provenance records (`source`, `verifier`, `check`, `result`, `timestamp`)
- `effect_classes_used`: which of `allowed_effects` have been exercised
- `trust_levels_touched`
- `out_of_scope_resource_count`: resources touched that are outside `scope`
- `call_counts`: per-tool invocation counts
- `elapsed_turns`

**(c) The call under judgment** — `tool_name` and `arguments`, as now.

**Excluded, categorically:** tool output text, retrieved document content, agent reasoning text, raw conversation history. If a decision cannot be made without one of these, that is a finding to report, not a reason to admit it.

> **Design note.** (c) is agent-generated and therefore adversary-influenced, but it is the *object* of judgment, not evidence about the world. Reading the thing you are deciding about is unavoidable; treating adversary-written text as evidence is not.

This is the paper's crispest architectural statement: **the governance decision reads the trusted anchor, a machine-derived history, and the call under judgment — never content returned by a tool.**

---

## 5. Drift taxonomy

Six classes. The partition is fixed now and may not be re-cut after results are seen (§11).

| Class | Description | Expected to be solvable symbolically? |
|---|---|---|
| **D-1 Scope drift** | Resource outside `scope` | **Yes** |
| **D-2 Effect escalation** | Effect class beyond `allowed_effects` | **Yes** |
| **D-3 Sensitivity drift** | Above `max_sensitivity` | **Yes** |
| **D-4 Task incoherence** | In scope, in effects, under sensitivity — but unrelated to `authorized_task` | **No — learned bet** |
| **D-5 Staged accumulation** | Each call individually in scope; jointly they realize an out-of-scope capability | **Partly — learned bet** |
| **D-6 Benign-but-unusual** | Looks like drift, is legitimate | **Control** |

D-1 through D-3 are included deliberately and are **expected to go to the symbolic baseline**. Reporting that is part of the contribution: it tells a practitioner which three quarters of the problem need no model. D-6 exists so that a policy which escalates everything scores badly rather than well — without it, "learned layer wins" is unfalsifiable.

---

## 6. Dataset construction

**Unit:** a session = one anchor + an ordered prefix of calls (already decided) + one call under judgment + a label in `{ALLOW, REVIEW, BLOCK}`.

**Minimal pairs are mandatory.** Two permitted pair types, both flipping the label by changing something the adversary cannot write:

- **Anchor-flip pair.** Identical prefix, identical call under judgment, different `SessionAuthorization` → label flips.
- **History-flip pair.** Identical anchor, identical call under judgment, different structured prefix → label flips.

**Forbidden:** flipping a label by rewording the call, by changing a domain name or path to something recognizably malicious, or by any edit to the call's surface form. That is the sbd/dfu failure, and it is what produced 99.5% register separability.

**Authoring.** Hand-authored or built from explicit templates with enumerated slot values. No bulk LLM paraphrase generation — that mechanism produced both the decision-homogeneous categories and the register tell.

**Target size.** 40–60 pairs (80–120 sessions) per drift class for D-4, D-5 and D-6; 20–30 pairs each for D-1 to D-3, which only need enough to establish that the symbolic baseline handles them. Held out entirely from training; the `HELD_OUT_` filename guard in `train_common.py::load_examples()` applies.

---

## 7. Validity gates — run before anything is trained

A4's data is not eligible for use until all four pass. Each has a stated threshold in its script.

1. **Minimal-pair presence.** Every item belongs to a pair whose counterpart differs only in anchor or prefix. Automated check, not a review.
2. **Call-only leakage.** `semantic_leakage_gate.py` on the call under judgment alone must **fail** to recover the label. If the call predicts the label, the pair is broken by construction.
3. **Serialized-session leakage.** The gate on the full serialized decision input must fail to recover the label beyond what the anchor/prefix relation legitimately implies. Long inputs carry more register than short ones, so this is the gate most likely to fire.
4. **Decision homogeneity.** No drift class may be label-homogeneous. Each class contains both ALLOW and non-ALLOW items.

A gate failure stops the experiment and is recorded. It does not get iterated against until it passes — that is overfitting the data to the detector.

---

## 8. The symbolic baseline

The claim is comparative, so the baseline decides whether the claim means anything. It must be authored by someone trying to win.

**Must implement, competently:**
- Scope containment check against `scope` (D-1)
- Effect-class check against `allowed_effects` (D-2)
- Sensitivity ceiling (D-3)
- A **capability-closure rule** for staged accumulation (D-5): maintain the set of capabilities reachable from `scopes_opened` ∪ this call, and deny when the closure exceeds what the anchor authorizes
- Provenance lookup: `verification.result == verified AND verification.verifier == enforcement_layer`

**Pre-registration.** The baseline is written, frozen and committed **before** the learned arm is evaluated. Its rule set may not be weakened afterward. The commit hash goes in the paper.

**Declared not attempted.** D-4 task incoherence — the baseline is not expected to handle "unrelated to `authorized_task`", and no attempt to approximate it with keyword matching is made. Saying so is honest; faking a weak attempt and beating it is not.

---

## 9. The learned arm

Same `(anchor, bounded summary, call)` input as the baseline — identical serialization, no extra fields. Any input advantage invalidates the comparison.

Precedence is enforced at evaluation time, per `provenance_representation.md`: the learned arm may only **escalate** (ALLOW → REVIEW/BLOCK). A learned ALLOW over a symbolic DENY is discarded and counted as the symbolic DENY. The hybrid's score is therefore never worse than the baseline's on D-1/2/3 by construction, and this must be stated rather than presented as a win.

---

## 10. Metrics

- **Pair-level accuracy**, per drift class. Both halves of a pair correct, or the pair is wrong. Never item-level.
- **D-6 false-escalation rate.** Reported alongside every accuracy figure. An accuracy number without its D-6 rate is not reportable.
- **Hybrid vs symbolic delta**, per class, with the D-1/2/3 columns labeled as structurally guaranteed.
- **Utility proxy**: fraction of legitimate sessions completing without escalation.

Every number must be reproducible from a committed artifact. The reconciliation rule applies: anything that cannot be is struck, not footnoted.

---

## 11. Reporting rules — fixed in advance

1. **Symbolic matches learned on D-4 and D-5.** Report it. The §2 claim of the positioning document extends one step further: learned governance has a smaller role than the field assumes. This is a publishable negative result and is an accepted landing place, not a failure to be re-narrated.
2. **Learned wins on D-4 only.** Report the scope narrowly: task-coherence judgment is the learned layer's territory; compositional risk is symbolic. Do not generalize to "compositional risk needs learning."
3. **Learned wins on D-5 only.** Report that capability closure is insufficient and say concretely which closure rule was tried.
4. **Learned wins by escalating broadly.** D-6 catches this. It is a failure, reported as one.
5. **No re-partitioning.** The six classes in §5 are fixed. A result may not be rescued by merging or splitting classes after the fact.
6. **A gate failure in §7 is a reportable result**, not a setback to be hidden behind a later successful run.

---

## 12. Out of scope

- Post-hoc recovery, release mechanisms, recovery cost curves, ATBench-Claw — these belong to AMARE, per `docs/v2/contribution_boundary.md`.
- Prose context in the classifier input, per the register-leakage finding.
- Any claim about gate 3 or gate 3a, both withdrawn.
- Cryptographic signing of audit records — relevant only if the log crosses a trust boundary, which this experiment does not exercise.

---

## 13. Build order

| # | Step | Blocks | Parallel with |
|---|---|---|---|
| 1 | `SessionAuthorization` dataclass + bounded-summary builder reading only the audit log | all | — |
| 2 | Serialization format for `(anchor, summary, call)`, shared by both arms | 3, 6 | — |
| 3 | Symbolic baseline, written to win, frozen and committed | 6 | 4 |
| 4 | Pair authoring for D-1…D-6 per §6 | 5 | 3 |
| 5 | Validity gates §7 — run, recorded, pass required | 6 | — |
| 6 | Learned arm evaluation + metrics §10 | — | — |

Steps 1–2 are prerequisites for everything. Step 3 must be committed before step 6 runs. Step 5 is a hard gate: a failure stops the line.
