"""OpenAI-compatible backend (OpenAI, DeepSeek, vLLM, Gemma via Ollama)."""
from __future__ import annotations
import os, logging
import httpx
from agentwarden.core.base import LLMProvider
from agentwarden.core.registry import register_provider

logger = logging.getLogger("agentwarden.providers.openai")

_STRIP_HEADERS = {"authorization", "content-length", "host", "content-type"}


def _safe_headers(headers: dict | None) -> dict:
    """Strip auth/size headers — use backend's own credentials instead."""
    return {k: v for k, v in (headers or {}).items()
            if k.lower() not in _STRIP_HEADERS}


def _fix_roles(request_body: dict) -> dict:
    """Convert 'developer' role → 'system' (unsupported by DeepSeek/OpenAI)."""
    if "messages" not in request_body:
        return request_body
    msgs = [
        {**m, "role": "system"} if m.get("role") == "developer" else m
        for m in request_body["messages"]
    ]
    return {**request_body, "messages": msgs}


@register_provider
class OpenAIProvider(LLMProvider):
    name = "openai"

    @property
    def base_url(self):
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    async def forward(self, request_body, headers=None, timeout=120.0):
        api_key = os.getenv("OPENAI_API_KEY", "")
        h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
             "Accept-Encoding": "identity"}
        h.update(_safe_headers(headers))
        # Force non-streaming — AgentWarden needs full JSON response for governance
        body = {**_fix_roles(request_body), "stream": False}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=h,
            )
            resp.raise_for_status()
            return resp.json()


@register_provider
class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"

    @property
    def base_url(self):
        return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    async def forward(self, request_body, headers=None, timeout=120.0):
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
             "Accept-Encoding": "identity"}
        h.update(_safe_headers(headers))
        body = {**_fix_roles(request_body), "stream": False}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=h,
            )
            resp.raise_for_status()
            return resp.json()


@register_provider
class VLLMProvider(OpenAIProvider):
    name = "vllm"

    @property
    def base_url(self):
        return os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1")
