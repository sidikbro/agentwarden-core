# AgentWarden — PyCharm Debugging Guide

Two approaches: debug the running Docker container remotely, or run the server locally with PyCharm's debugger.

**Recommendation: Option B (local run) is faster for development.**

---

## Option A — Remote debug into Docker container

### Step 1 — Add debugpy to the container

Add to `Dockerfile`:
```dockerfile
RUN pip install debugpy
```

Change the CMD to wait for debugger attach:
```dockerfile
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client",
     "-c", "import os, uvicorn; from agentwarden.server.app import create_app; ..."]
```

### Step 2 — Expose debug port in docker-compose

```yaml
services:
  agentwarden:
    ports:
      - "8000:8000"
      - "5678:5678"   # debugpy port
```

### Step 3 — Configure PyCharm remote debugger

1. **Run → Edit Configurations → + → Python Debug Server**
2. Set:
   - **IDE host name:** `localhost`
   - **Port:** `5678`
3. Click **Debug** — PyCharm waits for connection
4. Start the container: `docker compose up agentwarden`
5. Container connects to PyCharm automatically

### Step 4 — Set breakpoints

Good places to set breakpoints:
- `agentwarden/core/pipeline.py` line with `d = policy.evaluate(request)` — see every governance decision
- `agentwarden/policies/rules.py` inside `evaluate()` — trace Stage 1 decisions
- `agentwarden/server/app.py` inside `_proxy_request()` — see full request/response flow

---

## Option B — Run locally with PyCharm (recommended)

No Docker needed. Run the server directly in PyCharm with full debugging support.

### Step 1 — Set up the interpreter

1. Open `~/PycharmProjects/agentwarden-core` in PyCharm
2. **File → Settings → Project → Python Interpreter**
3. Select your conda environment: `agentwarden` (or whichever has the deps)
4. Verify: `which python` should show the conda env path

### Step 2 — Create a Run Configuration

1. **Run → Edit Configurations → + → Python**
2. Configure:
   - **Name:** `AgentWarden Server`
   - **Script path:** leave empty
   - **Module:** leave empty
   - **Parameters:** leave empty
   - **Script:** select `agentwarden/server/app.py`

Actually, easier — create a `run_server.py` in the project root:

```python
# run_server.py — PyCharm debug entrypoint
import os
import uvicorn
from agentwarden.server.app import create_app

# Set env vars for local development
os.environ.setdefault("AGENTWARDEN_RUNTIME", "openclaw")
os.environ.setdefault("AGENTWARDEN_BACKEND", "ollama")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("AGENTWARDEN_LOG_LEVEL", "DEBUG")
os.environ.setdefault("AGENTWARDEN_CLASSIFIER_MODEL", "agentwarden-router")
os.environ.setdefault("AGENTWARDEN_SEMANTIC_FILTER", "false")

app = create_app(
    runtime=os.getenv("AGENTWARDEN_RUNTIME", "generic"),
    backend=os.getenv("AGENTWARDEN_BACKEND", "ollama"),
    shadow_mode=os.getenv("AGENTWARDEN_SHADOW_MODE", "false").lower() == "true",
    backend_url=os.getenv("OLLAMA_BASE_URL") if os.getenv("AGENTWARDEN_BACKEND") == "ollama" else None,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
```

3. Create Run Configuration:
   - **Name:** `AgentWarden Dev Server`
   - **Script path:** `run_server.py`
   - **Working directory:** `~/PycharmProjects/agentwarden-core`

### Step 3 — Set environment variables in PyCharm

In the Run Configuration → **Environment variables**:
```
AGENTWARDEN_RUNTIME=openclaw
AGENTWARDEN_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
AGENTWARDEN_CLASSIFIER_MODEL=agentwarden-router
AGENTWARDEN_LOG_LEVEL=DEBUG
```

### Step 4 — Set breakpoints and run

**Best breakpoint locations:**

```
agentwarden/core/pipeline.py
  Line: d = policy.evaluate(request)
  → Watch: request.tool_call.name, request.tool_call.arguments

agentwarden/policies/rules.py
  Line: if name in self.always_block:
  → Watch: name, self.always_block

agentwarden/policies/classifier.py
  Line: result = self._call_classifier(...)
  → Watch: request.tool_call.name, result

agentwarden/server/app.py
  Line: llm_response = await pipeline.provider.forward(...)
  → Watch: body (full request), llm_response (full LLM output)

agentwarden/server/app.py
  Line: result = await pipeline.process(llm_response, ctx)
  → Watch: result.decisions, result.mutated_response
```

Click the green **Debug** button (not Run). PyCharm starts the server in debug mode.

### Step 5 — Send test requests

While the server is running in PyCharm, send requests from a terminal:

```bash
# Trigger a breakpoint by sending a tool call
curl -s http://localhost:8000/api/chat -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:e4b",
    "messages": [{"role":"user","content":"Run ls -la /tmp"}],
    "tools": [{"type":"function","function":{"name":"exec",
      "parameters":{"type":"object","properties":{"cmd":{"type":"string"}},
      "required":["cmd"]},"description":"Run shell"}}],
    "stream": false
  }'
```

PyCharm pauses at the breakpoint. You can:
- Inspect `request.tool_call.name` → should be `"exec"`
- Step through the `always_block` check
- Evaluate expressions in the **Debug Console**

---

## Useful PyCharm debug console expressions

While paused at a breakpoint, type these in the **Evaluate Expression** window:

```python
# See all loaded rules
from agentwarden.policies.rules import RuleBasedPolicy
p = RuleBasedPolicy()
sorted(p.always_block)

# Check if a specific tool would be blocked
p.evaluate(request).decision

# See classifier skip list
sorted(p.classifier_skip)

# Inspect the full pipeline
[pol.name for pol in pipeline.policies]

# Check what the LLM actually returned
llm_response.get("message", {}).get("tool_calls", [])
```

---

## Tips

**Hot reload during development:**
Run with `uvicorn --reload` to pick up code changes without restarting:
```python
uvicorn.run("agentwarden.server.app:create_app", 
            factory=True, host="0.0.0.0", port=8000, reload=True)
```
Note: breakpoints don't work well with `--reload`. Disable it when debugging.

**Watching the audit log:**
```bash
# In a separate terminal — watch decisions in real time
watch -n1 "sqlite3 ~/.agentwarden/audit/agentwarden_audit.db \
  'SELECT tool_name, decision, stage, substr(timestamp,1,19) as ts \
   FROM audit_log ORDER BY timestamp DESC LIMIT 10;'"
```

**PyCharm Source Roots:**
If imports show red underlines:
1. Right-click `agentwarden-core/` folder
2. **Mark Directory As → Sources Root**
3. Right-click `config/` folder → **Mark Directory As → Resources Root**
