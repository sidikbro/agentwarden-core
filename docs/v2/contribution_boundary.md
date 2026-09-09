# Contribution Boundary: AMARE vs. AgentWarden-v2
*Internal planning document — written before experiments to keep the two papers non-overlapping under either outcome of AMARE's review.*

## Why this document exists

AMARE is under review at USENIX. AgentWarden-v2 will be built during the review window, before its outcome is known. To protect both papers, AgentWarden-v2 must be designed so that it:

1. never depends on AMARE's results being citable (works even if AMARE is unpublished), and
2. never duplicates AMARE's core contribution (no collision if both are simultaneously in play after an AMARE rejection).

The two papers ask genuinely different questions, which makes a clean split possible. This document fixes that split.

---

## The one-line split

- **AMARE** answers: *given a governor that over-blocks, how much of that over-blocking can be safely undone after the fact — and at what cost?* (post-hoc recovery)
- **AgentWarden-v2** answers: *how should the enforcement layer decide what to expose and block in the first place, and when does a learned policy beat a static one?* (pre-action enforcement)

Pre-action vs. post-hoc. Enforcement vs. recovery. Different objective, different placement in the pipeline, different signals. AMARE §2.2 already draws exactly this line ("two kinds of learning, two objectives"); this document keeps that wall standing.

---

## What belongs to AMARE (do NOT put in AgentWarden-v2)

- The recall-first cost model (FN:FP = 100:1) as a framing device
- The precision-recovery **cost curve** on ATBench-Claw
- The ladder of post-hoc **release/recovery** mechanisms (surface, argument, per-chunk semantic, learned release policy)
- The false-positive **taxonomy** and the irreducible pre-reasoning-injection residual
- The "post-hoc recovery is structurally bounded" negative result
- The closed-loop measurement apparatus (Observer/Theorist/Architect/Reviewer/Executor), label-leakage gate, synthetic-realism lesson
- Any result computed on **ATBench-Claw**

If AgentWarden-v2 needs any of these, it **cites AMARE** (if published) or **refers to it as concurrent work without re-deriving** (if unpublished). It never reproduces them.

---

## What belongs to AgentWarden-v2 (AMARE does NOT contain these)

- The **enforcement architecture**: Capability Governor (tool exposure), Safety Router (per-call mediation), approval gate — as a system, with integration across runtimes
- The **three-decision decomposition**: (1) should the model *see* this tool? (2) should this *invocation* be allowed? (3) should the action require *approval*? — this is an enforcement-design contribution AMARE does not make
- The **policy-backend comparison** for the enforcement decision: all-tools-exposed, prompting-only self-restriction, global static allowlist, task-conditioned YAML, classifier-only, YAML+Router, learned-Governor+Router, oracle tool selection
- The scientific question: *under what conditions does learned capability governance outperform static task-conditioned policies without reducing task success?*
- **Multi-turn adaptive scoping**: tool-set expansion and revocation as a session evolves (search→fetch→analyze→execute, etc.), with latency/security/utility measured across transitions
- **End-to-end enforcement** metrics: latency/overhead, routing fraction, bypass resistance, direct-call attack blocking
- Generalization of the *enforcement* decision to unseen tools, aliased/renamed tools, unseen task compositions

---

## The trap to avoid (this is the important part)

The NeurIPS-reviewer feedback pushed for "precision–utility Pareto curves" and "false-positive analysis." Those phrases *sound* like AgentWarden work, but **AMARE already did exactly that on ATBench-Claw.** If AgentWarden-v2 puts ATBench-Claw cost curves or a post-hoc FP taxonomy in the paper, it collides with AMARE under both outcomes.

Resolution: AgentWarden-v2 measures precision/utility on a **different substrate** — its own multi-turn benchmark/harness and/or AgentDojo — framed as *properties of the enforcement decision at the point of action*, not as post-hoc recovery of a governor's over-blocking. Same words ("precision," "false positive"), different experiment, different pipeline stage. Keep ATBench-Claw out of AgentWarden-v2.

---

## Behavior under each AMARE outcome

**AMARE accepted:**
- AgentWarden-v2 cites AMARE as established prior/companion work: "post-hoc recovery of over-blocking is bounded [AMARE]; we therefore focus on the enforcement decision that determines the over-blocking in the first place."
- Clean, no risk.

**AMARE rejected (fix + resubmit):**
- Both papers unpublished and in play. Keep them:
  - at **different venues** (or at minimum different cycles) to avoid any salami-slicing appearance;
  - with the boundary above strictly enforced so a PC seeing both sees two distinct contributions, not one split in two.
- AgentWarden-v2 refers to AMARE as concurrent work by the same group and does not re-derive its results.

**Either way:** AgentWarden-v2 is written so its contribution stands without AMARE. It cites up if it can; it stands alone if it must.

**Scope is finalized now, not later.** Because this boundary makes AgentWarden-v2 scientifically independent of AMARE's result, its experimental scope can and should be frozen immediately. What waits on the AMARE decision is *only* the citation/positioning paragraph and venue coordination — never the science. Do not defer experimental design pending AMARE's outcome.

---

## The related-work paragraph (draft, for AgentWarden-v2)

> Our prior/companion work studies the *recovery* side of governance: given a recall-first governor that over-blocks safe behavior, it characterizes how much of that over-blocking can be undone by post-hoc adjudication, and shows the recovery is bounded by a cost curve with an irreducible residual. That work takes the governor's blocking as given and asks what can be repaired afterward. The present paper addresses the complementary and prior question: how the enforcement layer should decide what to expose and permit at the point of action, and when a learned policy for that decision outperforms a static one. The two are distinct in objective (recover vs. enforce), signal (blocked-trajectory→release vs. task/context→exposure), and placement (post-hoc second stage vs. pre-action gate).

*(If AMARE is published by submission time, replace "prior/companion work" with the citation.)*

---

## Standing rule for both papers

Every bibliography entry is verified against a primary source (title, authors, venue, year, identifier) before submission. This is now a required step, not an optional one. It applies to AgentWarden-v2, to any AMARE resubmission, and to MEMTIER/SafeSession alike.
