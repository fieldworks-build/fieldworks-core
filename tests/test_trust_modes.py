"""Tests for fieldworks.trust.modes — fieldworks-core#18."""

import pytest

from fieldworks.trust.audit import AuditLog, AuditLogConfig
from fieldworks.trust.intercept import ProposedAction, format_decision_result
from fieldworks.trust.modes import (
    Disposition,
    TrustMode,
    log_mode_change,
    resolve_disposition,
)


def test_supervised_always_intercepts():
    assert resolve_disposition(TrustMode.SUPERVISED) == Disposition.INTERCEPT


def test_advisory_never_intercepts_recommends_only():
    assert resolve_disposition(TrustMode.ADVISORY) == Disposition.RECOMMEND_ONLY


def test_autonomous_never_intercepts_auto_approves():
    assert resolve_disposition(TrustMode.AUTONOMOUS) == Disposition.AUTO_APPROVE


def test_collaborative_in_range_auto_approves():
    assert (
        resolve_disposition(TrustMode.COLLABORATIVE, in_normal_range=True)
        == Disposition.AUTO_APPROVE
    )


def test_collaborative_out_of_range_intercepts():
    assert (
        resolve_disposition(TrustMode.COLLABORATIVE, in_normal_range=False)
        == Disposition.INTERCEPT
    )


def test_collaborative_without_in_normal_range_raises():
    with pytest.raises(ValueError, match="in_normal_range"):
        resolve_disposition(TrustMode.COLLABORATIVE)


def test_in_normal_range_ignored_for_non_collaborative_modes():
    # Passing it for a mode that doesn't use it shouldn't change the outcome.
    assert (
        resolve_disposition(TrustMode.SUPERVISED, in_normal_range=False)
        == Disposition.INTERCEPT
    )
    assert (
        resolve_disposition(TrustMode.AUTONOMOUS, in_normal_range=False)
        == Disposition.AUTO_APPROVE
    )


def test_log_mode_change_records_transition(tmp_path):
    with pytest.warns(UserWarning):
        audit = AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl"))

    log_mode_change(
        audit,
        from_mode=TrustMode.SUPERVISED,
        to_mode=TrustMode.AUTONOMOUS,
        changed_by="operator-01",
        session_id="sess-abc",
    )

    entries = audit.read()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == "trust_mode_changed"
    assert entry["from_mode"] == "SUPERVISED"
    assert entry["to_mode"] == "AUTONOMOUS"
    assert entry["changed_by"] == "operator-01"
    assert entry["session_id"] == "sess-abc"


def test_format_decision_result_auto_approved():
    action = ProposedAction(
        action_id="abc123",
        description="Reduce chlorine dose",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
    )
    text = format_decision_result(action, "auto_approved")
    assert "auto-approved" in text
    assert "Chlorine_01" in text
    assert "setpoint_adjustment" in text


def test_format_decision_result_recommended():
    action = ProposedAction(
        action_id="abc123",
        description="Reduce chlorine dose",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
    )
    text = format_decision_result(action, "recommended")
    assert "ADVISORY" in text
    assert "manually" in text
    assert "Chlorine_01" in text
