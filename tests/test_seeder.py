"""Tests for seeding a fresh LadybugDB from a validated TopologyConfig."""


def test_seed_topology_counts(graph_client, wtp_topology):
    from fieldworks.topology.seeder import seed_topology

    counts = seed_topology(wtp_topology, graph_client)
    assert counts["facility"] == 1
    assert counts["process_areas"] == len(wtp_topology.process_areas)
    assert counts["equipment_types"] == len(wtp_topology.equipment_types)
    assert counts["equipment_instances"] == len(wtp_topology.equipment_instances)
    expected_bindings = sum(
        len(inst.tag_bindings) for inst in wtp_topology.equipment_instances
    )
    assert counts["tag_bindings"] == expected_bindings


def test_seed_topology_facility_queryable(graph_client, wtp_topology):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)
    rows = graph_client.query_graph(
        "MATCH (f:Facility) RETURN f.id AS id, f.name AS name"
    )
    assert len(rows) == 1
    assert rows[0]["id"] == wtp_topology.facility.site_id
    assert rows[0]["name"] == wtp_topology.facility.name


def test_seed_topology_attributes_namespaced_across_types(graph_client, wtp_topology):
    """Two equipment types can each define an attribute with the same short id
    (e.g. both reuse 'vibration') without a primary-key collision."""
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)
    rows = graph_client.query_graph("MATCH (a:Attribute) RETURN count(a) AS c")
    expected = sum(len(et.attributes) for et in wtp_topology.equipment_types)
    assert rows[0]["c"] == expected


def test_seed_topology_specialist_context_round_trip(graph_client, wtp_topology):
    """Seeded data should be queryable through the existing specialist-context path."""
    from fieldworks.memory.graph import aggregate_specialist_query
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)
    area_id = wtp_topology.process_areas[0].id
    rows = graph_client.get_specialist_context(area_id)
    ctx = aggregate_specialist_query(rows)
    assert ctx["area"] == wtp_topology.get_process_area(area_id).name
    assert len(ctx["equipment"]) == len(wtp_topology.instances_in_area(area_id))


def test_seed_topology_writable_attribute_flagged(graph_client, wtp_topology):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)
    writable = graph_client.get_writable_attributes()
    assert len(writable) > 0
