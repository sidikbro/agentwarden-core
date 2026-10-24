# Paper Outline v1 — What Agent-Security Benchmarks Actually Measure

**Working title:** *Measuring the Wrong Channel: Adversary-Writable Signal in Agent Security Benchmarks*
**Target:** USENIX Security '27, Cycle 2 — registration 2027-01-19, paper 2027-01-26 (≈12 weeks)
**Type:** Measurement / evaluation paper, not a system paper
**Date:** 2026-10-24

---

## 0. The claim

> Current agent-security benchmarks cannot distinguish a robust authorization mechanism from a text-matcher, and they systematically favour the forgeable design.

Three findings support it, two measured and one argued-plus-measured:

1. **Attack actions are identifiable from tool identity alone** in five of six widely-used benchmarks (AUC 0.660–1.000).
2. **Where that artifact is controlled away, essentially all remaining signal is adversary-writable tool output** — 99.2% of above-chance discriminative power on ASEval's tool-matched subset.
3. **An authorization decision that reads adversary-writable text is forgeable by the adversary who wrote it** — therefore a benchmark whose only signal lives in that channel rewards defenses that cannot hold, and penalises defenses that refuse the channel on principle.

The consequence for practitioners is concrete: a defense scoring well on these benchmarks may be reading the attack's own text, and a defense that refuses to read attacker-controlled content — which is what provenance-based authorization requires — scores at chance on benchmarks that have no other signal.

---

## 1. Introduction

Frame from the practitioner's problem, not from our system's failure. Agent authorization mechanisms are proliferating (Progent, MiniScope, SEAgent, IntentCap, three-source permissioning) and are evaluated on a small set of shared benchmarks. If those benchmarks' signal lives in a channel the adversary writes, the whole comparison is unsound.

State the three findings and the n up front. State the positive existence proof up front too — AgentHarm is clean, by its authors' deliberate construction — so the paper reads as diagnostic and constructive rather than as a complaint.

**One paragraph on provenance:** AgentWarden-v2 was built to a threat model that excludes tool output from authorization decisions, because tool output is adversary-writable. That design choice is what made the measurement visible: a defense that refuses the channel scores at chance, which prompted the audit rather than a retune. The paper uses the system as the motivating case, not as the contribution.

---

## 2. Background and related work

**What is already established, and must be cited rather than claimed:**
- Enforcement cannot be prompted — FORTIS (arXiv:2605.09163), 10 models.
- Capabilities should follow task intent and context source; field-level source ownership; narrow-only leases; deterministic checking — IntentCap (arXiv:2609.14631).
- Per-step monitors miss harm accumulating across individually-permissible turns; rule-based monitors never fire on decomposition attacks — Representation Transitions (arXiv:2610.00400).
- Task drift is detectable from internal activations — TaskTracker (arXiv:2406.00799).
- A single-view local detector cannot separate locally-benign fragments beyond total variation — arXiv:2607.11751, Prop. 1.
- Symbolic intersection bounding a learned component — arXiv:2607.22445.
- Permission minimisation does not verify semantic correctness of in-permission calls — MiniScope §2.1.
- Token trigger bias in text-based defenses — arXiv:2601.07185 (ACL 2026).
- Defense decay across turns under adaptive pressure — STAC's own reasoning defense, ≥58.6% residual ASR.

**The gap:** none of this work audits whether the benchmarks it is evaluated on carry the signal they are assumed to carry.

---

## 3. Methodology

Three instruments, all already built and committed:

