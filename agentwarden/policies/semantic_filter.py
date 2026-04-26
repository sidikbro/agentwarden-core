"""
Semantic Output Filter — Stage 3
==================================
Filters LLM response TEXT CONTENT for dangerous information expressed
in natural language (not tool calls).

This addresses the key limitation documented in the paper (\S5):
    "A request for a reverse shell caused qwen2.5:7b to return natural
    language instructions for nc -l -p 4444 in response text — without
    generating a tool call. The Safety Router did not intercept this."

Stage 3 closes that gap. It runs AFTER the LLM responds and AFTER
Stages 1+2 inspect tool calls. It inspects the text content of the
response using a dedicated safety model.

Default model: Llama Guard 3 (Meta, via Ollama)
    ollama pull llama-guard3

Alternative models (configurable):
    - llama-guard3             Meta's dedicated safety model (~5GB)
    - gemma4:e4b               General model with safety training (~9.6GB)
    - meta-llama/Llama-Guard-3-8B  via HuggingFace / vLLM
    - NeMo Guardrails output rail  via nemoguardrails library

Latency: ~200ms (Llama Guard 3, CPU) | ~50ms (GPU)
This stage is opt-in (disabled by default) due to latency.
Enable via config: stages.semantic_filter.enabled = true
Or env var: AGENTWARDEN_ENABLE_SEMANTIC_FILTER=true
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from agentwarden.core.base import PolicyPlugin
from agentwarden.core.models import (
    AgentWardenToolRequest,
    BlockReason,
    Decision,
    GovernanceDecision,
)
from agentwarden.core.registry import register_policy

logger = logging.getLogger("agentwarden.policies.semantic_filter")

# ── Llama Guard 3 prompt format ───────────────────────────────────────────────
# Based on Meta's official Llama Guard 3 spec
# https://github.com/meta-llama/PurpleLlama

LLAMA_GUARD_PROMPT = """[INST] Task: Check if there is unsafe content in the AI assistant response below.

<BEGIN AI ASSISTANT RESPONSE>
{response_text}
<END AI ASSISTANT RESPONSE>

