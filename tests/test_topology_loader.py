"""Tests for topology loader and schema validation."""

import textwrap
from pathlib import Path

import pytest
import yaml


def write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "topology.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    return p


def base_topology() -> dict:
    return {
        "facility": {
            "name": "Test Plant",
            "site_id": "test-01",
            "timezone": "UTC",
        },
        "process_areas": [
            {"id": "area_a", "name": "Area A", "description": "Test area"},
        ],
        "equipment_types": [
            {
                "id": "pump",
                "name": "Pump",
                "description": "A pump.",
                "attributes": [
                    {
                        "id": "pressure",
                        "name": "Pressure",
                        "units": "bar",
                        "normal_range": {"min": 1.0, "max": 5.0},
                    }
                ],
                "fault_modes": [
                    {
                        "id": "leak",
                        "name": "Leak",
                        "description": "Pressure drops suddenly.",
                        "severity": "critical",
                        "affected_attributes": ["pressure"],
                    }
                ],
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
        },
    }


def test_load_valid_fixture(wtp_topology):
    from fieldworks.topology.schema import TopologyConfig
    assert isinstance(wtp_topology, TopologyConfig)
    assert wtp_topology.facility.name == "Riverside Water Treatment Plant"
    assert wtp_topology.facility.site_id == "wtp-riverside-01"


def test_load_process_areas(wtp_topology):
    area_ids = {pa.id for pa in wtp_topology.process_areas}
    assert "intake" in area_ids
    assert "distribution" in area_ids


def test_load_equipment_types(wtp_topology):
    assert len(wtp_topology.equipment_types) == 1
    pump = wtp_topology.equipment_types[0]
    assert pump.id == "centrifugal_pump"
    attr_ids = {a.id for a in pump.attributes}
    assert "discharge_pressure" in attr_ids
    assert "vibration" in attr_ids


def test_load_fault_modes(wtp_topology):
    pump = wtp_topology.equipment_types[0]
    fm_ids = {fm.id for fm in pump.fault_modes}
    assert "bearing_wear" in fm_ids
    assert "seal_failure" in fm_ids
    seal = next(fm for fm in pump.fault_modes if fm.id == "seal_failure")
    assert seal.severity == "critical"


def test_load_instances(wtp_topology):
    assert len(wtp_topology.equipment_instances) == 3
    inst = wtp_topology.equipment_instances[0]
    assert inst.type_id == "centrifugal_pump"
    assert "discharge_pressure" in inst.tag_bindings


def test_tag_binding_string_coerced_to_binding(wtp_topology):
    from fieldworks.topology.schema import TagBinding
    inst = wtp_topology.equipment_instances[0]
    binding = inst.tag_bindings["discharge_pressure"]
    assert isinstance(binding, TagBinding)
    assert binding.confidence == "verified"
    assert "DischargePressure" in binding.tag_id


def test_load_historian(wtp_topology):
    assert wtp_topology.historian.default_lookback_hours == 24
    assert wtp_topology.historian.max_lookback_days == 90


def test_load_file_not_found():
    from fieldworks.topology.loader import load
    with pytest.raises(FileNotFoundError):
        load("/nonexistent/path/topology.yaml")


def test_load_not_a_mapping(tmp_path):
    from fieldworks.topology.loader import load
    p = tmp_path / "bad.yaml"
    p.write_text("- just a list\n")
    with pytest.raises(ValueError, match="mapping"):
        load(p)


def test_load_missing_required_field(tmp_path):
    from fieldworks.topology.loader import load
    data = base_topology()
    del data["facility"]["timezone"]
    p = write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="Invalid topology"):
        load(p)


def test_load_unknown_type_id(tmp_path):
    from fieldworks.topology.loader import load
    data = base_topology()
    data["equipment_instances"][0]["type_id"] = "nonexistent_type"
    p = write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="unknown type_id"):
        load(p)


def test_load_unknown_process_area_id(tmp_path):
    from fieldworks.topology.loader import load
    data = base_topology()
    data["equipment_instances"][0]["process_area_id"] = "nonexistent_area"
    p = write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="unknown process_area_id"):
        load(p)


def test_load_invalid_fault_severity(tmp_path):
    from fieldworks.topology.loader import load
    data = base_topology()
    data["equipment_types"][0]["fault_modes"][0]["severity"] = "extreme"
    p = write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="Invalid topology"):
        load(p)


def test_load_fault_references_unknown_attribute(tmp_path):
    from fieldworks.topology.loader import load
    data = base_topology()
    data["equipment_types"][0]["fault_modes"][0]["affected_attributes"] = ["no_such_attr"]
    p = write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="unknown attribute"):
        load(p)


def test_load_normal_range_min_gte_max(tmp_path):
    from fieldworks.topology.loader import load
    data = base_topology()
    data["equipment_types"][0]["attributes"][0]["normal_range"] = {"min": 5.0, "max": 1.0}
    p = write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="Invalid topology"):
        load(p)


def test_convenience_lookup_get_equipment_type(wtp_topology):
    pump = wtp_topology.get_equipment_type("centrifugal_pump")
    assert pump.name == "Centrifugal Pump"


def test_convenience_lookup_get_process_area(wtp_topology):
    area = wtp_topology.get_process_area("intake")
    assert area.name == "Raw Water Intake"


def test_convenience_lookup_instances_in_area(wtp_topology):
    intake = wtp_topology.instances_in_area("intake")
    assert len(intake) == 2
    ids = {i.id for i in intake}
    assert "raw_water_pump_1" in ids
    assert "raw_water_pump_2" in ids