- **Shortcut probe.** Can tool identity alone separate attack from benign actions? Out-of-fold, AUC plus TPR at a fixed FAR of 0.12 (matched to 2610.00400's realized rate).
- **Semantic leakage gate.** Embedding clustering (AMI) plus TF-IDF+LR balanced accuracy; PASS requires labels *not* recoverable from text alone. Thresholds stated in-file, not re-derived per benchmark.
- **Channel ablation.** Decompose the action representation into call-derived and response-derived fields and attribute discriminative power to each.

**Discipline to state explicitly, because it is a contribution in itself:**
- Separability is evidence of an artifact only for comparisons that are *matched* — same task, same position, same tool. Separability between legitimately different things is expected. (We state this because our own first pass got it wrong.)
- A benchmark's attack/benign definition and the action-extraction procedure are reported per benchmark. The audit's credibility rests on these, not on the numbers.
- Any number not reproducible from a committed artifact is struck, not footnoted.

---

## 4. Finding 1 — tool-identity separability

| Benchmark | n | tool-id AUC | TPR@FAR=.12 | content gate | tool-matched |
|---|---|---|---|---|---|
| InjecAgent | 2,652 | 1.000 | 1.000 | FAIL | 1/1,054 |
| STAC | 1,249 | 0.939 | 0.857 | FAIL | 30/471 |
| AgentDojo | 365 | 0.850 | 0.692 | FAIL | 4/4 |
| ASEval | 2,183 | 0.660 | 0.396 | FAIL | 233/403 |
| Agent Security Bench | — | — | — | FAIL | — |
| **AgentHarm** | — | **0.355** | — | **PASS** | **208/208** |

**The headline example:** InjecAgent reaches exactly 1.000 because user tools and attacker tools are drawn from disjoint pools by design — verified against the raw tool-name sets. No content is needed to classify an action; the tool name is the label.

**STAC's construction:** `chain_length = executed_length + 1` in 482 of 483 cases, so the attack is always the next-and-final call. Zero of 471 cases admit a length-matched benign-final negative. Position is not merely correlated with the label — it is determined by it. (Note that position-from-end is an oracle feature unavailable at runtime; we report tool identity alone, which carries the signal regardless, 0.836 vs 0.843 TPR.)

**Benchmarks not obtainable, and why** — reported rather than approximated: Boiling the Frog, Agent-SafetyBench, ToolEmu, SHADE-Arena (live-execution or gated); Adaptive Adversaries, Cross-Session Threats (no tool-call schema); R-Judge (86% unstructured); ToolSword (no static tool-call data). This is itself a finding about reproducibility in the subfield.

---

## 5. Finding 2 — the residual channel

On ASEval's 233-task tool-matched subset:

| Representation | AUC | TPR@FAR=.12 |
|---|---|---|
| Tool identity only | 0.501 | — |
| Full action (tool name + response) | 0.888 | 0.740 |
| **Response text only** | **0.885** | **0.737** |
| Tool name + call arguments | *not constructible* | — |

Matching removes the tool-identity shortcut completely (0.660 → 0.501, exact chance). What survives is carried almost entirely by response text: 99.2% of above-chance power.

**A schema finding worth reporting:** ASEval has no call-arguments field at all — a turn is `{user, tool_response, tool_name, injection_in_user, injection_in_tool, injection_type}`. The ablation that would isolate call content is not constructible, which means **the benchmark cannot evaluate a defense that declines to read tool output.** Stated as a limitation of the benchmark, not of the defense.

---

## 6. Finding 3 — forgeability

Step 3 is currently an argument supported by others' measurements. It needs one experiment of our own (§11).

**The argument.** Authorization is a decision about whether an action is permitted. If the deciding evidence is text the adversary authored, the adversary controls the decision. This is the standard provenance requirement — authorization variables settable only by trusted producers (RACG), field-level source ownership (IntentCap) — applied to evaluation rather than to design.

**Others' supporting measurements.** STAC's reasoning defense decays from a 29.8% refusal rate to ≥58.6% residual ASR across three turns. Surface Heuristics (arXiv:2601.07185) shows a single trigger token moving false refusals by up to 50%. Both are consistent with text-conditioned defenses being brittle under adaptive pressure.

**Our experiment (§11):** paraphrase the injected text and re-measure the response-only monitor. If it collapses, forgeability is measured rather than argued.

---

## 7. What a valid benchmark requires

The constructive half, and the reason the paper is useful rather than merely critical.

**AgentHarm as existence proof.** Tool-identity AUC 0.355, the only content-gate PASS of six, and 208/208 tasks tool-matched — 171/208 (82.2%) of harmful/benign pairs use *identical tool sequences*, differing only in the stated goal. Its authors built this in. It is possible.

**Requirements we can state from the audit:**
1. Harmful and benign variants of the same task must use the same tools. Otherwise tool identity is the label.
2. The attack must not occupy a structurally privileged position in the sequence.
3. The attack action's *content* must not be separable from benign content by a bag of words — report the gate, don't assume it.
4. The schema must separate call-derived fields from response-derived fields, so a defense that declines adversary-writable channels can be evaluated at all.
5. Report the attack/benign definition and the action-extraction procedure.

**A caveat we must state ourselves:** AgentHarm is clean but carries harm in the task *request* — 73.1% of tasks use only mundane tool names, and harm is legible from the request alone. So it is the right venue for this audit and the wrong venue for evaluating session-state reasoning. Cleanliness and fitness are separate properties, and no currently available benchmark has both.

---

## 8. Implications

- Reported defense comparisons across these benchmarks are not sound without a shortcut control. Publishing a tool-identity baseline alongside results would cost authors nothing and is our principal recommendation.
- Utility-cost figures are not comparable across defenses operating on different channels. Our own system's −50pp utility against Progent's −3.1pp is an instance: different channels, compared as if commensurable.
- A real gap follows: **no currently available benchmark can evaluate an authorization mechanism that refuses adversary-writable input.** Building one is the natural follow-on and should be named as such rather than promised.

---

## 9. Limitations

State plainly, in the paper, not in a footnote:
- Six benchmarks, of which only four yielded usable per-action data for finding 1 and one for finding 2.
- Finding 2 rests on a single benchmark. It is the only one admitting a tool-matched subset of usable size.
- The shortcut probes are discriminative classifiers with label access; a guardrail model without label access cannot exploit the same regularities. The artifact bounds what *trained* monitors can claim, not what every monitor does. (This distinction must be explicit — otherwise our 0.845 reads as contradicting STAC's ~0.5% prompt-harmfulness figure.)
- Attribution of signal to a channel is not a robustness claim. §11's paraphrase experiment addresses this partially, not fully.
- Six benchmarks were unobtainable; their construction is unaudited and may be better or worse.

---

## 10. Artifacts

Everything is already committed on `v2/benchmark-harness`: `scripts/semantic_leakage_gate.py`, `benchmark/a4/shortcut_audit.py`, per-benchmark loaders with extraction documented in each docstring, and the reconciled results record in `docs/v2/RECONCILED_STATE_v0.2.md` §11b–§14c. Releasing the audit harness is the artifact contribution and is cheap, since it exists.

---

## 11. Remaining work

| # | Item | Effort | Blocks |
|---|---|---|---|
| 1 | **Paraphrase/forgeability experiment.** Perturb injected text on ASEval's matched subset, re-measure response-only monitor. **Both classes must be perturbed** or the paraphrase becomes the signal. | Days | §6 |
| 2 | Extend finding 1 to any further obtainable benchmark; retry gated ones with credentials (MT-AgentRisk, SHADE-Arena) | Days, mostly waiting | n in §4 |
| 3 | Fill AgentDojo and Agent Security Bench rows completely in the §4 table | Hours | §4 |
| 4 | Confirm AgentHarm's numbers with the same harness and report n | Hours | §7 |
| 5 | Write | Weeks | — |

**Not required:** the symbolic baseline, arms 1–4, the black-box/white-box comparison, any training. A4's arms are retired from this paper and recorded as future work contingent on a fit benchmark existing.

---

## 12. What this costs us

AgentWarden-v2 as a system contribution does not appear in this paper. The architecture was independently published (IntentCap, Sept 2026) and the multi-turn result was independently published (Representation Transitions, Oct 2026). What the system's development produced is the measurement apparatus and the finding, and that is what gets submitted.

This should be a deliberate decision, recorded. The system work is not wasted — it is what made the measurement possible, and it remains the basis for a later system paper once a fit benchmark exists, whether built by us or by someone acting on §7.
