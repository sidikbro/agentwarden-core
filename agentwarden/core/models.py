"""AgentWarden canonical data models."""
from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class Decision(str, Enum):
    ALLOW  = "ALLOW"
    BLOCK  = "BLOCK"
    REVIEW = "REVIEW"

class BlockReason(str, Enum):
    ALWAYS_BLOCK_TOOL   = "always_block_tool"
    DANGEROUS_ARGUMENT  = "dangerous_argument"
    INJECTION_PATTERN   = "injection_pattern"
    RBAC_POLICY         = "rbac_policy"
    LLM_CLASSIFIER      = "llm_classifier"
    RL_POLICY           = "rl_policy"

class Runtime(str, Enum):
    OPENCLAW   = "openclaw"
    NEMOCLAW   = "nemoclaw"   # NVIDIA NemoClaw = OpenClaw + OpenShell sandbox
    HERMES     = "hermes"
    DEEPAGENTS = "deepagents"
    LANGGRAPH  = "langgraph"
    CREWAI     = "crewai"
    AUTOGEN    = "autogen"
    GENERIC    = "generic"

class TaskType(str, Enum):
    SUMMARISATION  = "summarisation"
    FILE_READ      = "file_read"
    WEB_RESEARCH   = "web_research"
    CODE_EXECUTION = "code_execution"
    EMAIL          = "email"
    UNKNOWN        = "unknown"

@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    raw_id: str | None = None
    raw_format: str | None = None

@dataclass
class GovernanceContext:
    session_id:    str            = field(default_factory=lambda: str(uuid.uuid4()))
    runtime:       Runtime        = Runtime.GENERIC
    task_type:     TaskType       = TaskType.UNKNOWN
    trust_level:   float          = 0.5
    allowed_tools: set[str]       = field(default_factory=set)
    tenant_id:     str | None     = None
    profile_name:  str | None     = None
    metadata:      dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentWardenToolRequest:
    tool_call:          ToolCall
    context:            GovernanceContext
    request_id:         str            = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:          float          = field(default_factory=time.time)
    raw_request_body:   dict[str, Any] = field(default_factory=dict)
    raw_response_body:  dict[str, Any] = field(default_factory=dict)

@dataclass
class GovernanceDecision:
    request_id:    str
    tool_name:     str
    decision:      Decision
    reason:        BlockReason | None = None
    reason_detail: str | None        = None
    confidence:    float | None      = None
    latency_ms:    float | None      = None
    stage:         str | None        = None
    metadata:      dict[str, Any]    = field(default_factory=dict)
    reward_signal: float | None      = None

@dataclass
class PipelineResult:
    session_id:       str
    decisions:        list[GovernanceDecision] = field(default_factory=list)
    mutated_response: dict[str, Any]           = field(default_factory=dict)
    total_latency_ms: float                    = 0.0

    @property
    def any_blocked(self): return any(d.decision == Decision.BLOCK for d in self.decisions)
    @property
    def block_count(self): return sum(1 for d in self.decisions if d.decision == Decision.BLOCK)
    @property
    def allow_count(self): return sum(1 for d in self.decisions if d.decision == Decision.ALLOW)
