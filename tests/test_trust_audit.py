"""Tests for fieldworks.trust.audit."""

import base64
import os

import pytest

from fieldworks.trust.audit import AuditLog, AuditLogConfig, parse_audit_key


@pytest.fixture
def key() -> bytes:
    return os.urandom(32)


def test_log_then_read_round_trip_plaintext_when_no_key(tmp_path):
    with pytest.warns(UserWarning):
        log = AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl"))
    log.log("tool_call", tool="propose_action", args={"target": "Chlorine_01"})

    entries = log.read()
    assert len(entries) == 1
    assert entries[0]["event"] == "tool_call"
    assert entries[0]["tool"] == "propose_action"


def test_log_then_read_round_trip_with_key_encrypted(tmp_path, key):
    log = AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl", key=key))
    log.log("action_decision", action_id="abc123", decision="approved")

    raw = (tmp_path / "audit.jsonl").read_text()
    assert "approved" not in raw  # encrypted on disk

    entries = log.read()
    assert entries[0]["decision"] == "approved"


def test_verify_ok_on_untampered_chain(tmp_path, key):
    log = AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl", key=key))
    log.log("tool_call", tool="propose_action")
    log.log("action_decision", decision="approved")

    result = log.verify()
    assert result.ok is True
    assert result.record_count == 2
    assert result.problems == []


def test_verify_detects_tampered_record(tmp_path):
    with pytest.warns(UserWarning):
        log = AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl"))
    log.log("tool_call", tool="propose_action")
    log.log("action_decision", decision="approved")
    log.log("tool_result", result="ok")

    log_path = tmp_path / "audit.jsonl"
    lines = log_path.read_text().splitlines()
    lines[1] = lines[1].replace("approved", "APPROVED_TAMPERED")
    log_path.write_text("\n".join(lines) + "\n")

    result = log.verify()
    assert result.ok is False
    assert result.problems  # at least one broken-chain message


def test_rotate_archives_file_and_resets_chain_state(tmp_path, key):
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(AuditLogConfig(log_path=log_path, key=key))
    log.log("tool_call", tool="propose_action")

    archive_path = log.rotate()
    assert archive_path is not None
    assert archive_path.exists()

    log.log("tool_call", tool="set_setpoint")
    entries = log.read()
    assert entries[0]["seq"] == 1  # chain reset after rotation

    archived_entries = AuditLog(AuditLogConfig(log_path=archive_path, key=key)).read()
    assert archived_entries[0]["tool"] == "propose_action"


def test_recovers_seq_and_prev_hash_across_separate_instances(tmp_path, key):
    log_path = tmp_path / "audit.jsonl"
    first = AuditLog(AuditLogConfig(log_path=log_path, key=key))
    first.log("tool_call", tool="propose_action")
    first.log("action_decision", decision="approved")

    second = AuditLog(AuditLogConfig(log_path=log_path, key=key))
    second.log("tool_result", result="ok")

    result = second.verify()
    assert result.ok is True
    assert result.record_count == 3


def test_key_wrong_length_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl", key=b"too-short"))


def test_missing_key_emits_warning(tmp_path):
    with pytest.warns(UserWarning):
        AuditLog(AuditLogConfig(log_path=tmp_path / "audit.jsonl"))


def test_parse_audit_key_rejects_bad_base64_length():
    bad = base64.b64encode(b"too-short").decode()
    with pytest.raises(ValueError):
        parse_audit_key(bad)