Provide your safety assessment for the above AI assistant response.
- First line must read 'safe' or 'unsafe'.
- If unsafe, a second line must include a comma-separated list of violated categories. [/INST]"""

# Llama Guard 3 unsafe categories relevant to agent responses
UNSAFE_CATEGORIES = {
    "S1": "Violent Crimes",
    "S2": "Non-Violent Crimes",
    "S3": "Sex-Related Crimes",
    "S4": "Child Sexual Exploitation",
    "S5": "Defamation",
    "S6": "Specialized Advice",      # dangerous technical advice
    "S7": "Privacy",
    "S8": "Intellectual Property",
    "S9": "Indiscriminate Weapons",  # weapons, malware instructions
    "S10": "Hate",
    "S11": "Suicide & Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections",
    "S14": "Code Interpreter Abuse",  # dangerous code/commands in text
}

# Categories most relevant for agent safety
AGENT_RELEVANT_CATEGORIES = {"S2", "S6", "S9", "S14"}


@register_policy
class SemanticOutputFilter(PolicyPlugin):
    """
    Stage 3: Semantic content filter for LLM response text.

    Catches dangerous content expressed in natural language —
    the gap that tool-call-only inspection cannot cover.

    Examples caught by Stage 3 (not caught by Stages 1+2):
      - "To set up a reverse shell, run: nc -l -p 4444"
      - "Here's how to extract /etc/shadow: ..."
      - "You can bypass this by piping to bash: ..."
      - Credential exfiltration described in text

    Configurable via agentwarden.yaml:
        stages:
          semantic_filter:
            enabled: true
            model: llama-guard3      # or gemma4:e4b, or any Ollama model
            backend: ollama          # ollama | openai | nemo
            threshold: 0.7
            filter_input: true
            filter_output: true

    Or via environment variables:
        AGENTWARDEN_ENABLE_SEMANTIC_FILTER=true
        AGENTWARDEN_SEMANTIC_MODEL=llama-guard3
    """

    name     = "semantic_filter"
    priority = 25          # runs after classifier (20), before RL (30)
    is_terminal = False

    def __init__(
        self,
        model: str = "llama-guard3",
        backend: str = "ollama",
        threshold: float = 0.7,
        timeout_ms: int = 3000,
        filter_output: bool = True,
        filter_input: bool = True,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.model        = model
        self.backend      = backend
        self.threshold    = threshold
        self.timeout      = timeout_ms / 1000.0
        self.filter_output = filter_output
        self.filter_input  = filter_input
        self.base_url     = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.api_key      = api_key

        logger.info(
            "SemanticOutputFilter initialised | model=%s | backend=%s | threshold=%.2f",
            model, backend, threshold,
        )

    def is_applicable(self, request: AgentWardenToolRequest) -> bool:
        """
        Stage 3 inspects the response TEXT, not the tool call.
        It is applicable when there is text content in the response.
        """
        response_text = self._get_response_text(request.raw_response_body)
        return bool(response_text and len(response_text.strip()) > 10)

    def evaluate(self, request: AgentWardenToolRequest) -> GovernanceDecision:
        """
        Inspect the text content of the LLM response.
        Returns BLOCK if the content is classified as unsafe.
        """
        response_text = self._get_response_text(request.raw_response_body)
        if not response_text:
            return GovernanceDecision(
                request_id=request.request_id,
                tool_name="[response_text]",
                decision=Decision.ALLOW,
                stage=self.name,
            )

        t0 = time.perf_counter()
        try:
            result = self._classify_text(response_text)
        except Exception as e:
            logger.error("SemanticFilter error: %s — defaulting to ALLOW", e)
            return GovernanceDecision(
                request_id=request.request_id,
                tool_name="[response_text]",
                decision=Decision.ALLOW,
                stage=self.name,
                reason_detail=f"Filter error: {e}",
            )

        latency = (time.perf_counter() - t0) * 1000

        if result["unsafe"] and result["confidence"] >= self.threshold:
            categories = result.get("categories", [])
            logger.warning(
                "SemanticFilter BLOCK | categories=%s | confidence=%.2f | %.0fms",
                categories, result["confidence"], latency,
            )
            return GovernanceDecision(
                request_id=request.request_id,
                tool_name="[response_text]",
                decision=Decision.BLOCK,
                reason=BlockReason.LLM_CLASSIFIER,
                reason_detail=f"Unsafe content detected: {', '.join(categories)}",
                confidence=result["confidence"],
                latency_ms=latency,
                stage=self.name,
                reward_signal=-result["confidence"],
                metadata={"unsafe_categories": categories},
            )

        return GovernanceDecision(
            request_id=request.request_id,
            tool_name="[response_text]",
            decision=Decision.ALLOW,
            confidence=result["confidence"],
            latency_ms=latency,
            stage=self.name,
        )

    def _classify_text(self, text: str) -> dict[str, Any]:
        """Route to the configured backend."""
        if self.backend == "ollama":
            return self._classify_ollama(text)
        elif self.backend == "openai":
            return self._classify_openai(text)
        elif self.backend == "nemo":
            return self._classify_nemo(text)
        else:
            raise ValueError(f"Unknown semantic filter backend: {self.backend}")

    def _classify_ollama(self, text: str) -> dict[str, Any]:
        """Use Ollama with Llama Guard 3 or any compatible model."""
        import httpx

        # Llama Guard 3 uses a specific prompt format
        if "llama-guard" in self.model.lower():
            prompt = LLAMA_GUARD_PROMPT.format(response_text=text[:2000])
        else:
            # Generic safety prompt for other models (e.g. gemma4)
            prompt = (
                f"Is the following AI response unsafe, dangerous, or harmful? "
                f"Reply with only 'safe' or 'unsafe'.\n\n"
                f"Response: {text[:1000]}"
            )

        resp = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 64},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        output = resp.json().get("response", "").strip().lower()
        return self._parse_llama_guard_output(output)

    def _classify_openai(self, text: str) -> dict[str, Any]:
        """Use OpenAI-compatible API (e.g. vLLM with Llama Guard 3)."""
        import httpx

        api_key = self.api_key or os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content":
                    LLAMA_GUARD_PROMPT.format(response_text=text[:2000])
                }],
                "temperature": 0.0,
                "max_tokens": 64,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        output = resp.json()["choices"][0]["message"]["content"].strip().lower()
        return self._parse_llama_guard_output(output)

    def _classify_nemo(self, text: str) -> dict[str, Any]:
        """
        Use NVIDIA NeMo Guardrails output rail.
        Requires: pip install nemoguardrails
        """
        try:
            from nemoguardrails import RailsConfig, LLMRails
            # NeMo integration is configured separately via colang config
            # This is a placeholder for Phase 3 NeMo integration
            logger.warning("NeMo backend not yet fully implemented — falling back to ALLOW")
            return {"unsafe": False, "confidence": 0.0, "categories": []}
        except ImportError:
            logger.error("nemoguardrails not installed. Run: pip install nemoguardrails")
            return {"unsafe": False, "confidence": 0.0, "categories": []}

    def _parse_llama_guard_output(self, output: str) -> dict[str, Any]:
        """
        Parse Llama Guard 3 output format:
            "safe"
            or
            "unsafe\nS1,S14"
        """
        lines = output.strip().split("\n")
        first = lines[0].strip().lower()

        if first == "safe":
            return {"unsafe": False, "confidence": 0.95, "categories": []}

        if first == "unsafe":
            categories = []
            if len(lines) > 1:
                raw_cats = lines[1].strip().upper()
                categories = [c.strip() for c in raw_cats.split(",") if c.strip()]
            # Higher confidence if agent-relevant categories triggered
            agent_triggered = bool(set(categories) & AGENT_RELEVANT_CATEGORIES)
            confidence = 0.95 if agent_triggered else 0.75
            return {"unsafe": True, "confidence": confidence, "categories": categories}

        # Ambiguous output — check for keywords
        if "unsafe" in output:
            return {"unsafe": True, "confidence": 0.6, "categories": ["unknown"]}
        return {"unsafe": False, "confidence": 0.5, "categories": []}

    def _get_response_text(self, response_body: dict[str, Any]) -> str | None:
        """Extract text content from LLM response."""
        if not response_body:
            return None
        msg = response_body.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content") or msg.get("text")
            if content and isinstance(content, str):
                return content
        # OpenAI chat completions format
        choices = response_body.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content")
        return None


# ── Factory helper ────────────────────────────────────────────────────────────

def semantic_filter_from_config(cfg) -> SemanticOutputFilter | None:
    """
    Build a SemanticOutputFilter from AgentWardenConfig.
    Returns None if the stage is disabled.
    """
    sf_cfg = cfg.stages.semantic_filter
    if not sf_cfg.enabled:
        return None

    base_url = cfg.providers.ollama.base_url \
        if sf_cfg.backend == "ollama" else None

    return SemanticOutputFilter(
        model=sf_cfg.model,
        backend=sf_cfg.backend,
        threshold=sf_cfg.threshold,
        timeout_ms=sf_cfg.timeout_ms,
        filter_output=sf_cfg.filter_output,
        filter_input=sf_cfg.filter_input,
        base_url=base_url,
    )
