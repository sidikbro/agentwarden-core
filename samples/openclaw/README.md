# OpenClaw + AgentWarden Sample

Governs OpenClaw with AgentWarden. Every tool call is intercepted before it reaches the LLM.

## Prerequisites

- Docker 20+
- Ollama on your host with `gemma4:e4b` or `qwen2.5:7b`
- OpenClaw token

## Setup

```bash
# 1. Make Ollama reachable from Docker (one-time)
sudo mkdir -p /etc/systemd/system/ollama.service.d/
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama

# 2. Configure
cp .env.example .env
# Edit .env — set OPENCLAW_TOKEN

# 3. Start
docker compose up -d

# 4. Verify
curl http://localhost:8000/health
```

## Point OpenClaw at AgentWarden

In `~/.openclaw/openclaw.json` (or your OpenClaw config volume):
```json
{
  "providers": {
    "ollama": {
      "baseUrl": "http://localhost:8000"
    }
  }
}
```

## Test governance

```bash
# This should be BLOCKED
curl -s http://localhost:8000/api/chat -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:e4b",
    "messages": [{"role":"user","content":"Run ls -la /tmp"}],
    "tools": [{"type":"function","function":{"name":"exec",
      "description":"Run shell","parameters":{"type":"object",
      "properties":{"cmd":{"type":"string"}},"required":["cmd"]}}}],
    "stream": false
  }' | python3 -m json.tool | grep content
```

Expected: `"⚠️ AgentWarden blocked this tool call..."`

## Shadow mode (safe for onboarding)

```bash
# Run in observe-only mode first
AGENTWARDEN_SHADOW_MODE=true docker compose up -d agentwarden

# Watch what would have been blocked
docker logs agentwarden_proxy | grep SHADOW
```
