# AgentWarden — Troubleshooting

Every error documented here was encountered during real testing.
If you hit something not listed, open an issue on GitHub.

---

## Startup errors

### `ModuleNotFoundError: No module named 'rich'`
```
from agentwarden.cli import cli
ModuleNotFoundError: No module named 'rich'
```
**Cause:** `rich` is missing from the installed package.
**Fix:** Rebuild the Docker image after updating `pyproject.toml`:
```bash
docker compose build --no-cache agentwarden
docker compose up -d agentwarden
```

---

### `ImportError: cannot import name 'cli' from 'agentwarden.cli'`
```
ImportError: cannot import name 'cli' from 'agentwarden.cli'
```
**Cause:** The CLI entrypoint in `pyproject.toml` points to `cli` but the Click group is named `main`.
**Fix:** Update `pyproject.toml`:
```toml
[project.scripts]
agentwarden = "agentwarden.cli:main"
```
Or bypass the CLI entirely in the Dockerfile:
```dockerfile
CMD ["python", "-c", "import os, uvicorn; from agentwarden.server.app import create_app; ..."]
```

---

### `Error loading ASGI app. Attribute "app" not found`
```
ERROR: Error loading ASGI app. Attribute "app" not found in module "agentwarden.server.app"
```
**Cause:** The server uses a factory function `create_app()`, not a module-level `app` variable.
**Fix:** The Dockerfile CMD must call `create_app()`:
```dockerfile
CMD ["python", "-c", "\
import os, uvicorn; \
from agentwarden.server.app import create_app; \
backend = os.getenv('AGENTWARDEN_BACKEND','ollama'); \
backend_url = os.getenv('OLLAMA_BASE_URL') if backend == 'ollama' else None; \
app = create_app(\
  runtime=os.getenv('AGENTWARDEN_RUNTIME','generic'),\
  backend=backend,\
  shadow_mode=os.getenv('AGENTWARDEN_SHADOW_MODE','false').lower()=='true',\
  backend_url=backend_url\
); \
uvicorn.run(app, host='0.0.0.0', port=8000) \
"]
```

---

### `yaml: unmarshal errors: mapping key "volumes" already defined`
**Cause:** Appending a second `volumes:` section to `docker-compose.yml`.
**Fix:** Add new volumes under the existing `volumes:` section, not as a new one.

---

## Connection errors

### `All connection attempts failed`
```json
{"error": "All connection attempts failed"}
```
**Cause:** AgentWarden container cannot reach Ollama.

**Check 1 — Ollama is bound to localhost only:**
```bash
ss -tlnp | grep 11434
# If shows 127.0.0.1:11434 → Ollama is not reachable from Docker
```
**Fix:** Make Ollama listen on all interfaces:
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d/
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

**Check 2 — Wrong host IP:**
```bash
# Find the correct gateway IP for your Docker network
docker network inspect <network_name> | python3 -c \
  "import json,sys; d=json.load(sys.stdin); \
   print(d[0]['IPAM']['Config'][0]['Gateway'])"

# Test from inside the container
docker exec agentwarden_proxy curl -s http://<gateway_ip>:11434/api/tags
```

---

### `Too little data for declared Content-Length`
**Cause:** Forwarding the original `content-length` and `host` headers to Ollama or DeepSeek. These must be stripped before forwarding.
**Fix:** The provider's `_clean_headers()` function must include these in `_STRIP_HEADERS`:
```python
_STRIP_HEADERS = {
    "host", "content-length", "transfer-encoding",
    "connection", "keep-alive", "authorization", "content-type",
}
```

---

