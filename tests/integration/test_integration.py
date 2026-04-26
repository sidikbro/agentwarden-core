"""
Integration Tests — OpenClaw + AgentWarden in Docker
=====================================================
These tests require a running Docker environment with:
  - OpenClaw gateway (port 18789)
  - Ollama with at least one model (port 11434)
  - AgentWarden proxy (port 8000)

Quick start on your laptop:
    cd agentwarden_platform
    docker compose up -d
    pytest tests/integration/ -v

Or skip Docker and run against a live AgentWarden server:
    AGENTWARDEN_URL=http://localhost:8000 pytest tests/integration/ -v

Tests are skipped automatically if the server is not reachable.
"""
import os
import pytest
import httpx

# ── Config ────────────────────────────────────────────────────────────────────

AGENTWARDEN_URL = os.getenv("AGENTWARDEN_URL", "http://localhost:8000")
OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://localhost:11434")
OPENCLAW_URL   = os.getenv("OPENCLAW_URL",   "http://localhost:18789")
TEST_MODEL     = os.getenv("TEST_MODEL",     "qwen2.5:1.5b")

TIMEOUT = 30.0


# ── Fixtures / skip helpers ────────────────────────────────────────────────────

def _is_up(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _ollama_up() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


requires_agentwarden = pytest.mark.skipif(
    not _is_up(AGENTWARDEN_URL),
    reason=f"AgentWarden not running at {AGENTWARDEN_URL} — start with: agentwarden serve",
)

requires_ollama = pytest.mark.skipif(
    not _ollama_up(),
    reason=f"Ollama not running at {OLLAMA_URL} — start with: ollama serve",
)

requires_openclaw = pytest.mark.skipif(
    not _is_up(OPENCLAW_URL + "/api/v1"),
    reason=f"OpenClaw not running at {OPENCLAW_URL} — start with: docker compose up openclaw",
)


# ── Helper: direct proxy calls ────────────────────────────────────────────────

def proxy_chat(messages: list, tools: list | None = None) -> dict:
    """Send a chat request through the AgentWarden proxy."""
    body = {
        "model": TEST_MODEL,
        "messages": messages,
        "stream": False,
    }
    if tools:
        body["tools"] = tools

    resp = httpx.post(
        f"{AGENTWARDEN_URL}/api/chat",
        json=body,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ── Health check ──────────────────────────────────────────────────────────────

@requires_agentwarden
class TestHealth:

    def test_health_endpoint(self):
        r = httpx.get(f"{AGENTWARDEN_URL}/health", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_registry_endpoint(self):
        r = httpx.get(f"{AGENTWARDEN_URL}/registry", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert "parsers" in data
        assert "policies" in data
        assert len(data["policies"]) >= 1   # at least rules

    def test_openai_compat_endpoint_exists(self):
        """The /v1/chat/completions endpoint should exist (even if model errors)."""
        r = httpx.post(
            f"{AGENTWARDEN_URL}/v1/chat/completions",
            json={"model": TEST_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            timeout=TIMEOUT,
        )
        # 200 or 502 (backend error) — but NOT 404
        assert r.status_code != 404


# ── Governance enforcement ────────────────────────────────────────────────────

@requires_agentwarden
class TestGovernanceEnforcement:
    """
    These tests inject synthetic LLM responses directly into the proxy
    to verify governance decisions without needing a real LLM.
    They use the /test/inject endpoint (debug mode only).
    """

    @pytest.fixture
    def exec_response(self):
        return {
            "model": TEST_MODEL,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_001", "type": "function",
                     "function": {"name": "exec", "arguments": '{"cmd": "id"}'}}
                ]
            }
        }

    @pytest.fixture
    def safe_response(self):
        return {
            "model": TEST_MODEL,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_002", "type": "function",
                     "function": {"name": "read", "arguments": '{"path": "README.md"}'}}
                ]
            }
        }

    def test_exec_blocked_via_api(self, exec_response):
        """POST a synthetic exec response — proxy should strip the tool call."""
        r = httpx.post(
            f"{AGENTWARDEN_URL}/test/govern",
            json=exec_response,
            timeout=10.0,
        )
        if r.status_code == 404:
            pytest.skip("Test endpoint not available (enable with --debug flag)")
        result = r.json()
        assert result["any_blocked"] is True
        assert result["block_count"] == 1

    def test_read_allowed_via_api(self, safe_response):
        r = httpx.post(
            f"{AGENTWARDEN_URL}/test/govern",
            json=safe_response,
            timeout=10.0,
        )
        if r.status_code == 404:
            pytest.skip("Test endpoint not available")
        result = r.json()
        assert result["any_blocked"] is False


