"""Tests for the MemoryClient facade (graph + specialist memory)."""


def _make_client(graph_client, tmp_path):
    from fieldworks.memory.client import MemoryClient
    from fieldworks.memory.specialist import SpecialistMemory

    return MemoryClient(
        graph=graph_client,
        specialist_memory=SpecialistMemory(tmp_path / "specialist-memory"),
    )


def test_get_context_empty_when_nothing_recorded(graph_client, wtp_topology, tmp_path):
    client = _make_client(graph_client, tmp_path)
    area_id = wtp_topology.process_areas[0].id
    instance_ids = [i.id for i in wtp_topology.instances_in_area(area_id)]

    assert client.get_context(area_id, instance_ids) == ""


def test_get_context_includes_specialist_memory(graph_client, wtp_topology, tmp_path):
    client = _make_client(graph_client, tmp_path)
    area_id = wtp_topology.process_areas[0].id
    client.specialist_memory.append(area_id, "Pump 1 runs hot in summer.")

    context = client.get_context(area_id, [])
    assert "Pump 1 runs hot in summer." in context


def test_get_context_includes_recent_incidents(graph_client, wtp_topology, tmp_path):
    from fieldworks.topology.seeder import seed_topology

    seed_topology(wtp_topology, graph_client)
    client = _make_client(graph_client, tmp_path)
    area_id = wtp_topology.process_areas[0].id
    instance_id = wtp_topology.instances_in_area(area_id)[0].id

    graph_client.record_incident(
        session_id="s1",
        equipment_id=instance_id,
        diagnosis="Bearing vibration trending upward.",
        confidence=0.8,
        status="anomaly_detected",
    )

    context = client.get_context(area_id, [instance_id])
    assert "Bearing vibration trending upward." in context
    assert instance_id in context
