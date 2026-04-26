"""Audit logger."""
from __future__ import annotations
import logging
logger = logging.getLogger("agentwarden.audit")

class AuditLogger:
    async def log_pipeline_result(self, result, context) -> None:
        for d in result.decisions:
            logger.info("AUDIT | session=%s | tool=%s | decision=%s | latency=%.1fms",
                context.session_id, d.tool_name, d.decision.value, d.latency_ms or 0)
