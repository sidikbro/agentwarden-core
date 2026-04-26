"""FastAPI governance proxy application."""
from __future__ import annotations
import logging, os
from typing import Any
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import httpx
from agentwarden.core.models import GovernanceContext, Runtime
from agentwarden.core.pipeline import build_pipeline, GovernancePipeline

logger = logging.getLogger("agentwarden.server")

def create_app(runtime: str = "generic", backend: str = "ollama",
               policy_name: str | None = None, shadow_mode: bool = False,
               rules_file: str | None = None, backend_url: str | None = None) -> FastAPI:

    if backend_url:
        os.environ[f"{backend.upper()}_BASE_URL"] = backend_url

    runtime_enum = Runtime(runtime)
    pipeline: GovernancePipeline = build_pipeline(
        runtime=runtime_enum, backend=backend,
        profile_name=policy_name, shadow_mode=shadow_mode,
    )

    app = FastAPI(title="AgentWarden Gateway", version="0.1.0",
                  description="Universal capability governance for AI agents.")

    @app.get("/health")
    async def health():
        return {"status": "ok", "runtime": runtime, "backend": backend,
                "shadow_mode": shadow_mode, "policy": policy_name}

    @app.get("/registry")
    async def registry_summary():
        from agentwarden.core.registry import get_registry
        return get_registry().summary()

    # OpenAI-compatible chat completions endpoint
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        return await _proxy_request(request, pipeline, runtime_enum)

    # Ollama-compatible endpoint
    @app.post("/api/chat")
    async def ollama_chat(request: Request):
        return await _proxy_request(request, pipeline, runtime_enum)

    return app

async def _proxy_request(request: Request, pipeline: GovernancePipeline, runtime: Runtime):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Build governance context
    ctx = GovernanceContext(runtime=runtime)

    # First: forward to LLM to get its response
    try:
        llm_response = await pipeline.provider.forward(body, dict(request.headers))
    except httpx.HTTPStatusError as e:
        logger.error("Backend error: %s", e)
        return JSONResponse({"error": "Backend error", "detail": str(e)}, status_code=502)
    except Exception as e:
        logger.error("Provider forward failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=502)

    # Then: run governance pipeline on LLM response
    result = await pipeline.process(llm_response, ctx)

    return JSONResponse(result.mutated_response)
