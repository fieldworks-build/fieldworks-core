"""Who approved an action, and how the deployment knows (spec Part I,
Operator identity; Part III, auth_method and dispatch disposition).

Every action record carries `operator_id` and `auth_method`. Both must be
honest: a person's own id with `user`, a documented fixed value such as
`shared-token` with `shared_credential`, or `trust-mode:<mode>` with
`trust_mode` when trust-mode dispatch decided without a person. Never a
placeholder person.

The disposition needs no field of its own. An auto-approval is
`decision='auto_approved'` from `auth_method='trust_mode'`; an operator's
approval is `decision='approved'` from a person or shared credential. A
reader can always tell the two apart, which is what Part III requires.
"""

from __future__ import annotations

from fieldworks.trust.modes import Disposition, TrustMode

AUTH_METHODS = ("user", "shared_credential", "trust_mode")

# What happened to a proposed action. pending/approved/denied/timed_out are
# the intercept's outcomes; auto_approved/recommended are dispatch's.
DECISIONS = (
    "pending",
    "approved",
    "denied",
    "timed_out",
    "auto_approved",
    "recommended",
)
_DISPATCH_DECISIONS = {"auto_approved", "recommended"}
_TRUST_MODE_PREFIX = "trust-mode:"


def trust_mode_operator(mode: TrustMode) -> str:
    """The operator_id for an action dispatch approved without a person,
    e.g. "trust-mode:autonomous"."""
    return _TRUST_MODE_PREFIX + mode.value.lower()


def dispatch_approver(mode: TrustMode, disposition: Disposition) -> dict[str, str]:
    """The decision, operator_id and auth_method to record for an action
    dispatch settled itself. Spread the result into both
    ActionEventStore.log_action_event() and the AuditLog record, so the two
    sinks agree.

    INTERCEPT has no dispatch approver: a person decides, and the host
    records that person (or its shared credential) instead.
    """
    if disposition == Disposition.INTERCEPT:
        raise ValueError(
            "an intercepted action is decided by a person; record their "
            "operator_id and auth_method, not trust mode's"
        )
    decision = (
        "auto_approved" if disposition == Disposition.AUTO_APPROVE else "recommended"
    )
    return {
        "decision": decision,
        "operator_id": trust_mode_operator(mode),
        "auth_method": "trust_mode",
    }


def check_approver(*, decision: str, operator_id: str, auth_method: str) -> None:
    """Raise ValueError unless the three fields tell a consistent, honest
    story: a known decision and auth_method, dispatch decisions only from
    trust mode, and trust mode only as `trust-mode:<mode>`."""
    if auth_method not in AUTH_METHODS:
        raise ValueError(
            f"auth_method {auth_method!r} is not one of {', '.join(AUTH_METHODS)}"
        )
    if decision not in DECISIONS:
        raise ValueError(f"decision {decision!r} is not one of {', '.join(DECISIONS)}")
    if not operator_id:
        raise ValueError("operator_id is required")

    by_trust_mode = auth_method == "trust_mode"
    if (decision in _DISPATCH_DECISIONS) != by_trust_mode:
        if by_trust_mode:
            raise ValueError(
                f"trust mode records only auto_approved or recommended, "
                f"not {decision!r}"
            )
        raise ValueError(f"{decision!r} comes from trust mode, not {auth_method!r}")
    if by_trust_mode:
        mode = operator_id.removeprefix(_TRUST_MODE_PREFIX)
        if mode == operator_id:
            raise ValueError(
                f"trust-mode operator_id must be 'trust-mode:<mode>', "
                f"not {operator_id!r}"
            )
        TrustMode.parse(mode)
    elif operator_id.startswith(_TRUST_MODE_PREFIX):
        raise ValueError(
            f"operator_id {operator_id!r} names trust mode but auth_method "
            f"is {auth_method!r}"
        )
