"""
Governance pipeline orchestrator.

Strict separation of concerns:
  Governor (Layer 1) = selects which tools are exposed (RL policy / YAML profile)
  Router   (Layer 2) = enforces decisions, never makes them

  Pipeline:
    parse → [Stage 1: rules] → [Stage 2: classifier] → [Stage 3: semantic filter]
          → reconstruct → audit

Safe fallback behaviour:
  - If any stage raises an exception → log error, ALLOW and continue to next stage
  - If ALL stages fail (pipeline_error) → apply safe_default() → block high-risk tools
  - If shadow_mode=True → log decisions but never mutate response

This means:
  A transient LLM classifier timeout does NOT block legitimate traffic.
  Stage 1 rules (0.1ms, deterministic) always run first and are the
  primary safety guarantee. Stage 2+ are defence-in-depth.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from agentwarden.core.audit import AuditLogger
from agentwarden.core.base import LLMProvider, PolicyPlugin, ToolParser
from agentwarden.core.models import (
    AgentWardenToolRequest,
    BlockReason,
    Decision,
    GovernanceContext,
    GovernanceDecision,
    PipelineResult,
    Runtime,
)

logger = logging.getLogger("agentwarden.pipeline")

# Risk level threshold for safe_default() fallback
# Tools with risk_level > this are blocked when the pipeline has errors
_SAFE_DEFAULT_MAX_RISK = 2


class GovernancePipeline:
    """
    Orchestrates the governance pipeline.

    Separation of concerns:
      - Parser:   translates raw LLM response → AgentWardenToolRequest objects
      - Policies: evaluate each request → GovernanceDecision (ALLOW/BLOCK)
                  Policies are PURE — they only decide, never execute
      - Provider: forwards allowed requests to LLM backend (in server/app.py)
      - Audit:    records all decisions asynchronously
    """

    def __init__(
        self,
        parser:      ToolParser,
        policies:    list[PolicyPlugin],
        provider:    LLMProvider,
        audit:       AuditLogger | None = None,
        shadow_mode: bool = False,
    ):
        self.parser      = parser
        self.policies    = sorted(policies, key=lambda p: p.priority)
        self.provider    = provider
        self.audit       = audit or AuditLogger()
        self.shadow_mode = shadow_mode

        policy_names = [p.name for p in self.policies]
        logger.info(
            "[Pipeline] Initialised | policies=%s | shadow_mode=%s",
            policy_names, shadow_mode,
        )

    async def process(
        self,
        raw_response: dict[str, Any],
        context:      GovernanceContext,
    ) -> PipelineResult:
        """
        Main entry point. Parse → evaluate → reconstruct → audit.

        Never raises — all exceptions are caught and logged.
        On pipeline-level failure, safe_default() is applied.
        """
        t0     = time.perf_counter()
        result = PipelineResult(session_id=context.session_id)

        try:
            requests = self.parser.parse(raw_response, context)
        except Exception as e:
            logger.error("[Pipeline] Parser error: %s — returning raw response", e)
            result.mutated_response = raw_response
            result.total_latency_ms = (time.perf_counter() - t0) * 1000
            result.pipeline_error   = str(e)
            return result

        if not requests:
            result.mutated_response = raw_response
            result.total_latency_ms = (time.perf_counter() - t0) * 1000
            return result

        allowed:   list[AgentWardenToolRequest] = []
        decisions: list[GovernanceDecision]    = []
        had_pipeline_error = False

        for req in requests:
            decision, error = self._run_chain(req)

            if error:
                had_pipeline_error = True
                # Safe fallback: apply risk-level check when chain failed
                decision = self._safe_default(req, error_reason=error)

            decisions.append(decision)

            if self.shadow_mode:
                # Shadow mode: log decision but always allow
                allowed.append(req)
                if decision.decision == Decision.BLOCK:
                    logger.info(
                        "[SHADOW] Would block | tool=%s | reason=%s | stage=%s",
                        req.tool_call.name, decision.reason, decision.stage,
                    )
                elif decision.decision == Decision.REVIEW:
                    logger.info(
                        "[SHADOW] Would require review | tool=%s | reason=%s | stage=%s",
                        req.tool_call.name, decision.reason_detail, decision.stage,
                    )
            elif decision.decision == Decision.ALLOW:
                allowed.append(req)
            elif decision.decision == Decision.REVIEW:
                logger.info(
                    "[REVIEW] tool=%s | reason=%s | stage=%s | latency=%.1fms",
                    req.tool_call.name, decision.reason_detail,
                    decision.stage, decision.latency_ms or 0,
                )
            else:
                logger.info(
                    "[BLOCK] tool=%s | reason=%s | stage=%s | latency=%.1fms",
                    req.tool_call.name, decision.reason,
                    decision.stage, decision.latency_ms or 0,
                )

        result.decisions         = decisions
        result.had_pipeline_error= had_pipeline_error
        result.mutated_response  = self.parser.reconstruct(raw_response, allowed)
        result.total_latency_ms  = (time.perf_counter() - t0) * 1000

        try:
            await self.audit.log_pipeline_result(result, context)
        except Exception as e:
            logger.error("[Pipeline] Audit log error: %s", e)

        return result

    def _run_chain(
        self, request: AgentWardenToolRequest
    ) -> tuple[GovernanceDecision, str | None]:
        """
        Run all policies in priority order.

        Returns (decision, error_reason).
        error_reason is None if chain completed normally.
        If ALL policies fail (exceptions), returns (None, error_message).

        Design:
          - A single policy exception → log, skip that stage, continue chain
          - If stage 1 (rules) succeeds → tool is definitively blocked or
            proceeds to stage 2. Stage 1 never raises in practice (pure regex).
          - If stage 2 (LLM classifier) times out → skip, ALLOW at this stage
            (stage 1 already cleared the obvious dangers)
        """
        any_policy_ran = False

        for policy in self.policies:
            if not policy.is_applicable(request):
                continue

            t0 = time.perf_counter()
            try:
                decision         = policy.evaluate(request)
                decision.latency_ms = (time.perf_counter() - t0) * 1000
                any_policy_ran   = True
            except Exception as e:
                latency = (time.perf_counter() - t0) * 1000
                logger.error(
                    "[Pipeline] Policy '%s' error (%.0fms): %s — skipping stage",
                    policy.name, latency, e,
                )
                continue

            # BLOCK and REVIEW are both chain-terminal: once a policy
            # decides a call should not simply execute, no later stage
            # gets to override that back to ALLOW.
            if decision.decision in (Decision.BLOCK, Decision.REVIEW):
                return decision, None

            # Terminal policy (e.g. RL policy) stops the chain on ALLOW too
            if policy.is_terminal:
                return decision, None

        if not any_policy_ran:
            return (
                GovernanceDecision(
                    request_id=request.request_id,
                    tool_name=request.tool_call.name,
                    decision=Decision.ALLOW,
                    stage="pipeline",
                ),
                "no_policy_ran",
            )

        # All policies ran, none blocked — ALLOW. Return the real terminal
        # stage's own decision object (its stage name, confidence, and
        # latency_ms intact), not a synthetic stage="pipeline" record that
        # discards which stage actually decided and how long it took.
        # `decision` is bound here: any_policy_ran is True, and any BLOCK or
        # terminal-policy decision already returned above.
        return decision, None

    def _safe_default(
        self,
        request:      AgentWardenToolRequest,
        error_reason: str,
    ) -> GovernanceDecision:
        """
        Fallback decision when the policy chain had errors.

        Strategy: block any tool with risk_level > _SAFE_DEFAULT_MAX_RISK (default 2).
        Tools without metadata default to risk_level=2 (medium) — allowed.

        This means:
          - read, web_search, memory operations → ALLOW (risk 0-1)
          - write, edit → ALLOW (risk 2)
          - exec, sessions_spawn → BLOCK (risk 3-4, caught by rules anyway)

        In practice, Stage 1 (rules) is pure Python regex and almost never fails.
        This fallback is for edge cases like corrupted config or unexpected exceptions.
        """
        risk_level = getattr(request.context, "tool_risk_level", 2)

        if risk_level > _SAFE_DEFAULT_MAX_RISK:
            logger.warning(
                "[SAFE_DEFAULT] Blocking high-risk tool=%s (risk=%d) due to pipeline error: %s",
                request.tool_call.name, risk_level, error_reason,
            )
            return GovernanceDecision(
                request_id   = request.request_id,
                tool_name    = request.tool_call.name,
                decision     = Decision.BLOCK,
                reason       = BlockReason.ALWAYS_BLOCK_TOOL,
                reason_detail= f"Safe default: pipeline error ({error_reason}), blocking risk>{_SAFE_DEFAULT_MAX_RISK} tool.",
                confidence   = 0.9,
                stage        = "safe_default",
                reward_signal= -1.0,
            )

        logger.info(
            "[SAFE_DEFAULT] Allowing low-risk tool=%s (risk=%d) despite pipeline error: %s",
            request.tool_call.name, risk_level, error_reason,
        )
        return GovernanceDecision(
            request_id   = request.request_id,
            tool_name    = request.tool_call.name,
            decision     = Decision.ALLOW,
            reason_detail= f"Safe default: pipeline error ({error_reason}), allowing risk<={_SAFE_DEFAULT_MAX_RISK} tool.",
            stage        = "safe_default",
        )


def build_pipeline(
    runtime:             Runtime,
    backend:             str,
    profile_name:        str | None = None,
    shadow_mode:         bool = False,
    rules_file:          str | None = None,
    tools_file:          str | None = None,
    extra_always_block:  list[str] | None = None,
) -> GovernancePipeline:
    """
    Build a fully configured pipeline from registry + config.

    Args:
        runtime:            Agent runtime (openclaw, nemoclaw, hermes, etc.)
        backend:            LLM backend (ollama, openai, deepseek, vllm)
        profile_name:       Optional governance profile from hub
        shadow_mode:        Log decisions but never block
        rules_file:         Override path to rules.yaml
        tools_file:         Override path to tools.yaml
        extra_always_block: Additional tool names to always-block
    """
    from agentwarden.core.registry import get_registry
    from agentwarden.policies.rules import RuleBasedPolicy

    reg      = get_registry()
    parser   = reg.get_parser(runtime)
    provider = reg.get_provider(backend)

    # Build policies — inject config file paths into RuleBasedPolicy
    policies = []
    for policy in reg.get_policies():
        if isinstance(policy, RuleBasedPolicy):
            # Rebuild with correct config paths
            policy = RuleBasedPolicy(
                rules_file=rules_file,
                tools_file=tools_file,
                extra_always_block=extra_always_block or [],
            )
        policies.append(policy)

    # If no RuleBasedPolicy in registry, add one (always present)
    if not any(isinstance(p, RuleBasedPolicy) for p in policies):
        policies.insert(0, RuleBasedPolicy(
            rules_file=rules_file,
            tools_file=tools_file,
            extra_always_block=extra_always_block or [],
        ))

    return GovernancePipeline(
        parser=parser,
        policies=policies,
        provider=provider,
        shadow_mode=shadow_mode,
    )
