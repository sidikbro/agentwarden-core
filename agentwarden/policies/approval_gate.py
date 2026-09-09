"""
Approval Gate — D3 (approve)
=============================
Tools in config/tools.yaml's `route_to_review` set (process, kill, chmod,
chown, sessions_spawn, subagent, subagents, delegate, task) are
conditionally legitimate — routine in CI/ops or multi-agent orchestration
— but high-risk enough that a bare classifier ALLOW shouldn't be the last
word. This stage runs after Stage 1 (rules) and Stage 2 (classifier),
which can still BLOCK such a call outright on content grounds (e.g. a
`chmod` call whose arguments target `/etc/shadow`). If neither of those
blocked it, this stage downgrades the call from ALLOW to Decision.REVIEW
rather than letting it execute silently.

There is currently no synchronous approval channel anywhere in this
codebase — no queue, no approver, no UI, nothing that could pause a
request and wait on a human. The proxy (agentwarden/server/app.py) is a
single synchronous HTTP request/response cycle. So REVIEW resolves to
"not executed" today — functionally the call is blocked — but the
decision is tagged and explained distinctly from an unconditional Stage-1
BLOCK, so:
  - audit records and future training data can tell "categorically
    forbidden" apart from "needs a human, none available"
  - a human can act on the record after the fact (e.g. pre-authorize the
    tool for that session/tenant)
  - once a real approval channel exists, raising
    stages.approval.timeout_ms above 0 changes this stage's behaviour
    without any other code change

Configurable via agentwarden.yaml:
    stages:
      approval:
        enabled: true
        timeout_ms: 0            # 0 = no synchronous approver exists yet
        default_on_timeout: block
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from agentwarden.core.base import PolicyPlugin
from agentwarden.core.models import (
    AgentWardenToolRequest,
    Decision,
    GovernanceDecision,
)
from agentwarden.core.registry import register_policy

logger = logging.getLogger("agentwarden.policies.approval_gate")

_HERE        = Path(__file__).parent.parent.parent   # repo root
_RULES_YAML  = _HERE / "config" / "rules.yaml"
_TOOLS_YAML  = _HERE / "config" / "tools.yaml"


def load_route_to_review(
    rules_file: Path | str | None = None,
    tools_file: Path | str | None = None,
) -> set[str]:
    """Tool names that are conditionally legitimate but must not be
    silently ALLOWed by Stage 2 alone — see module docstring. Loaded the
    same way RuleBasedPolicy loads always_block: tools.yaml's per-tool
    `route_to_review: true` flag, merged with rules.yaml's explicit
    `route_to_review` list (operator-editable mirror)."""
    rules_path = Path(rules_file) if rules_file else _RULES_YAML
    tools_path = Path(tools_file) if tools_file else _TOOLS_YAML

    route: set[str] = set()

    if tools_path.exists():
        try:
            tools_data = yaml.safe_load(tools_path.read_text()) or {}
            for name, cfg in (tools_data.get("tools") or {}).items():
                if cfg.get("route_to_review"):
                    route.add(name.lower())
        except Exception as e:
            logger.error("Could not load %s: %s", tools_path, e)

    if rules_path.exists():
        try:
            rules_data = yaml.safe_load(rules_path.read_text()) or {}
            for name in (rules_data.get("route_to_review") or []):
                route.add(name.lower())
        except Exception as e:
            logger.error("Could not load %s: %s", rules_path, e)

    return route


@register_policy
class ApprovalGatePolicy(PolicyPlugin):
    """
    D3 (approve). Runs after Stage 1 (rules) and Stage 2 (classifier).

    Applicable only to config/tools.yaml's route_to_review set. For those
    tools, a classifier ALLOW is downgraded to Decision.REVIEW rather than
    executing. Stage 1/2 can still BLOCK outright on content grounds
    before this stage ever runs — this stage never overrides a BLOCK,
    it only intercepts what would otherwise have been an ALLOW.
    """

    name        = "approval_gate"
    priority    = 22   # after classifier (20), before semantic_filter (25)
    is_terminal = False
    # Not marked terminal: GovernancePipeline._run_chain() treats any
    # BLOCK-or-REVIEW decision as chain-terminal by decision value, so a
    # policy doesn't need is_terminal=True to stop the chain when it
    # emits REVIEW.

    def __init__(
        self,
        route_to_review: set[str] | None = None,
        rules_file: str | None = None,
        tools_file: str | None = None,
        enabled: bool = True,
    ):
        self.route_to_review = (
            route_to_review if route_to_review is not None
            else load_route_to_review(rules_file, tools_file)
        )
        self.enabled = enabled

        logger.info(
            "[ApprovalGatePolicy] Loaded: %d route_to_review tools | enabled=%s",
            len(self.route_to_review), enabled,
        )

    def is_applicable(self, request: AgentWardenToolRequest) -> bool:
        return self.enabled and request.tool_call.name.lower() in self.route_to_review

    def evaluate(self, request: AgentWardenToolRequest) -> GovernanceDecision:
        # No synchronous approval channel exists yet (see module
        # docstring). This resolves to "not executed" for every call
        # today, but as Decision.REVIEW, not Decision.BLOCK — the
        # distinction is the entire point of this stage.
        return GovernanceDecision(
            request_id=request.request_id,
            tool_name=request.tool_call.name,
            decision=Decision.REVIEW,
            reason_detail=(
                f"'{request.tool_call.name}' requires approval; no approver "
                f"is configured (stages.approval.timeout_ms=0), so it was "
                f"not executed."
            ),
            confidence=1.0,
            stage=self.name,
        )
