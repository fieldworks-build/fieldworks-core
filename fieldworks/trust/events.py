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
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fieldworks.trust.identity import check_approver

logger = logging.getLogger(__name__)


# Columns added after the first release, with the DDL that adds them to an
# existing table. Constant names and types only: never user input.
_ADDED_COLUMNS = (
    ("site_id", "TEXT NOT NULL DEFAULT ''"),
    ("auth_method", "TEXT"),
)


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
                    outcome      TEXT    DEFAULT 'pending',
                    site_id      TEXT    NOT NULL DEFAULT '',
                    auth_method  TEXT
                );
                """)
            # Additive migration for stores created before a column existed.
            have = {
                row["name"] for row in c.execute("PRAGMA table_info(action_events)")
            }
            for name, ddl in _ADDED_COLUMNS:
                if name not in have:
                    c.execute(f"ALTER TABLE action_events ADD COLUMN {name} {ddl}")
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
        auth_method: str | None = None,
        outcome: str = "pending",
    ) -> None:
        """Record one step of a proposed action.

        `auth_method` says how the deployment established `operator_id`
        (spec Part III): "user", "shared_credential" or "trust_mode". With
        it, the record is checked for honesty (see
        fieldworks.trust.identity.check_approver) and a ValueError raised
        before anything is written. For an action dispatch settled itself,
        pass the fields from dispatch_approver().

        Omitting it is deprecated: the record is written without one, as
        before 1.6.0.
        """
        if auth_method is None:
            warnings.warn(
                "log_action_event() without auth_method is deprecated; spec "
                "v0.3 requires it on every record that carries operator_id",
                DeprecationWarning,
                stacklevel=2,
            )
        else:
            check_approver(
                decision=decision, operator_id=operator_id, auth_method=auth_method
            )
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    """INSERT INTO action_events
                       (ts, session_id, action_type, target, value, description,
                        operator_id, decision, outcome, auth_method)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        auth_method,
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
