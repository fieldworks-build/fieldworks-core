"""Runtime conformance testing against the FieldworksAdapter nine-tool contract.

The contract is defined in fieldworks-adapters/fieldworks-adapter-core/src/lib.rs
and fieldworks-adapters/CLAUDE.md. FieldworksAdapter there is a specification
document, not compiler-enforced — rmcp's tool macros don't compose with a
hand-written trait impl, so nothing else checks these guarantees at runtime.
This module does, by spawning the adapter binary as an MCP stdio subprocess
and probing it directly.

Checks are split into two tiers:
  - Static checks (tool discovery, tool annotations, get_server_info shape)
    need no live
    connection — both adapters answer these while disconnected.
  - Connection checks (error-code mapping on read_tag/write_tag/
    read_tag_history) require an active connect() to a real broker/server.
    Skipped, not failed, when no host is given — most local runs won't have
    a broker up; CI wires that in separately.
  - Known-tag checks (spec Part II's suite list: well-formed descriptors, a
    valid VQT from read_tag, ordered history, non-empty scan/browse, a
    structured tree) need a tag the surface actually carries: the one given
    as `tag_id`, else the first discover_tags returns. A surface with no
    tags (an empty test broker) skips them with that reason rather than
    failing an adapter for its data.
  - The INVALID_VALUE check sends a real write_tag. It runs only when the
    caller names a writable tag and a value outside its engineering range,
    because an adapter that fails the check would perform that write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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

# MCP clients gate on tool annotations, and under the spec's defaults an
# unannotated tool may be destructive — so a client that honors them can't
# tell read_tag from write_tag unless the adapter says (fieldworks-adapters#15).
READ_ONLY_TOOLS = (
    {"discover_tags", "read_tag", "read_tag_history", "get_server_info"}
    | SCAN_TOOL_ALTERNATIVES
    | TREE_TOOL_ALTERNATIVES
)
NON_DESTRUCTIVE_TOOLS = {"connect", "disconnect"}
DESTRUCTIVE_TOOLS = {"write_tag"}

_NONEXISTENT_TAG_ID = "__fieldworks_conformance_nonexistent_tag__"

QUALITIES = {"good", "uncertain", "bad"}
# Part I, discover_tags: every descriptor carries these; normal_range may be
# null when the adapter knows none.
DESCRIPTOR_FIELDS = {
    "tag_id": str,
    "name": str,
    "description": str,
    "units": str,
    "data_type": str,
    "writable": bool,
    "process_area": str,
    "equipment_id": str,
}
_SCAN_ARGS = {"scan": {"scan_duration_ms": 2000}, "browse": {}}

# Check names, shared by the run and the skip paths.
CHECK_DISCOVER = "discover_tags: well-formed descriptors under 'tags'"
CHECK_READ_KNOWN = "read_tag: known tag returns a valid VQT envelope"
CHECK_HISTORY_KNOWN = (
    "read_tag_history: known tag returns ordered VQTs or HISTORY_UNAVAILABLE"
)
CHECK_SCAN = "browse/scan: non-empty result under 'entries'"
CHECK_TREE = "get_topic_tree/get_node_tree: structured hierarchy"
CHECK_INVALID_VALUE = "write_tag: out-of-range value maps to INVALID_VALUE"


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
    """Extract the JSON payload from a CallToolResult, preferring structured_content."""
    if result.structured_content is not None:
        return result.structured_content
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
    tag_id: str | None = None,
    write_tag_id: str | None = None,
    invalid_value: float | None = None,
    scan_args: dict | None = None,
) -> ConformanceReport:
    """Run the conformance suite against an adapter launched via stdio.

    connect_host/connect_port enable the connection-dependent checks
    (error-code mapping). Without them, those checks are skipped.

    tag_id names a readable tag for the known-tag checks; without it the
    suite uses the first tag discover_tags returns. write_tag_id and
    invalid_value (a value outside that tag's engineering range) enable the
    INVALID_VALUE check, which sends a real write. scan_args are passed
    to browse/scan for an adapter whose scan needs protocol-specific
    arguments (modbus-mcp: register_type, start_address, count).
    """
    report = ConformanceReport()
    params = StdioServerParameters(command=command, args=args or [])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}

            _check_tool_discovery(report, tool_names)
            _check_tool_annotations(report, tools_result.tools)
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
                for name in (CHECK_DISCOVER, *_KNOWN_TAG_CHECKS, CHECK_INVALID_VALUE):
                    report.skip(name, "skipped (no connect_host given)")
            else:
                connected = await _check_connect(
                    report, session, connect_host, connect_port
                )
                if connected:
                    await _check_read_tag_not_found(report, session)
                    await _check_write_tag_rejected(report, session)
                    await _check_read_tag_history(report, session)
                    descriptors = await _check_discover_tags(report, session)
                    known = tag_id or (
                        descriptors[0]["tag_id"] if descriptors else None
                    )
                    if known is None:
                        for name in _KNOWN_TAG_CHECKS:
                            report.skip(
                                name,
                                "skipped (discover_tags found no tags and no "
                                "tag_id was given)",
                            )
                    else:
                        await _check_read_known(report, session, known)
                        await _check_history_known(report, session, known)
                        await _check_scan(
                            report, session, tools_result.tools, scan_args
                        )
                        await _check_tree(report, session, tool_names)
                    if write_tag_id is None or invalid_value is None:
                        report.skip(
                            CHECK_INVALID_VALUE,
                            "skipped (needs a writable tag and an out-of-range "
                            "value; this check sends a real write)",
                        )
                    else:
                        await _check_invalid_value(
                            report, session, write_tag_id, invalid_value, descriptors
                        )

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


def _check_tool_annotations(report: ConformanceReport, tools) -> None:
    """Read tools must be readOnly, connect/disconnect non-destructive, and
    write_tag must not claim to be either. Idempotent/open-world hints are
    left to each adapter."""
    problems = []
    for tool in tools:
        hints = tool.annotations
        read_only = hints is not None and hints.read_only_hint is True
        non_destructive = read_only or (
            hints is not None and hints.destructive_hint is False
        )
        if tool.name in READ_ONLY_TOOLS and not read_only:
            problems.append(f"{tool.name}: readOnlyHint must be true")
        elif tool.name in NON_DESTRUCTIVE_TOOLS and not non_destructive:
            problems.append(f"{tool.name}: destructiveHint must be false")
        elif tool.name in DESTRUCTIVE_TOOLS and non_destructive:
            problems.append(f"{tool.name}: must not be read-only or non-destructive")
    report.add(
        "tool annotations: read-only/destructive hints declared",
        not problems,
        "ok" if not problems else "; ".join(problems),
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
        not result.is_error and not missing_keys,
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
    ok = not result.is_error and payload.get("connected") is True
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
    ok = result.is_error and code in {"TAG_NOT_FOUND", "TIMEOUT"}
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
    ok = result.is_error and code in {
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
    if result.is_error:
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


_KNOWN_TAG_CHECKS = (CHECK_READ_KNOWN, CHECK_HISTORY_KNOWN, CHECK_SCAN, CHECK_TREE)


def _error_code(payload: dict) -> str | None:
    error = payload.get("error")
    return error.get("code") if isinstance(error, dict) else None


def _parse_utc(value) -> datetime | None:
    """An ISO 8601 UTC timestamp, or None if it isn't one (Part I: always
    UTC, never local time)."""
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.utcoffset() != timedelta(0):
        return None
    return ts


def _vqt_problems(vqt, tag_id: str | None = None) -> list[str]:
    """What's wrong with a VQT envelope, or [] if nothing."""
    if not isinstance(vqt, dict):
        return [f"not an object: {vqt!r}"]
    problems = []
    for key in ("tag_id", "value", "quality", "timestamp", "units"):
        if key not in vqt:
            problems.append(f"missing {key}")
    if tag_id is not None and "tag_id" in vqt and vqt["tag_id"] != tag_id:
        problems.append(f"tag_id {vqt['tag_id']!r} does not echo {tag_id!r}")
    if "value" in vqt and not isinstance(vqt["value"], (int, float, str, bool)):
        problems.append(f"value {vqt['value']!r} is not a number, string or boolean")
    if "quality" in vqt and vqt["quality"] not in QUALITIES:
        problems.append(f"quality {vqt['quality']!r} is not good/uncertain/bad")
    if "timestamp" in vqt and _parse_utc(vqt["timestamp"]) is None:
        problems.append(f"timestamp {vqt['timestamp']!r} is not ISO 8601 UTC")
    if "units" in vqt and not isinstance(vqt["units"], str):
        problems.append("units is not a string")
    return problems


