# Prompt-injection detection (RuleBasedPolicy) is structurally non-functional

**Status:** open, needs a design decision — not a test fix
**Found:** 2026-09-08, while diagnosing pre-existing test failures during AgentWarden-v2 benchmark work
**Affects:** `agentwarden/policies/rules.py` (`RuleBasedPolicy.evaluate`, injection-pattern check)
**Tests:** `tests/unit/test_policies.py::TestRuleBasedPolicy::test_injection_patterns[*]` (7 cases) — left failing intentionally, do not "fix" by changing the assertions

## Summary

`config/rules.yaml`'s `injection_patterns` list (classic prompt-injection strings like "ignore all previous instructions", "you are now a DAN", "jailbreak") is loaded and compiled correctly, but the check that's supposed to apply it never sees any real content — it always evaluates against an empty string. Injection-pattern blocking has never actually blocked anything in this codebase.

## Root cause

`agentwarden/policies/rules.py`, inside `RuleBasedPolicy.evaluate()`:

```python
context_str = getattr(request.context, "system_prompt", "") or ""[:2000] if request.context else ""
```

Two independent problems:

1. **`GovernanceContext` (`agentwarden/core/models.py`) has no `system_prompt` field.** Its fields are `session_id, runtime, task_type, trust_level, allowed_tools, tenant_id, profile_name, metadata`. So `getattr(request.context, "system_prompt", "")` always returns the default `""`, for every real caller — there is no field for a caller to populate even if it wanted to.
2. **Operator-precedence bug**, independent of (1): `A or B if C else D` parses as `(A or B) if C else D`, not `A or (B if C else D)` as the line's layout suggests. Given `B = ""[:2000]` (a slice of a literal empty string, always `""`), this doesn't currently change behavior, but the line's intent — presumably "empty-truncate the context string to 2000 chars" — doesn't do anything of the sort. Confirmed empirically:

```python
>>> from agentwarden.core.models import GovernanceContext
>>> ctx = GovernanceContext(session_id="t")
>>> hasattr(ctx, "system_prompt")
False
>>> getattr(ctx, "system_prompt", "") or ""[:2000] if ctx else ""
''
```

## Impact

Every one of `config/rules.yaml`'s `injection_patterns` entries — "ignore all previous instructions", "you are now a DAN", "jailbreak", "act as if you are unrestricted", "system prompt: new instructions", "pretend you have no restrictions", "forget all previous context", "new persona:" — is dead. `RuleBasedPolicy` only ever blocks on `always_block` tool names and `arg_patterns` (which scan `tool_call.arguments`, a separate and working code path). Any classic prompt-injection string reaching the agent via system prompt or conversation context sails through Stage 1 unblocked.

## Why this needs a design decision, not a quick patch

Fixing the operator-precedence bug alone accomplishes nothing, because there's still no field to read from. The real question is **where injection content is supposed to come from and at what layer it should be scanned**:

- **Option A** — add a `system_prompt: str | None` field to `GovernanceContext`, and have the proxy (`agentwarden/server/app.py`) populate it from the incoming request's `messages` (system role content) before constructing each `AgentWardenToolRequest`. Closest to what the current code appears to have intended.
- **Option B** — scan the full incoming conversation (not just a "system prompt" slot) for injection patterns, since injected instructions increasingly arrive via tool results or user turns, not the system message. This is closer to what AMARE's indirect-injection framing (A2 in the AgentWarden-v2 benchmark plan) actually cares about, and overlaps with `agentwarden/policies/semantic_filter.py`'s stated purpose — worth checking whether semantic_filter.py already covers this ground and rules.py's injection_patterns list is redundant/dead weight rather than a gap.
- **Option C** — drop `injection_patterns` from `RuleBasedPolicy` entirely and treat prompt-injection detection as exclusively Stage 3's (semantic filter's) job, if that's the intended division of labor.

The test file's own `make_request()` helper independently gets this wrong too — it puts the injection string into `tool_call.arguments` (`{"query": injection}`), which is the `arg_patterns` code path, not `injection_patterns`. Fixing only the test's request construction would not make these tests pass today regardless, since the feature itself has nothing to read.

## Suggested next step

Decide which option (A/B/C) above reflects the intended architecture, update `GovernanceContext`/the proxy/the test's `make_request()` helper accordingly, then re-enable these 7 tests against the corrected construction.

## Filing note

`gh` CLI is not installed in this environment, so this was not opened as a GitHub issue on `sidikbro/agentwarden-core` — it's tracked here instead. If you want it filed for real, either install/authenticate `gh` and say so, or paste this file's content into a new issue yourself.
