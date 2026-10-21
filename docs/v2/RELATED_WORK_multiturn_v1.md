# Related Work — Multi-Turn Agent Governance, Intent Anchoring, Compositional Risk

**Version:** 1.0
**Date:** 2026-10-21
**Purpose:** Positions AgentWarden-v2 against the literature as of October 2026, and records explicitly which claims are no longer available to us. Every entry was fetched and read, not cited from memory.

---

## 1. The three papers that constrain us most

### IntentCap — capabilities follow task intent and context source
[arXiv:2609.14631](https://arxiv.org/abs/2609.14631) · Sept 2026

**Claim.** Agent capabilities should be scoped to the current task intent, not to a sandbox or session lifetime. No single context source defines a complete capability.

**Mechanism.** Capabilities are built from four sources — user intent, workflow instructions, tool schemas, runtime environment. Each source *owns* specific fields and none may fill another's. An LLM generates short-lived leases; the lease "only narrows the user's authorized authority, never widens it." A **deterministic checker** validates each lease before any side effect commits, backed by tool- and OS-level information-flow policies.

**Why it matters to us.** This is AgentWarden-v2's §3–§5 architecture, published a month before we specified it: the trusted anchor, provenance by write-authority (expressed as field-level source ownership), the narrow-only precedence rule, and the conclusion that enforcement is deterministic with the model confined to proposal. Arrived at independently; irrelevant that it was independent.

**Its gap, which is our opening.** No quantitative evaluation. The claims are qualitative — blocks tested violations, each source boundary independently necessary, checker generalizes across boundaries. No benchmark, no dataset, no numbers.

**Available to us:** the evaluation. **Not available:** the design.

---

### Representation Transitions — emerging safety risks in multi-turn agents
[arXiv:2610.00400](https://arxiv.org/html/2610.00400) · Oct 2026

**Mechanism.** Reads the agent's hidden state (last token, fixed layer) before and after each context segment. A safety direction is learned as the difference of means between harmful and benign transitions; each transition is projected onto it and the scores are **summed over the trajectory**, so the monitor flags cumulative displacement. Benign mean and leading benign variation directions are projected out (rank 16 / rank 2) to stop benign drift accumulating into false alarms. Attribution is exact — the largest single contributing segment is named.

**Numbers.** MT-AgentRisk: ASR 84% → 25%, every attack caught at 12% realized false-alarm rate, benign utility 93% → 85%; strongest multi-turn baseline (ToolShield) reaches 55%. ASEval: ASR 97% → 52%, no false alarms, catch 60–85%; without denoising, catch drops to 7–40%. Overhead 0.14–0.56 s/step. Generalizes to single-turn indirect injection (InjecAgent, AgentDojo) unmodified.

**The result that constrains A4 v0.1 directly.** Action-level enforcement judges calls in isolation; in decomposition attacks each step is individually permissible, so **rule-based AgentSpec never fires on MT-AgentRisk**, leaving ASR 0.80–1.00. Per-step scoring cannot see harm that only accumulates.

**Acknowledged limits, which matter for our framing.** Residual ASR on ASEval stays 0.35–0.68 per model. The natural-language reminder mitigation backfires on some 8B-class models, raising ASR under single-turn injection. For agent-intrinsic misuse with no injection (Agent-SafetyBench) the signal is weak: held-out AUROC 0.65–0.71, which the authors call a boundary of the method.

**Critically for us: the monitor requires the acting model's forward pass.** It is a white-box method. That is the gap A4 v0.2 is built on.

**Available to us:** the controlled black-box-vs-white-box comparison, on one model at matched FAR. **Not available:** the claim that per-step monitoring is insufficient, or that cumulative drift detection works.

---

### TaskTracker — catching LLM task drift with activation deltas
[arXiv:2406.00799](https://arxiv.org/abs/2406.00799) · SaTML 2025 · [code + activation data](https://github.com/microsoft/TaskTracker)

Task drift detected from internal activations via a linear probe and a metric-learning variant; the activation dataset is released. The canonical prior art for drift detection as such, and also white-box.

**Not available to us:** novelty for "detect whether the agent is still doing the authorized task."

---

## 2. Compositional risk

### STAC — sequential tool attack chaining
[arXiv:2509.25624](https://arxiv.org/html/2509.25624v2)

**Threat model.** Multi-turn attacker; harm is a real environmental change from a tool call, not harmful text. The malicious objective "can only be revealed via full-sequence monitoring."

**Construction.** Four-stage pipeline: Generator plans 2–6 calls where only the final one is malicious; Verifier executes and revises; Prompt Writer builds benign-looking prompts and synthetic history; Planner adaptively prompts the real agent over up to three turns.

**Scale and numbers.** 483 cases, 1,352 interaction sets, 10 failure modes, drawn from SHADE-Arena and Agent-SafetyBench; 8 target agents. ASR 80.0% at T, 88.9% at T+1, 91.2% at T+2. **Prompt harmfulness ~0.5%** — individual prompts almost never look harmful. On 390 SHADE-Arena cases, 95.1% ASR vs 72.8% single-turn and 61.5% X-Teaming. Their reasoning defense cuts first-turn ASR by up to 28.8% but decays over turns; attacks remain ≥58.6%.

**What it is and isn't.** An attack pipeline, a benchmark, and a *prompt-level* defense. **No runtime enforcement** — the defenses are instructions in the agent's prompt, explicitly because the authors cite a lack of effective agentic guardrail models.

**Available to us:** STAC as the primary A4 benchmark, and its no-runtime-enforcement gap as our position. **Not available:** the compositional attack construct as our contribution.

---

### When local monitors miss compositional harm
[arXiv:2607.11751](https://arxiv.org/html/2607.11751v1)

**Formal result.** *Local benignness*: every fragment passes its own check while the assembled object is harmful. Proposition 1 bounds any single-view local detector's advantage by the total variation between benign and attack fragment distributions — a detector seeing one fragment cannot separate them beyond that distance, however strong.

**Numbers.** Per-step monitors under local benignness: AUROC 0.475–0.504. AgentDojo's shipped detector per-step ≈0.50, but 1.000 with a cross-fragment coordination view. Marker-free one-class assembly monitor: 0.874 mean AUROC leave-one-family-out. Supervised assembly monitor: 1.000. No-defense ASR 0.58–1.00; decoded-view gate 0/50 everywhere (which the authors call a diagnostic ceiling, not deployable).

**Scope limits.** K fragments one per step, K=3 in main experiments; the bound covers single-view detectors and alarm-if-any aggregation, not joint scoring. Longer horizons, varying K, adaptive attackers and non-code harms are outside the claim. A natural-language payload drops the one-class monitor to 0.406 — the approach does not transfer cleanly.

**Available to us:** citing the impossibility bound as motivation, and the natural-language transfer failure as open. **Not available:** the formal argument.

---

### Semantic intent fragmentation
[arXiv:2604.08608](https://arxiv.org/html/2604.08608v1) — single-shot compositional attack on multi-agent pipelines. Adjacent; read before submission.

---

## 3. Permission architectures

### Three-source permission architecture / dynamic capability scoping
[arXiv:2607.22445](https://arxiv.org/html/2607.22445v1)

Permissions granted only where **all three** sources allow: a deterministic role-based ceiling; a fine-tuned multi-label task-context classifier (15 permissions, risk-varying confidence thresholds, acknowledged manipulable by prompt injection); and deterministic combination prohibitions removing dangerous pairs (`database_read` with `email_send_external` or `http_request` — the "lethal trifecta"). The final decision is a **symbolic intersection bounding the learned component**.

**This is our hybrid precedence rule.** Not available as novel architecture.

**Its weakness.** 600 synthetic prompts, single expert reviewer on a 10% sample, sensitivity-tier labels at only 60% agreement and excluded from metrics, and the paper states the architecture's empirical performance **is not yet evaluated** — classifier training and the full comparison are future work.

### MiniScope
[arXiv:2512.11147](https://arxiv.org/pdf/2512.11147) — least-privilege authorization for tool-calling agents. §2.1 states it "does not verify the semantic correctness of tool calls that are already within those permissions." The cleanest statement in the literature of the gap A4 targets.

### Progent (2504.11703), SEAgent (2601.11893)
Symbolic enforcement, no learned policy, no compositional handling. Progent: ASR 39.9% → 1.0% at −3.1pp utility. SEAgent: → 0.00%. **Cite as correct for their layer, not as baselines we beat.** Our B5 at −50pp utility is the number a reviewer will set against Progent's −3.1pp.

---

## 4. Multi-turn detection, non-activation

### DeepContext
[arXiv:2602.16935](https://arxiv.org/html/2602.16935v1)

A 3-layer GRU, 2048 hidden, maintaining a recurrent state updated each turn from a task-attention-weighted BERT embedding of the user turn; MLP head scores risk. Trained on 437,058 conversations (~20% malicious), BCE + focal loss. Multi-turn F1 0.84 (baseline Llama-Prompt-Guard-2-86M 0.67, Llama-Guard-4-12B 0.51); single-turn JailBreakBench F1 0.98; mean 4.24 turns to detection; ~19 ms/turn.

**Why it is only partly relevant.** It reads **user turns**, not tool output, and not agent actions — the authors list agent-action monitoring as future work. It is a jailbreak guardrail, not a capability governor.

**Reproducibility caveats worth noting in the paper:** training data largely proprietary; some evaluation datasets also appear in training; latency claims (A100 in Table 7 vs T4 in the abstract) not reconciled.

### Intent drift, other senses
[arXiv:2609.32520](https://arxiv.org/abs/2609.32520) measures and repairs intent drift where the *user changes their mind* — a usability problem, not a security one. **Terminology collision:** we must define "drift" explicitly or be misread.

---

## 5. Information flow and provenance

- **NeuroTaint** ([arXiv:2604.23374](https://arxiv.org/abs/2604.23374)) — taint tracking extended beyond content transfer to semantic transformation, causal influence on decisions, and cross-session persistence through memory. **Offline trace auditing**, not runtime enforcement. TaintBench: 400 scenarios, 20 frameworks; outperforms FIDES.
- **Intent-to-execution integrity** ([arXiv:2605.16976](https://arxiv.org/html/2605.16976v1)) — a position paper proposing four conjoined properties (Instruction, Data Flow, Judgment, Tool Integrity). **No experiments**; a coverage table over 11 defenses finds none achieves full coverage, and states Judgment Integrity has no strong mechanism yet. Useful as a framing citation and as evidence that our target is an acknowledged gap.
- **Agent traces to trust** ([arXiv:2606.04990](https://arxiv.org/html/2606.04990v4)) — survey of evidence tracing and execution provenance. Positions our audit-log-as-trusted-source design.
- **Origin-bound memory authority** ([arXiv:2606.24322](https://arxiv.org/html/2606.24322)) — non-malleable, origin-bound authority for agent long-term memory with machine-checked guarantees. Closest formal treatment of write-authority; read before claiming that property.

---

## 6. Benchmarks available

| Benchmark | Content |
|---|---|
| STAC | 483 cases, 1,352 interaction sets, sequential chains |
| MT-AgentRisk | Decomposition attacks; rule-based monitors never fire |
| ASEval | Harmful instructions injected into benign trajectories |
| AgentDojo | Standard utility/security tradeoff; everyone reports it |
| [Boiling the Frog](https://arxiv.org/abs/2605.22643v2) | Multi-turn agentic safety |
| [Adaptive Adversaries](https://arxiv.org/abs/2607.18063) | Multi-turn, multi-LLM agent security |
| [Cross-Session Threats](https://arxiv.org/html/2604.21131v1) | Benchmark, evaluation, algorithms for cross-session attacks |
| SHADE-Arena, Agent-SafetyBench, InjecAgent, R-Judge, ToolEmu | Component sources used by the above |

Hand-authoring our own multi-turn pairs is not justified while these exist.

---

## 7. Claims no longer available to AgentWarden-v2

Recorded so they are not reintroduced by accident in drafting.

1. Task-intent-anchored capability scoping as a novel architecture — IntentCap.
2. Narrow-only / symbolic-precedence as a novel rule — IntentCap, Three-Source.
3. Per-step monitoring is insufficient for multi-turn harm — Representation Transitions, Local Monitors.
4. Cumulative or trajectory-level drift detection works — Representation Transitions, TaskTracker.
5. Compositional risk from individually-benign calls as a novel construct — STAC, Local Monitors.
6. Detecting task drift as such — TaskTracker.
7. Hybrid symbolic-bounding-learned as a novel composition — Three-Source.

## 8. What remains ours

1. **The controlled black-box vs white-box comparison** at matched false-alarm rate on one model. Every effective result is white-box; production is black-box; nobody has measured the gap.
2. **The state-requirement result** — which tier of session state (S0/S1/S2) black-box governance actually needs.
3. **Evaluation discipline for synthetic safety data**, demonstrated on our own system: label-leakage rule, reconciliation rule, degeneracy gate, minimal-pair requirement, semantic leakage gate. The field is making these mistakes now — Three-Source's unevaluated architecture and 60%-agreement labels, DeepContext's train/eval overlap and proprietary data — which makes the contribution timely rather than pedantic.
4. **The evaluation IntentCap lacks**, for an architecture of that family.
