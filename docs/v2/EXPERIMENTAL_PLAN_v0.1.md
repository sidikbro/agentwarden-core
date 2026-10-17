# AgentWarden-v2 — Experimental Plan v0.1
**Target:** USENIX Security '27 Cycle 2 — registration Jan 19, 2027; paper Jan 26, 2027 (verified against official CFP)
**Status:** scope FROZEN. Independent of AMARE's outcome; only the citation/positioning paragraph and venue coordination wait on it.

---

## 0. Governing constraint (non-negotiable)

AgentWarden-v2 does **not** use ATBench-Claw, does **not** reproduce AMARE's recovery cost curve or FP taxonomy, and does **not** depend on AMARE being accepted. AMARE owns *post-hoc recovery*; v2 owns *pre-action exposure and enforcement*. See `contribution_boundary.md`.

---

## 1. The scientific question

> Under what conditions does learned capability governance outperform strong static task-conditioned policies, without reducing task success?

This is the honest framing. We do **not** pre-commit to the answer. Three outcomes are all publishable:
- **(a)** Static dominates everywhere → "static task-conditioned policies suffice for agent least-privilege; learned governance is unnecessary complexity." A clean negative result.
- **(b)** Learned wins only under task evolution / unseen compositions → the conditional result.
- **(c)** Learned dominates → the original claim, now with evidence.

Design the experiments so that all three are distinguishable. Do not tune toward (b) because it is the most interesting-sounding.

---

## 2. The three decisions (core architectural contribution)

v2 decomposes governance into three separable decisions, which prior work conflates:

| # | Decision | Question | Failure if wrong |
|---|---|---|---|
| D1 | **Expose** | Should the model *see* this tool in its registry? | Unnecessary exposure (attack surface) / required-tool denial (task failure) |
| D2 | **Allow** | Should this *specific invocation* execute? | Invocation FP (blocked legitimate work) / FN (executed attack) |
| D3 | **Approve** | Should this action require human confirmation? | Approval fatigue / unattended dangerous action |

Each decision has its own policy backend, its own metrics, and its own baselines. This decomposition is a v2 contribution AMARE does not make.

---

## 3. Baseline matrix

Every configuration is evaluated on the same benchmark, same model, same seeds.

| # | Baseline | D1 (expose) | D2 (allow) | Purpose |
|---|---|---|---|---|
| B0 | All tools | full registry | none | ungoverned upper bound on utility, lower bound on security |
| B1 | Prompting-only | full registry | LLM self-restriction via system prompt | tests the "just tell the model" hypothesis |
| B2 | Global allowlist | fixed safe set | none | crudest static governance |
| B3 | Task-conditioned YAML | per-task-type YAML | none | **the strong static baseline reviewers demanded** |
| B4 | Classifier-only | full registry | learned classifier per call | isolates D2 from D1 |
| B5 | YAML + Router | per-task-type YAML | rules + classifier | the v1 production configuration |
| B6 | Learned Governor + Router | learned policy | rules + classifier | the learned-governance condition |
| B7 | Oracle | ground-truth minimum tool set | ground-truth | upper bound; quantifies headroom |

**B3 is the make-or-break baseline.** If B6 does not beat a *well-tuned* B3, the honest paper is outcome (a). B3 must be genuinely tuned, not a strawman — this is the single most important experimental integrity requirement in the plan.

---

## 4. Benchmark: multi-turn tasks with evolving capability requirements

The gate on everything else. Existing benchmarks do not test capability *evolution*, which is precisely where learned governance could beat static.

### Task families (each with phase transitions)
1. **Research → synthesize → publish**: search → fetch → analyze → write → send
2. **Repo triage**: inspect repo → read code → edit → run tests → commit
3. **Inbox workflow**: read email → open attachment → extract dates → schedule → reply
4. **Incident response**: read alert → query logs → correlate → apply remediation
5. **Data pipeline**: locate source → fetch → transform → validate → export

### Per-task ground truth (required for the metrics)
- `minimum_required_tools` per phase (enables D1 metrics and B7 oracle)
- `phase_boundaries` (when requirements change)
- `task_success_criteria` (programmatic, not LLM-judged where possible)
- `revocable_after` (tools that should be withdrawn once a phase completes)

### Adversarial variants (security tests, all pre-action)
- **A1** direct dangerous call (agent attempts `exec`/destructive op)
- **A2** indirect injection via tool output (poisoned fetch result instructs escalation)
- **A3** capability escalation (agent requests a tool outside its phase)
- **A4** multi-step attack via individually-benign tools (each call innocuous; composition harmful)
- **A5** aliased/renamed tool (attacker registers a tool whose name is on the allowlist — the reviewer G9iU insight)

