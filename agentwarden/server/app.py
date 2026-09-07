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
_session_store: dict = {}  # module-level session accumulator
_outcome_logger_instance = None  # module-level outcome logger



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
    # OpenClaw expects content=null when tool_calls present
    if normalized:
        msg["content"] = None
    result = {**original}
    result["choices"] = [{
        "index": 0,
        "message": msg,
        "finish_reason": "tool_calls" if normalized else response.get("done_reason", "stop"),
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
    from agentwarden.session_outcomes import SessionOutcomeLogger as _SOL, SessionOutcomeRecord as _SOR
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Detect if caller expects OpenAI format (/v1/chat/completions)
    openai_format = str(request.url.path).startswith("/v1/")
    logger.info("REQUEST body keys=%s model=%s stream=%s msg_count=%s", list(body.keys()), body.get("model"), body.get("stream"), len(body.get("messages",[])))

    # ── Session tracking for AMARE RL ──────────────────────────────────────
    import time as _time, hashlib as _hashlib
    _msgs0 = body.get("messages", [])
    _first_user0 = next((m.get("content","") for m in _msgs0 if m.get("role")=="user"), "")
    _first_str0 = _first_user0 if isinstance(_first_user0, str) else str(_first_user0)
    _req_session_id = _hashlib.md5(_first_str0[:200].encode()).hexdigest()[:16]
    if _req_session_id not in _session_store:
        _session_store[_req_session_id] = {"tools_used":[],"blocks":[],"start_ms":int(_time.time()*1000)}
    _sess0 = _session_store[_req_session_id]
    _session_start_ms = _sess0["start_ms"]
    _session_tools_used = _sess0["tools_used"]
    _session_blocks = _sess0["blocks"]
    # ─────────────────────────────────────────────────────────────────────
    # Build governance context
    ctx = GovernanceContext(runtime=runtime)

    body_original = body.copy()
    # Rewrite model name to backend's actual model name
    # (agent sends "my-model" or "my-openai-proxy/my-model" but backend needs "deepseek-chat")
    import os as _os
    backend = _os.getenv("AGENTWARDEN_BACKEND", "ollama")
    backend_model_map = {
        "deepseek": _os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "openai":   _os.getenv("OPENAI_MODEL", "gpt-4o"),
    }
    if backend in backend_model_map:
        body = {**body, "model": backend_model_map[backend]}

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

    # Filter blocked tool calls from response message
    # Instead of returning error, remove blocked calls so agent continues with allowed ones
    if result.decisions:
        blocked_ids = {
            d.request_id for d in result.decisions
            if hasattr(d, "decision") and str(d.decision).endswith("BLOCK")
        }
        blocked_tools = {
            d.tool_name for d in result.decisions
            if hasattr(d, "decision") and str(d.decision).endswith("BLOCK")
        }
        if blocked_tools and "message" in response:
            msg = dict(response["message"])
            original_calls = msg.get("tool_calls") or []
            allowed_calls = [
                tc for tc in original_calls
                if tc.get("function", {}).get("name") not in blocked_tools
            ]
            if len(allowed_calls) < len(original_calls):
                removed = [tc.get("function", {}).get("name") for tc in original_calls
                          if tc.get("function", {}).get("name") in blocked_tools]
                logger.info("[FILTER] Removed blocked tool calls: %s", removed)
                if allowed_calls:
                    msg["tool_calls"] = allowed_calls
                else:
                    # All calls blocked — return text explanation
                    msg["tool_calls"] = []
                    msg["content"] = (
                        f"I cannot perform the requested operation. "
                        f"The following tools are not permitted in this governed session: "
                        f"{', '.join(blocked_tools)}. "
                        f"Please request an alternative approach."
                    )
                response = {**response, "message": msg}

    # Audit log + accumulate session tools for AMARE RL
    for d in (result.decisions if result.decisions else []):
        _tn = getattr(d, "tool_name", "unknown")
        _dec = getattr(d, "decision", None)
        _dec_str = str(_dec.value) if hasattr(_dec, "value") else str(_dec)
        _lat = getattr(d, "latency_ms", 0) or 0
        logger.info("AUDIT | session=%s | tool=%s | decision=%s | latency=%.1fms",
                    ctx.session_id, _tn, _dec_str, _lat)
        _session_tools_used.append(_tn)
        if _dec_str.endswith("BLOCK"):
            _stage = getattr(d, "stage", None)
            _stage_str = str(_stage.value) if hasattr(_stage, "value") else str(_stage or "unknown")
            _session_blocks.append({"tool": _tn, "stage": _stage_str})
    # Audit log + accumulate session tools for AMARE RL
    for d in (result.decisions if result.decisions else []):
        _tn = getattr(d, "tool_name", "unknown")
        _dec = getattr(d, "decision", None)
        _dec_str = str(_dec.value) if hasattr(_dec, "value") else str(_dec)
        _lat = getattr(d, "latency_ms", 0) or 0
        logger.info("AUDIT | session=%s | tool=%s | decision=%s | latency=%.1fms",
                    ctx.session_id, _tn, _dec_str, _lat)
        _session_tools_used.append(_tn)
        if _dec_str.endswith("BLOCK"):
            _stage = getattr(d, "stage", None)
            _stage_str = str(_stage.value) if hasattr(_stage, "value") else str(_stage or "unknown")
            _session_blocks.append({"tool": _tn, "stage": _stage_str})
    # Restore OpenAI format for /v1/chat/completions callers (DeepAgents, LangGraph)
    if openai_format and "message" in response:
        response = _normalize_ollama_to_openai(response, original_response)
        # Preserve the model name from the original request (not backend model name)
        response["model"] = body.get("model", response.get("model", ""))

    # Return SSE format if original request was streaming
    original_stream = body_original.get("stream", False) if hasattr(body_original, "get") else False
    logger.warning("RESP_CHECK openai=%s stream=%s keys=%s", openai_format, original_stream, list(response.keys()) if isinstance(response, dict) else type(response))
    if openai_format and original_stream and "choices" in response:
        from fastapi.responses import StreamingResponse
        import json as _json

        def sse_stream(_tools_used=_session_tools_used, _blocks=_session_blocks, _start=_session_start_ms, _sid=_req_session_id, _sess_store=_session_store):
            msg = response["choices"][0]["message"]
            # Chunk 1: role
            chunk = {**response, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {"role": msg.get("role","assistant"), "content": ""}, "finish_reason": None}]}
            yield "data: " + _json.dumps(chunk) + "\n\n"


            # Chunk 2: content or tool_calls
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                delta = {"tool_calls": tool_calls}
            else:
                delta = {"content": msg.get("content") or ""}
            chunk2 = {**response, "object": "chat.completion.chunk",
                      "choices": [{"index": 0, "delta": delta,
                                   "finish_reason": response["choices"][0].get("finish_reason")}]}
            yield "data: " + _json.dumps(chunk2) + "\n\n"


            # Log session outcome (final SSE turn)
            try:
                import os as _o2, time as _t2
                _fn = "stop"
                if "choices" in response:
                    _fn = response["choices"][0].get("finish_reason", "stop") or "stop"
                logger.warning("SESSION_DBG fn=%s sid=%s tools=%s", _fn, _sid, _tools_used)
                if _fn not in ("tool_calls", "tool_use"):
                    _ex = []
                    for _t in (body.get("tools") or []):
                        if isinstance(_t, dict):
                            _n = (_t.get("function") or {}).get("name") or _t.get("name") or ""
                            if _n:
                                _ex.append(_n)
                    _us = list(dict.fromkeys(_tools_used))
                    _bc = len(_blocks)
                    _sr = round(len([x for x in _us if x in _ex]) / max(len(_ex), 1), 4) if _ex else 0.0
                    logger.warning("SESSION_OUTCOME id=%s tools=%s ser=%s bc=%s", _sid, _us, _sr, _bc)
                    _log_inst = _outcome_logger_instance or _SOL()
                    _log_inst.log(_SOR(
                        session_id=_sid,
                        tenant_id=_o2.getenv("AGENTWARDEN_TENANT_ID", "default"),
                        task_type=getattr(ctx, "task_type", "unknown"),
                        task_success=0,
                        tools_exposed=_ex,
                        tools_used=_us,
                        failure_reason="blocked" if _bc > 0 else None,
                        missing_tools=[b["tool"] for b in _blocks],
                        ser=_sr,
                        block_count=_bc,
                        stage1_blocks=sum(1 for b in _blocks if b.get("stage") == "rules"),
                        stage2_blocks=sum(1 for b in _blocks if b.get("stage") == "classifier"),
                        duration_ms=int(_t2.time() * 1000) - _start,
                        notes="runtime:" + runtime.value,
                    ))
                    _sess_store.pop(_sid, None)
            except Exception as _se:
                logger.warning("SESSION_OUTCOME_FAIL %s", _se)
            yield "data: [DONE]\n\n"

        # Log session outcome before streaming (synchronous, has full response)
        try:
            _fn4 = response["choices"][0].get("finish_reason", "stop") or "stop"
            _us4 = list(dict.fromkeys(_session_tools_used))
            _bc4 = len(_session_blocks)
            _ex4 = [t.get("function", {}).get("name", t.get("name", "")) for t in (body.get("tools") or []) if isinstance(t, dict)]
            _sr4 = round(len([t for t in _us4 if t in _ex4]) / max(len(_ex4), 1), 4) if _ex4 else 0.0
            print(f"PRE_SSE fn={_fn4} sid={_req_session_id} tools={_us4} ser={_sr4} bc={_bc4}", flush=True)
            if _fn4 not in ("tool_calls", "tool_use"):
                import os as _o4, time as _t4
                (_outcome_logger_instance or _SOL()).log(_SOR(
                    session_id=_req_session_id,
                    tenant_id=_o4.getenv("AGENTWARDEN_TENANT_ID", "default"),
                    task_type=getattr(ctx, "task_type", "unknown"),
                    task_success=0,
                    tools_exposed=_ex4,
                    tools_used=_us4,
                    failure_reason="blocked" if _bc4 > 0 else None,
                    missing_tools=[b["tool"] for b in _session_blocks],
                    ser=_sr4,
                    block_count=_bc4,
                    stage1_blocks=sum(1 for b in _session_blocks if b.get("stage") == "rules"),
                    stage2_blocks=sum(1 for b in _session_blocks if b.get("stage") == "classifier"),
                    duration_ms=int(_t4.time() * 1000) - _session_start_ms,
                    notes="runtime:" + runtime.value,
                ))
                _session_store.pop(_req_session_id, None)
        except Exception as _se4:
            print(f"PRE_SSE_FAIL {_se4}", flush=True)
        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    # Log session outcome on every governed request turn
    try:
        _fn3 = "stop"
        if "choices" in response:
            _fn3 = response["choices"][0].get("finish_reason", "stop") or "stop"
        elif "done_reason" in response:
            _fn3 = response.get("done_reason", "stop")
        _us3 = list(dict.fromkeys(_session_tools_used))
        _bc3 = len(_session_blocks)
        _ex3 = [t.get("function", {}).get("name", t.get("name", "")) for t in (body.get("tools") or []) if isinstance(t, dict)]
        _sr3 = round(len([t for t in _us3 if t in _ex3]) / max(len(_ex3), 1), 4) if _ex3 else 0.0
        logger.warning("SESSION_LOG fn=%s sid=%s tools=%s ser=%s bc=%s", _fn3, _req_session_id, _us3, _sr3, _bc3)
        if _fn3 not in ("tool_calls", "tool_use"):
            import os as _o3, time as _t3
            (_outcome_logger_instance or _SOL()).log(_SOR(
                session_id=_req_session_id,
                tenant_id=_o3.getenv("AGENTWARDEN_TENANT_ID", "default"),
                task_type=getattr(ctx, "task_type", "unknown"),
                task_success=0,
                tools_exposed=_ex3,
                tools_used=_us3,
                failure_reason="blocked" if _bc3 > 0 else None,
                missing_tools=[b["tool"] for b in _session_blocks],
                ser=_sr3,
                block_count=_bc3,
                stage1_blocks=sum(1 for b in _session_blocks if b.get("stage") == "rules"),
                stage2_blocks=sum(1 for b in _session_blocks if b.get("stage") == "classifier"),
                duration_ms=int(_t3.time() * 1000) - _session_start_ms,
                notes="runtime:" + runtime.value,
            ))
            _session_store.pop(_req_session_id, None)
    except Exception as _se3:
        logger.warning("SESSION_LOG_FAIL %s", _se3)
    return JSONResponse(response)
