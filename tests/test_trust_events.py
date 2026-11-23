"""Tests for fieldworks.trust.events."""

from fieldworks.trust.events import ActionEventStore, ActionEventStoreConfig


def _store(tmp_path) -> ActionEventStore:
    return ActionEventStore(ActionEventStoreConfig(db_path=tmp_path / "events.db"))


def test_log_action_event_then_get_action_events_round_trip(tmp_path):
    store = _store(tmp_path)
    store.log_action_event(
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="Reduce chlorine dose",
        decision="approved",
        operator_id="alice",
        auth_method="user",
    )

    events = store.get_action_events()
    assert len(events) == 1
    assert events[0]["target"] == "Chlorine_01"
    assert events[0]["decision"] == "approved"


def test_get_action_events_filters_by_session_id(tmp_path):
    store = _store(tmp_path)
    store.log_action_event(
        session_id="s1",
        action_type="t",
        target="A",
        value="",
        description="",
        decision="approved",
        operator_id="shared-token",
        auth_method="shared_credential",
    )
    store.log_action_event(
        session_id="s2",
        action_type="t",
        target="B",
        value="",
        description="",
        decision="approved",
        operator_id="shared-token",
        auth_method="shared_credential",
    )

    events = store.get_action_events(session_id="s1")
    assert len(events) == 1
    assert events[0]["target"] == "A"


def test_approval_and_denial_produce_identical_record_shape(tmp_path):
    store = _store(tmp_path)
    store.log_action_event(
        session_id="s1",
        action_type="setpoint_adjustment",
        target="A",
        value="1.0",
        description="desc",
        decision="approved",
        operator_id="shared-token",
        auth_method="shared_credential",
    )
    store.log_action_event(
        session_id="s1",
        action_type="setpoint_adjustment",
        target="B",
        value="2.0",
        description="desc",
        decision="denied",
        operator_id="shared-token",
        auth_method="shared_credential",
    )

    events = store.get_action_events(session_id="s1")
    assert len(events) == 2
    approved, denied = events[1], events[0]  # most-recent-first: denied logged last
    assert set(approved.keys()) == set(denied.keys())
    assert all(v is not None for v in denied.values())


def test_get_action_events_orders_most_recent_first_and_respects_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.log_action_event(
            session_id="s1",
            action_type="t",
            target=f"target-{i}",
            value="",
            description="",
            decision="approved",
            operator_id="shared-token",
            auth_method="shared_credential",
        )

    events = store.get_action_events(limit=2)
    assert len(events) == 2
    assert events[0]["target"] == "target-4"
    assert events[1]["target"] == "target-3"


def test_constructor_creates_schema_file_without_prior_import_side_effect(tmp_path):
    db_path = tmp_path / "fresh.db"
    assert not db_path.exists()

    store = ActionEventStore(ActionEventStoreConfig(db_path=db_path))
    assert db_path.exists()
    assert store.get_action_events() == []


# ── auth_method and disposition (core#43, spec Part III) ─────────────────────

import sqlite3  # noqa: E402

import pytest  # noqa: E402

from fieldworks.trust import (  # noqa: E402
    Disposition,
    TrustMode,
    dispatch_approver,
    resolve_disposition,
)


def _log(store, **overrides):
    fields = dict(
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="Reduce chlorine dose",
        decision="approved",
        operator_id="shared-token",
        auth_method="shared_credential",
    )
    fields.update(overrides)
    store.log_action_event(**fields)


def test_auth_method_is_recorded(tmp_path):
    store = _store(tmp_path)
    _log(store)
    assert store.get_action_events()[0]["auth_method"] == "shared_credential"


def test_auto_approval_is_told_apart_from_an_operators(tmp_path):
    store = _store(tmp_path)
    _log(store)
    mode = TrustMode.COLLABORATIVE
    _log(
        store,
        **dispatch_approver(mode, resolve_disposition(mode, in_normal_range=True)),
    )
    auto, operator = store.get_action_events()
    assert (auto["decision"], auto["operator_id"], auto["auth_method"]) == (
        "auto_approved",
        "trust-mode:collaborative",
        "trust_mode",
    )
    assert (operator["decision"], operator["auth_method"]) == (
        "approved",
        "shared_credential",
    )


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"auth_method": "password"}, "auth_method 'password'"),
        ({"decision": "maybe"}, "decision 'maybe'"),
        ({"operator_id": ""}, "operator_id is required"),
        # A person's approval can't be filed under trust mode, or vice versa.
        (
            {"decision": "approved", "auth_method": "trust_mode"},
            "only auto_approved or recommended",
        ),
        ({"decision": "auto_approved"}, "comes from trust mode"),
        # Trust mode names itself, and only trust mode may.
        (
            {
                "decision": "auto_approved",
                "auth_method": "trust_mode",
                "operator_id": "operator_01",
            },
            "must be 'trust-mode:<mode>'",
        ),
        (
            {
                "decision": "auto_approved",
                "auth_method": "trust_mode",
                "operator_id": "trust-mode:yolo",
            },
            "unknown trust mode 'yolo'",
        ),
        ({"operator_id": "trust-mode:autonomous"}, "names trust mode"),
    ],
)
def test_dishonest_records_are_refused_before_writing(tmp_path, overrides, message):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match=message):
        _log(store, **overrides)
    assert store.get_action_events() == []


def test_omitting_auth_method_still_writes_but_warns(tmp_path):
    store = _store(tmp_path)
    with pytest.warns(DeprecationWarning, match="auth_method"):
        _log(store, auth_method=None, operator_id="operator_01")
    assert store.get_action_events()[0]["auth_method"] is None


def test_store_from_before_auth_method_gains_the_column(tmp_path):
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as c:
        c.execute("""CREATE TABLE action_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            session_id TEXT NOT NULL, action_type TEXT, target TEXT,
            value TEXT, description TEXT, operator_id TEXT NOT NULL,
            decision TEXT, outcome TEXT DEFAULT 'pending')""")
        c.execute("""INSERT INTO action_events
            (ts, session_id, operator_id, decision)
            VALUES ('2026-01-01', 's0', 'operator_01', 'approved')""")

    store = ActionEventStore(ActionEventStoreConfig(db_path=db_path))
    _log(store)
    new, old = store.get_action_events()
    assert new["auth_method"] == "shared_credential"
    assert (old["auth_method"], old["site_id"]) == (None, "")


def test_dispatch_approver_refuses_an_intercept():
    with pytest.raises(ValueError, match="decided by a person"):
        dispatch_approver(TrustMode.SUPERVISED, Disposition.INTERCEPT)


def test_advisory_records_a_recommendation():
    assert dispatch_approver(TrustMode.ADVISORY, Disposition.RECOMMEND_ONLY) == {
        "decision": "recommended",
        "operator_id": "trust-mode:advisory",
        "auth_method": "trust_mode",
    }
