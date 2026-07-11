"""Tests for fieldworks.topology_builder.discovery against a fake stdio MCP adapter."""

import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

FAKE_ADAPTER = Path(__file__).parent / "fixtures" / "fake_adapter.py"


@pytest.mark.anyio
async def test_crawl_mqtt_returns_topic_names():
    from fieldworks.topology_builder.discovery import crawl_mqtt

    params = StdioServerParameters(
        command=sys.executable, args=[str(FAKE_ADAPTER), "conformant"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            topics = await crawl_mqtt(session)

    assert "Plant/WTP/Pump/RawWater_01/Flow" in topics
    assert "Plant/WTP/Pump/RawWater_01/Running" in topics


@pytest.mark.anyio
async def test_crawl_opcua_flattens_tree_to_leaf_paths():
    from fieldworks.topology_builder.discovery import crawl_opcua

    params = StdioServerParameters(
        command=sys.executable, args=[str(FAKE_ADAPTER), "conformant"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            nodes = await crawl_opcua(session)

    assert "Plant/Pump/Flow" in nodes
    assert "Plant/Pump/Running" in nodes
    # Internal (non-leaf) nodes shouldn't appear on their own.
    assert "Plant" not in nodes
    assert "Plant/Pump" not in nodes


@pytest.mark.anyio
async def test_crawl_mqtt_and_opcua_feed_infer_topology():
    """End-to-end: crawl (via fake adapter) -> infer_topology, using the real
    water-treatment-municipal template, proving the shapes are compatible."""
    from fieldworks.topology_builder.discovery import crawl_mqtt
    from fieldworks.topology_builder.inference import infer_topology, load_template

    template_path = (
        Path(__file__).parent.parent
        / "examples"
        / "waterworks"
        / "topology_builder"
        / "water-treatment-municipal.yaml"
    )
    template = load_template(template_path)

    params = StdioServerParameters(
        command=sys.executable, args=[str(FAKE_ADAPTER), "conformant"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            topics = await crawl_mqtt(session)

    results = infer_topology(topics, [], template)
    assert any(r["instance_id"] == "RawWater_01" for r in results)


@pytest.mark.anyio
async def test_discovered_instances_seed_into_graph(graph_client):
    """Full pipeline: crawl -> infer_topology -> GraphClient.seed_discovered_topology.
    infer_topology's instance shape (instance_id/ladybug_type_id/area_id/
    confidence_level/attributes[...]['tag']) was already designed to match
    seed_discovered_topology's expected input (M3) — this proves it end to end
    rather than just asserting the two shapes match on paper.
    """
    from fieldworks.topology_builder.discovery import crawl_mqtt
    from fieldworks.topology_builder.inference import infer_topology, load_template

    template_path = (
        Path(__file__).parent.parent
        / "examples"
        / "waterworks"
        / "topology_builder"
        / "water-treatment-municipal.yaml"
    )
    template = load_template(template_path)

    params = StdioServerParameters(
        command=sys.executable, args=[str(FAKE_ADAPTER), "conformant"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            topics = await crawl_mqtt(session)

    instances = infer_topology(topics, [], template)
    result = graph_client.seed_discovered_topology(
        facility_id="test-facility", facility_name="Test Facility", instances=instances
    )
    assert result["seeded_count"] == len(instances)
    assert result["errors"] == 0

    rows = graph_client.query_graph("MATCH (e:Equipment) RETURN e.id AS id")
    assert {r["id"] for r in rows} == {i["instance_id"] for i in instances}
