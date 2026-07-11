"""Tests for GraphClient.get_severity_for_attribute — runtime severity lookup
replacing static topology.yaml alarm_lo/alarm_hi config (fieldworks-core#6)."""


def test_severity_picks_highest_tier_across_multiple_fault_modes(
    graph_client, wtp_topology
):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)

    # motor_current is affected by bearing_wear (warning), cavitation (warning),
    # AND seal_failure (critical) — critical must win.
    severity = graph_client.get_severity_for_attribute(
        "centrifugal_pump", "motor_current"
    )
    assert severity == "critical"


def test_severity_single_fault_mode(graph_client, wtp_topology):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)

    # bearing_temp is only affected by bearing_wear (warning).
    severity = graph_client.get_severity_for_attribute(
        "centrifugal_pump", "bearing_temp"
    )
    assert severity == "warning"


def test_severity_none_when_no_fault_mode_affects_attribute(graph_client, wtp_topology):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)

    # speed_setpoint isn't listed in any fault mode's affected_attributes.
    severity = graph_client.get_severity_for_attribute(
        "centrifugal_pump", "speed_setpoint"
    )
    assert severity is None


def test_severity_none_for_unknown_type(graph_client, wtp_topology):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)

    severity = graph_client.get_severity_for_attribute("nonexistent_type", "flow")
    assert severity is None


# ── Directional severity (fieldworks-core#6 follow-up) ──────────────────────
# Real alarm config is often asymmetric: a pump running low on flow (cavitation
# risk) may be critical while running high is merely advisory.


def _asymmetric_topology(tmp_path):
    import yaml

    from fieldworks.topology.loader import load

    data = {
        "facility": {"name": "Test Plant", "site_id": "t-01", "timezone": "UTC"},
        "process_areas": [{"id": "area_a", "name": "Area A", "description": "Test"}],
        "historian": {"default_lookback_hours": 24, "max_lookback_days": 90},
        "equipment_types": [
            {
                "id": "pump",
                "name": "Pump",
                "description": "A pump.",
                "attributes": [
                    {
                        "id": "flow",
                        "name": "Flow",
                        "units": "L/min",
                        "normal_range": {"min": 200, "max": 450},
                    }
                ],
                "fault_modes": [
                    {
                        "id": "low_flow",
                        "name": "Low Flow",
                        "description": "Cavitation risk",
                        "severity": "critical",
                        "direction": "below_min",
                        "affected_attributes": ["flow"],
                    },
                    {
                        "id": "high_flow",
                        "name": "High Flow",
                        "description": "Minor over-delivery",
                        "severity": "advisory",
                        "direction": "above_max",
                        "affected_attributes": ["flow"],
                    },
                ],
            }
        ],
        "equipment_instances": [
            {
                "id": "pump_1",
                "name": "Pump 1",
                "type_id": "pump",
                "process_area_id": "area_a",
                "tag_bindings": {"flow": "Plant/Pump1/Flow"},
            }
        ],
    }
    p = tmp_path / "topology.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    return load(p)


def test_no_condition_considers_both_directions(graph_client, tmp_path):
    from fieldworks.topology.seeder import seed_topology

    topology = _asymmetric_topology(tmp_path)
    seed_topology(topology, graph_client)

    fault = topology.get_equipment_type("pump").fault_modes[0]
    assert fault.direction == "below_min"  # explicit value preserved

    # No condition given — considers both fault modes, critical wins.
    severity = graph_client.get_severity_for_attribute("pump", "flow")
    assert severity == "critical"


def test_direction_filters_below_min(graph_client, tmp_path):
    from fieldworks.topology.seeder import seed_topology

    topology = _asymmetric_topology(tmp_path)
    seed_topology(topology, graph_client)

    severity = graph_client.get_severity_for_attribute(
        "pump", "flow", condition="below_min"
    )
    assert severity == "critical"


def test_direction_filters_above_max(graph_client, tmp_path):
    from fieldworks.topology.seeder import seed_topology

    topology = _asymmetric_topology(tmp_path)
    seed_topology(topology, graph_client)

    severity = graph_client.get_severity_for_attribute(
        "pump", "flow", condition="above_max"
    )
    assert severity == "advisory"
