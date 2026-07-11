"""Deterministic prompt-cache injection for Anthropic API calls.

Wraps the `cache_control: {"type": "ephemeral"}` pattern validated in
waterworks-ai's multi_agent_loop.py so any Fieldworks agent gets cache
hits without hand-rolling the breakpoint placement per call site.

Tools are sorted by name before caching — the aggregator's `list_tools()`
order is not guaranteed stable across restarts, and an unstable tool list
before the cache breakpoint silently invalidates every cache read.
"""

from __future__ import annotations

CACHE_CONTROL_EPHEMERAL = {"type": "ephemeral"}


def cache_tools(tools: list[dict]) -> list[dict]:
    """Return tools sorted by name, in Anthropic tool-param shape, with
    cache_control on the last element.

    Args:
        tools: Dicts with at least "name", "description", "inputSchema"
            (the shape returned by MCP's list_tools()).

    Returns:
        Dicts with "name", "description", "input_schema", ready to pass
        as the `tools=` kwarg. Empty input returns an empty list.
    """
    ordered = sorted(tools, key=lambda t: t["name"])
    api_tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in ordered
    ]
    if api_tools:
        api_tools[-1]["cache_control"] = CACHE_CONTROL_EPHEMERAL
    return api_tools


def cache_system(text: str) -> list[dict]:
    """Return a `system=` block list with cache_control on the (only) block."""
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": CACHE_CONTROL_EPHEMERAL,
        }
    ]
