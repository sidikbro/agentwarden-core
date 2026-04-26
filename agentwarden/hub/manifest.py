"""
AgentWarden Policy Manifest
============================
The policy manifest format — think Docker images but for governance policies.
Defines what a policy does, what it blocks, and what weights it needs.

`agentwarden pull policy:customer-support-v1` downloads and installs a manifest.
`agentwarden serve --policy customer-support-v1` loads it at startup.

Manifest files live in ~/.agentwarden/policies/<name>/manifest.yaml
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("agentwarden.hub.manifest")

# Default Hub URL — can be overridden via AGENTWARDEN_HUB_URL env var
DEFAULT_HUB_URL = "https://hub.agentwarden.ai/v1"


@dataclass
class PolicyManifest:
    """
    Describes a governance policy — its rules, classifier, and RL weights.

    Example manifest YAML:

        name: customer-support-v1
        version: 1.0.0
        description: "Safe defaults for customer-facing support agents"
        author: "AgentWarden Team"
        license: "Apache-2.0"

        # Capability scoping
        always_block:
          - exec
          - sessions_spawn
          - subagents
          - write_file

        allowed_tools:
          - read
          - web_search
          - send_email
          - create_ticket
          - read_knowledge_base

        trust_level: 0.3

        # Classifier weights (open-source tier)
        classifier:
          model: qwen-1.5B-safety-v1
          sha256: abc123...
          size_mb: 950

        # RL policy weights (AMARE Enterprise only — null in OSS tier)
        rl_policy: null

        # Custom YAML rules (merged with defaults)
        extra_rules:
          always_block:
            - deploy_to_prod   # example enterprise-specific addition
          arg_patterns:
            - pattern: "DROP TABLE"
              description: "SQL injection attempt"

        tags:
          - customer-support
          - production-safe
          - no-exec
    """

    name:        str
    version:     str
    description: str = ""
    author:      str = "community"
    license:     str = "Apache-2.0"

    # Capability scoping
    always_block:   list[str] = field(default_factory=list)
    allowed_tools:  list[str] = field(default_factory=list)
    trust_level:    float = 0.5

    # Weights references
    classifier:   dict[str, Any] | None = None   # OSS tier
    rl_policy:    dict[str, Any] | None = None   # AMARE Enterprise only

    # Extra rules merged on top of defaults
    extra_rules:  dict[str, Any] = field(default_factory=dict)

    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path | str) -> PolicyManifest:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_yaml(self) -> str:
        import dataclasses
        return yaml.dump(dataclasses.asdict(self), default_flow_style=False)

    def save(self, path: Path | str) -> None:
        Path(path).write_text(self.to_yaml())

    @property
    def is_enterprise(self) -> bool:
        """True if this manifest requires AMARE Enterprise (has RL weights)."""
        return self.rl_policy is not None

    @property
    def policy_id(self) -> str:
        return f"{self.name}:{self.version}"


# ── Built-in policy manifests (free tier) ────────────────────────────────────

BUILTIN_POLICIES: dict[str, dict] = {

    "customer-support-v1": {
        "name": "customer-support-v1",
        "version": "1.0.0",
        "description": "Safe defaults for customer-facing support agents. Allows read, email, tickets. Blocks all execution and filesystem writes.",
        "author": "AgentWarden Team",
        "always_block": ["exec", "execute", "bash", "sessions_spawn", "subagents", "task",
                         "write_file", "edit_file", "deploy", "credential_access"],
        "allowed_tools": ["read", "web_search", "send_email", "create_ticket",
                          "read_knowledge_base", "memory_search", "memory_get"],
        "trust_level": 0.3,
        "tags": ["customer-support", "production-safe", "no-exec"],
    },

    "devops-safe-v1": {
        "name": "devops-safe-v1",
        "version": "1.0.0",
        "description": "DevOps agent with exec and write allowed, but network restricted to internal IPs. No credential access.",
        "author": "AgentWarden Team",
        "always_block": ["sessions_spawn", "subagents", "task", "credential_access",
                         "cloud_metadata", "deploy_external"],
        "allowed_tools": ["exec", "read", "write_file", "edit_file", "git",
                          "docker", "kubectl", "logs", "web_search"],
        "trust_level": 0.7,
        "extra_rules": {
            "arg_patterns": [
                {"pattern": "169\\.254\\.169\\.254", "description": "Cloud metadata endpoint"},
                {"pattern": "~/.aws/credentials",    "description": "AWS credentials"},
            ]
        },
        "tags": ["devops", "internal-only", "exec-allowed"],
    },

    "research-agent-v1": {
        "name": "research-agent-v1",
        "version": "1.0.0",
        "description": "Read-only research agent. Broad web access, no writes, no execution.",
        "author": "AgentWarden Team",
        "always_block": ["exec", "execute", "bash", "sessions_spawn", "subagents", "task",
                         "write_file", "edit_file", "send_email", "deploy"],
        "allowed_tools": ["read", "web_search", "web_fetch", "memory_search",
                          "memory_get", "read_todos"],
        "trust_level": 0.5,
        "tags": ["research", "read-only", "safe"],
    },

    "data-analyst-v1": {
        "name": "data-analyst-v1",
        "version": "1.0.0",
        "description": "Data analyst with sandbox write access. No production deployment or network egress.",
        "author": "AgentWarden Team",
        "always_block": ["exec", "sessions_spawn", "subagents", "deploy",
                         "send_email", "credential_access"],
        "allowed_tools": ["read", "write_file", "web_search", "memory_search",
                          "sql_query_sandbox", "python_sandbox", "read_todos"],
        "trust_level": 0.5,
        "tags": ["data", "analytics", "sandbox"],
    },

    "finance-agent-v1": {
        "name": "finance-agent-v1",
        "version": "1.0.0",
        "description": "Finance agent. Read ERP, send reports, approve transactions under threshold. No exec or external writes.",
        "author": "AgentWarden Team",
        "always_block": ["exec", "execute", "bash", "sessions_spawn", "subagents",
                         "write_file", "edit_file", "external_write", "credential_access"],
        "allowed_tools": ["read_erp", "send_report", "approve_under_threshold",
                          "read", "memory_search"],
        "trust_level": 0.4,
        "tags": ["finance", "compliance", "read-mostly"],
    },

    "it-admin-elevated-v1": {
        "name": "it-admin-elevated-v1",
        "version": "1.0.0",
        "description": "Elevated IT admin. Exec allowed but audited. No cloud metadata or SSH credential access.",
        "author": "AgentWarden Team",
        "always_block": ["sessions_spawn", "subagents", "cloud_metadata"],
        "allowed_tools": ["exec", "read", "write_file", "edit_file",
                          "sessions_spawn_internal", "logs", "kubectl", "docker"],
        "trust_level": 0.8,
        "extra_rules": {
            "arg_patterns": [
                {"pattern": "~/.ssh/", "description": "SSH credential path"},
                {"pattern": "169\\.254\\.169\\.254", "description": "Cloud metadata"},
            ]
        },
        "tags": ["it-admin", "elevated", "audited"],
    },
}


def get_builtin_policy(name: str) -> PolicyManifest:
    """Get a built-in policy manifest by name (strips version suffix for lookup)."""
    data = BUILTIN_POLICIES.get(name)
    if data is None:
        available = list(BUILTIN_POLICIES.keys())
        raise ValueError(f"Policy '{name}' not found. Available: {available}")
    return PolicyManifest(**data)


def list_builtin_policies() -> list[str]:
    return list(BUILTIN_POLICIES.keys())
