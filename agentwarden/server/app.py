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


def _normalize_openai_to_ollama(response: dict) -> dict:
    """
    Normalize OpenAI/DeepSeek response format to Ollama format.
    OpenAI: {"choices": [{"message": {...}}]}
    Ollama: {"message": {...}}
    Called before governance pipeline when backend returns OpenAI format.
    """
    import json as _json
    if "choices" not in response or "message" in response:
        return response  # already Ollama format or unknown
    choices = response.get("choices", [])
    if not choices:
        return response
    message = dict(choices[0].get("message", {}))
    # Normalize tool_call arguments: OpenAI uses JSON strings, Ollama uses dicts
    tool_calls = message.get("tool_calls", []) or []
    normalized = []
    for tc in tool_calls:
        tc = dict(tc)
        fn = dict(tc.get("function", {}))
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = _json.loads(args)
            except Exception:
                args = {"_raw": args}
        fn["arguments"] = args
        tc["function"] = fn
        normalized.append(tc)
    message["tool_calls"] = normalized
    return {
        **response,
        "message": message,
        "done": True,
        "done_reason": choices[0].get("finish_reason", "stop"),
    }


def _normalize_ollama_to_openai(response: dict, original: dict) -> dict:
    """
    Restore OpenAI format after pipeline processing.
    /v1/chat/completions callers (DeepAgents) expect OpenAI format back.
    """
    import json as _json
    if "message" not in response:
        return response
    msg = dict(response["message"])
    tool_calls = msg.get("tool_calls", []) or []
    normalized = []
    for tc in tool_calls:
        tc = dict(tc)
        fn = dict(tc.get("function", {}))
        args = fn.get("arguments", {})
        if isinstance(args, dict):
            fn["arguments"] = _json.dumps(args)
        tc["function"] = fn
        normalized.append(tc)
    msg["tool_calls"] = normalized
    result = {**original}
    result["choices"] = [{
        "index": 0,
        "message": msg,
        "finish_reason": response.get("done_reason", "stop"),
    }]
    for k in ["message", "done", "done_reason"]:
        result.pop(k, None)
    return result


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

    # Detect if caller expects OpenAI format (/v1/chat/completions)
    openai_format = str(request.url.path).startswith("/v1/")

    # Build governance context
    ctx = GovernanceContext(runtime=runtime)

    # Forward to LLM backend
    try:
        llm_response = await pipeline.provider.forward(body, dict(request.headers))
    except httpx.HTTPStatusError as e:
        logger.error("Backend error: %s", e)
        return JSONResponse({"error": "Backend error", "detail": str(e)}, status_code=502)
    except Exception as e:
        logger.error("Provider forward failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=502)

    # Normalize OpenAI format → Ollama format for pipeline processing
    # DeepSeek/OpenAI returns {"choices":[{"message":{...}}]}
    # Pipeline expects {"message":{...}}
    original_response = llm_response
    if "choices" in llm_response and "message" not in llm_response:
        llm_response = _normalize_openai_to_ollama(llm_response)

    # Run governance pipeline
    result = await pipeline.process(llm_response, ctx)
    response = result.mutated_response

    # Restore OpenAI format for /v1/chat/completions callers (DeepAgents, LangGraph)
    if openai_format and "message" in response:
        response = _normalize_ollama_to_openai(response, original_response)

    return JSONResponse(response)
