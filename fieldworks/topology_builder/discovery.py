"""Topology discovery via the FieldworksAdapter MCP tool contract.

Crawls call an already-connected mcp.ClientSession for a protocol adapter
(mqtt-mcp / opcua-mcp) rather than owning protocol clients directly.
Adapters already implement get_topic_tree (MQTT) and get_node_tree (OPC-UA)
for exactly this "full address-space dump for topology onboarding" purpose
— see fieldworks-adapters/CLAUDE.md. The caller owns the session's
lifecycle (stdio subprocess, aggregator SSE connection, whatever), so this
module has no transport or process-management concerns of its own.

Deliberately NOT using mqtt-mcp's `scan` / opcua-mcp's `browse`: both return
a bare JSON array as structuredContent, which violates the MCP spec (that
field must be an object) and makes the official Python `mcp` client raise a
pydantic ValidationError trying to parse the response. get_topic_tree/
get_node_tree don't have this problem — both return a properly-shaped
nested object — and they're the tools actually documented for this
onboarding use case anyway. Filed as fieldworks-adapters#2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp import ClientSession


def _payload(result: Any) -> Any:
    """Extract the JSON payload from a CallToolResult, preferring structuredContent."""
    if result.structuredContent is not None:
        return result.structuredContent
    if result.content:
        first = result.content[0]
        text = getattr(first, "text", None)
        if text:
            import json

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
    return None


async def crawl_mqtt(
    session: "ClientSession", topic_prefix: str | None = None
) -> list[str]:
    """Return all MQTT topics observed during a full topic-tree dump.

    Calls the adapter's `get_topic_tree` tool, which returns a nested object
    keyed by topic segment. Flattened here to '/'-joined leaf paths — these
    reconstruct the original topic strings exactly, since the adapter builds
    the tree by splitting each topic on '/' in the first place.
    """
    params: dict[str, Any] = {}
    if topic_prefix is not None:
        params["topic_prefix"] = topic_prefix

    result = await session.call_tool("get_topic_tree", params)
    tree = _payload(result) or {}

    topics: list[str] = []
    _flatten_topic_tree(tree, "", topics)
    return topics


async def crawl_opcua(
    session: "ClientSession",
    root_node: str | None = None,
    depth: int | None = None,
) -> list[str]:
    """Return leaf node paths from a recursive OPC-UA node-tree browse.

    Calls the adapter's `get_node_tree` tool, which returns a nested object
    keyed by display name (not NodeId — display names are what
    fieldworks.topology_builder.inference pattern-matches against, same as
    the MQTT topic strings). Flattened here to '/'-joined leaf paths.
    """
    params: dict[str, Any] = {}
    if root_node is not None:
        params["root_node"] = root_node
    if depth is not None:
        params["depth"] = depth

    result = await session.call_tool("get_node_tree", params)
    tree = _payload(result) or {}

    paths: list[str] = []
    _flatten_node_tree(tree, "", paths)
    return paths


def _flatten_topic_tree(tree: dict, prefix: str, out: list[str]) -> None:
    """MQTT's get_topic_tree shape: each dict is *either* a leaf value (has a
    'tag_id' key) *or* a map of further segments — there's no explicit
    'children' wrapper the way OPC-UA's tree has, so a 'tag_id' key is the
    leaf marker instead.
    """
    for name, entry in tree.items():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(entry, dict) and "tag_id" not in entry:
            _flatten_topic_tree(entry, path, out)
        else:
            out.append(path)


def _flatten_node_tree(tree: dict, prefix: str, out: list[str]) -> None:
    """OPC-UA's get_node_tree shape: each entry has node_id/node_class plus an
    optional 'children' key holding the next level — a leaf is an entry with
    no 'children' key.
    """
    for name, entry in tree.items():
        path = f"{prefix}/{name}" if prefix else name
        children = entry.get("children") if isinstance(entry, dict) else None
        if children:
            _flatten_node_tree(children, path, out)
        else:
            out.append(path)
