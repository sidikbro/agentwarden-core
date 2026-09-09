# AgentWarden-v2 — Experimental Plan v0.2
**Target:** USENIX Security '27 Cycle 2 — registration Jan 19, 2027; paper Jan 26, 2027
**Status:** supersedes `EXPERIMENTAL_PLAN_v0.1.md`. v0.1's scope is unchanged in substance; v0.2 records what has actually been built since (§§2-9 status annotations), and adds four requirements that close gaps found while building it (§3b, §4a, §11a, §12).
**Gate:** no benchmark expansion and no training run may start until `docs/v2/RECONCILED_STATE_v0.2.md` — the artifact-by-artifact reconciliation this plan requires (§12) — is produced and every number in it is either VERIFIED or STRUCK. See that file.

---

## 0. Governing constraint (unchanged from v0.1)

AgentWarden-v2 does **not** use ATBench-Claw, does **not** reproduce AMARE's recovery cost curve or FP taxonomy, and does **not** depend on AMARE being accepted. AMARE owns *post-hoc recovery*; v2 owns *pre-action exposure and enforcement*. See `contribution_boundary.md`.

Clarification added in v0.2: "does not use ATBench-Claw" governs what enters *this repository's training/benchmark data*. It does not prohibit reading ATBench-Claw's own artifacts (produced entirely outside this repo, under AMARE) to check a factual claim about them — see `docs/issues/atbench_274_279_not_toolname_driven.md` for exactly that: a read-only attribution check, no ATBench-Claw content copied in.

---

## 1. The scientific question (unchanged)

> Under what conditions does learned capability governance outperform strong static task-conditioned policies, without reducing task success?

Three outcomes remain all publishable — (a) static dominates, (b) learned wins conditionally, (c) learned dominates. Do not tune toward (b).

---

## 2. The three decisions — status update

| # | Decision | Question | v0.1 status | v0.2 status |
|---|---|---|---|---|
| D1 | **Expose** | Should the model *see* this tool? | designed, not built | **built**: `agentwarden/profiles/capability_governor.py` (`CapabilityGovernor`), declaration-first + structural fallback (`agentwarden/profiles/structural_task_type.py`), wired into the real proxy (`agentwarden/server/app.py`) |
| D2 | **Allow** | Should this invocation execute? | built (Stage 1 rules + Stage 2 classifier) | unchanged mechanism; classifier's degeneracy diagnosed (§9, `docs/issues/aethelgard-router-degenerate.md`) |
| D3 | **Approve** | Should this require human confirmation? | designed only; `Decision.REVIEW` never emitted anywhere | **built**: `agentwarden/policies/approval_gate.py` (`ApprovalGatePolicy`) gives D3 a real producer. `config/tools.yaml`'s `route_to_review` set (`process, kill, chmod, chown, sessions_spawn, subagent, subagents, delegate, task`) routes to Stage 2/3 instead of Stage-1 hard-block; the remaining `always_block` set (`exec, execute, bash, shell, run_command, terminal, system, sudo, su, spawn, create_agent`) stays irreducible. **No synchronous approval channel exists** (`stages.approval.timeout_ms=0`, `default_on_timeout=block`) — REVIEW currently resolves to "not executed," tagged and audited distinctly from BLOCK. |

---

## 3. Baseline matrix — status update

| # | Baseline | D1 (expose) | D2 (allow) | Status |
|---|---|---|---|---|
| B0 | All tools | full registry | none | built, real numbers (`benchmark/baselines.py::run_b0`) |
| B1 | Prompting-only | full registry | LLM self-restriction via system prompt | **resolved in v0.2 — see §3a.** Real live-model variant built and run. |
| B2 | Global allowlist | fixed safe set | none | built, real numbers |
| B3 | Task-conditioned YAML | per-task-type YAML | none | built, real numbers, genuine headroom confirmed (see `RECONCILED_STATE_v0.2.md` — `required_tool_denial_rate>0` on 8/20 rows, `unnecessary_exposure_ratio>0` on 16/20) |
| B4 | Classifier-only | full registry | learned classifier per call | built; zero-shot numbers real, fine-tuned numbers **quarantined** — the only fine-tuned artifact available (`aethelgard-router`) is confirmed degenerate (blocks 12/12 tested calls including benign ones) |
| B5 | YAML + Router | per-task-type YAML | rules + classifier | built; same fine-tuned-model quarantine as B4 |
| B6 | Learned Governor + Router | learned policy | rules + classifier | built as a **placeholder only** (`PlaceholderLearnedGovernor` — explicitly not trained). **Gated in v0.2 — see §3b.** Its own numbers currently FAIL the gate; they establish the gate works, not a B6 result. |
| B7 | Oracle | ground-truth minimum tool set | ground-truth | built, real numbers |

