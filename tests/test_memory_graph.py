"""Tests for the LadybugDB graph client."""

import pytest


def test_schema_creates_empty_facility_table(graph_client):
    result = graph_client.query_graph("MATCH (n:Facility) RETURN count(n) AS c")
    assert result[0]["c"] == 0


def test_schema_does_not_seed_topology_data(graph_client):
    assert graph_client.get_topology() == []


def test_record_and_retrieve_incident(graph_client, wtp_seed_path):
    graph_client.load_cypher_file(wtp_seed_path)

    incident_id = graph_client.record_incident(
        session_id="s1",
        equipment_id="RawWater_01",
        diagnosis="Suction starvation suspected.",
        confidence=0.8,
        status="anomaly_detected",
        fault_mode_id="pump_suction_starvation",
    )
    assert incident_id

    history = graph_client.get_equipment_history("RawWater_01")
    assert len(history["incidents"]) == 1
    assert history["incidents"][0]["diagnosis"] == "Suction starvation suspected."
    assert history["incidents"][0]["fault_mode"] == "Suction Starvation"


def test_record_observation(graph_client, wtp_seed_path):
    graph_client.load_cypher_file(wtp_seed_path)

    graph_client.record_observation(
        session_id="s1",
        equipment_id="UV_01",
        text="Lamp hours approaching threshold.",
        confidence=0.9,
        specialist="treatment",
    )
    history = graph_client.get_equipment_history("UV_01")
    assert len(history["observations"]) == 1
    assert history["observations"][0]["text"] == "Lamp hours approaching threshold."


def test_link_incident_precedes(graph_client, wtp_seed_path):
    graph_client.load_cypher_file(wtp_seed_path)

    a = graph_client.record_incident(
        "s1", "RawWater_01", "Cavitation.", 0.7, "fault_detected"
    )
    b = graph_client.record_incident(
        "s1", "RawWater_01", "Bearing wear.", 0.6, "fault_detected"
    )
    graph_client.link_incident_precedes(a, b, hours_apart=6.5)

    rows = graph_client.query_graph(
        "MATCH (a:Incident {id: $a})-[p:PRECEDES]->(b:Incident {id: $b})"
        " RETURN p.hours_apart AS hours_apart",
        {"a": a, "b": b},
    )
    assert rows[0]["hours_apart"] == 6.5


def test_query_graph_rejects_write_keywords(graph_client):
    with pytest.raises(ValueError):
        graph_client.query_graph("CREATE (:Facility {id: 'x'})")


def test_query_graph_accepts_parameters(graph_client, wtp_seed_path):
    graph_client.load_cypher_file(wtp_seed_path)
    rows = graph_client.query_graph(
        "MATCH (e:Equipment {id: $id}) RETURN e.name AS name", {"id": "RawWater_01"}
    )
    assert rows[0]["name"] == "Raw Water Pump 1"


def test_get_writable_attributes(graph_client, wtp_seed_path):
    graph_client.load_cypher_file(wtp_seed_path)
    writable = graph_client.get_writable_attributes()
    assert any(a["attribute"] == "Setpoint" for a in writable)


def test_aggregate_specialist_query_dedups_fault_modes():
    from fieldworks.memory.graph import aggregate_specialist_query

    rows = [
        {
            "process_area": "Raw Water Intake",
            "area_context": "context",
            "equipment": "RawWater_01",
            "equipment_notes": "",
            "equipment_type": "Centrifugal Pump",
            "attribute": "Flow",
            "units": "L/min",
            "normal_min": 180.0,
            "normal_max": 350.0,
            "tag_id": "Plant/WTP/Pump/RawWater_01/Flow",
            "binding_confidence": "verified",
            "fault_mode": "Cavitation",
            "fault_severity": "warning",
            "fault_description": "desc",
        },
        {
            "process_area": "Raw Water Intake",
            "area_context": "context",
            "equipment": "RawWater_01",
            "equipment_notes": "",
            "equipment_type": "Centrifugal Pump",
            "attribute": "Pressure",
            "units": "bar",
            "normal_min": 3.5,
            "normal_max": 8.5,
            "tag_id": "Plant/WTP/Pump/RawWater_01/Pressure",
            "binding_confidence": "verified",
            "fault_mode": "Cavitation",
            "fault_severity": "warning",
            "fault_description": "desc",
        },
    ]
    result = aggregate_specialist_query(rows)
    assert len(result["equipment"]) == 1
    assert len(result["equipment"][0]["fault_modes"]) == 1
    assert len(result["equipment"][0]["attributes"]) == 2


def test_get_specialist_context_via_seed(seeded_graph_client):
    rows = seeded_graph_client.get_specialist_context("intake")

    from fieldworks.memory.graph import aggregate_specialist_query

    ctx = aggregate_specialist_query(rows)
    assert ctx["area"] == "Raw Water Intake"
    assert len(ctx["equipment"]) == 2


def test_seed_produces_expected_topology(seeded_graph_client):
    topology = seeded_graph_client.get_topology()
    equipment_ids = {row["equipment"] for row in topology}
    assert equipment_ids == {
        "RawWater_01",
        "RawWater_02",
        "HighService_01",
        "HighService_02",
        "UV_01",
        "UV_02",
        "Chlorine_01",
        "Fluoride_01",
        "Clarifier_01",
        "FinishedWater_01",
    }
