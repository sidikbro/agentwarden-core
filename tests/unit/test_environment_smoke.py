"""Environment smoke test — fails loudly if this Python environment cannot
actually run AgentWarden, rather than surfacing as a confusing traceback
deep inside some other test's import chain.

Two kinds of dependency are deliberately treated differently:
  - CORE packaging deps (declared in pyproject.toml's base [project]
    dependencies — fastapi, uvicorn, httpx, yaml, pydantic, click,
    aiosqlite, torch, stable_baselines3): missing means the package was
    never actually installed (`pip install -e .`) in this environment.
    That's a hard, loud failure here — not a skip. A USENIX artifact
    evaluator running this cold needs to see "you forgot to install the
    package" immediately, not a wall of ModuleNotFoundError from some
    unrelated test file.
  - OPTIONAL runtime services (Ollama, a live AgentWarden proxy, GitHub's
    `gh` CLI): those are legitimately absent in many valid environments
    and are skipped elsewhere (see tests/integration/test_integration.py's
    requires_ollama/requires_agentwarden pattern) — this file does not
    touch that distinction.
"""
from __future__ import annotations

import importlib

import pytest

# name as imported -> the pip/extras name a reviewer needs to install
CORE_DEPENDENCIES = {
    "fastapi":            "fastapi",
    "uvicorn":             "uvicorn",
    "httpx":               "httpx",
    "yaml":                "pyyaml",
    "pydantic":            "pydantic",
    "click":               "click",
    "aiosqlite":           "aiosqlite",
    "stable_baselines3":   "stable-baselines3",
    "torch":               "torch",
}


@pytest.mark.parametrize("module_name,pip_name", sorted(CORE_DEPENDENCIES.items()))
def test_core_dependency_importable(module_name, pip_name):
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(
            f"Core dependency '{module_name}' (pip package '{pip_name}') is not "
            f"installed in this environment — {e}. AgentWarden was likely never "
            f"pip-installed here. Fix: run `pip install -e '.[dev]'` from the "
            f"repo root, then re-run the tests.",
            pytrace=False,
        )


def test_agentwarden_package_itself_is_importable():
    try:
        import agentwarden  # noqa: F401
    except ImportError as e:
        pytest.fail(
            f"The 'agentwarden' package itself is not importable — {e}. "
            f"Fix: run `pip install -e '.[dev]'` from the repo root.",
            pytrace=False,
        )


def test_server_app_constructs_and_health_endpoint_responds():
    """The strongest possible smoke test: actually build the FastAPI app
    and hit /health, in-process, no network. If this fails, the server
    cannot start in this environment regardless of what `agentwarden serve`
    would report."""
    try:
        from fastapi.testclient import TestClient

        from agentwarden.server.app import create_app
    except ImportError as e:
        pytest.fail(
            f"Cannot import the server entry point — {e}. "
            f"Fix: run `pip install -e '.[dev]'` from the repo root.",
            pytrace=False,
        )

    app = create_app(runtime="generic", backend="ollama")
    client = TestClient(app)
    resp = client.get("/health")

    assert resp.status_code == 200, (
        f"/health returned {resp.status_code}, expected 200 — the server "
        f"constructs but is not healthy: {resp.text}"
    )
    body = resp.json()
    assert body.get("status") == "ok", f"/health body did not report ok: {body}"


def test_cli_entry_point_is_registered():
    """Confirms `agentwarden` (the console_script from pyproject.toml's
    [project.scripts]) resolves to a real, callable entry point — this is
    what `pip install -e .` is supposed to register on PATH."""
    try:
        from agentwarden.cli import main  # noqa: F401
    except ImportError as e:
        pytest.fail(
            f"CLI entry point 'agentwarden.cli:main' is not importable — {e}. "
            f"Fix: run `pip install -e '.[dev]'` from the repo root.",
            pytrace=False,
        )
