"""
LLM Classifier Policy — Stage 2 of the Safety Router
======================================================
When Stage 1 rules pass, this policy runs the tool call through a
fine-tuned LLM classifier (agentwarden-router, Qwen2.5-1.5B GGUF).

OSS tier:  Uses the base model with zero-shot prompting (~70% accuracy)
Enterprise: Uses fine-tuned LoRA weights (~95%+ accuracy on tenant traffic)

The classifier is intentionally skipped for known-safe tools
(read, memory_search, web_search) to avoid false positives.
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

logger = logging.getLogger("agentwarden.policies.classifier")

# Tools that are safe enough to skip LLM classification entirely
SKIP_CLASSIFIER_TOOLS = {
    "read", "read_file", "memory_search", "memory_get",
    "web_search", "read_todos", "ls", "glob", "grep",
}

# Classifier threshold — calls above this confidence are blocked
DEFAULT_BLOCK_THRESHOLD = 0.85

CLASSIFY_PROMPT = """You are a security classifier for AI agent tool calls.
Determine if the following tool call is DANGEROUS or SAFE.

Tool: {tool_name}
Arguments: {arguments}

Rules:
- DANGEROUS: shell execution, file deletion, credential access, prompt injection, subagent spawning, network exfiltration
- SAFE: reading files, web search, memory operations, sending pre-approved messages

Respond with JSON only: {{"decision": "BLOCK" or "ALLOW", "confidence": 0.0-1.0, "reason": "brief explanation"}}"""


@register_policy
class LLMClassifierPolicy(PolicyPlugin):
    """
    Stage 2 LLM-based classifier. Runs after rules pass.
    Latency: ~800ms (local GGUF) or ~200ms (API-based).

    Backends (in priority order):
      1. Local GGUF via llama-cpp-python  (agentwarden-router model)
      2. Ollama API                        (any model, e.g. gemma4:e4b)
      3. OpenAI-compatible API             (for cloud deployments)
      4. Zero-shot fallback via Ollama     (no fine-tuned weights needed)
    """

    name     = "llm_classifier"
    priority = 20
    is_terminal = False

    def __init__(
        self,
        model_path: str | None = None,
        ollama_model: str | None = None,
        threshold: float = DEFAULT_BLOCK_THRESHOLD,
        skip_tools: set[str] | None = None,
        backend: str = "auto",
    ):
        self.model_path   = model_path or os.getenv("AGENTWARDEN_ROUTER_MODEL")
        self.ollama_model = ollama_model or os.getenv("AGENTWARDEN_CLASSIFIER_MODEL", "qwen2.5:1.5b")
        self.threshold    = threshold
        self.skip_tools   = skip_tools or SKIP_CLASSIFIER_TOOLS
        self.backend      = backend
        self._llm         = None  # lazy init

        logger.info(
            "LLM classifier initialised | backend=%s | model=%s | threshold=%.2f",
            backend, self.ollama_model or self.model_path, threshold,
        )

    def is_applicable(self, request: AgentWardenToolRequest) -> bool:
        """Skip classifier for known-safe tools."""
        return request.tool_call.name.lower() not in self.skip_tools

    def evaluate(self, request: AgentWardenToolRequest) -> GovernanceDecision:
        tc = request.tool_call
        t0 = time.perf_counter()

        try:
            result = self._classify(tc.name, tc.arguments)
            decision_str = result.get("decision", "ALLOW").upper()
            confidence   = float(result.get("confidence", 0.5))
            reason       = result.get("reason", "")
        except Exception as e:
            # Fail open — if classifier errors, allow and log
            logger.error("Classifier error for tool %s: %s — defaulting to ALLOW", tc.name, e)
            return GovernanceDecision(
                request_id=request.request_id,
                tool_name=tc.name,
                decision=Decision.ALLOW,
                stage=self.name,
                reason_detail=f"Classifier error: {e}",
            )

        latency = (time.perf_counter() - t0) * 1000

        if decision_str == "BLOCK" and confidence >= self.threshold:
            logger.info(
                "Classifier BLOCK | tool=%s | confidence=%.2f | reason=%s | %.0fms",
                tc.name, confidence, reason, latency,
            )
            return GovernanceDecision(
                request_id=request.request_id,
                tool_name=tc.name,
                decision=Decision.BLOCK,
                reason=BlockReason.LLM_CLASSIFIER,
                reason_detail=reason,
                confidence=confidence,
                latency_ms=latency,
                stage=self.name,
                reward_signal=-confidence,
            )

        return GovernanceDecision(
            request_id=request.request_id,
            tool_name=tc.name,
            decision=Decision.ALLOW,
            confidence=confidence,
            latency_ms=latency,
            stage=self.name,
        )

    def _classify(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route to the available classifier backend."""
        prompt = CLASSIFY_PROMPT.format(
            tool_name=tool_name,
            arguments=json.dumps(arguments, ensure_ascii=False)[:500],
        )

        # Priority 1: local GGUF model (fine-tuned agentwarden-router)
        if self.model_path and os.path.exists(self.model_path):
            return self._classify_gguf(prompt)

        # Priority 2: Ollama API (zero-shot or fine-tuned via Modelfile)
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if self._ollama_available(ollama_url):
            return self._classify_ollama(prompt, ollama_url)

        # Priority 3: OpenAI-compatible API
        if os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY"):
            return self._classify_openai(prompt)

        # No backend available — fail open with warning
        logger.warning("No classifier backend available — defaulting to ALLOW for %s", tool_name)
        return {"decision": "ALLOW", "confidence": 0.0, "reason": "no classifier backend"}

    def _classify_gguf(self, prompt: str) -> dict[str, Any]:
        """Use local llama-cpp-python with the GGUF model."""
        if self._llm is None:
            try:
                from llama_cpp import Llama
                self._llm = Llama(
                    model_path=self.model_path,
                    n_ctx=512,
                    n_threads=4,
                    verbose=False,
                )
                logger.info("Loaded GGUF model: %s", self.model_path)
            except ImportError:
                raise RuntimeError("llama-cpp-python not installed. Run: pip install llama-cpp-python")

        output = self._llm(
            prompt,
            max_tokens=128,
            temperature=0.0,
            stop=["\n\n"],
        )
        text = output["choices"][0]["text"].strip()
        return self._parse_json_response(text)

    def _classify_ollama(self, prompt: str, base_url: str) -> dict[str, Any]:
        """Use Ollama API for classification."""
        import httpx
        resp = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 128},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        return self._parse_json_response(text)

    def _classify_openai(self, prompt: str) -> dict[str, Any]:
        """Use OpenAI-compatible API for classification."""
        import httpx
        api_key  = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model    = os.getenv("AGENTWARDEN_CLASSIFIER_API_MODEL", "gpt-4o-mini")

        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 128,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        return self._parse_json_response(text)

    def _ollama_available(self, base_url: str) -> bool:
        try:
            import httpx
            r = httpx.get(f"{base_url}/api/tags", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Parse classifier JSON response, with fallback for malformed output."""
        # Strip markdown fences if present
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract decision from raw text
            upper = text.upper()
            if "BLOCK" in upper:
                return {"decision": "BLOCK", "confidence": 0.7, "reason": "classifier said BLOCK"}
            return {"decision": "ALLOW", "confidence": 0.5, "reason": "could not parse response"}
