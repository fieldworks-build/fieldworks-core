"""Tests for the soft topology validator."""

import yaml
from pathlib import Path


def write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "topology.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    return p


def test_valid_topology_no_warnings(wtp_topology):
    from fieldworks.topology.validator import validate
    result = validate(wtp_topology)
    assert result.valid
    assert result.warnings == []


def test_missing_tag_binding_produces_warning(tmp_path):
    from fieldworks.topology.loader import load
    from fieldworks.topology.validator import validate

    data = {
        "facility": {"name": "Test", "site_id": "t-01", "timezone": "UTC"},
        "process_areas": [{"id": "area_a", "name": "A", "description": "Test"}],
        "equipment_types": [
            {
                "id": "pump",
                "name": "Pump",
                "description": "A pump.",
                "attributes": [
                    {"id": "pressure", "name": "Pressure", "units": "bar",
                     "normal_range": {"min": 1.0, "max": 5.0}},
                    {"id": "temp", "name": "Temperature", "units": "degC",
                     "normal_range": {"min": 10.0, "max": 80.0}},
                ],
                "fault_modes": [],
            }
        ],
        "equipment_instances": [
            {
                "id": "pump_1",
                "name": "Pump 1",
                "type_id": "pump",
                "process_area_id": "area_a",
                "tag_bindings": {
                    "pressure": "Plant/Pump1/Pressure",
                    # temp intentionally omitted
                },
            }
        ],
        "historian": {"default_lookback_hours": 24, "max_lookback_days": 90},
    }
    p = write_yaml(tmp_path, data)
    topology = load(p)
    result = validate(topology)
    assert result.valid  # warnings don't make it invalid
    assert len(result.warnings) == 1
    assert "temp" in result.warnings[0]
    assert "pump_1" in result.warnings[0]


def test_historian_source_valid(wtp_topology):
    from fieldworks.topology.validator import validate
    result = validate(wtp_topology, aggregator_server_names={"mqtt_intake", "influxdb"})
    assert result.valid


def test_historian_source_unknown_server(tmp_path):
    from fieldworks.topology.loader import load
    from fieldworks.topology.validator import validate

    data = {
        "facility": {"name": "Test", "site_id": "t-01", "timezone": "UTC"},
        "process_areas": [{"id": "area_a", "name": "A", "description": "Test"}],
        "equipment_types": [
            {
                "id": "pump",
                "name": "Pump",
                "description": "A pump.",
                "attributes": [
                    {"id": "pressure", "name": "Pressure", "units": "bar",
                     "normal_range": {"min": 1.0, "max": 5.0}},
                ],
                "fault_modes": [],
            }
        ],
        "equipment_instances": [
            {
                "id": "pump_1",
                "name": "Pump 1",
                "type_id": "pump",
                "process_area_id": "area_a",
                "tag_bindings": {"pressure": "Plant/Pump1/Pressure"},
            }
        ],
        "historian": {
            "default_lookback_hours": 24,
            "max_lookback_days": 90,
            "source": "my_historian",
        },
    }
    p = write_yaml(tmp_path, data)
    topology = load(p)
    result = validate(topology, aggregator_server_names={"mqtt_intake", "influxdb"})
    assert not result.valid
    assert any("my_historian" in e for e in result.errors)


def test_no_aggregator_skips_historian_check(tmp_path):
    """Without aggregator_server_names, historian.source is not validated."""
    from fieldworks.topology.loader import load
    from fieldworks.topology.validator import validate

    data = {
        "facility": {"name": "Test", "site_id": "t-01", "timezone": "UTC"},
        "process_areas": [{"id": "area_a", "name": "A", "description": "Test"}],
        "equipment_types": [
            {
                "id": "pump",
                "name": "Pump",
                "description": "A pump.",
                "attributes": [
                    {"id": "pressure", "name": "Pressure", "units": "bar",
                     "normal_range": {"min": 1.0, "max": 5.0}},
                ],
                "fault_modes": [],
            }
        ],
        "equipment_instances": [
            {
                "id": "pump_1",
                "name": "Pump 1",
                "type_id": "pump",
                "process_area_id": "area_a",
                "tag_bindings": {"pressure": "Plant/Pump1/Pressure"},
            }
        ],
        "historian": {
            "default_lookback_hours": 24,
            "max_lookback_days": 90,
            "source": "nonexistent_server",
        },
    }
    p = write_yaml(tmp_path, data)
    topology = load(p)
    result = validate(topology)  # no aggregator_server_names
    assert result.valid
    assert result.errors == []
