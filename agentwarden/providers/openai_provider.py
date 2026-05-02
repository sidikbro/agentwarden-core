"""OpenAI-compatible backend (OpenAI, DeepSeek, vLLM, Gemma via Ollama)."""
from __future__ import annotations
import os, logging
import httpx
from agentwarden.core.base import LLMProvider
from agentwarden.core.registry import register_provider

logger = logging.getLogger("agentwarden.providers.openai")

@register_provider
class OpenAIProvider(LLMProvider):
    name = "openai"
    @property
    def base_url(self): return os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1")
    async def forward(self, request_body, headers=None, timeout=120.0):
        api_key = os.getenv("OPENAI_API_KEY","")
        h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        safe_headers = {k: v for k, v in (headers or {}).items()
                       if k.lower() not in ("authorization", "content-length", "host")}
        h.update(safe_headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=request_body, headers=h)
            resp.raise_for_status()
            return resp.json()

@register_provider
class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"
    @property
    def base_url(self): return "https://api.deepseek.com/v1"
    async def forward(self, request_body, headers=None, timeout=120.0):
        api_key = os.getenv("DEEPSEEK_API_KEY","")
        h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        # Strip incoming auth headers — use our backend key, not the agent's fake key
        safe_headers = {k: v for k, v in (headers or {}).items()
                       if k.lower() not in ("authorization", "content-length", "host")}
        h.update(safe_headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=request_body, headers=h)
            resp.raise_for_status()
            return resp.json()

@register_provider
class VLLMProvider(OpenAIProvider):
    name = "vllm"
    @property
    def base_url(self): return os.getenv("VLLM_BASE_URL","http://localhost:8080/v1")
