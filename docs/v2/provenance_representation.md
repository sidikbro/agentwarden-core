# Verification-history representation — design constraint

Status: constraint statement only. **Nothing in this document is
implemented.** It exists to record the constraint before any
`GovernanceContext` change is proposed, so the eventual implementation
isn't designed around whatever's most convenient at the time.

## Background

`docs/v2/RECONCILED_STATE_v0.2.md` §11b's gate 3a (defensively-framed-but-
unsafe tool calls, zero-tolerance BLOCK) didn't move when training volume
for its sibling category (safe-but-defended) increased 37×. Investigation
found the likely reason: `TrainingExample.context` (`router_training/
schema.py`) — the field where the synthetic dataset's authors wrote the
actual verification signal (e.g. *"a prior read step already confirmed
outbound traffic to malicious-c2.example.com"* vs. *"no prior step
verified this interpreter as compromised"*) — is written by every
generator and then dropped before the model ever sees it, in both
training (`to_training_pair`) and serving (`build_classify_prompt`).

A ceiling experiment (`router_training/train_pilot_ceiling.py`) retrains
the pilot with that field included, to find out whether the model can use
the signal at all *given a trusted oracle that just states the ground
truth*. That experiment is explicitly not a serving design — see its
module docstring — because the oracle it assumes doesn't exist. This
document is about the part the experiment can't answer: if a real
checkpoint needed a verification-status signal in production, where would
it legitimately come from?

## The constraint

**A verification-history field on `GovernanceContext` may only ever be
written by the enforcement layer itself, from its own audit log of prior
governance decisions in the current session — never from tool output,
never from model-generated text, and never from a claim embedded in the
current tool call's own arguments.**

Why this has to be the rule, not just a preference: the entire point of
gate 3a is catching tool calls that *assert* their own verification
("trust me," "no time to verify," "we detected fraud, act now") with
nothing backing the claim. Any field populated from tool output or
model-generated text is a field the same adversary who writes the
unverified claim can also write — populating "verification status" from
attacker-reachable text doesn't add a signal, it adds a new place for the
attacker to assert the thing they were already asserting, now laundered
through a field name that sounds authoritative. A verification-status
field is only meaningful if it's structurally impossible for the content
being classified to influence it — which means it can only be derived
from decisions AgentWarden itself already made and already logged, about
actions that already happened, not from anything in the current request.

This also means the field can't be "the previous tool call's stated
purpose" or "a summary of recent conversation" — both are still text an
attacker-controlled upstream (a poisoned tool result, an injected
instruction) can shape. It has to be AgentWarden's own record of its own
prior `GovernanceDecision`s: what was actually allowed, blocked, and why,
in this session, as AgentWarden itself decided it — not as anyone
describes it after the fact.

## Candidate source

`docs/architecture.md` §"Audit trail" describes a queryable `audit_log`
table as the system's record of governance decisions. **Checked while
writing this document: that's not what exists today.**
`agentwarden/core/audit.py`'s `AuditLogger.log_pipeline_result()` is a
single `logger.info(...)` call per decision — a log line, not a
persisted, queryable store. There is nothing in this codebase right now
that a verification-history lookup could query by session_id.

So the audit log is the right *shape* of candidate source — a record of
this system's own prior decisions, immune by construction to being
rewritten by the current tool call — but it does not currently exist in
a form that satisfies the constraint. Building a real queryable audit
store is therefore a prerequisite for this feature, not a detail inside
it, and should be scoped and reviewed as its own piece of work before any
`GovernanceContext` verification field is designed against it.

## What this document does not do

It does not propose a field name, a schema, a population mechanism, or an
implementation plan for `GovernanceContext`. It does not evaluate whether
the audit log (if real) is fast enough to query synchronously in the
request path, what "verified" should mean as a predicate over a decision
history, or how far back in a session a verification should count.
Those are real design questions and should be worked through deliberately,
not answered implicitly by whatever the first implementation happens to
do.
