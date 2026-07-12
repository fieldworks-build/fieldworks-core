"""Structured, queryable log of propose/approve/execute decisions.

This is the SQLite-backed companion to `AuditLog` — where `AuditLog` is an
encrypted, hash-chained append-only chain (compliance-grade, tamper-evident),
`ActionEventStore` is a plain queryable table for building UI/reporting
("show me every action taken on this equipment in the last 24 hours").
Approval and denial are logged with identical shape (denial parity) so
neither path is a second-class citizen in the record.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ActionEventStoreConfig:
    db_path: str | Path


class ActionEventStore:
    def __init__(self, config: ActionEventStoreConfig) -> None:
        self._db_path = Path(config.db_path)
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS action_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts           TEXT    NOT NULL,
                    session_id   TEXT    NOT NULL,
                    action_type  TEXT,
                    target       TEXT,
                    value        TEXT,
                    description  TEXT,
                    operator_id  TEXT    NOT NULL,
                    decision     TEXT,
                    outcome      TEXT    DEFAULT 'pending'
                );
                """)
            c.commit()

    def log_action_event(
        self,
        *,
        session_id: str,
        action_type: str,
        target: str,
        value: str,
        description: str,
        decision: str,
        operator_id: str,
        outcome: str = "pending",
    ) -> None:
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    """INSERT INTO action_events
                       (ts, session_id, action_type, target, value, description,
                        operator_id, decision, outcome)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        session_id,
                        action_type,
                        target,
                        value,
                        description,
                        operator_id,
                        decision,
                        outcome,
                    ),
                )
                c.commit()
        except Exception as exc:
            logger.warning("action_event write failed: %s", exc)

    def get_action_events(
        self, session_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        with self._lock, self._conn() as c:
            if session_id:
                rows = c.execute(
                    """SELECT * FROM action_events
                       WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM action_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
