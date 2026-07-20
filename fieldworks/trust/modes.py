"""Trust-mode dispatch — deciding whether a proposed action needs interception.

`intercept.py` covers SUPERVISED (always intercept) and the mechanics of the
intercept itself. This module covers the other three modes from CLAUDE.md's
trust table:

  ADVISORY      — agent recommends, operator executes manually. Never
                  intercepts (there's nothing to approve — the agent never
                  proceeds on its own either way), never blocks.
  COLLABORATIVE — confirm writes outside normal range only. Needs the host
                  to say whether the proposed value is in range; auto-
                  approves if so, intercepts (same as SUPERVISED) if not.
  AUTONOMOUS    — agent acts within configured limits, logs everything.
                  Never intercepts, but must be logged with identical
                  fidelity to an approved SUPERVISED action — this mode
                  trades the pause for a stronger audit trail, not a
                  weaker one.

Dispatch is a pure function: given the mode (and, for COLLABORATIVE, an
in-range flag the host computes from its own topology/threshold data), it
returns what to do. Actually doing it — awaiting an intercept, logging an
event, presenting a recommendation — stays the host's job, same division of
labor as intercept.py.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fieldworks.trust.audit import AuditLog


class TrustMode(str, Enum):
    SUPERVISED = "SUPERVISED"
    ADVISORY = "ADVISORY"
    COLLABORATIVE = "COLLABORATIVE"
    AUTONOMOUS = "AUTONOMOUS"


class Disposition(str, Enum):
    INTERCEPT = "intercept"  # block for operator approval, same as SUPERVISED
    RECOMMEND_ONLY = "recommend_only"  # surface the recommendation, never execute
    AUTO_APPROVE = "auto_approve"  # proceed without blocking, log as approved


def resolve_disposition(
    mode: TrustMode, *, in_normal_range: bool | None = None
) -> Disposition:
    """Decide how a proposed action should be handled under the given mode.

    in_normal_range is COLLABORATIVE-only — the host determines it (e.g.
    against topology.yaml's normal_range for the target attribute) and
    supplies it here; a ValueError if COLLABORATIVE is requested without it,
    since silently defaulting either way would hide a real decision. Ignored
    for every other mode.
    """
    if mode == TrustMode.ADVISORY:
        return Disposition.RECOMMEND_ONLY
    if mode == TrustMode.AUTONOMOUS:
        return Disposition.AUTO_APPROVE
    if mode == TrustMode.COLLABORATIVE:
        if in_normal_range is None:
            raise ValueError(
                "COLLABORATIVE mode requires in_normal_range to decide "
                "whether to intercept"
            )
        return Disposition.AUTO_APPROVE if in_normal_range else Disposition.INTERCEPT
    return Disposition.INTERCEPT  # SUPERVISED


def log_mode_change(
    audit: "AuditLog",
    *,
    from_mode: TrustMode,
    to_mode: TrustMode,
    changed_by: str,
    session_id: str | None = None,
) -> None:
    """Record a trust-mode transition. Per CLAUDE.md: "the record shows
    when and by whom the mode was set" — this is that record. Mode changes
    go through the hash-chained AuditLog, not ActionEventStore — a mode
    change isn't an action event, and it should be exactly as tamper-evident
    as the actions it goes on to govern.
    """
    audit.log(
        "trust_mode_changed",
        from_mode=from_mode,
        to_mode=to_mode,
        changed_by=changed_by,
        session_id=session_id,
    )
