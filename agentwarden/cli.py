"""
AgentWarden CLI
===============
The main command-line interface.

Usage:
    agentwarden serve   --runtime hermes --backend ollama --policy customer-support-v1
    agentwarden pull    policy:customer-support-v1
    agentwarden list    policies
    agentwarden status
    agentwarden shadow  --runtime deepagents --backend openai --days 7
"""
from __future__ import annotations

import os
import sys
import logging

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from agentwarden.__version__ import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="agentwarden")
@click.option("--debug", is_flag=True, help="Enable debug logging.")
def main(debug: bool):
    """
    AgentWarden — Universal Capability Governance for AI Agents.

    The Envoy proxy for AI agent frameworks. Sits between your agent
    and your LLM, enforcing least-privilege tool governance.

    Quickstart:
        agentwarden pull policy:customer-support-v1
        agentwarden serve --runtime hermes --backend ollama

    Then set your agent's LLM endpoint to http://localhost:8000.
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# ── serve ──────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--runtime",   default="generic",          show_default=True,
              type=click.Choice(["hermes", "deepagents", "openclaw", "langgraph",
                                 "crewai", "autogen", "generic"]),
              help="Agent framework to govern.")
@click.option("--backend",   default="ollama",           show_default=True,
              type=click.Choice(["ollama", "openai", "deepseek", "vllm", "anthropic"]),
              help="LLM backend to proxy to.")
@click.option("--policy",    default=None,
              help="Governance policy to load (e.g. customer-support-v1).")
@click.option("--port",      default=8000,               show_default=True,
              help="Port to listen on.")
@click.option("--host",      default="0.0.0.0",          show_default=True,
              help="Host to bind to.")
@click.option("--shadow",    is_flag=True,
              help="Shadow mode: log decisions but never block.")
@click.option("--rules-file", default=None,
              help="Path to custom YAML rules file.")
@click.option("--backend-url", default=None,
              help="Override backend URL (e.g. http://localhost:11434).")
def serve(runtime, backend, policy, port, host, shadow, rules_file, backend_url):
    """
    Start the AgentWarden governance proxy.

    Examples:
        # Govern Hermes Agent with Ollama backend
        agentwarden serve --runtime hermes --backend ollama

        # Govern DeepAgents with customer support policy
        agentwarden serve --runtime deepagents --backend openai \\
                         --policy customer-support-v1

        # Shadow mode — observe without blocking
        agentwarden serve --runtime hermes --backend ollama --shadow
    """
    import uvicorn
    from agentwarden.server.app import create_app
    from agentwarden.core.models import Runtime

    if shadow:
        console.print("[yellow]⚠  Shadow mode enabled — decisions logged but NOT enforced.[/yellow]")

    if policy:
        console.print(f"[green]✓[/green] Loading policy: [bold]{policy}[/bold]")

    console.print(
        f"\n[bold cyan]AgentWarden[/bold cyan] v{__version__} starting...\n"
        f"  Runtime : [bold]{runtime}[/bold]\n"
        f"  Backend : [bold]{backend}[/bold]\n"
        f"  Policy  : [bold]{policy or 'default (rules only)'}[/bold]\n"
        f"  Shadow  : [bold]{shadow}[/bold]\n"
        f"  Listen  : [bold]http://{host}:{port}[/bold]\n"
    )
    console.print("[dim]Point your agent's LLM endpoint at the address above.[/dim]\n")

    app = create_app(
        runtime=runtime,
        backend=backend,
        policy_name=policy,
        shadow_mode=shadow,
        rules_file=rules_file,
        backend_url=backend_url,
    )

    uvicorn.run(app, host=host, port=port, log_level="warning")


# ── pull ───────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("ref")   # e.g. policy:customer-support-v1
def pull(ref: str):
    """
    Pull a policy or model weights from the AgentWarden Hub.

    Examples:
        agentwarden pull policy:customer-support-v1
        agentwarden pull policy:devops-safe-v1
        agentwarden pull router:qwen-1.5B-safety-v1
    """
    from agentwarden.hub.manifest import get_builtin_policy, list_builtin_policies

    if ":" not in ref:
        console.print(f"[red]Invalid ref format. Use policy:<name> or router:<name>[/red]")
        sys.exit(1)

    kind, name = ref.split(":", 1)

    if kind == "policy":
        try:
            manifest = get_builtin_policy(name)
            _install_policy(manifest)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            console.print(f"\nAvailable policies: {list_builtin_policies()}")
            sys.exit(1)
    else:
        console.print(f"[red]Unknown ref type: {kind}. Supported: policy, router[/red]")
        sys.exit(1)


def _install_policy(manifest) -> None:
    import json
    policy_dir = _policy_dir() / manifest.name
    policy_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = policy_dir / "manifest.yaml"
    manifest.save(manifest_path)

    console.print(f"[green]✓[/green] Pulled [bold]{manifest.policy_id}[/bold]")
    console.print(f"  Saved to: {manifest_path}")
    if manifest.is_enterprise:
        console.print(
            f"  [yellow]⚠  RL weights require AMARE Enterprise.[/yellow]\n"
            f"  [dim]Contact sidik@post.bgu.ac.il for enterprise access.[/dim]"
        )
    else:
        console.print(f"  [green]✓ Rule-based policy ready (no weights required)[/green]")


# ── list ───────────────────────────────────────────────────────────────────────

@main.command(name="list")
@click.argument("what", type=click.Choice(["policies", "runtimes", "backends"]))
def list_cmd(what: str):
    """List available policies, runtimes, or backends."""
    if what == "policies":
        from agentwarden.hub.manifest import BUILTIN_POLICIES
        table = Table(title="Available Policies (Free Tier)", show_header=True)
        table.add_column("Name",         style="bold cyan")
        table.add_column("Description",  style="white")
        table.add_column("Tags",         style="dim")

        for name, data in BUILTIN_POLICIES.items():
            table.add_row(
                name,
                data.get("description", "")[:60] + "...",
                ", ".join(data.get("tags", [])),
            )
        console.print(table)
        console.print(
            "\n[dim]Pull a policy with: agentwarden pull policy:<name>[/dim]"
        )

    elif what == "runtimes":
        table = Table(title="Supported Agent Runtimes", show_header=True)
        table.add_column("Runtime",     style="bold cyan")
        table.add_column("Framework",   style="white")
        table.add_column("Stars",       style="dim")
        table.add_column("Status",      style="green")
        rows = [
            ("hermes",     "NousResearch Hermes Agent", "61k",  "stable"),
            ("deepagents", "LangChain DeepAgents",      "9.3k", "stable"),
            ("openclaw",   "OpenClaw",                  "OSS",  "stable"),
            ("langgraph",  "LangGraph",                 "OSS",  "beta"),
            ("crewai",     "CrewAI",                    "OSS",  "planned"),
            ("autogen",    "Microsoft AutoGen",         "OSS",  "planned"),
            ("generic",    "Any OpenAI-compatible",     "--",   "stable"),
        ]
        for r in rows:
            table.add_row(*r)
        console.print(table)

    elif what == "backends":
        table = Table(title="Supported LLM Backends", show_header=True)
        table.add_column("Backend",   style="bold cyan")
        table.add_column("Type",      style="white")
        table.add_column("Status",    style="green")
        rows = [
            ("ollama",    "Local (Ollama server)",     "stable"),
            ("openai",    "OpenAI API",                "stable"),
            ("deepseek",  "DeepSeek API",              "stable"),
            ("vllm",      "vLLM inference server",     "stable"),
            ("anthropic", "Anthropic API",             "beta"),
        ]
        for r in rows:
            table.add_row(*r)
        console.print(table)


# ── status ─────────────────────────────────────────────────────────────────────

@main.command()
def status():
    """Show current AgentWarden installation status."""
    from agentwarden.hub.manifest import list_builtin_policies

    console.print(f"\n[bold cyan]AgentWarden[/bold cyan] v{__version__}")
    console.print(f"  Install dir    : {_install_dir()}")
    console.print(f"  Policies dir   : {_policy_dir()}")

    installed = _list_installed_policies()
    if installed:
        console.print(f"  Installed      : {', '.join(installed)}")
    else:
        console.print(f"  Installed      : [dim]none — run 'agentwarden pull policy:<name>'[/dim]")


# ── shadow ─────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--runtime",  required=True,
              type=click.Choice(["hermes","deepagents","openclaw","generic"]))
@click.option("--backend",  required=True,
              type=click.Choice(["ollama","openai","deepseek","vllm"]))
@click.option("--port",     default=8000, show_default=True)
@click.option("--days",     default=7,    show_default=True,
              help="Suggested Shadow Mode observation period.")
def shadow(runtime, backend, port, days):
    """
    Start in Shadow Mode — observe without blocking.

    Use this for the enterprise onboarding workflow:
    1. Run shadow mode for the suggested observation period
    2. Review flagged calls in the audit log
    3. Approve false positives to build your training dataset
    4. Switch to enforcement mode when satisfied

    Example:
        agentwarden shadow --runtime deepagents --backend openai --days 7
    """
    console.print(
        f"\n[yellow bold]Shadow Mode[/yellow bold] — observe {days} days before enforcing\n"
        f"Audit log: ~/.agentwarden/audit/shadow.db\n"
        f"After {days} days, run: agentwarden serve --runtime {runtime} --backend {backend}\n"
    )
    # Delegate to serve with shadow flag
    from click.testing import CliRunner
    runner = CliRunner()
    runner.invoke(serve, [
        "--runtime", runtime, "--backend", backend,
        "--port", str(port), "--shadow",
    ])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _install_dir() -> "Path":
    from pathlib import Path
    d = Path.home() / ".agentwarden"
    d.mkdir(exist_ok=True)
    return d

def _policy_dir() -> "Path":
    d = _install_dir() / "policies"
    d.mkdir(exist_ok=True)
    return d

def _list_installed_policies() -> list[str]:
    from pathlib import Path
    policy_dir = _policy_dir()
    return [
        p.name for p in policy_dir.iterdir()
        if p.is_dir() and (p / "manifest.yaml").exists()
    ]


if __name__ == "__main__":
    main()
