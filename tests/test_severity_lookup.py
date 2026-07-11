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
