"""TrainingExample record format — the review-status/provenance metadata
is not optional decoration, it's what makes "hand-authored/reviewed"
auditable rather than asserted. See docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md
§2's authorship/review protocol.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Decision = Literal["ALLOW", "BLOCK"]
Source = Literal["hand_authored", "paraphrase_generated"]
ReviewStatus = Literal["pending", "approved", "corrected", "rejected"]

# The category taxonomy the plan's §2/§3/§3a balance table is stratified
# over. "reason_type" mirrors §2's stratification axis.
ReasonType = Literal[
    "always_block_name",
    "arg_pattern_trigger",
    "injection_pattern_trigger",
    "safe_but_defended",
    "defensively_framed_but_unsafe",
    "near_miss_allow",
    "generic_safe",
]


@dataclass
class TrainingExample:
    tool_name: str
    tool_description: str
    arguments: dict[str, Any]
    context: str                     # minimal surrounding context, e.g. a prior tool result or task framing
    decision: Decision
    reason: str                      # the target model's expected justification text
    risk_level: int                  # 0-4, tools.yaml scale; -1 if not tools.yaml-derived (hand-authored novel scenario)
    reason_type: ReasonType
    subcategory: str                 # free-text pointer into §3/§3a's numbered subcategories, or "n/a"
    source: Source

    # Provenance / review audit trail — required fields, not afterthoughts.
    drafted_by: str                   # model name if LLM-drafted, "human" if written directly
    review_status: ReviewStatus = "pending"
    reviewer: str | None = None
    review_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetManifest:
    """Written alongside generated data — counts and composition, so a
    reviewer can check the actual output against the plan's targets
    without re-deriving them from the raw files."""
    total: int
    by_decision: dict[str, int] = field(default_factory=dict)
    by_reason_type: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_review_status: dict[str, int] = field(default_factory=dict)
    contamination_check: dict[str, Any] = field(default_factory=dict)
