"""Runtime conformance testing against the FieldworksAdapter nine-tool contract.

The contract is defined in fieldworks-adapters/fieldworks-adapter-core/src/lib.rs
and fieldworks-adapters/CLAUDE.md. FieldworksAdapter there is a specification
document, not compiler-enforced — rmcp's tool macros don't compose with a
hand-written trait impl, so nothing else checks these guarantees at runtime.
This module does, by spawning the adapter binary as an MCP stdio subprocess
and probing it directly.

Checks are split into two tiers:
  - Static checks (tool discovery, get_server_info shape) need no live
    connection — both adapters answer these while disconnected.
  - Connection checks (error-code mapping on read_tag/write_tag/
    read_tag_history) require an active connect() to a real broker/server.
    Skipped, not failed, when no host is given — most local runs won't have
    a broker up; CI wires that in separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REQUIRED_TOOLS = {
    "connect",
    "disconnect",
    "discover_tags",
    "read_tag",
    "read_tag_history",
    "write_tag",
    "get_server_info",
}
SCAN_TOOL_ALTERNATIVES = {"scan", "browse"}
TREE_TOOL_ALTERNATIVES = {"get_topic_tree", "get_node_tree"}

_NONEXISTENT_TAG_ID = "__fieldworks_conformance_nonexistent_tag__"


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    skipped: bool = False


@dataclass
class ConformanceReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if not c.skipped)

    def add(self, name: str, passed: bool, message: str = "") -> None:
        self.checks.append(CheckResult(name, passed, message))

    def skip(self, name: str, message: str) -> None:
        self.checks.append(
            CheckResult(name, passed=True, message=message, skipped=True)
        )


def _payload(result) -> dict:
    """Extract the JSON payload from a CallToolResult, preferring structuredContent."""
    if result.structuredContent is not None:
        return result.structuredContent
    if result.content:
        first = result.content[0]
        text = getattr(first, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {}
    return {}


async def run_conformance(
    command: str,
    args: list[str] | None = None,
    *,
    connect_host: str | None = None,
    connect_port: int | None = None,
) -> ConformanceReport:
    """Run the conformance suite against an adapter launched via stdio.

    connect_host/connect_port enable the connection-dependent checks
    (error-code mapping). Without them, those checks are skipped.
    """
    report = ConformanceReport()
    params = StdioServerParameters(command=command, args=args or [])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}

            _check_tool_discovery(report, tool_names)
            await _check_server_info(report, session, tool_names)

            if connect_host is None:
                report.skip(
                    "connect: establishes a connection",
                    "skipped (no connect_host given)",
                )
                report.skip(
                    "read_tag: unknown tag_id maps to TAG_NOT_FOUND or TIMEOUT",
                    "skipped (no connect_host given)",
                )
                report.skip(
                    "write_tag: rejected write maps to an error code",
                    "skipped (no connect_host given)",
                )
                report.skip(
                    "read_tag_history: returns VQT list or HISTORY_UNAVAILABLE",
                    "skipped (no connect_host given)",
                )
            else:
                connected = await _check_connect(
                    report, session, connect_host, connect_port
                )
                if connected:
                    await _check_read_tag_not_found(report, session)
                    await _check_write_tag_rejected(report, session)
                    await _check_read_tag_history(report, session)

    return report


def _check_tool_discovery(report: ConformanceReport, tool_names: set[str]) -> None:
    missing = REQUIRED_TOOLS - tool_names
    report.add(
        "tool discovery: required tools present",
        not missing,
        "all present" if not missing else f"missing: {sorted(missing)}",
    )

    scan_found = tool_names & SCAN_TOOL_ALTERNATIVES
    report.add(
        "tool discovery: scan/browse slot filled",
        len(scan_found) >= 1,
        (
            f"found: {sorted(scan_found)}"
            if scan_found
            else "neither 'scan' nor 'browse' present"
        ),
    )

    tree_found = tool_names & TREE_TOOL_ALTERNATIVES
    report.add(
        "tool discovery: get_topic_tree/get_node_tree slot filled",
        len(tree_found) >= 1,
        (
            f"found: {sorted(tree_found)}"
            if tree_found
            else "neither 'get_topic_tree' nor 'get_node_tree' present"
        ),
    )


async def _check_server_info(
    report: ConformanceReport, session: ClientSession, tool_names: set[str]
) -> None:
    result = await session.call_tool("get_server_info", {})
    info = _payload(result)

    required_keys = {
        "server_name",
        "protocol",
        "protocol_version",
        "connected",
        "connection_state",
        "capabilities",
        "uptime_seconds",
    }
    missing_keys = required_keys - info.keys()
    report.add(
        "get_server_info: response shape",
        not result.isError and not missing_keys,
        "ok" if not missing_keys else f"missing keys: {sorted(missing_keys)}",
    )

    capabilities = set(info.get("capabilities", []))
    missing_caps = tool_names - capabilities
    report.add(
        "get_server_info: capabilities lists discovered tools",
        not missing_caps,
        (
            "ok"
            if not missing_caps
            else f"not listed in capabilities: {sorted(missing_caps)}"
        ),
    )


async def _check_connect(
    report: ConformanceReport,
    session: ClientSession,
    host: str,
    port: int | None,
) -> bool:
    args = {"host": host}
    if port is not None:
        args["port"] = port
    result = await session.call_tool("connect", args)
    payload = _payload(result)
    ok = not result.isError and payload.get("connected") is True
    report.add(
        "connect: establishes a connection",
        ok,
        "ok" if ok else f"unexpected response: {payload}",
    )
    return ok


async def _check_read_tag_not_found(
    report: ConformanceReport, session: ClientSession
) -> None:
    """TAG_NOT_FOUND is the ideal response, but not every protocol can tell
    "doesn't exist" apart from "hasn't published recently" — MQTT has no
    server-side topic registry to check against, only an empirical "did a
    message ever arrive." Confirmed against a live mqtt-mcp: an unknown
    topic times out (protocol-honest — it can't claim non-existence it
    can't verify), while opcua-mcp's real address space lets it return
    TAG_NOT_FOUND outright. Both are conformant; a protocol that could
    prove non-existence and returned TIMEOUT instead would not be."""
    result = await session.call_tool("read_tag", {"tag_id": _NONEXISTENT_TAG_ID})
    payload = _payload(result)
    code = payload.get("error", {}).get("code")
    ok = result.isError and code in {"TAG_NOT_FOUND", "TIMEOUT"}
    report.add(
        "read_tag: unknown tag_id maps to TAG_NOT_FOUND or TIMEOUT",
        ok,
        "ok" if ok else f"expected error code TAG_NOT_FOUND or TIMEOUT, got: {payload}",
    )


async def _check_write_tag_rejected(
    report: ConformanceReport, session: ClientSession
) -> None:
    result = await session.call_tool(
        "write_tag",
        {
            "tag_id": _NONEXISTENT_TAG_ID,
            "value": 0.0,
            "units": "",
            "operator_id": "fieldworks-conformance",
            "reason": "conformance check",
        },
    )
    payload = _payload(result)
    code = payload.get("error", {}).get("code")
    ok = result.isError and code in {
        "TAG_NOT_WRITABLE",
        "TAG_NOT_FOUND",
        "PERMISSION_DENIED",
    }
    report.add(
        "write_tag: rejected write maps to an error code",
        ok,
        "ok" if ok else f"expected a rejection error code, got: {payload}",
    )


async def _check_read_tag_history(
    report: ConformanceReport, session: ClientSession
) -> None:
    result = await session.call_tool(
        "read_tag_history",
        {
            "tag_id": _NONEXISTENT_TAG_ID,
            "start_time": "2020-01-01T00:00:00.000Z",
            "end_time": "2020-01-01T01:00:00.000Z",
        },
    )
    payload = _payload(result)
    if result.isError:
        code = payload.get("error", {}).get("code")
        ok = code in {"HISTORY_UNAVAILABLE", "TAG_NOT_FOUND"}
        message = "ok (unsupported)" if ok else f"unexpected error code: {code}"
    else:
        # structuredContent must be an object per the MCP spec — a bare VQT
        # array isn't valid, so a conformant adapter wraps it (opcua-mcp:
        # {"values": [...]}, fieldworks-adapters#2/#4 fixed the same bug for
        # discover_tags/scan/browse).
        ok = isinstance(payload, dict) and isinstance(payload.get("values"), list)
        message = (
            "ok (returned a VQT list under 'values')"
            if ok
            else f"unexpected response shape: {payload}"
        )
    report.add("read_tag_history: returns VQT list or HISTORY_UNAVAILABLE", ok, message)