**B3 remains the make-or-break baseline** (unchanged from v0.1).

### 3a. B1 resolution (v0.2 addition — was an open decision in v0.1)

v0.1 left B1 as a stated limitation with two options, undecided (`docs/v2/B1_prompting_only_limitation.md`). **Decided: option 1, build the live-model variant.** Reviewer BNSs asked for this baseline specifically; a stated-limitation-only answer leaves that ask formally unmet, and the infrastructure cost turned out to be smaller than v0.1 estimated because it composes existing pieces (`OpenAIParser`, the Ollama provider, each task family's already-existing world-state functions) rather than requiring new ones.

Built: `benchmark/live_runner.py::run_b1_live` — a genuine multi-turn agent loop. Unlike `run_scripted`/`run_via_pipeline` (which replay a fixed plan), a real model (`qwen2.5:3b` via Ollama) sees the task's `initial_prompt` plus a safety system-prompt instruction, is offered the family's full tool registry (D1 = full registry per spec), and chooses which tool to call at each turn (D2 = none — nothing is ever blocked, isolating pure prompting self-restraint). `scripts/report_b1_live.py` runs and reports it.

**Scope, stated plainly:** one family (`research_synth` v1), one model (`qwen2.5:3b`), N=3 runs at `temperature=0.2`. This is the "minimal live-model variant," not a claim of generality across families or models. Extending to the other four families is a mechanical repeat of the same pattern against each family's own world-state functions — not done in this pass. A stable, citable number needs more seeds; see `RECONCILED_STATE_v0.2.md` for exactly what ran and what it showed (real result: 0/3 task success, and the decoy `exec_shell` tool was called in 2/3 runs despite an explicit system-prompt instruction not to).

### 3b. Track C gate (v0.2 addition)

"Track C" = the learned-governance track: B6 today, L1-L6 once real training exists (§8). **No Track C number may be reported in the paper until the exposure policy under test passes all three checks in `benchmark/degeneracy_gate.py::run_track_c_gate`:**

1. **not_expose_everything** — avg `|exposed \ required| / |exposed|` across probed (task_type, phase) contexts must be `< 0.5`. (Measured this way, not as a raw exposed/registry-size ratio — see the module docstring for why the size-ratio proxy was tried first and rejected: it's insensitive at this benchmark's registry scale.)
2. **not_expose_nothing** — avg `|exposed ∩ required| / |required|` must be `> 0.05`.
3. **g3_rename_invariant** — direct test of the v1 diagnosis (policy learned tool *identity*, not risk). Every tool in the catalog is renamed to an opaque, **shuffled** alias (not sorted — sorting would preserve alphabetical rank and let a rank-keyed policy pass incorrectly) with descriptions held fixed; the exposed *set of descriptions* must be identical to the un-renamed run.

**Why this exists:** the current placeholder's own reported `unnecessary_exposure_ratio` (~0.83-0.96 depending on measurement) is exactly the confound this gate is built to catch — broad, under-scoped exposure that happens to key on crude keyword categories rather than task/phase discrimination. Running the gate against it (`scripts/report_track_c_gate.py`) confirms: **FAILS `not_expose_everything` (0.964), PASSES `not_expose_nothing` and `g3_rename_invariant`.** The placeholder was built specifically to avoid identity-keying and it does — its failure is breadth of exposure, not the v1 failure mode. This is the expected, correct outcome of the gate, not evidence the gate is broken.

Any future trained L1-L6 policy must pass this same gate before its numbers enter a results table.

---

## 4. Benchmark: multi-turn tasks with evolving capability requirements (unchanged task families; v0.2 adds the expansion protocol)

Task families 1-5, adversarial variants A1-A5, and the four ground-truth fields are unchanged from v0.1 §4.

### 4a. Benchmark expansion — authorship and validation protocol (v0.2 addition)

Expanding the benchmark by 90 new task instances is the same scale of work as the D2 classifier training dataset (`docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md` §2), and carries the **same failure mode**: model-generated volume that is structurally identical variation dressed up as diversity, rather than instances that actually exercise different governance behavior. The classifier dataset's authorship/review protocol is the template; apply it here directly rather than re-deriving a separate one:

- **Every one of the 90 new instances must pass all five `benchmark/validate.py` checks before it is added to the suite** — `check_required_tools_subset`, `check_oracle_succeeds`, `check_withholding_breaks_success`, `check_phases_differ`, `check_attack_succeeds_under_b0`. **Check 3 (`check_withholding_breaks_success`) is the load-bearing one** (same as in v0.1's original validation-gate decision): it is the check that would have caught both real mutation-ordering bugs found during the original five families' construction (`inbox_workflow._schedule_event`, `repo_triage._run_tests`). A new instance that passes checks 1/2/4/5 but not 3 is not a real instance — it means withholding a required tool doesn't actually break the task, i.e. the "required" tool isn't required.
- **Authorship**: instances may be drafted by a model (consistent with how the D2 dataset's hand-authored and paraphrase-diversified buckets were produced), but every drafted instance is `review_status=pending` until a human reviews it — same field, same meaning, same gate as `router_training/schema.py::TrainingExample`.
- **Review means**: a human (not a model) reads the task's `initial_prompt`, `phases_for()`, `make_ground_truth()`, and `build_oracle_plan()`, and confirms by hand that (a) the required-tools set for each phase is actually minimal and actually necessary — not just "a plausible-sounding tool for this phase" — and (b) the oracle plan is the one a competent human would actually execute for this task, not a mechanically-generated withholding-proof shortcut. Confirming that `validate.py` passes is necessary but not sufficient for review sign-off; a reviewer who only ran the checks and didn't read the instance has not reviewed it.
- **Overcorrection guard** (same concern as the D2 dataset's §2 clarification): expanding instance count must not silently skew the benchmark's family/variant/difficulty-type balance (overlapping vocab, within-family variation, content-dependence, distractors — the four difficulty categories added after the original all-perfect-scores finding). Report the new instances' distribution across those four categories alongside the expansion, not just a total count.
- No instance is added to any *reported* baseline run until it is past `review_status=pending`. A pending instance may exist in the repo for iteration, but a baseline run over a batch that includes pending instances is not a reportable number — same rule as §12 below.

---

## 5. Metrics (unchanged definitions; one status note)

D3's metric (`approval_request_rate`) was previously known-zero for every trajectory (v0.1: "no policy anywhere ever constructs REVIEW"). As of the D3 build (§2), this is no longer structurally zero — it reads non-zero for any real-pipeline trajectory (`run_via_pipeline`) that invokes a `route_to_review` tool. Still structurally zero for scripted baselines (`run_scripted`), which never emit REVIEW by construction. See `benchmark/metrics.py::approval_request_rate`'s current docstring.

All other metric definitions (§5 of v0.1) are unchanged. Exact formulas and file:line pointers are in `RECONCILED_STATE_v0.2.md`, not restated here — restating formulas in two places is exactly the kind of drift the reconciliation rule (§12) exists to prevent.

---

## 6. Generalization splits (unchanged)

G0-G4 unchanged from v0.1. G3 is now operationalized concretely by §3b's gate (`g3_rename_invariant` *is* a G3 probe, run automatically rather than as a one-off analysis).

---

## 7. Policy input schema (unchanged)

`SessionState` (`agentwarden/core/models.py`) implements the required input shape — `prior_actions`, `phase_history`, `data_provenance`, `turn`, `extra` — passed to every `GovernanceProfile.expose()` call. Unchanged design; now actually implemented and wired (§2).

---

## 8. Learning conditions to compare (unchanged)

L0 (B3) through L6, multi-seed (≥5) with CIs, unchanged from v0.1. None have started. §3b's gate is a precondition for reporting any of L1-L6, not only B6.

---

## 9. Critical path and sequencing — status update

```
Phase 1 (Sep-Oct)  Benchmark harness + task families + ground truth + adversarial variants -- DONE (5 families, difficulty added, 5 checks enforced)
                   D1 Capability Governor -- DONE. D3 Approval Gate -- DONE (not in v0.1's Phase 1 scope; pulled forward because it was needed to make REVIEW real).
                   B1 live-model resolution -- DONE (minimal scope, §3a).
Phase 1.5 (new)    Benchmark expansion (90 instances, §4a protocol) -- NOT STARTED. Gated on RECONCILED_STATE_v0.2.md (see below).
Phase 2 (Oct-Nov)  Baselines B0-B5, B7 -- DONE, real numbers. B6 -- placeholder only, gated (§3b).
Phase 3 (Nov-Dec)  Learned conditions L1-L6 -- NOT STARTED. Gated on §3b passing for each.
Phase 4 (Dec)      Generalization G1-G4; security tests A1-A5 -- NOT STARTED (only A1 built, N=1 scripted scenario).
Phase 5 (Jan 1-19) Writing, artifact packaging, bibliography verification, registration.
Jan 26             Submit
```

Slippage rule unchanged: cut task families 5→3 before compressing Phase 2, if needed.

**New precondition, not in v0.1:** Phase 1.5 (benchmark expansion) and Phase 3 (learned conditions) may not start until `docs/v2/RECONCILED_STATE_v0.2.md` shows every currently-claimed number as VERIFIED or STRUCK. This is the gate the user's most recent request establishes; treat it as a hard blocker on the critical path, not a parallel-track nicety.

---

## 10. Reviewer-to-action matrix (unchanged from v0.1, one row updated)

| Reviewer concern | Addressed by |
|---|---|
| PPO unnecessary | B3 vs B6; L0 vs L1-L6 |
| PPO unreliable | multi-seed + CIs; L2/L3 constrained reward |
| SER gameable | joint metrics; SER never reported alone |
| False positives | D2 FPR, per-tool/per-task breakdown |
| Tasks too easy | multi-turn benchmark; difficulty categories added post-finding |
| No multi-turn adaptation | exposure/revocation metrics |
| Generalization | G1-G4; G3 now automated via §3b |
| Architecture inconsistency | D1/D2/D3 (§2), D3 now real |
| Injection weakness | A2/A4/A5 |
| Latency unclear | end-to-end latency + routed-call fraction |
| **Reviewer BNSs: prompting-only baseline (B1)** | **§3a — resolved, not carried as open** |
| Citation integrity | mandatory primary-source verification before submission |

---

## 11. Standing requirements (unchanged from v0.1, plus §11a)

- Every bibliography entry verified against a primary source before submission.
- No result written into the paper before the experiment that produces it has run.
- Artifact prepared for USENIX artifact evaluation.
- Registration Jan 19 with fixed title/authors/abstract.

### 11a. Reconciliation failure rule (v0.2 addition)

Three reported numbers have already failed verification in this project's history (v1's "10.5x SER improvement," "100% TPR / 0% FPR," and "N=500" claims — see `docs/issues/v1_headline_numbers_unverifiable.md` and `docs/issues/aethelgard-router-degenerate.md`) plus one mischaracterized attribution (the ATBench "274/279 blocked" figure read as tool-name-driven when it is 99.8% content-driven — `docs/issues/atbench_274_279_not_toolname_driven.md`). This rule is written now, before it is needed a fourth time:

> **Any number that cannot be reproduced from an immutable artifact is struck, not footnoted, and any claim resting on it is withdrawn until re-derived.**

Definitions, so this is enforceable rather than aspirational:
- **Immutable artifact** = a specific git commit hash + file path (or a dataset/model file with a recorded checksum), such that `git show <hash>:<path>` or re-running the exact recorded command against that commit reproduces the number bit-for-bit or within stated numerical tolerance. A number that only exists in a chat transcript, a slide, a comment, or an uncommitted working-tree file is **not** backed by an immutable artifact — see `RECONCILED_STATE_v0.2.md`'s finding that the entire benchmark harness is currently uncommitted, which is why that table's "commit" column mostly reads UNCOMMITTED right now, and why committing is listed as the first action item there.
- **Struck** means removed from the paper draft and from any table that reports it — not moved to a footnote, not hedged with "approximately," not kept with a caveat. A struck number is gone until it is re-derived from an artifact and re-enters the paper as a new claim.
- **Any claim resting on it is withdrawn** means transitively: if baseline X's reported success rate depended on the struck number, X's success rate is also withdrawn, not just the struck number itself, until X is re-run.
- This rule applies retroactively to every number already in any draft, README, or docs file, not only to numbers produced from now on.

---

## 12. Reconciled state table (the gate)

`docs/v2/RECONCILED_STATE_v0.2.md` is a separate artifact, not a section of this document, because it needs to be re-generated/re-checked independently of plan revisions. It is produced now, alongside this plan, and **is the gate**: no benchmark expansion (§4a) and no training run (§8) may start until every row in it is VERIFIED or STRUCK — no PENDING rows may remain open past that point without an explicit, dated exception logged in this file.
