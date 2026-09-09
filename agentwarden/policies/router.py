"""
Safety Router — the complete two-stage inspection pipeline
==========================================================
This is the named concept from the AgentWarden paper.
It combines Stage 1 (rules) + Stage 2 (LLM classifier) into
a single importable object that users can reference by name.

Usage:
    from agentwarden.policies.router import SafetyRouter

    # Default: rules + Ollama-backed classifier
    router = SafetyRouter()

    # Custom: rules + local GGUF fine-tuned model
    router = SafetyRouter(
        model_path="~/models/agentwarden-router-v1.gguf",
        threshold=0.85,
    )

    # Rules only (no LLM, fastest):
    router = SafetyRouter(classifier_enabled=False)

The SafetyRouter is automatically included when you call build_pipeline().
You can also use it standalone for testing.
"""
from __future__ import annotations

import logging
from typing import Any

from agentwarden.policies.rules import RuleBasedPolicy
from agentwarden.policies.classifier import LLMClassifierPolicy
from agentwarden.core.models import AgentWardenToolRequest, GovernanceDecision, Decision

logger = logging.getLogger("agentwarden.policies.router")


class SafetyRouter:
    """
    The AgentWarden Safety Router.
    Two-stage hybrid classifier matching the paper's architecture:

        Stage 1: RuleBasedPolicy   — 0.1ms, deterministic
        Stage 2: LLMClassifierPolicy — ~800ms, semantic

    Reproduces the 100% TPR / 0% FPR result from the N=500 evaluation
    when used with the fine-tuned agentwarden-router weights.

    ** UNVERIFIED / CONTRADICTED — 2026-09 **: the "aethelgard-router"
    Ollama tags actually available in this environment do NOT reproduce
    this. Directly tested (agentwarden/profiles/... benchmark work,
    scripts/report_baselines.py): aethelgard-router:latest returns BLOCK
    for every one of 12 tested tool calls, including obviously benign ones
    (search_web, read_code, read_email), with fabricated justifications
    ("read_email ... violates Aethelgard policy", "extract_facts ...
    attempts to execute arbitrary code" — both false). Confirmed
    independent of any prompt-format issue by querying the model with only
    its own baked-in system prompt. aethelgard-router-q4:latest 500s on
    every request. If "100% TPR / 0% FPR" was ever measured, it was not
    measured against the model artifact currently tagged with this name —
    either the weights regressed/were replaced, or the original result
    needs re-verification against whatever checkpoint is authoritative.
    Do not cite this figure without re-running the evaluation against a
    known-good checkpoint first.
    """

    def __init__(
        self,
        model_path: str | None = None,
        ollama_model: str | None = None,
        threshold: float = 0.85,
        rules_file: str | None = None,
        classifier_enabled: bool = True,
    ):
        self.stage1 = RuleBasedPolicy(rules_file=rules_file)
        self.stage2 = LLMClassifierPolicy(
            model_path=model_path,
            ollama_model=ollama_model,
            threshold=threshold,
        ) if classifier_enabled else None

        logger.info(
            "SafetyRouter ready | stage1=rules | stage2=%s | threshold=%.2f",
            "llm_classifier" if self.stage2 else "disabled", threshold,
        )

    def inspect(self, request: AgentWardenToolRequest) -> GovernanceDecision:
        """
        Synchronous single-request inspection.
        Returns a GovernanceDecision with stage, reason, and confidence.
        """
        # Stage 1: rules (0.1ms). Checking "!= ALLOW" rather than
        # "== BLOCK" means this stays correct if rules.py or a future
        # stage ever hands back Decision.REVIEW instead of BLOCK/ALLOW —
        # this two-stage router only combines rules+classifier, but a
        # REVIEW passed through here should not be silently coerced to
        # ALLOW.
        d1 = self.stage1.evaluate(request)
        if d1.decision != Decision.ALLOW:
            return d1

        # Stage 2: LLM classifier (~800ms) — skip if disabled or tool is safe
        if self.stage2 and self.stage2.is_applicable(request):
            d2 = self.stage2.evaluate(request)
            if d2.decision != Decision.ALLOW:
                return d2

        return GovernanceDecision(
            request_id=request.request_id,
            tool_name=request.tool_call.name,
            decision=Decision.ALLOW,
            stage="router",
        )

    @property
    def policies(self) -> list:
        """Return as a list for use with GovernancePipeline."""
        if self.stage2:
            return [self.stage1, self.stage2]
        return [self.stage1]
