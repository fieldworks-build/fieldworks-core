"""Tests for prompt-cache injection helpers."""


def test_cache_tools_empty_list():
    from fieldworks.agents.caching import cache_tools

    assert cache_tools([]) == []


def test_cache_tools_maps_input_schema_key():
    from fieldworks.agents.caching import cache_tools

    tools = [{"name": "a", "description": "d", "inputSchema": {"type": "object"}}]
    result = cache_tools(tools)
    assert result[0]["input_schema"] == {"type": "object"}
    assert "inputSchema" not in result[0]


def test_cache_tools_only_last_has_cache_control():
    from fieldworks.agents.caching import cache_tools

    tools = [
        {"name": "a", "description": "d", "inputSchema": {}},
        {"name": "b", "description": "d", "inputSchema": {}},
        {"name": "c", "description": "d", "inputSchema": {}},
    ]
    result = cache_tools(tools)
    assert "cache_control" not in result[0]
    assert "cache_control" not in result[1]
    assert result[2]["cache_control"] == {"type": "ephemeral"}


def test_cache_tools_deterministic_regardless_of_input_order():
    from fieldworks.agents.caching import cache_tools

    tools_a = [
        {"name": "zebra", "description": "d", "inputSchema": {}},
        {"name": "apple", "description": "d", "inputSchema": {}},
        {"name": "mango", "description": "d", "inputSchema": {}},
    ]
    tools_b = [
        {"name": "mango", "description": "d", "inputSchema": {}},
        {"name": "zebra", "description": "d", "inputSchema": {}},
        {"name": "apple", "description": "d", "inputSchema": {}},
    ]
    result_a = cache_tools(tools_a)
    result_b = cache_tools(tools_b)
    assert [t["name"] for t in result_a] == ["apple", "mango", "zebra"]
    assert result_a == result_b


def test_cache_system_shape():
    from fieldworks.agents.caching import cache_system

    result = cache_system("You are Cascade.")
    assert result == [
        {
            "type": "text",
            "text": "You are Cascade.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
