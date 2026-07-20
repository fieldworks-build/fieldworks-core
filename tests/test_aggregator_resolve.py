"""Tests for fieldworks.aggregator.resolve — fieldworks-core#17."""


def test_resolve_tools_filters_by_include_tools(wtp_aggregator):
    from fieldworks.aggregator import resolve_tools

    server = wtp_aggregator.get_server("mqtt_intake")
    available = ["read_tag", "read_tag_history", "discover_tags", "write_tag"]

    resolved = resolve_tools(server, available)

    assert resolved == ["read_tag", "read_tag_history", "discover_tags"]
    assert "write_tag" not in resolved


def test_resolve_tools_no_include_tools_returns_everything(wtp_aggregator):
    from fieldworks.aggregator import resolve_tools

    server = wtp_aggregator.get_server("influxdb")
    available = ["query", "write_point", "list_measurements"]

    assert resolve_tools(server, available) == available


def test_resolve_tools_include_tools_names_not_in_available_are_dropped(
    wtp_aggregator,
):
    from fieldworks.aggregator import resolve_tools

    server = wtp_aggregator.get_server("mqtt_intake")
    # Server only actually exposes read_tag today — the other include_tools
    # entries (read_tag_history, discover_tags) aren't live.
    assert resolve_tools(server, ["read_tag"]) == ["read_tag"]


def test_merge_call_args_merges_defaults_under_explicit(wtp_aggregator):
    from fieldworks.aggregator import merge_call_args

    server = wtp_aggregator.get_server("mqtt_intake")
    args = merge_call_args(server, {"tag_id": "Flow"})

    assert args == {
        "topic_filter": "Plant/WTP/Pump/RawWater_*",
        "tag_id": "Flow",
    }


def test_merge_call_args_explicit_wins_over_default(wtp_aggregator):
    from fieldworks.aggregator import merge_call_args

    server = wtp_aggregator.get_server("mqtt_intake")
    args = merge_call_args(server, {"topic_filter": "override"})

    assert args["topic_filter"] == "override"


def test_merge_call_args_no_default_args_returns_explicit_unchanged(wtp_aggregator):
    from fieldworks.aggregator import merge_call_args

    server = wtp_aggregator.get_server("influxdb")
    explicit = {"query": "SELECT *"}

    assert merge_call_args(server, explicit) == explicit
