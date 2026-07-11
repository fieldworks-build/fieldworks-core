"""Tests for AttributeDef's boolean/discrete data_type (fieldworks-core#15).

SCADA points are routinely boolean (run/stop feedback) or discrete
(multi-state selectors), not just continuous numeric ranges.
"""

import pytest
import yaml

_BASE = {
    "facility": {"name": "Test Plant", "site_id": "t-01", "timezone": "UTC"},
    "process_areas": [{"id": "area_a", "name": "Area A", "description": "Test"}],
    "historian": {"default_lookback_hours": 24, "max_lookback_days": 90},
}


def _topology_with_attribute(attr: dict, tmp_path):
    from fieldworks.topology.loader import load

    data = {
        **_BASE,
        "equipment_types": [
            {
                "id": "pump",
                "name": "Pump",
                "description": "A pump.",
                "attributes": [attr],
                "fault_modes": [],
            }
        ],
        "equipment_instances": [
            {
                "id": "pump_1",
                "name": "Pump 1",
                "type_id": "pump",
                "process_area_id": "area_a",
                "tag_bindings": {attr["id"]: "Plant/Pump1/" + attr["name"]},
            }
        ],
    }
    p = tmp_path / "topology.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    return load(p)


# ── Schema validation ────────────────────────────────────────────────────────


def test_numeric_defaults_and_requires_normal_range(tmp_path):
    with pytest.raises(ValueError, match="normal_range"):
        _topology_with_attribute(
            {"id": "flow", "name": "Flow", "units": "L/min", "data_type": "numeric"},
            tmp_path,
        )


def test_boolean_requires_normal_state(tmp_path):
    with pytest.raises(ValueError, match="normal_state"):
        _topology_with_attribute(
            {"id": "running", "name": "Running", "units": "", "data_type": "boolean"},
            tmp_path,
        )


def test_boolean_valid(tmp_path):
    topology = _topology_with_attribute(
        {
            "id": "running",
            "name": "Running",
            "units": "",
            "data_type": "boolean",
            "normal_state": True,
        },
        tmp_path,
    )
    attr = topology.get_equipment_type("pump").attributes[0]
    assert attr.data_type == "boolean"
    assert attr.normal_state is True


def test_discrete_requires_allowed_values(tmp_path):
    with pytest.raises(ValueError, match="allowed_values"):
        _topology_with_attribute(
            {
                "id": "mode",
                "name": "Mode",
                "units": "",
                "data_type": "discrete",
                "normal_values": ["AUTO"],
            },
            tmp_path,
        )


def test_discrete_requires_normal_values(tmp_path):
    with pytest.raises(ValueError, match="normal_values"):
        _topology_with_attribute(
            {
                "id": "mode",
                "name": "Mode",
                "units": "",
                "data_type": "discrete",
                "allowed_values": ["AUTO", "MANUAL", "FAULTED"],
            },
            tmp_path,
        )


def test_discrete_normal_values_must_be_subset_of_allowed(tmp_path):
    with pytest.raises(ValueError, match="not in allowed_values"):
        _topology_with_attribute(
            {
                "id": "mode",
                "name": "Mode",
                "units": "",
                "data_type": "discrete",
                "allowed_values": ["AUTO", "MANUAL"],
                "normal_values": ["AUTO", "FAULTED"],
            },
            tmp_path,
        )


def test_discrete_valid(tmp_path):
    topology = _topology_with_attribute(
        {
            "id": "mode",
            "name": "Mode",
            "units": "",
            "data_type": "discrete",
            "allowed_values": ["AUTO", "MANUAL", "FAULTED"],
            "normal_values": ["AUTO", "MANUAL"],
        },
        tmp_path,
    )
    attr = topology.get_equipment_type("pump").attributes[0]
    assert attr.allowed_values == ["AUTO", "MANUAL", "FAULTED"]
    assert attr.normal_values == ["AUTO", "MANUAL"]


# ── Specialist prompt rendering ──────────────────────────────────────────────


def test_prompt_renders_boolean_normal_state(tmp_path):
    from fieldworks.agents.specialist import build_specialist_prompt

    topology = _topology_with_attribute(
        {
            "id": "running",
            "name": "Running",
            "units": "",
            "data_type": "boolean",
            "normal_state": True,
        },
        tmp_path,
    )
    prompt = build_specialist_prompt("area_a", topology)
    assert "normal state: true" in prompt
    # No empty parens when units is "".
    assert "Running ()" not in prompt


def test_prompt_renders_discrete_normal_values(tmp_path):
    from fieldworks.agents.specialist import build_specialist_prompt

    topology = _topology_with_attribute(
        {
            "id": "mode",
            "name": "Mode",
            "units": "",
            "data_type": "discrete",
            "allowed_values": ["AUTO", "MANUAL", "FAULTED"],
            "normal_values": ["AUTO", "MANUAL"],
        },
        tmp_path,
    )
    prompt = build_specialist_prompt("area_a", topology)
    assert "normal state(s): AUTO, MANUAL" in prompt
    assert "allowed: AUTO, MANUAL, FAULTED" in prompt


def test_prompt_still_renders_numeric_normal_range(tmp_path):
    from fieldworks.agents.specialist import build_specialist_prompt

    topology = _topology_with_attribute(
        {
            "id": "flow",
            "name": "Flow",
            "units": "L/min",
            "normal_range": {"min": 200, "max": 450},
        },
        tmp_path,
    )
    prompt = build_specialist_prompt("area_a", topology)
    assert "normal 200.0–450.0" in prompt


# ── Graph seed + read round-trip ─────────────────────────────────────────────


def test_boolean_attribute_round_trips_through_graph(tmp_path, graph_client):
    from fieldworks.memory.graph import aggregate_specialist_query
    from fieldworks.topology.seeder import seed_topology

    topology = _topology_with_attribute(
        {
            "id": "running",
            "name": "Running",
            "units": "",
            "data_type": "boolean",
            "normal_state": True,
        },
        tmp_path,
    )
    seed_topology(topology, graph_client)
    rows = graph_client.get_specialist_context("area_a")
    ctx = aggregate_specialist_query(rows)
    attr = ctx["equipment"][0]["attributes"]["Running"]
    assert attr["data_type"] == "boolean"
    assert attr["normal_state"] is True


def test_discrete_attribute_round_trips_through_graph(tmp_path, graph_client):
    from fieldworks.memory.graph import aggregate_specialist_query
    from fieldworks.topology.seeder import seed_topology

    topology = _topology_with_attribute(
        {
            "id": "mode",
            "name": "Mode",
            "units": "",
            "data_type": "discrete",
            "allowed_values": ["AUTO", "MANUAL", "FAULTED"],
            "normal_values": ["AUTO", "MANUAL"],
        },
        tmp_path,
    )
    seed_topology(topology, graph_client)
    rows = graph_client.get_specialist_context("area_a")
    ctx = aggregate_specialist_query(rows)
    attr = ctx["equipment"][0]["attributes"]["Mode"]
    assert attr["allowed_values"] == ["AUTO", "MANUAL", "FAULTED"]
    assert attr["normal_values"] == ["AUTO", "MANUAL"]