def _descriptor_problems(desc) -> list[str]:
    if not isinstance(desc, dict):
        return [f"not an object: {desc!r}"]
    label = desc.get("tag_id", "?")
    problems = []
    for key, kind in DESCRIPTOR_FIELDS.items():
        if key not in desc:
            problems.append(f"{label}: missing {key}")
        elif not isinstance(desc[key], kind):
            problems.append(f"{label}: {key} is not a {kind.__name__}")
    normal = desc.get("normal_range")
    if normal is not None:
        lo = normal.get("min") if isinstance(normal, dict) else None
        hi = normal.get("max") if isinstance(normal, dict) else None
        numbers = all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lo, hi)
        )
        if not numbers or lo >= hi:
            problems.append(
                f"{label}: normal_range must be {{min < max}}, got {normal}"
            )
    return problems


async def _check_discover_tags(
    report: ConformanceReport, session: ClientSession
) -> list[dict]:
    """Returns the descriptors it found well-formed, for the checks after."""
    result = await session.call_tool("discover_tags", {})
    payload = _payload(result)
    tags = payload.get("tags") if isinstance(payload, dict) else None
    if result.is_error or not isinstance(tags, list):
        report.add(CHECK_DISCOVER, False, f"expected {{tags: [...]}}, got: {payload}")
        return []
    problems = [p for desc in tags for p in _descriptor_problems(desc)]
    if problems:
        shown = "; ".join(problems[:5])
        more = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
        report.add(CHECK_DISCOVER, False, shown + more)
        return []
    report.add(
        CHECK_DISCOVER,
        True,
        f"ok ({len(tags)} tags)" if tags else "ok (no tags on this surface)",
    )
    return tags


