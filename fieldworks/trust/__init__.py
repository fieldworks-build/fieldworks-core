"""Trust layer — propose/approve/execute across all four trust modes.

Covers the operator-approval intercept mechanism (SUPERVISED), dispatch for
the other three modes (ADVISORY/COLLABORATIVE/AUTONOMOUS — see modes.py),
and two logging sinks (compliance-grade hash-chained audit trail, queryable
action-event store).

Requires the optional `trust` extra: pip install fieldworks-core[trust]
"""

from fieldworks.trust.audit import (
    AuditLog,
    AuditLogConfig,
    VerifyResult,
    parse_audit_key,
)
from fieldworks.trust.events import ActionEventStore, ActionEventStoreConfig
from fieldworks.trust.intercept import (
    PROPOSE_ACTION_SCHEMA,
    PROPOSE_ACTION_TOOL,
    PendingActionRegistry,
    ProposedAction,
    format_decision_result,
    generate_action_id,
)
from fieldworks.trust.modes import (
    Disposition,
    TrustMode,
    log_mode_change,
    resolve_disposition,
)

__all__ = [
    "AuditLog",
    "AuditLogConfig",
    "VerifyResult",
    "parse_audit_key",
    "ActionEventStore",
    "ActionEventStoreConfig",
    "PROPOSE_ACTION_TOOL",
    "PROPOSE_ACTION_SCHEMA",
    "ProposedAction",
    "PendingActionRegistry",
    "generate_action_id",
    "format_decision_result",
    "TrustMode",
    "Disposition",
    "resolve_disposition",
    "log_mode_change",
]