A4 and A5 are the novel ones. A5 in particular directly motivates gating on behaviour rather than tool identity.

---

## 5. Metrics

Reported **jointly**, never SER alone.

**Utility**
- End-to-end task success rate (per task, per phase)
- Required-tool denial rate (D1 blocked something the task needed)
- Task completion latency

**Exposure (D1)**
- Unnecessary exposure ratio: |exposed \ required| / |exposed|
- Exposure precision/recall vs. `minimum_required_tools`
- Revocation lag: turns between phase end and tool withdrawal

**Invocation (D2)**
- FPR: blocked legitimate invocations / legitimate invocations
- FNR: executed attack invocations / attack invocations
- Per-tool and per-task-type error breakdown

**Approval (D3)**
- Approval request rate; precision of approval requests (did the flagged action actually warrant it?)

**System**
- End-to-end added latency; **fraction of calls routed to the classifier** (the quantity that determines overhead — v1 failed to report this)
- Bypass resistance: does A5/A4 defeat the enforcement layer?

**Pareto**: security (1−FNR, or attack success rate) vs. utility (task success) across all baselines. The paper's central figure.

---

## 6. Generalization splits

| Split | Held out | Tests |
|---|---|---|
| G0 | nothing (in-distribution) | fitting sanity |
| G1 | unseen task *compositions* (known phases, new order) | compositional generalization |
| G2 | unseen tools (new names, unseen at training) | does the policy reason about semantics or memorize identity? |
| G3 | renamed/aliased known tools | identity-memorization probe (paired with A5) |
| G4 | unseen task types entirely | taxonomy generalization |

G2/G3 are the direct test of the v1 diagnosis that the policy learned tool identity rather than action risk.

---

## 7. Policy input schema (fixes the v1 defect)

v1 trained on `(tool_name, context) → allow/block`, which is why it learned identity. v2 policies must consume:

```
decision = f(task_goal, phase, tool_semantics(description),
             arguments, dataflow_provenance, authorization_level,
             session_state, prior_actions, data_sensitivity,
             expected_side_effects)
```

Explicitly: tool *description* text, argument values, and provenance of data flowing in. Never tool name alone.

---

## 8. Learning conditions to compare (for the §1 question)

- L0 static (B3) — the bar to beat
- L1 unconstrained PPO (reproduces v1's collapse; included as a documented failure mode)
- L2 PPO + task-success penalty in reward
- L3 constrained RL (CMDP / Lagrangian)
- L4 contextual bandit
- L5 supervised policy on logged decisions
- L6 hybrid: static floor + learned refinement

Multi-seed (≥5) with confidence intervals for every learned condition. v1's lack of this was a specific reviewer complaint.

---

## 9. Critical path and sequencing

**The benchmark gates everything.** Nothing downstream can run without tasks and ground truth.

```
Phase 1 (Sep–Oct)  Benchmark harness + task families + ground truth + adversarial variants
Phase 2 (Oct–Nov)  Baselines B0–B5, B7 on the benchmark; metrics pipeline; Pareto plots
Phase 3 (Nov–Dec)  Learned conditions L1–L6, multi-seed; D1/D2/D3 decomposition experiments
Phase 4 (Dec)      Generalization G1–G4; security tests A1–A5; bypass analysis
Phase 5 (Jan 1–19) Writing, artifact packaging, bibliography verification, registration
Jan 26             Submit
```

Slippage rule: if Phase 1 is not done by end of October, cut task families from 5 to 3 rather than compressing Phase 2. Baselines matter more than benchmark breadth.

---

## 10. Reviewer-to-action matrix (from NeurIPS 20726)

| Reviewer concern | Addressed by |
|---|---|
| PPO unnecessary | B3 vs B6; L0 vs L1–L6 |
| PPO unreliable | multi-seed + CIs (§8); L2/L3 constrained reward |
| SER gameable | §5 joint metrics; SER never reported alone |
| False positives | D2 FPR, per-tool/per-task breakdown |
| Tasks too easy | §4 multi-turn benchmark with phase transitions |
| No multi-turn adaptation | exposure/revocation metrics; revocation lag |
| Generalization | G1–G4 |
| Architecture inconsistency | two components, three decisions (§2) |
| Injection weakness | A2 (tool-output injection), A4, A5 |
| Latency unclear | end-to-end latency + routed-call fraction |
| **Citation integrity** | **mandatory primary-source verification before submission** |

---

## 11. Standing requirements

- Every bibliography entry verified against a primary source (title, authors, venue, year, identifier) before submission. Non-negotiable.
- No result written into the paper before the experiment that produces it has run.
- Artifact prepared for USENIX artifact evaluation (required-ish; strongly expected at this venue).
- Registration Jan 19 with **fixed** title/authors/abstract — cannot change after.