async def _check_read_known(
    report: ConformanceReport, session: ClientSession, tag_id: str
) -> None:
    result = await session.call_tool("read_tag", {"tag_id": tag_id})
    payload = _payload(result)
    if result.is_error:
        report.add(
            CHECK_READ_KNOWN,
            False,
            f"{tag_id}: error {_error_code(payload)}: {payload}",
        )
        return
    problems = _vqt_problems(payload, tag_id)
    report.add(
        CHECK_READ_KNOWN,
        not problems,
        f"ok ({tag_id})" if not problems else f"{tag_id}: " + "; ".join(problems),
    )


async def _check_history_known(
    report: ConformanceReport, session: ClientSession, tag_id: str
) -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    result = await session.call_tool(
        "read_tag_history",
        {
            "tag_id": tag_id,
            "start_time": start.isoformat().replace("+00:00", "Z"),
            "end_time": end.isoformat().replace("+00:00", "Z"),
        },
    )
    payload = _payload(result)
    if result.is_error:
        code = _error_code(payload)
        ok = code == "HISTORY_UNAVAILABLE"
        report.add(
            CHECK_HISTORY_KNOWN,
            ok,
            "ok (protocol has no history)" if ok else f"{tag_id}: error {code}",
        )
        return
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        report.add(
            CHECK_HISTORY_KNOWN, False, f"expected {{values: [...]}}, got: {payload}"
        )
        return
    problems = [p for v in values for p in _vqt_problems(v, tag_id)]
    stamps = [_parse_utc(v.get("timestamp")) for v in values if isinstance(v, dict)]
    if not problems and stamps != sorted(stamps):
        problems.append("values are not ordered by timestamp ascending")
    report.add(
        CHECK_HISTORY_KNOWN,
        not problems,
        f"ok ({len(values)} values)" if not problems else "; ".join(problems[:5]),
    )


async def _check_scan(
    report: ConformanceReport,
    session: ClientSession,
    tools,
    scan_args: dict | None,
) -> None:
    by_name = {t.name: t for t in tools}
    tool = next(iter(sorted(by_name.keys() & SCAN_TOOL_ALTERNATIVES)), None)
    if tool is None:
        report.add(CHECK_SCAN, False, "no browse or scan tool")
        return
    args = scan_args if scan_args is not None else _SCAN_ARGS[tool]
    # Part I's browse/scan parameters are all optional, but a protocol's
    # slot tool may need its own (modbus-mcp's scan: register_type,
    # start_address, count). The suite can't invent those.
    required = set((by_name[tool].input_schema or {}).get("required", []))
    missing = sorted(required - args.keys())
    if missing:
        report.skip(
            CHECK_SCAN,
            f"skipped ({tool} requires {', '.join(missing)}; pass them as "
            "scan_args / --scan-args)",
        )
        return
    result = await session.call_tool(tool, args)
    payload = _payload(result)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    ok = not result.is_error and isinstance(entries, list) and len(entries) > 0
    report.add(
        CHECK_SCAN,
        ok,
        (
            f"ok ({tool}: {len(entries)} entries)"
            if ok
            else f"{tool}: expected non-empty {{entries: [...]}}, got: {payload}"
        ),
    )


async def _check_tree(
    report: ConformanceReport, session: ClientSession, tool_names: set[str]
) -> None:
    tool = next(iter(sorted(tool_names & TREE_TOOL_ALTERNATIVES)), None)
    if tool is None:
        report.add(CHECK_TREE, False, "no get_topic_tree or get_node_tree tool")
        return
    result = await session.call_tool(tool, {})
    payload = _payload(result)
    # opcua-mcp wraps its tree as {"tree": {...}, "node_count", "truncated"};
    # mqtt-mcp returns the hierarchy itself.
    tree = payload.get("tree", payload) if isinstance(payload, dict) else None
    ok = not result.is_error and isinstance(tree, dict) and len(tree) > 0
    report.add(
        CHECK_TREE,
        ok,
        (
            f"ok ({tool})"
            if ok
            else f"{tool}: expected a non-empty object, got: {payload}"
        ),
    )


async def _check_invalid_value(
    report: ConformanceReport,
    session: ClientSession,
    tag_id: str,
    value: float,
    descriptors: list[dict],
) -> None:
    units = next((d["units"] for d in descriptors if d["tag_id"] == tag_id), "")
    result = await session.call_tool(
        "write_tag",
        {
            "tag_id": tag_id,
            "value": value,
            "units": units,
            "operator_id": "fieldworks-conformance",
            "reason": "conformance check: out-of-range value must be refused",
        },
    )
    payload = _payload(result)
    code = _error_code(payload)
    ok = result.is_error and code == "INVALID_VALUE"
    if ok:
        message = "ok"
    elif not result.is_error:
        message = f"{tag_id}={value} was WRITTEN, not refused: {payload}"
    else:
        message = f"{tag_id}={value}: expected INVALID_VALUE, got {code}"
    report.add(CHECK_INVALID_VALUE, ok, message)
