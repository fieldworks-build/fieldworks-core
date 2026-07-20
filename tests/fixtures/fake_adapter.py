"""Minimal fake MCP stdio adapter for exercising fieldworks.adapters.conformance
without a real Rust adapter binary or a live broker.

Usage: python fake_adapter.py <conformant|broken>

conformant implements the nine-tool contract correctly. broken deliberately
violates it in a few ways (missing tool, wrong error code, malformed
get_server_info) so tests can assert the conformance suite actually catches
regressions instead of always passing.
"""

import asyncio
import json
import sys

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

MODE = sys.argv[1] if len(sys.argv) > 1 else "conformant"

_EMPTY_SCHEMA = {"type": "object", "properties": {}}

_CONFORMANT_TOOLS = [
    "connect",
    "disconnect",
    "discover_tags",
    "scan",
    "get_topic_tree",
    "read_tag",
    "read_tag_history",
    "write_tag",
    "get_server_info",
]
# Deliberately drops write_tag to trip the tool-discovery check.
_BROKEN_TOOLS = [t for t in _CONFORMANT_TOOLS if t != "write_tag"]

server = Server("fake-adapter")


def _result(payload, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
        isError=is_error,
    )


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    names = _BROKEN_TOOLS if MODE == "broken" else _CONFORMANT_TOOLS
    return [
        types.Tool(name=name, description=name, inputSchema=_EMPTY_SCHEMA)
        for name in names
    ]


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict):
    if name == "connect":
        return _result(
            {
                "connected": True,
                "server_name": "fake-adapter",
                "protocol_version": "1.0",
                "timestamp": "2026-01-01T00:00:00.000Z",
            }
        )

    if name == "get_server_info":
        info = {
            "server_name": "fake-adapter",
            "protocol": "FAKE",
            "protocol_version": "1.0",
            "connected": False,
            "connection_state": "disconnected",
            "capabilities": _BROKEN_TOOLS if MODE == "broken" else _CONFORMANT_TOOLS,
            "uptime_seconds": 0,
            "last_error": None,
        }
        if MODE == "broken":
            del info["capabilities"]  # trips the response-shape check
        return _result(info)

    if name == "get_topic_tree":
        # Real shape (mqtt-mcp's build_topic_tree): no "children" wrapper —
        # each level is either a leaf dict (has "tag_id") or a plain map of
        # further segments.
        return _result(
            {
                "Plant": {
                    "WTP": {
                        "Pump": {
                            "RawWater_01": {
                                "Flow": {"tag_id": "Plant/WTP/Pump/RawWater_01/Flow"},
                                "Running": {
                                    "tag_id": "Plant/WTP/Pump/RawWater_01/Running"
                                },
                            }
                        }
                    }
                }
            }
        )

    if name == "get_node_tree":
        # Real opcua-mcp wraps the tree in {"tree": ..., "node_count": ...,
        # "truncated": ...} (fieldworks-adapters/opcua-mcp/src/server.rs) — this
        # fixture used to return the tree bare, which masked a real unwrapping
        # bug in crawl_opcua (fieldworks-core, fixed alongside this fixture).
        tree = {
            "Plant": {
                "node_id": "ns=2;s=Plant",
                "node_class": "Object",
                "children": {
                    "Pump": {
                        "node_id": "ns=2;s=Plant.Pump",
                        "node_class": "Object",
                        "children": {
                            "Flow": {
                                "node_id": "ns=2;s=Plant.Pump.Flow",
                                "node_class": "Variable",
                            },
                            "Running": {
                                "node_id": "ns=2;s=Plant.Pump.Running",
                                "node_class": "Variable",
                            },
                        },
                    }
                },
            }
        }
        return _result({"tree": tree, "node_count": 4, "truncated": False})

    if name == "read_tag":
        # "timeout" mode: some protocols (MQTT) can't tell "doesn't exist"
        # apart from "hasn't published recently" and can only time out —
        # exercises the TIMEOUT branch of the not-found check, which
        # TAG_NOT_FOUND-returning "conformant" mode doesn't reach.
        if MODE == "broken":
            code = "SOMETHING_ELSE"
        elif MODE == "timeout":
            code = "TIMEOUT"
        else:
            code = "TAG_NOT_FOUND"
        return _result(
            {
                "error": {
                    "code": code,
                    "message": "not found",
                    "tag_id": arguments.get("tag_id"),
                }
            },
            is_error=True,
        )

    if name == "write_tag":
        return _result(
            {
                "error": {
                    "code": "TAG_NOT_WRITABLE",
                    "message": "not writable",
                    "tag_id": arguments.get("tag_id"),
                }
            },
            is_error=True,
        )

    if name == "read_tag_history":
        if MODE == "broken":
            return _result(
                {
                    "error": {
                        "code": "HISTORY_UNAVAILABLE",
                        "message": "no history",
                        "tag_id": arguments.get("tag_id"),
                    }
                },
                is_error=True,
            )
        # "values" wraps the VQT list — a bare array isn't valid
        # structuredContent per the MCP spec (fieldworks-adapters#2/#4).
        return _result(
            {
                "values": [
                    {
                        "tag_id": arguments.get("tag_id"),
                        "value": 1.0,
                        "quality": "good",
                        "timestamp": "2026-01-01T00:00:00.000Z",
                        "units": "",
                    }
                ]
            }
        )

    return _result(
        {"error": {"code": "TAG_NOT_FOUND", "message": "unknown tool"}}, is_error=True
    )


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
