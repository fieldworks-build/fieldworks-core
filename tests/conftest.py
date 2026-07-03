"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def wtp_topology_path() -> Path:
    return FIXTURES / "wtp_topology.yaml"


@pytest.fixture
def wtp_aggregator_path() -> Path:
    return FIXTURES / "wtp_aggregator.json"


@pytest.fixture
def wtp_topology(wtp_topology_path):
    from fieldworks.topology.loader import load

    return load(wtp_topology_path)


@pytest.fixture
def wtp_aggregator(wtp_aggregator_path):
    from fieldworks.aggregator.config import load_aggregator_config

    return load_aggregator_config(wtp_aggregator_path)


@pytest.fixture
def wtp_seed_path() -> Path:
    return (
        Path(__file__).parent.parent / "examples" / "waterworks" / "schema_seed.cypher"
    )


@pytest.fixture
def graph_client(tmp_path):
    from fieldworks.memory.graph import GraphClient, GraphConfig

    return GraphClient(GraphConfig(db_path=tmp_path / "graph.db"))


@pytest.fixture
def seeded_graph_client(tmp_path, wtp_seed_path):
    from fieldworks.memory.graph import GraphClient, GraphConfig

    client = GraphClient(GraphConfig(db_path=tmp_path / "graph.db"))
    client.load_cypher_file(wtp_seed_path)
    return client
