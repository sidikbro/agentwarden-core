"""Abstract base classes — the three plugin interfaces."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from agentwarden.core.models import AgentWardenToolRequest, GovernanceContext, GovernanceDecision, Runtime, SessionState

class ToolParser(ABC):
    runtime: Runtime = Runtime.GENERIC
    @abstractmethod
    def can_parse(self, raw_response: dict[str, Any]) -> bool: ...
    @abstractmethod
    def parse(self, raw_response: dict[str, Any], context: GovernanceContext) -> list[AgentWardenToolRequest]: ...
    def reconstruct(self, raw_response: dict[str, Any], allowed_requests: list[AgentWardenToolRequest]) -> dict[str, Any]:
        return raw_response

class PolicyPlugin(ABC):
    name: str = "unnamed"
    priority: int = 99
    is_terminal: bool = False
    @abstractmethod
    def evaluate(self, request: AgentWardenToolRequest) -> GovernanceDecision: ...
    def is_applicable(self, request: AgentWardenToolRequest) -> bool: return True

class LLMProvider(ABC):
    name: str = "generic"
    @abstractmethod
    async def forward(self, request_body: dict[str, Any], headers: dict[str, str] | None = None, timeout: float = 120.0) -> dict[str, Any]: ...
    @property
    @abstractmethod
    def base_url(self) -> str: ...

class GovernanceProfile(ABC):
    """D1: decides which tools the model gets to SEE. `expose()` is the
    primary interface — task_type is a plain string (not the narrow, mostly
    unused TaskType enum) so it can name benchmark task families directly.
    `get_allowed_tools(context)` is a compatibility wrapper for callers that
    only have a GovernanceContext, not a (task_type, phase, session_state)
    triple in hand.
    """
    name: str = "unnamed"
    description: str = ""

    @abstractmethod
    def expose(self, task_type: str, phase: str | None, session_state: SessionState) -> set[str]: ...

    def get_allowed_tools(self, context: GovernanceContext) -> set[str]:
        task_type = context.task_type.value if hasattr(context.task_type, "value") else str(context.task_type)
        phase = context.metadata.get("phase")
        session_state = context.metadata.get("session_state") or SessionState()
        return self.expose(task_type, phase, session_state)

    @abstractmethod
    def get_always_block(self, context: GovernanceContext) -> set[str]: ...
    def get_trust_level(self, context: GovernanceContext) -> float: return 0.5
    def to_agents_md(self, context: GovernanceContext) -> str:
        allowed = sorted(self.get_allowed_tools(context))
        joined = ', '.join(allowed)
        return f"# AgentWarden Governance Active\nProfile: {self.name}\nAvailable tools: {joined}.\n"
