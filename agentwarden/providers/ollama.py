"""Ollama backend provider."""
from __future__ import annotations
import os, logging
import httpx
from agentwarden.core.base import LLMProvider
from agentwarden.core.registry import register_provider

logger = logging.getLogger("agentwarden.providers.ollama")

@register_provider
class OllamaProvider(LLMProvider):
    name = "ollama"
    @property
    def base_url(self): return os.getenv("OLLAMA_BASE_URL","http://localhost:11434")
    async def forward(self, request_body, headers=None, timeout=120.0):
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=request_body, headers=headers or {})
            resp.raise_for_status()
            return resp.json()
