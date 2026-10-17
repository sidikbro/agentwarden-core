"""
AgentWarden Configuration System
=================================
YAML-driven configuration for all pipeline stages.
Every stage can be independently enabled/disabled and
its model can be swapped without code changes.

Config file locations (in priority order):
  1. Path from AGENTWARDEN_CONFIG env var
  2. ./agentwarden.yaml
  3. ~/.agentwarden/config.yaml
  4. Built-in defaults

Example agentwarden.yaml:

    runtime: hermes
    backend: ollama
    shadow_mode: false
    policy: customer-support-v1

    stages:
      rules:
        enabled: true
        # No model needed — deterministic

      classifier:
        enabled: true
        model: qwen2.5:1.5b        # swap to gemma4:e4b or any Ollama model
        backend: ollama             # ollama | gguf | openai
        model_path: null            # path to GGUF file (overrides model)
        threshold: 0.85
        timeout_ms: 2000
        skip_tools:
          - read
          - memory_search
          - web_search
          - read_todos

      approval:
        enabled: true
        timeout_ms: 0                # 0 = no synchronous approver exists yet
        default_on_timeout: block    # only supported value today

      semantic_filter:
        enabled: true
        model: llama-guard3         # or meta-llama/Llama-Guard-3-8B via HF
        backend: ollama             # ollama | openai | nemo
        threshold: 0.7
        timeout_ms: 3000
        filter_input: true          # filter user messages
        filter_output: true         # filter LLM response text

      rl_policy:
        enabled: false              # Enterprise only
        model_path: null            # path to best_model.zip

    providers:
      ollama:
        base_url: http://localhost:11434
        keep_alive: -1
      openai:
        base_url: https://api.openai.com/v1
        api_key: null               # reads OPENAI_API_KEY env var
      deepseek:
        base_url: https://api.deepseek.com/v1
        api_key: null               # reads DEEPSEEK_API_KEY env var
      vllm:
        base_url: http://localhost:8080/v1

    audit:
      enabled: true
      db_path: ~/.agentwarden/audit/agentwarden_audit.db
      log_allowed: true
      log_blocked: true

    server:
      host: 0.0.0.0
      port: 8000
      workers: 1
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("agentwarden.config")

# ── Stage configs ─────────────────────────────────────────────────────────────

@dataclass
class RulesStageConfig:
    enabled: bool = True
    rules_file: str | None = None        # optional custom YAML rules
    extra_always_block: list[str] = field(default_factory=list)

@dataclass
class ClassifierStageConfig:
    enabled: bool = True
    model: str = "qwen2.5:1.5b"         # Ollama model name
    backend: str = "ollama"              # ollama | gguf | openai
    model_path: str | None = None        # GGUF file path (overrides model)
    threshold: float = 0.85
    timeout_ms: int = 2000
    skip_tools: list[str] = field(default_factory=lambda: [
        "read", "read_file", "memory_search", "memory_get",
        "web_search", "read_todos", "ls", "glob", "grep",
    ])

@dataclass
class SemanticFilterConfig:
    enabled: bool = False                # opt-in — adds latency
    model: str = "llama-guard3"          # Ollama model name
    backend: str = "ollama"              # ollama | openai | nemo
    threshold: float = 0.7
    timeout_ms: int = 3000
    filter_input: bool = True            # filter user messages before LLM
    filter_output: bool = True           # filter LLM response text

@dataclass
class ApprovalStageConfig:
    """D3 (approve) — see agentwarden/policies/approval_gate.py.

    There is currently no synchronous approval channel (no queue, no
    approver, no UI) anywhere in this codebase — the proxy is a single
    synchronous request/response cycle. timeout_ms=0 / default_on_timeout
    ="block" reflects that: a route_to_review tool that Stage 1/2 didn't
    block resolves to Decision.REVIEW, which behaves as "not executed"
    until a real approval channel exists. Raising timeout_ms only becomes
    meaningful once one does.
    """
    enabled: bool = True
    timeout_ms: int = 0                  # 0 = no synchronous approver exists yet
    default_on_timeout: str = "block"    # only supported value today

@dataclass
class RLPolicyConfig:
    enabled: bool = False                # Enterprise only
    model_path: str | None = None        # path to best_model.zip
    trust_constraints: bool = True       # enforce exec requires trust>=4

@dataclass
class StagesConfig:
    rules:           RulesStageConfig     = field(default_factory=RulesStageConfig)
    classifier:      ClassifierStageConfig = field(default_factory=ClassifierStageConfig)
    approval:        ApprovalStageConfig   = field(default_factory=ApprovalStageConfig)
    semantic_filter: SemanticFilterConfig  = field(default_factory=SemanticFilterConfig)
    rl_policy:       RLPolicyConfig        = field(default_factory=RLPolicyConfig)

# ── Provider configs ──────────────────────────────────────────────────────────

@dataclass
class OllamaProviderConfig:
    base_url: str = "http://localhost:11434"
    keep_alive: int = -1

@dataclass
class OpenAIProviderConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None

@dataclass
class ProvidersConfig:
    ollama:   OllamaProviderConfig  = field(default_factory=OllamaProviderConfig)
    openai:   OpenAIProviderConfig  = field(default_factory=OpenAIProviderConfig)
    deepseek: OpenAIProviderConfig  = field(
        default_factory=lambda: OpenAIProviderConfig(
            base_url="https://api.deepseek.com/v1"
        )
    )

# ── Audit config ──────────────────────────────────────────────────────────────

@dataclass
class AuditConfig:
    enabled: bool = True
    db_path: str = "~/.agentwarden/audit/agentwarden_audit.db"
    log_allowed: bool = True
    log_blocked: bool = True

# ── Server config ─────────────────────────────────────────────────────────────

@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

# ── Master config ─────────────────────────────────────────────────────────────

@dataclass
class AgentWardenConfig:
    """
    Master configuration object.
    Loaded from YAML, env vars, or built-in defaults.
    """
    # Top-level
    runtime:     str        = "generic"
    backend:     str        = "ollama"
    shadow_mode: bool       = False
    policy:      str | None = None

    # Stage configs
    stages:    StagesConfig    = field(default_factory=StagesConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    audit:     AuditConfig     = field(default_factory=AuditConfig)
    server:    ServerConfig    = field(default_factory=ServerConfig)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def active_stages(self) -> list[str]:
        """Return names of all enabled stages in pipeline order."""
        active = []
        if self.stages.rules.enabled:
            active.append("rules")
        if self.stages.classifier.enabled:
            active.append("classifier")
        if self.stages.approval.enabled:
            active.append("approval")
        if self.stages.semantic_filter.enabled:
            active.append("semantic_filter")
        if self.stages.rl_policy.enabled:
            active.append("rl_policy")
        return active

    def summarise(self) -> dict[str, Any]:
        return {
            "runtime":      self.runtime,
            "backend":      self.backend,
            "shadow_mode":  self.shadow_mode,
            "policy":       self.policy,
            "active_stages": self.active_stages,
            "classifier_model": self.stages.classifier.model
                if self.stages.classifier.enabled else None,
            "semantic_model": self.stages.semantic_filter.model
                if self.stages.semantic_filter.enabled else None,
        }

    # ── Loaders ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> AgentWardenConfig:
        """
        Load config from YAML file.
        Falls back through default locations if config_path not given.
        """
        path = _resolve_config_path(config_path)
        if path is None:
            logger.debug("No config file found, using defaults.")
            cfg = cls()
        else:
            logger.info("Loading config from %s", path)
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            cfg = cls._from_dict(data)

        # Apply env var overrides
        cfg._apply_env_overrides()
        return cfg

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> AgentWardenConfig:
        """Build config from a raw YAML dict."""
        cfg = cls()

        # Top-level fields
        cfg.runtime     = data.get("runtime",     cfg.runtime)
        cfg.backend     = data.get("backend",     cfg.backend)
        cfg.shadow_mode = data.get("shadow_mode", cfg.shadow_mode)
        cfg.policy      = data.get("policy",      cfg.policy)

        # Stages
        stages_data = data.get("stages", {})
        if "rules" in stages_data:
            _update_dc(cfg.stages.rules, stages_data["rules"])
        if "classifier" in stages_data:
            _update_dc(cfg.stages.classifier, stages_data["classifier"])
        if "approval" in stages_data:
            _update_dc(cfg.stages.approval, stages_data["approval"])
        if "semantic_filter" in stages_data:
            _update_dc(cfg.stages.semantic_filter, stages_data["semantic_filter"])
        if "rl_policy" in stages_data:
            _update_dc(cfg.stages.rl_policy, stages_data["rl_policy"])

        # Providers
        providers_data = data.get("providers", {})
        if "ollama" in providers_data:
            _update_dc(cfg.providers.ollama, providers_data["ollama"])
        if "openai" in providers_data:
            _update_dc(cfg.providers.openai, providers_data["openai"])
        if "deepseek" in providers_data:
            _update_dc(cfg.providers.deepseek, providers_data["deepseek"])

        # Audit
        if "audit" in data:
            _update_dc(cfg.audit, data["audit"])

        # Server
        if "server" in data:
            _update_dc(cfg.server, data["server"])

        return cfg

    def _apply_env_overrides(self) -> None:
        """Environment variables override config file values."""
        # Top-level
        if v := os.getenv("AGENTWARDEN_RUNTIME"):
            self.runtime = v
        if v := os.getenv("AGENTWARDEN_BACKEND"):
            self.backend = v
        if os.getenv("AGENTWARDEN_SHADOW_MODE", "").lower() in ("1","true","yes"):
            self.shadow_mode = True

        # Stage enables
        if os.getenv("AGENTWARDEN_DISABLE_CLASSIFIER", "").lower() in ("1","true"):
            self.stages.classifier.enabled = False
        if os.getenv("AGENTWARDEN_ENABLE_SEMANTIC_FILTER", "").lower() in ("1","true"):
            self.stages.semantic_filter.enabled = True
        if os.getenv("AGENTWARDEN_ENABLE_RL_POLICY", "").lower() in ("1","true"):
            self.stages.rl_policy.enabled = True

        # Model swaps
        if v := os.getenv("AGENTWARDEN_CLASSIFIER_MODEL"):
            self.stages.classifier.model = v
        if v := os.getenv("AGENTWARDEN_SEMANTIC_MODEL"):
            self.stages.semantic_filter.model = v
        if v := os.getenv("AGENTWARDEN_ROUTER_MODEL"):
            self.stages.classifier.model_path = v

        # Provider URLs
        if v := os.getenv("OLLAMA_BASE_URL"):
            self.providers.ollama.base_url = v
        if v := os.getenv("OPENAI_BASE_URL"):
            self.providers.openai.base_url = v
        if v := os.getenv("OPENAI_API_KEY"):
            self.providers.openai.api_key = v
        if v := os.getenv("DEEPSEEK_API_KEY"):
            self.providers.deepseek.api_key = v

    def save(self, path: str | Path) -> None:
        """Save current config to YAML."""
        import dataclasses
        Path(path).write_text(yaml.dump(dataclasses.asdict(self), default_flow_style=False))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_config_path(explicit: str | Path | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    candidates = [
        Path(os.getenv("AGENTWARDEN_CONFIG", "")),
        Path("agentwarden.yaml"),
        Path("agentwarden.yml"),
        Path.home() / ".agentwarden" / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _update_dc(obj: Any, data: dict[str, Any]) -> None:
    """Update a dataclass instance from a dict, ignoring unknown keys."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(obj)}
    for k, v in data.items():
        if k in fields:
            setattr(obj, k, v)


# ── Global singleton ──────────────────────────────────────────────────────────

_global_config: AgentWardenConfig | None = None

def get_config(config_path: str | None = None) -> AgentWardenConfig:
    global _global_config
    if _global_config is None:
        _global_config = AgentWardenConfig.load(config_path)
    return _global_config

def reset_config() -> None:
    """Force reload on next get_config() call. Useful for testing."""
    global _global_config
    _global_config = None
