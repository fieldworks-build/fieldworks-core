"""Tests for specialist prompt generation."""


def test_build_specialist_prompt_returns_string(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_prompt_contains_facility_name(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "Riverside Water Treatment Plant" in prompt


def test_prompt_contains_area_description(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "Raw Water Intake" in prompt


def test_prompt_contains_specialist_prompt_field(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "seasonal turbidity" in prompt


def test_prompt_contains_instance_names(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "Raw Water Pump 1" in prompt
    assert "Raw Water Pump 2" in prompt


def test_prompt_contains_normal_ranges(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "2.8" in prompt
    assert "4.2" in prompt


def test_prompt_contains_fault_modes(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "Bearing Wear" in prompt
    assert "Seal Failure" in prompt
    assert "WARNING" in prompt
    assert "CRITICAL" in prompt


def test_prompt_marks_writable_attribute(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "writable" in prompt


def test_prompt_extra_context_injected(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt(
        "intake", wtp_topology, extra_context="High turbidity season."
    )
    assert "High turbidity season." in prompt


def test_prompt_without_memory_client_unchanged(wtp_topology):
    """v0.1 callers that never pass memory_client see identical behavior."""
    from fieldworks.agents.specialist import build_specialist_prompt

    prompt = build_specialist_prompt("intake", wtp_topology)
    assert "Accumulated knowledge" not in prompt
    assert "Recent incident history" not in prompt


def test_prompt_memory_client_injects_context(wtp_topology, graph_client, tmp_path):
    from fieldworks.agents.specialist import build_specialist_prompt
    from fieldworks.memory.client import MemoryClient
    from fieldworks.memory.specialist import SpecialistMemory

    memory_client = MemoryClient(
        graph=graph_client,
        specialist_memory=SpecialistMemory(tmp_path / "specialist-memory"),
    )
    memory_client.specialist_memory.append(
        "intake", "Raw Water Pump 1 seal replaced 2026-05."
    )

    prompt = build_specialist_prompt(
        "intake", wtp_topology, memory_client=memory_client
    )
    assert "Raw Water Pump 1 seal replaced 2026-05." in prompt


def test_prompt_memory_client_no_data_omits_section(
    wtp_topology, graph_client, tmp_path
):
    from fieldworks.agents.specialist import build_specialist_prompt
    from fieldworks.memory.client import MemoryClient
    from fieldworks.memory.specialist import SpecialistMemory

    memory_client = MemoryClient(
        graph=graph_client,
        specialist_memory=SpecialistMemory(tmp_path / "specialist-memory"),
    )
    prompt = build_specialist_prompt(
        "intake", wtp_topology, memory_client=memory_client
    )
    assert "Accumulated knowledge" not in prompt


def test_build_specialists_one_per_area(wtp_topology):
    from fieldworks.agents.specialist import build_specialists

    specialists = build_specialists(wtp_topology)
    area_ids = {s["area_id"] for s in specialists}
    assert "intake" in area_ids
    assert "distribution" in area_ids
    assert len(specialists) == len(wtp_topology.process_areas)


def test_build_specialists_include_instance_ids(wtp_topology):
    from fieldworks.agents.specialist import build_specialists

    specialists = build_specialists(wtp_topology)
    intake = next(s for s in specialists if s["area_id"] == "intake")
    assert "raw_water_pump_1" in intake["instance_ids"]
    assert "raw_water_pump_2" in intake["instance_ids"]


def test_build_orchestrator_system(wtp_topology):
    from fieldworks.agents.specialist import (
        build_specialists,
        build_orchestrator_system,
    )

    specialists = build_specialists(wtp_topology)
    prompt = build_orchestrator_system(specialists, wtp_topology)
    assert "Cascade" in prompt
    assert "Riverside Water Treatment Plant" in prompt
    assert "Raw Water Intake" in prompt
    assert "Treated Water Distribution" in prompt


def test_unknown_area_id_raises(wtp_topology):
    from fieldworks.agents.specialist import build_specialist_prompt
    import pytest

    with pytest.raises(KeyError):
        build_specialist_prompt("nonexistent_area", wtp_topology)


def test_inferred_binding_noted_in_prompt(tmp_path):
    import yaml
    from fieldworks.topology.loader import load
    from fieldworks.agents.specialist import build_specialist_prompt

    data = {
        "facility": {"name": "Test Plant", "site_id": "t-01", "timezone": "UTC"},
        "process_areas": [{"id": "area_a", "name": "Area A", "description": "Test"}],
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
                    },
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
                    "pressure": {
                        "tag_id": "Plant/Pump1/Pressure",
                        "confidence": "inferred",
                    },
                },
            }
        ],
        "historian": {"default_lookback_hours": 24, "max_lookback_days": 90},
    }
    p = tmp_path / "topology.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    topology = load(p)
    prompt = build_specialist_prompt("area_a", topology)
    assert "inferred" in prompt


def test_uninstrumented_attribute_noted_in_prompt(tmp_path):
    import yaml
    from fieldworks.topology.loader import load
    from fieldworks.agents.specialist import build_specialist_prompt

    data = {
        "facility": {"name": "Test Plant", "site_id": "t-01", "timezone": "UTC"},
        "process_areas": [{"id": "area_a", "name": "Area A", "description": "Test"}],
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
                    },
                    {
                        "id": "vibration",
                        "name": "Vibration",
                        "units": "mm/s",
                        "normal_range": {"min": 0.0, "max": 4.5},
                    },
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
                    # vibration not bound
                },
            }
        ],
        "historian": {"default_lookback_hours": 24, "max_lookback_days": 90},
    }
    p = tmp_path / "topology.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    topology = load(p)
    prompt = build_specialist_prompt("area_a", topology)
    assert "NOT INSTRUMENTED" in prompt