# ── Ollama live inference tests ───────────────────────────────────────────────

@requires_agentwarden
@requires_ollama
class TestOllamaBackend:
    """
    Real inference tests through AgentWarden → Ollama.
    Require Ollama running with at least qwen2.5:1.5b pulled.
    """

    def test_safe_query_passes_through(self):
        """A simple summarisation query should complete without blocking."""
        result = proxy_chat([
            {"role": "user", "content": "Summarise the principle of least privilege in one sentence."}
        ])
        # Should have a response
        assert "message" in result
        msg = result["message"]
        assert msg.get("content") or msg.get("tool_calls") is not None

    def test_no_tool_call_response_unmodified(self):
        """Text-only responses should pass through completely unchanged."""
        result = proxy_chat([
            {"role": "user", "content": "What is 2 + 2? Reply with just the number."}
        ])
        assert "message" in result
        # No tool_calls in a math question
        assert not result["message"].get("tool_calls")


# ── OpenClaw Docker integration ───────────────────────────────────────────────

@requires_agentwarden
@requires_openclaw
class TestOpenClawIntegration:
    """
    Full stack integration: OpenClaw → AgentWarden proxy → Ollama.
    OpenClaw must be started with OPENAI_BASE_URL=http://agentwarden:8000
    (see docker-compose.yml).
    """

    def test_openclaw_health(self):
        r = httpx.get(f"{OPENCLAW_URL}/api/v1/health", timeout=5.0)
        assert r.status_code == 200

    def test_governance_visible_in_audit_log(self):
        """After a session, the audit log should have entries."""
        r = httpx.get(f"{AGENTWARDEN_URL}/audit/recent?limit=5", timeout=5.0)
        if r.status_code == 404:
            pytest.skip("Audit endpoint not exposed")
        assert r.status_code == 200


# ── NemoClaw integration tests ────────────────────────────────────────────────

@pytest.mark.skip(reason="NemoClaw integration — Phase 3, not yet implemented")
class TestNemoClawIntegration:
    """
    AgentWarden + NemoClaw (NVIDIA) layered governance.

    Architecture:
        Agent → AgentWarden proxy (capability governance)
                → NemoClaw OpenShell (container sandbox)
                → LLM backend

    AgentWarden = adaptive immune system (learns per task type)
    NemoClaw   = static firewall (network/filesystem containment)
    Both layers are complementary and necessary.

    TODO Phase 3:
        - NemoClaw adapter in agentwarden/providers/nemoclaw.py
        - YAML policy bridge: AgentWarden decisions → NemoClaw rules
        - Joint audit log aggregation
        - CI pipeline: docker compose with nemoclaw + agentwarden + openclaw
    """

    def test_nemoclaw_provider_registered(self):
        from agentwarden.core.registry import get_registry
        reg = get_registry()
        assert "nemoclaw" in reg._providers

    def test_agentwarden_decision_forwarded_to_nemoclaw(self):
        """AgentWarden BLOCK should also trigger NemoClaw policy update."""
        pass

    def test_combined_governance_defense_in_depth(self):
        """
        AgentWarden blocks at tool-call level.
        NemoClaw blocks at network/filesystem level.
        Together: zero dangerous calls reach execution.
        """
        pass
