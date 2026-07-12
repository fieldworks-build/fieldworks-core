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
        operator_id="operator_01",
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
        operator_id="op",
    )
    store.log_action_event(
        session_id="s2",
        action_type="t",
        target="B",
        value="",
        description="",
        decision="approved",
        operator_id="op",
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
        operator_id="op",
    )
    store.log_action_event(
        session_id="s1",
        action_type="setpoint_adjustment",
        target="B",
        value="2.0",
        description="desc",
        decision="denied",
        operator_id="op",
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
            operator_id="op",
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
