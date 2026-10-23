# A4 — Black-Box vs White-Box Multi-Turn Governance: Experiment Specification

**Version:** 0.2 (design — supersedes v0.1 entirely)
**Date:** 2026-10-21
**Depends on:** `docs/v2/provenance_representation.md`, `docs/v2/RELATED_WORK_multiturn_v1.md`, `scripts/semantic_leakage_gate.py`
**Implemented so far:** `SessionAuthorization`, `BoundedSessionSummary`, `VerificationRecord`, `build_decision_input()` (commit `056dfab`)

---

## 1. What changed from v0.1, and why

Two findings landed after v0.1 was written. Each invalidates a different part of it.

**(a) The literature.** A4 v0.1's claim — a learned policy can judge intent drift where a symbolic rule cannot — is substantially established, and its architecture is substantially published.

- **IntentCap** ([arXiv:2609.14631](https://arxiv.org/abs/2609.14631), Sept 2026) is v0.1 §3–§5: capabilities scoped to task intent rather than session lifetime, field-level source ownership so no context source can fill another's fields, leases that narrow and never widen, an LLM generating leases and a *deterministic checker* enforcing them. Its gap: no quantitative evaluation.
- **Representation Transitions** ([arXiv:2610.00400](https://arxiv.org/html/2610.00400), Oct 2026) is v0.1's result: per-step monitors miss harm accumulating across individually-permissible turns; rule-based AgentSpec "never fires" on their decomposition set (ASR 0.80–1.00); their cumulative monitor achieves ASR 84%→25% at 12% realized false-alarm rate, utility 93%→85%, 0.14–0.56s/step.
- **TaskTracker** ([arXiv:2406.00799](https://arxiv.org/abs/2406.00799), SaTML 2025) is the canonical task-drift-from-activations result, with activation data released.

Re-deriving these with 40–60 hand-authored pairs per drift class would spend the whole runway to reproduce known findings.

**(b) The infrastructure.** `AuditLogger.log_pipeline_result()` is a single `logger.info()` emitting `session_id`, `tool_name`, `decision`, `latency_ms`. It is not a persisted, queryable, session-keyed store. Six of v0.1 §4(b)'s seven fields are unavailable, each for a different missing reason: no persisted store, no scope concept in the data model, no structured verification record, no effect-class taxonomy, `trust_level` never written to the log, and no turn counter. Building all six on spec is a quarter of engineering before a single measurement exists.

**The common lesson.** v0.1 assumed the expensive thing (hand-authored data, full session state) and the cheap thing (a known result) were the other way round. v0.2 inverts both: measure with what exists, on benchmarks that exist, and build only what the measurement justifies.

---

## 2. The claim under test

> Every effective multi-turn governance result to date reads the acting model's internal activations. Production agents overwhelmingly call hosted models through a gateway, where activations are unavailable. **Can a black-box governance layer — trusted anchor, structured session state, call under judgment, no model internals — match a white-box activation probe on multi-turn drift, at matched false-alarm rate?**

The question is unanswered, deployment-critical, and publishes either way:

- **Black-box matches white-box** → gateway architectures are viable; the governance layer needs no model access, which is a strong positive result with immediate practical consequence.
- **Black-box does not match** → effective multi-turn governance structurally requires white-box access, so every proxy and gateway deployment in production is limited by construction. Stated with numbers and a diagnosed cause, this is the stronger and more surprising paper.

**What makes it ours rather than a cross-paper comparison:** the white-box results use locally hosted open models. We have the same class of model and the HPC capacity to run both arms **on the same model, the same benchmark, the same false-alarm budget**. Nobody has run that controlled comparison; the existing numbers come from different papers with different setups and are not comparable.

---

## 3. Threat model

Unchanged from v0.1. The adversary controls everything a tool returns — retrieved documents, file contents, web pages, subagent output — and may control earlier user-role turns in a relayed session. The adversary does not control the `SessionAuthorization`, the enforcement layer's audit log, or state derived from it.

Every input to the governance decision comes from the side the adversary cannot write, with one stated exception (§5).

---

## 4. Prior-art placement — mandatory framing

The paper must place these before claiming anything:

| Work | What it establishes | What we must not claim |
|---|---|---|
| IntentCap | Task-intent-anchored capability scoping; source-ownership; narrow-only leases; deterministic enforcement | The architecture. Ours is the same family; our contribution is the evaluation IntentCap lacks |
| Representation Transitions | Cumulative drift beats per-step monitors; rule-based monitors never fire on decomposition attacks | That per-step monitoring is insufficient — that is theirs, we cite it |
| TaskTracker | Task drift is detectable from activation deltas | Novelty for drift detection as such |
| STAC | Sequential tool-attack chaining; 483 cases; ~0.5% prompt harmfulness; 91.2% ASR by T+2 | A novel compositional attack construct |
| Local Monitors / Compositional Harm | Formal bound: a single-view local detector cannot separate locally-benign fragments beyond total variation | The impossibility argument |
| Three-Source Permissions | Symbolic intersection bounding a learned component | Hybrid precedence as a novel architecture |

Claiming the design as new, a month after IntentCap, would be read as unawareness. Claiming the evaluation it lacks is both honest and sufficient.

---

## 5. The anchor

`SessionAuthorization`, implemented in `056dfab` as a frozen dataclass: `authorized_task`, `task_type`, `scope`, `allowed_effects`, `max_sensitivity`, `issued_by`, `issued_at`, `expires_at`. Set once at session start by a trusted producer; never inferred from conversation; a change requires a new authorization event emitted by the enforcement layer.

`authorized_task` is natural language and is the **one prose field the decision reads**. It is safe because a trusted producer writes it before the adversary has any influence. This exception must be stated explicitly in the paper; a reviewer will look for exactly it.

Cite IntentCap's narrowing rule here. This is the same property arrived at independently, and saying so costs nothing.

---

## 6. Decision input — tiered, not all-or-nothing

v0.1 specified one summary requiring six missing subsystems. v0.2 specifies three tiers, and **S0 is what runs first**.

**S0 — available today.** Anchor + `call_counts` (real per-tool tally) + `invocations_observed` (named for what it is: a tool-call count, not a conversational turn count) + the call under judgment. No fabricated fields; `build_bounded_summary()` continues to raise `AuditLogInsufficientError` rather than approximate.

**S1 — cheap additions, built only if S0 shows signal.** A persisted, session-keyed audit store (prerequisite for everything else); `trust_levels_touched` (the field exists on `GovernanceContext` and merely isn't logged); a real turn counter.

**S2 — expensive, built only if S1 is insufficient.** A scope concept in the data model, an effect-class taxonomy, and structured `VerificationRecord` emission. Each is a design decision in its own right, not a field to add.

**Excluded at every tier:** tool output text, retrieved document content, agent reasoning text, raw conversation history.

The tiering is itself a result. "Which state does black-box governance actually need?" is answered by which tier first carries signal, and that is a more useful answer than a single accuracy figure.

---

## 7. Benchmarks — no hand-authored pairs in v0

| Benchmark | Role |
|---|---|
| **STAC** ([2509.25624](https://arxiv.org/html/2509.25624v2)) | **Demoted 2026-10-23 — shortcut-audit reference point only, no longer primary.** Its trajectories remain static and pre-recorded, so it still *could* carry activation replay (arm 4) in principle, but §12a/§13a/§14 jointly establish there is no way to use STAC for A4's arms without a shortcut dominating the result: zero length-matched negatives exist at any usable scale (§13a, 0 of 471 cases), and tool identity alone reaches TPR=0.857 @ FAR=0.12 (§14) — well above what the matched-tool subset (30/471, far below a usable scale) could control for. STAC stays in the shortcut-audit table (§14) as a reference point and remains available for arm 1's per-step floor as a point of comparison, but is no longer the benchmark any A4 detection-capability result is drawn from |
| **ASEval** ([2605.22321](https://arxiv.org/abs/2605.22321), via its citation in [2610.00400](https://arxiv.org/html/2610.00400)) | **Promoted 2026-10-23 — primary, specifically the 233-task tool-matched subset (`docs/v2/RECONCILED_STATE_v0.2.md` §14a), replacing STAC.** Unlike STAC, this subset is constructed so tool identity cannot carry the label: arm 0 collapses from AUC=0.660 (full set) to AUC=0.501 (exact chance) on it, confirmed directly (§14a), and arm 1 (the existing per-step floor) sits at or below chance on both the full set and the subset (AUC 0.488 / 0.530) — meaning neither trivial baseline has already solved what a session-state arm (3) would need to add value over. 673 records across 233 tasks (balance: 45.8% attack, higher than the full set's 30.1% — disclosed in §14a, does not bias AUC/TPR-at-fixed-FAR). Whether this subset's size (233 tasks) is large enough for arm 2/3's own training is a separate, not-yet-answered question — promotion here is about *validity* (no shortcut to ride), not about having confirmed sufficient scale for training. **Not yet confirmed:** whether ASEval's turn-level data supports activation replay (arm 4) the way STAC's did — this requires running the chosen local model over ASEval's own trajectory text to extract hidden states, which has not been attempted. **Also surfaced by the same audit, not substituted for the above:** AgentHarm (`docs/v2/RECONCILED_STATE_v0.2.md` §14) shows an even cleaner shortcut profile on its full set with no restriction needed (tool-identity AUC 0.355, content-leakage gate PASS, 208/208 tasks tool-matched by construction) — it was not investigated for activation-replay feasibility or instructed as a promotion target, and is flagged here as a candidate worth the same scrutiny, not adopted unilaterally in ASEval's place |
| **MT-AgentRisk** (via [2610.00400](https://arxiv.org/html/2610.00400)) | **Secondary, gated on dataset access.** `CHATS-Lab/MT-AgentRisk` on HuggingFace requires a terms-of-use form (name/affiliation/email) that was not completed in this session — see `benchmark/a4/mt_agentrisk_adapter.py::MTAgentRiskDatasetNotAvailableError`. Its live-execution design (an OpenHands-controlled agent against sandboxed MCP servers) means the adapter can only emit the staged task instructions, never a recorded trajectory — there is no `interaction_history` equivalent to replay activations against, so it cannot carry arm 4 the way STAC's static trajectories could (and ASEval's may, pending the confirmation named in that row) |
| **AgentDojo** | **Utility and ASR-comparability only — explicitly excluded from detection evidence.** Mandatory for comparable utility-cost numbers and ASR figures every competitor reports; it does **not** contribute to any arm's detection-capability result. Reason, stated plainly: its call-only leakage (§9 gate 3) persists even after matching the tool between the benign and attack candidate (TF-IDF+LR balanced accuracy 0.789, `docs/v2/RECONCILED_STATE_v0.2.md` §12a) — unlike STAC's, where the matched re-run passes. A detection result that pooled AgentDojo cases in would be measuring that shortcut as much as the arm under test, and there is no coarsening or matching left to apply that would fix it (§9's amendment). ASEval's tool-matched subset is now the sole benchmark any detection-capability result is drawn from (§8; STAC was demoted 2026-10-23, see that row above) |
| **Cross-Session Threats** ([2604.21131](https://arxiv.org/html/2604.21131v1)) | **Not usable at the tool-call level.** Obtained and inspected directly (`intrinsec-ai/cstm-bench` on HuggingFace, no credentials) as part of the 2026-10-22 shortcut audit (`docs/v2/RECONCILED_STATE_v0.2.md` §14): every session is free-form natural-language chat text, with no `tool_name`/`arguments` field anywhere across all 54 scenarios checked. It cannot feed the A4 decision-input pipeline (§6) or any gate/arm in this spec as currently scoped. If the anchor's session-lifetime property is tested against it, that would have to be at the narrative/message level, a different and unscoped piece of work, not a drop-in secondary benchmark |
| Hand-authored pairs | **Suspended.** Revisit only if the benchmarks prove unable to express a needed condition |

Anchors are not supplied by these benchmarks and must be derived. The derivation procedure must be mechanical and stated — e.g. the benchmark's declared task becomes `authorized_task`, with `scope`/`allowed_effects` inferred by a fixed rule — and must not be hand-tuned per case, which would smuggle the label into the anchor.

**Citation vs. reproduction.** "Rule-based monitors never fire on decomposition attacks" (ASR 0.80–1.00) is 2610.00400's own result, against their own decomposition set, under their own monitor. It is cited here, not reproduced — we do not have that set (see MT-AgentRisk's row above). Arm 1 (§8) instead establishes **our own** per-step floor, measured directly on STAC (§13) and, since the 2026-10-23 promotion above, on ASEval's full set and tool-matched subset too (§14a) — AUC 0.488/0.530, at or below chance on both. These are AgentWarden's own per-step classifier numbers against each benchmark's own chains, not a reproduction of 2610.00400's figure against MT-AgentRisk's. None of the three are interchangeable and must not be conflated in any write-up.

**AgentDojo coarse-anchor requirement.** AgentDojo's adapter (`benchmark/a4/agentdojo_adapter.py`) derives `allowed_effects` from each task's `ground_truth` call sequence — informative, unlike STAC's and MT-AgentRisk's deliberately uninformative `ALL_EFFECTS` (`benchmark/a4/common.py`), because AgentDojo is the one benchmark where that derivation isn't confounded by the benchmark's own construction (§8's arm-4 discussion; see `agentdojo_adapter.py`'s docstring). When AgentDojo cases are pooled into the A4 arms comparison (§8, §10), this anchor **must be coarsened to `ALL_EFFECTS`** before pooling, so every benchmark's anchor carries the same informativeness going into the comparison — otherwise a pooled result could differ because AgentDojo's anchor told the arms more, not because the arms themselves differ, which would be a confound masquerading as a finding. The informative, ground-truth-derived anchor is kept for AgentDojo's own standalone utility/cost role (§13 step 2, independent of A4); only the copy pooled into A4's arms comparison is coarsened. This requirement now applies only to AgentDojo's utility/ASR-comparability role (the row above) — there is no detection-evidence pooling for it to confound, since that role was removed for a different, independent reason (persistent call-only leakage, not anchor informativeness).

---

## 8. Arms

All five run on the **same model** (arms 1–4; arm 0 needs no model), the **same benchmark split**, and are compared at **matched false-alarm rate**.

0. **Shortcut baseline.** Sees only the call's tool name and its position in the sequence — no arguments, no anchor, no session history content, nothing else. Added 2026-10-21, after gate 3 (§9) found that exactly this information predicts BENIGN/ATTACK above chance on STAC (unmatched) and on AgentDojo (matched and unmatched). Not a competitor arm 1–4 are trying to beat for its own sake: it exists so the shortcut gate 3 found has a measured strength, not an assumed one. Every contender arm (2–4) must exceed it at matched false-alarm rate (§11) to be reported as a result at all.

   **Position feature corrected 2026-10-22: index-from-start, not "final step or not."** The original wording here — "final step or not" — is an index-from-end concept: knowing a call is the session's *last* one requires knowing no further call follows it, which is knowledge of the future a real-time monitor evaluating the current call does not have. It was an oracle feature from the start, not something this measurement introduced. The position feature is `invocations_observed` — the number of calls already observed before this one, genuinely available at decision time (`benchmark/a4/arms.py::arm0_scores`'s `index_from_start`, now the default; `index_from_end_oracle` reproduces the original, oracle-inclusive measurement for the historical record only). Re-measured on STAC, the two variants are nearly identical (TPR 0.836 vs. 0.843 @ FAR=0.12) — the oracle feature was doing almost no work; tool identity alone already carried nearly all of it. See `docs/v2/RECONCILED_STATE_v0.2.md` §13a.

   **Not widened to cover argument content.** `docs/v2/RECONCILED_STATE_v0.2.md` §12c found that the call's own argument content — independent of which tool it is — carries additional, separately leaking signal on both STAC and AgentDojo. Arm 0 is deliberately *not* extended to include it: a tool-name-plus-position feature set widened to also see arguments is no longer a sub-floor distinct from arm 1 — it is arm 1, the per-step floor, which already judges the full call (tool + arguments) in isolation and is the correct, existing control for exactly that content. Giving arm 0 the same inputs as arm 1 would collapse the two into one measurement and remove the floor-beneath-the-floor arm 0 is meant to be. Arm 0 stays tool identity + position, full stop; argument-content leakage is arm 1's territory to be measured against, not arm 0's to absorb.
1. **Per-step floor.** The existing D2 classifier judging each call in isolation. Establishes the floor the literature predicts (near-chance on locally-benign chains).
2. **Black-box symbolic.** Rules over the S0/S1/S2 input, including a capability-closure rule for staged accumulation. Written to win, frozen and committed with its hash **before** any learned arm is evaluated; may not be weakened afterward.
3. **Black-box learned.** Same serialized input as arm 2, byte-identical (`build_decision_input()` plus its regression test). Precedence enforced at evaluation: a learned ALLOW over a symbolic DENY is discarded and counted as the DENY.
4. **White-box reference.** A difference-of-means probe on hidden-state deltas, per 2610.00400, on the same local model. This is the ceiling the black-box arms are measured against, reproduced internally rather than quoted across papers.

Arm 4 is what makes the comparison controlled. If it cannot be reproduced to within a reasonable margin of the published numbers, say so and report the comparison as bounded by that failure rather than proceeding as if the ceiling were established.

Arm 0 is what makes the comparison honest about shortcuts. It is evaluated first, on the same split as everything else, and its own number is reported alongside every other arm's — never silently subtracted out or used only as an internal sanity check.

---

## 9. Validity gates

Run before any arm is trained or tuned. Thresholds stated in each script.

1. **Serialized-input leakage — scope corrected 2026-10-21: excludes the call under judgment.** `semantic_leakage_gate.py` on the serialized decision input, **minus the call under judgment**, must fail to recover labels. The anchor + `call_counts` + `invocations_observed` portion is tested; the `call` field is not, and never was meant to be — see the correction below for why.

   **This gate was mis-specified, not failed, and the correction is not the same move as gate 3's amendment below — the two must not be blurred together.** The original wording ("the full serialized decision input must fail to recover labels") tested an impossible condition: any well-formed governance input necessarily contains the call under judgment, and an attack call *must* differ in content from a benign call for there to be anything to govern at all — a gate that fails whenever the call's own content is label-predictive is not detecting a flaw in the input design, it is restating the fact that BENIGN and ATTACK calls are not the same call. Gate 3 (below) is the opposite situation: it found a *real* shortcut — the call's tool identity and position predicting the label on their own, a property worth disclosing and measuring (arm 0) because an arm could win on it without having learned anything about session-level drift. Gate 1, by contrast, was never measuring a real property of the input; it was asking a question with no coherent PASS state as originally written. Correcting the gate's scope is not "converting a real finding into a measured baseline" the way gate 3's amendment did — it is removing a test that could never have passed, for any input design, on any benchmark.

   Re-run with the call under judgment excluded entirely (anchor + `call_counts` + `invocations_observed` only — `docs/v2/RECONCILED_STATE_v0.2.md` §12c's SESSION-STATE-ONLY construction, which already measured exactly this as part of localizing gate 1's original, now-superseded FAIL): STAC 0.148, AgentDojo 0.149 TF-IDF+LR balanced accuracy, both **PASS**, consistent with — and no larger than — gate 2's anchor-only numbers, which is expected since `call_counts`/`invocations_observed` are identical between the BENIGN and ATTACK instance of every pair by construction and so carry zero information about the label beyond what the anchor alone already carries. **Gate 1 now passes, correctly, as its intended scope.** The original full-input numbers (STAC 0.745, AgentDojo 0.722, both previously recorded as FAIL) are kept as the historical record in `docs/v2/RECONCILED_STATE_v0.2.md` §12/§12c — struck as a verdict on the corrected gate, not deleted, since they remain the accurate record of what the mis-specified test actually measured.
2. **Anchor-only leakage.** The derived anchor alone must not predict the label. If it does, the derivation procedure is smuggling ground truth.
3. **Call-only leakage — disclosed property with a mandated control, not a blocking gate.** *Amended 2026-10-21, after this gate failed and before arm 0 or any other arm had been built or run; the commit that makes this amendment is the evidence of that order, not a retrofit written to explain away an already-seen arm result.*

   Originally specified as blocking: "the call under judgment alone must not predict the label on the chain sets; STAC reports ~0.5% prompt harmfulness, which predicts this should pass; verify rather than assume." It was verified, not assumed, and it did not pass: the call alone predicts BENIGN/ATTACK well above chance on STAC unmatched (TF-IDF+LR balanced accuracy 0.845) and on AgentDojo both unmatched (0.928) and matched on tool identity (0.789) — see `docs/v2/RECONCILED_STATE_v0.2.md` §12/§12a for the full numbers and construction. STAC's own matched re-run (0.190, the 29 cases with a genuine within-task, same-tool negative) is the one place the leak disappears.

   **Why blocking is the wrong response, stated in full.** The gate's actual purpose was never "no signal of any kind may exist in the call under judgment" — it was to prevent a shortcut (tool identity, sequence position) from being misread as evidence of governance capability further downstream, e.g. an arm reported as having learned something about session-level drift when it had only learned "final-position calls to this tool are usually bad." Blocking achieves that by refusing to proceed at all. **Measuring achieves the same purpose more directly: arm 0 (§8)**, which sees only tool identity and position and nothing else, turns the shortcut's strength into a reported number instead of an assumption anyone has to take on faith, and §11's new reporting rule makes every other arm's result conditional on beating that number at matched FAR. That is a strictly stronger discipline than a pre-training gate: it is enforced on every arm's actual result, not checked once on the raw data and then trusted for everything built afterward.

   The 29 STAC cases with a genuine within-task, same-tool matched negative (`docs/v2/RECONCILED_STATE_v0.2.md` §12a) are retained as a separate, clean subset for exactly this reason: the shortcut is absent there, so any arm's result on that subset is informative on its own terms and should be reported alongside the main result, not folded into it or discarded because the main set carries the shortcut.

   This amendment does not reopen gates 2 or 4, and is a distinct move from gate 1's correction above (see gate 1's own text for why the two must not be read as the same kind of change) — gate 1's resolution does not retroactively soften gate 3's: gate 3 found a real, measured shortcut and converted blocking into disclosure-plus-control; gate 1's original form never tested anything real at all.
4. **No fabricated fields.** Automated assertion that no tier emits a field the audit log cannot supply.

Gates 1, 2, and 4 are blocking and all three now pass (gate 1 at its corrected scope, as of 2026-10-21). A failure of any of them stops the line and is recorded as a result. Gate 3's failure does not stop the line — per its amendment above, it is disclosed and controlled for via arm 0 (§8) and the reporting rule in §11, not blocked on.

---

## 10. Metrics

- **Primary reported quantity: the arm 3 − max(arm 0, arm 1) delta at matched FAR, not absolute detection performance.** Added 2026-10-21, corrected 2026-10-22. The 2026-10-21 version of this entry read "arm 3 − arm 1," on the assumption that arm 1 (the per-step floor) would be the stronger of the two trivial baselines. Measurement (`docs/v2/RECONCILED_STATE_v0.2.md` §13) found the opposite on STAC: arm 0 (TPR 0.836 @ FAR=0.12, `index_from_start` position feature) beats arm 1 (TPR 0.366) by a wide margin. A delta against whichever baseline happens to be weaker is not informative about session-state value — it is informative only if measured against the *strongest* trivial baseline, so that beating it cannot be explained by either shortcut. This is a correction of a mis-specified quantity, not a new finding about either arm being disclosed and controlled for (contrast gate 3's amendment, §9): the formula itself named the wrong baseline, the way gate 1 named the wrong scope, and is fixed for that reason. Arm 0 and arm 1's own absolute numbers are still given for context, not as the headline.
- **ASR reduction at matched false-alarm rate.** The FAR must be fixed across arms before measurement; 2610.00400's 12% realized rate is the natural reference point. An ASR number without its FAR is not reportable.
- **Benign utility**, reported for every arm at that same FAR.
- **Per-arm overhead**, wall-clock per monitored step. 2610.00400 reports 0.14–0.56s; a black-box arm that matches on accuracy but costs 10× is a different conclusion.
- **Tier at which signal appears** (S0/S1/S2) — the state-requirement result.
- **Attribution**, where available: which turn or call drove the decision.
- **Anchor informativeness held constant across pooled benchmarks.** Per §7's AgentDojo coarse-anchor requirement, any metric that pools cases across STAC/MT-AgentRisk/AgentDojo uses AgentDojo's coarsened (`ALL_EFFECTS`) anchor, never its ground-truth-derived one. A pooled number computed against the informative anchor is not reportable as an A4 arms result — it is a different, uncontrolled comparison and must be labeled as such if reported at all.

Reconciliation rule applies: any number not reproducible from a committed artifact is struck, not footnoted.

---

## 11. Reporting rules — fixed now

0. **Every contender arm (2–4) must exceed arm 0 (§8) at matched false-alarm rate to be reported as a result at all.** An arm that does not clear the shortcut baseline is reported as **no result** — not as a weak result, not with a caveat, not with its raw number given alongside arm 0's as if the two were comparable findings. This applies to arms 2–4 equally, including arm 4 (the white-box reference): a ceiling that does not beat the shortcut baseline is not a ceiling. Added 2026-10-21, together with arm 0 itself and gate 3's amendment (§9).

   **Scope corrected 2026-10-22: applies to contender arms 2–4, not to arm 1.** The original wording said "arms 1–4... equally," with no exception for arm 1. Measurement (`docs/v2/RECONCILED_STATE_v0.2.md` §13) showed this was a mistake, not a tolerable consequence: arm 1 (the per-step floor) scored below arm 0 on STAC, and applying rule 0 literally would disqualify arm 1's own number as "no result" — even though arm 1's weakness is exactly the predicted, intended-to-be-reported reference point §8 built the experiment around ("establishes the floor the literature predicts"). Arm 1 is a **reference point**, not a contender trying to clear a bar: its number is reported regardless of how it compares to arm 0, the same way a floor is reported even when a sub-floor turns out to sit above it. Arm 0 and arm 1 are both baselines against which contenders (2–4) are judged (§10's `max(arm 0, arm 1)`); rule 0 governs only the contenders. This is a correction of the rule's own stated scope, the same kind of fix as gate 1's correction (§9) — not a new disclosed property the way gate 3's amendment was, and the two must not be read as the same move.
1. **Black-box S0/S1 matches white-box at matched FAR.** Report it as the headline. Gateway architectures are viable; name the tier required.
2. **Black-box matches only at S2.** Report the infrastructure cost as the finding: black-box governance is possible but requires scope, effect and verification state that no current agent framework maintains.
3. **Black-box does not match at any tier.** This is the primary negative result and is reported as the headline, not buried. Required: a diagnosed cause, and the gap quantified at matched FAR.
4. **Symbolic matches learned on the black-box side.** Report it. The positioning document's §2 claim extends: the learned layer's role is smaller still.
5. **The white-box arm fails to reproduce.** Report the comparison as bounded; do not substitute published numbers from a different setup.
6. **No re-partitioning or post-hoc FAR selection.** The FAR is fixed before measurement, and arms are not re-tuned after seeing results.

---

## 12. Staged decision gates

The point of v0.2 is that each stage decides whether the next is worth paying for.

| Gate | Decision |
|---|---|
| **G1** — S0 on ASEval's tool-matched subset, arms 1–3 (updated 2026-10-23; was STAC) | Does any black-box signal exist at all? If none, S1/S2 are unlikely to rescue it; consider reporting the negative result early |
| **G2** — arm 4 reproduced | Is the ceiling established? If not, the comparison is bounded and that must be said |
| **G3** — S0 result vs ceiling | Build S1 only if S0 shows partial signal. Do not build S1 to rescue a null S0 without a reason to expect it to |
| **G4** — S1 result | Build S2 only if S1 narrows the gap. S2 is a quarter of work and needs evidence, not hope |

---

## 13. Build order

| # | Step | Blocks | Parallel with |
|---|---|---|---|
| 1 | STAC + MT-AgentRisk harness adapters; mechanical anchor derivation | all | 2 |
| 2 | AgentDojo harness (independent, mandatory regardless of A4) | — | 1 |
| 3 | Validity gates §9 on S0 inputs | 4,5 | — |
| 4 | Symbolic baseline, frozen and committed with hash | 6 | 5 |
| 5 | White-box reference arm (local model, HPC) | 6 | 4 |
| 6 | Per-step floor + black-box learned arm; metrics §10 at matched FAR | G1–G3 | — |

Steps 1–2 start now. Nothing in S1 or S2 is built until G3.
