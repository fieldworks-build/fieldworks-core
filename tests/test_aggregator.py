"""Tests for aggregator config loader."""

import json
from pathlib import Path

import pytest


def test_load_valid_aggregator(wtp_aggregator):
    from fieldworks.aggregator.config import AggregatorConfig

    assert isinstance(wtp_aggregator, AggregatorConfig)
    assert len(wtp_aggregator.servers) == 3


def test_aggregator_server_names(wtp_aggregator):
    names = wtp_aggregator.server_names()
    assert "mqtt_intake" in names
    assert "mqtt_distribution" in names
    assert "influxdb" in names


def test_aggregator_get_server(wtp_aggregator):
    server = wtp_aggregator.get_server("mqtt_intake")
    assert server.url == "http://localhost:8001/sse"
    assert "read_tag" in server.include_tools


def test_aggregator_get_server_missing(wtp_aggregator):
    with pytest.raises(KeyError):
        wtp_aggregator.get_server("nonexistent")


def test_aggregator_default_args(wtp_aggregator):
    server = wtp_aggregator.get_server("mqtt_intake")
    assert server.default_args == {"topic_filter": "Plant/WTP/Pump/RawWater_*"}


def test_aggregator_default_timeout(wtp_aggregator):
    server = wtp_aggregator.get_server("influxdb")
    assert server.timeout_ms == 5000


def test_load_file_not_found():
    from fieldworks.aggregator.config import load_aggregator_config

    with pytest.raises(FileNotFoundError):
        load_aggregator_config("/nonexistent/aggregator.json")


def test_load_not_an_array(tmp_path):
    from fieldworks.aggregator.config import load_aggregator_config

    p = tmp_path / "agg.json"
    p.write_text(json.dumps({"servers": []}))
    with pytest.raises(ValueError, match="array"):
        load_aggregator_config(p)


def test_load_missing_required_field(tmp_path):
    from fieldworks.aggregator.config import load_aggregator_config

    p = tmp_path / "agg.json"
    p.write_text(json.dumps([{"name": "mqtt"}]))  # missing url
    with pytest.raises(ValueError, match="Invalid aggregator"):
        load_aggregator_config(p)


def test_load_minimal_server(tmp_path):
    from fieldworks.aggregator.config import load_aggregator_config

    p = tmp_path / "agg.json"
    p.write_text(json.dumps([{"name": "mqtt", "url": "http://localhost:8001/sse"}]))
    config = load_aggregator_config(p)
    assert len(config.servers) == 1
    server = config.servers[0]
    assert server.include_tools is None
    assert server.default_args is None
    assert server.timeout_ms == 5000
