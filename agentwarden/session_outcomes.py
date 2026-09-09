"""Session outcome logging for AMARE constrained RL training."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("agentwarden.session_outcomes")


@dataclass
class SessionOutcomeRecord:
    session_id: str
    tenant_id: str = "default"
    task_type: str = "unknown"
    task_success: int = 0          # 1=completed, 0=failed
    tools_exposed: list = field(default_factory=list)
    tools_used: list = field(default_factory=list)
    failure_reason: Optional[str] = None
    missing_tools: list = field(default_factory=list)
    ser: float = 0.0
    block_count: int = 0
    review_count: int = 0
    stage1_blocks: int = 0
    stage2_blocks: int = 0
    duration_ms: Optional[int] = None
    notes: str = ""


class SessionOutcomeLogger:
    """Logs session outcomes to SQLite for AMARE RL training."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS session_outcomes (
        id              TEXT PRIMARY KEY,
        timestamp       TEXT NOT NULL,
        session_id      TEXT NOT NULL,
        tenant_id       TEXT NOT NULL DEFAULT 'default',
        task_type       TEXT NOT NULL,
        task_success    INTEGER NOT NULL,
        tools_exposed   TEXT NOT NULL,
        tools_used      TEXT NOT NULL,
        failure_reason  TEXT,
        missing_tools   TEXT,
        ser             REAL,
        block_count     INTEGER DEFAULT 0,
        review_count    INTEGER DEFAULT 0,
        stage1_blocks   INTEGER DEFAULT 0,
        stage2_blocks   INTEGER DEFAULT 0,
        duration_ms     INTEGER,
        notes           TEXT
    );
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv(
            "AGENTWARDEN_DB_PATH", "/app/audit/agentwarden_audit.db"
        )
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(self.SCHEMA)
            # review_count is new — add it to any pre-existing DB from
            # before Decision.REVIEW existed. CREATE TABLE IF NOT EXISTS
            # doesn't alter an already-existing table.
            try:
                conn.execute("ALTER TABLE session_outcomes ADD COLUMN review_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already exists
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("SessionOutcomeLogger: DB init failed: %s", e)

    def log(self, record: SessionOutcomeRecord) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO session_outcomes
                   (id, timestamp, session_id, tenant_id, task_type, task_success,
                    tools_exposed, tools_used, failure_reason, missing_tools,
                    ser, block_count, review_count, stage1_blocks, stage2_blocks, duration_ms, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()),
                    __import__("datetime").datetime.utcnow().isoformat(),
                    record.session_id,
                    record.tenant_id,
                    record.task_type,
                    record.task_success,
                    json.dumps(record.tools_exposed),
                    json.dumps(record.tools_used),
                    record.failure_reason,
                    json.dumps(record.missing_tools),
                    record.ser,
                    record.block_count,
                    record.review_count,
                    record.stage1_blocks,
                    record.stage2_blocks,
                    record.duration_ms,
                    record.notes,
                ),
            )
            conn.commit()
            conn.close()
            logger.info(
                "SESSION_OUTCOME | session=%s type=%s success=%d ser=%.3f blocks=%d",
                record.session_id, record.task_type, record.task_success,
                record.ser, record.block_count,
            )
            return True
        except Exception as e:
            logger.warning("SessionOutcomeLogger: log failed: %s", e)
            return False
