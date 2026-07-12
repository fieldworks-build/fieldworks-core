"""Trust layer — propose/approve/execute for SUPERVISED trust mode.

Covers the operator-approval intercept mechanism and its two logging sinks
(compliance-grade hash-chained audit trail, queryable action-event store).
ADVISORY/COLLABORATIVE/AUTONOMOUS trust-mode dispatch (deciding whether an
action needs interception at all) is out of scope here — tracked separately.

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
]