### `401 Unauthorized` (DeepSeek)
```json
{"error": "Backend error", "detail": "Client error '401 Unauthorized'..."}
```
**Cause:** The incoming `authorization` header (lowercase) from the agent passes through the strip filter, then both `authorization` (agent's fake key) and `Authorization` (real key) are sent. HTTP clients use the first match.
**Fix:** Add `"authorization"` to `_STRIP_HEADERS` in `openai_provider.py`.

---

### `404 Not Found` on `/api/tags`
```json
{"detail": "Not Found"}
```
**Cause:** AgentWarden doesn't proxy `/api/tags` — it only handles `/api/chat` and `/v1/chat/completions`.
**This is expected.** The proxy only intercepts LLM inference calls.

---

## Governance not working

### Tool calls pass through without being blocked

**Check 1 — Is the proxy actually being used?**
```bash
docker logs agentwarden_proxy | grep "POST /api/chat\|POST /v1"
# Should show incoming requests
```

**Check 2 — Are rules loaded correctly?**
```bash
docker exec agentwarden_proxy python3 -c "
from agentwarden.policies.rules import RuleBasedPolicy
p = RuleBasedPolicy()
print('always_block count:', len(p.always_block))
print('exec in always_block:', 'exec' in p.always_block)
"
```

**Check 3 — Is the runtime set correctly?**
```bash
docker exec agentwarden_proxy env | grep AGENTWARDEN_RUNTIME
curl http://localhost:8000/health | python3 -m json.tool | grep runtime
```

**Check 4 — DeepAgents LocalShellBackend bypass:**
DeepAgents executes shell commands via `subprocess` locally, bypassing the LLM proxy entirely.
Use `FilesystemBackend()` instead:
```python
from deepagents.backends.filesystem import FilesystemBackend
agent = create_deep_agent(..., backend=FilesystemBackend())
```
See [architecture.md](architecture.md#threat-model) for the full explanation.

---

### `[Pipeline] Policy 'rules' error: expected string or bytes-like object, got 'list'`
**Cause:** DeepAgents sends `system` message content as a list of content blocks, not a string. The injection pattern check tries to run regex on a list.
**Fix:** The `rules.py` policy must handle list-format content:
```python
raw_ctx = getattr(request.context, "system_prompt", "") or ""
if isinstance(raw_ctx, list):
    context_str = " ".join(
        str(m.get("content", m) if isinstance(m, dict) else m)
        for m in raw_ctx
    )
else:
    context_str = str(raw_ctx)
```

---

### Stage 3 semantic filter blocks XML tool calls (false positive)
**Symptom:** Llama Guard 3 blocks responses with `<tool_call>` XML format (category S1).
**Cause:** Llama Guard misclassifies XML tags as dangerous content.
**Fix:** Skip Stage 3 for responses that are pure tool calls:
```python
is_pure_tool_call = response_has_tool_calls and (
    not response_text or
    response_text.strip() == "" or
    "<tool_call>" in response_text
)
if semantic_filter and not shadow_mode and not is_pure_tool_call:
    ...
```

---

### Stage 2 classifier blocks all `write` calls
**Symptom:** Even benign writes like `write("poem.txt", "...")` are blocked at 0.95 confidence.
**Cause:** Known training artifact in `agentwarden-router` model — overfit on HTTP server write patterns during fine-tuning.
**Fix:** Add `write`, `edit`, `write_file` to `classifier_skip` in `config/rules.yaml`.
This is documented in the paper (§5, False Positive Analysis).

---

### `runtime: generic` in health even though `AGENTWARDEN_RUNTIME=openclaw` is set
**Cause:** `create_app()` uses default parameters. The Dockerfile CMD must explicitly read the env var:
```dockerfile
CMD ["python", "-c", "... app = create_app(runtime=os.getenv('AGENTWARDEN_RUNTIME','generic'), ...)"]
```

---

## DeepSeek-specific issues

### `404 Not Found` for url `http://172.18.0.1:11434/chat/completions`
**Cause:** When `AGENTWARDEN_BACKEND=deepseek` but `OLLAMA_BASE_URL` is being passed as `backend_url` to `create_app()`, it sets `DEEPSEEK_BASE_URL=http://172.18.0.1:11434` — overwriting the correct DeepSeek URL.
**Fix:** Only pass `backend_url` for the Ollama backend:
```python
backend = os.getenv('AGENTWARDEN_BACKEND', 'ollama')
backend_url = os.getenv('OLLAMA_BASE_URL') if backend == 'ollama' else None
app = create_app(backend=backend, backend_url=backend_url, ...)
```

---

### DeepSeek eval shows `tools=0` for all tasks
**Cause:** DeepSeek returns OpenAI format (`choices[0].message`) but the pipeline expects Ollama format (`message`). Tool calls are not extracted.
**Fix:** Normalize OpenAI → Ollama format before pipeline processing:
```python
if "choices" in llm_response and "message" not in llm_response:
    llm_response = _normalize_openai_to_ollama(llm_response)
```

---

## Semantic filter (Stage 3) errors

### `SemanticFilter error: timed out — defaulting to ALLOW`
**Cause:** Default timeout is 3000ms but Llama Guard 3 cold start takes ~10,000ms.
**Fix:** Increase timeout in `semantic_filter.py`:
```python
timeout_ms: int = 30000  # 30s for cold start
```

### `SemanticFilter error: There is no current event loop in thread`
**Cause:** The semantic filter's sync `httpx.post()` call was wrapped in async code incorrectly.
**Fix:** Use `asyncio.to_thread()` to run the blocking call in a thread pool:
```python
decision = await asyncio.to_thread(semantic_filter.evaluate, synthetic_req)
```

---

## GPU and Docker

### GPU not detected in Ollama container
```bash
# Verify nvidia-container-toolkit is installed
nvidia-container-cli info

# Test GPU in Docker
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

### OOM killer during NemoClaw image push
**Cause:** NemoClaw sandbox image is ~2.4GB compressed. Decompression requires ~8GB RAM.
**Fix:** Add 8GB swap or use a machine with more RAM.

---

## PyCharm debugging

See [debugging.md](debugging.md) for the full guide on setting up PyCharm to debug the running proxy with breakpoints.
