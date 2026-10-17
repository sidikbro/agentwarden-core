"""B6's Governor — NOT a trained policy.

No training pipeline exists yet (L0-L6, docs/v2/EXPERIMENTAL_PLAN_v0.1.md
§8): a real PPO/CMDP/contextual-bandit run needs logged rollouts, a reward
signal, multi-seed training infra, and compute — a separate, later pass,
not something this session can produce. This class exists so B6 is
RUNNABLE today, implementing the interface a trained policy will have to
honor, so the eventual trained model is a drop-in replacement for this
class — same GovernanceProfile.expose() signature, nothing else changes.

The one property this class IS built to prove, because it's the property
that matters most: v1's policy learned tool IDENTITY instead of risk,
because tool_name was the only signal available to it. This class makes
tool_name structurally unavailable — expose() never reads
`request.tool_call.name` or any tool_name string for scoring. The only
signals read are:
  - tool_description (from a caller-supplied catalog — see
    benchmark/tool_metadata.py for the benchmark's version), risk-scored
    by a crude keyword heuristic, not learned;
  - SessionState.phase_history — mutating tools only unlock once the
    session has completed enough prior phases, inferred from HOW FAR the
    session has progressed, not from a declared phase label. This is
    deliberately a different mechanism from B3/B5 (which trust an
    externally-declared phase name) — B6 infers progression instead.

SessionState.prior_actions and .data_provenance are accepted and are
available to a real trained policy's feature set, but this placeholder's
heuristic does not condition on them beyond phase_history — that is a
known simplification of the placeholder, not a claim that provenance
doesn't matter. A trained policy would very plausibly use them (e.g. "was
this artifact's source external/untrusted" from data_provenance).
"""
from __future__ import annotations

from agentwarden.core.base import GovernanceProfile
from agentwarden.core.models import GovernanceContext, SessionState

# A description containing any of these is NEVER exposed, regardless of
# session_state — irreversible/dangerous actions don't unlock just because
# a session looks far along.
DANGEROUS_VERBS = {"execute", "arbitrary", "delete", "permanent", "sudo", "credential", "kill"}

# A description containing any of these is exposed unconditionally —
# read/query/diagnostic actions carry no meaningful escalation risk.
SAFE_VERBS = {
    "search", "fetch", "extract", "parse", "summarize", "list", "inspect",
    "read", "query", "correlate", "locate", "transform", "validate", "open", "run", "check",
}

# A description containing any of these is exposed only once the session
# has completed at least MIN_PHASES_FOR_MUTATION_TRUST distinct phases.
MUTATING_VERBS = {"write", "send", "modify", "apply", "create", "export"}

MIN_PHASES_FOR_MUTATION_TRUST = 2


class PlaceholderLearnedGovernor(GovernanceProfile):
    """See module docstring. Constructed with a tool catalog (name ->
    description) representing the runtime's registered tools — analogous
    to CapabilityGovernor being constructed with capability_profiles.yaml,
    a real Governor implementation needs to know its candidate pool up
    front since expose()'s own signature doesn't carry one.
    """

    name = "placeholder_learned_governor"
    description = "B6 placeholder: description + SessionState.phase_history risk heuristic, not a trained policy."

    def __init__(
        self,
        tool_catalog: dict[str, str],
        min_phases_for_mutation_trust: int = MIN_PHASES_FOR_MUTATION_TRUST,
    ):
        self._catalog = dict(tool_catalog)
        self._min_phases = min_phases_for_mutation_trust

    def _category(self, description: str) -> str:
        text = description.lower()
        if any(w in text for w in DANGEROUS_VERBS):
            return "dangerous"
        if any(w in text for w in SAFE_VERBS):
            return "safe"
        if any(w in text for w in MUTATING_VERBS):
            return "mutating"
        return "unknown"   # no keyword matched -- treated as not-yet-trusted, like "mutating"

    def expose(self, task_type: str, phase: str | None, session_state: SessionState) -> set[str]:
        trust_earned = len(session_state.phase_history) >= self._min_phases
        exposed = set()
        for tool_name, tool_description in self._catalog.items():
            category = self._category(tool_description)
            if category == "dangerous":
                continue
            if category == "safe":
                exposed.add(tool_name)
            elif trust_earned:   # "mutating" or "unknown"
                exposed.add(tool_name)
        return exposed

    def get_always_block(self, context: GovernanceContext) -> set[str]:
        return {
            name for name, desc in self._catalog.items()
            if self._category(desc) == "dangerous"
        }
