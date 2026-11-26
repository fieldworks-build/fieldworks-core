"""Tests for fieldworks.adapters.conformance against a fake stdio MCP adapter."""

import sys
from pathlib import Path

import pytest

FAKE_ADAPTER = Path(__file__).parent / "fixtures" / "fake_adapter.py"


async def _run(mode: str, **kwargs):
    from fieldworks.adapters.conformance import run_conformance

    return await run_conformance(sys.executable, [str(FAKE_ADAPTER), mode], **kwargs)


@pytest.mark.anyio
async def test_conformant_adapter_passes_static_checks():
    report = await _run("conformant")
    assert report.passed
    names = {c.name for c in report.checks}
    assert "tool discovery: required tools present" in names
    assert "get_server_info: capabilities lists discovered tools" in names


@pytest.mark.anyio
async def test_broken_adapter_fails_tool_discovery():
    report = await _run("broken")
    assert not report.passed
    discovery = next(
        c for c in report.checks if c.name == "tool discovery: required tools present"
    )
    assert not discovery.passed
    assert "write_tag" in discovery.message


@pytest.mark.anyio
async def test_conformant_adapter_passes_annotation_check():
    report = await _run("conformant")
    check = next(c for c in report.checks if c.name.startswith("tool annotations"))
    assert check.passed, check.message


@pytest.mark.anyio
async def test_broken_adapter_fails_annotation_check():
    report = await _run("broken")
    check = next(c for c in report.checks if c.name.startswith("tool annotations"))
    assert not check.passed
    assert "read_tag: readOnlyHint must be true" in check.message
    assert "connect: destructiveHint must be false" in check.message


def test_write_tag_marked_non_destructive_fails_annotation_check():
    import mcp.types as types

    from fieldworks.adapters.conformance import (
        ConformanceReport,
        _check_tool_annotations,
    )

    report = ConformanceReport()
    write_tag = types.Tool(
        name="write_tag",
        inputSchema={"type": "object"},
        annotations=types.ToolAnnotations(destructive_hint=False),
    )
    _check_tool_annotations(report, [write_tag])
    assert not report.passed
    assert "write_tag: must not be" in report.checks[0].message


@pytest.mark.anyio
async def test_broken_adapter_fails_server_info_shape():
    report = await _run("broken")
    shape_check = next(
        c for c in report.checks if c.name == "get_server_info: response shape"
    )
    assert not shape_check.passed


@pytest.mark.anyio
async def test_no_connect_host_skips_connection_checks():
    report = await _run("conformant")
    connect_check = next(
        c for c in report.checks if c.name == "connect: establishes a connection"
    )
    assert connect_check.skipped


@pytest.mark.anyio
async def test_connect_host_runs_connection_dependent_checks():
    report = await _run("conformant", connect_host="localhost", connect_port=1883)
    names = {c.name: c for c in report.checks}
    assert not names["connect: establishes a connection"].skipped
    assert names["connect: establishes a connection"].passed
    assert names["read_tag: unknown tag_id maps to TAG_NOT_FOUND or TIMEOUT"].passed
    assert names["write_tag: rejected write maps to an error code"].passed
    assert names["read_tag_history: returns VQT list or HISTORY_UNAVAILABLE"].passed


@pytest.mark.anyio
async def test_broken_adapter_fails_read_tag_error_code():
    report = await _run("broken", connect_host="localhost", connect_port=1883)
    check = next(
        c
        for c in report.checks
        if c.name == "read_tag: unknown tag_id maps to TAG_NOT_FOUND or TIMEOUT"
    )
    assert not check.passed


@pytest.mark.anyio
async def test_timeout_is_accepted_for_read_tag_not_found():
    """Protocols without a server-side tag registry (MQTT) can only time
    out on an unknown tag — TIMEOUT must be as conformant as TAG_NOT_FOUND,
    not just something "broken" adapters happen to trigger."""
    report = await _run("timeout", connect_host="localhost", connect_port=1883)
    check = next(
        c
        for c in report.checks
        if c.name == "read_tag: unknown tag_id maps to TAG_NOT_FOUND or TIMEOUT"
    )
    assert check.passed


@pytest.mark.anyio
async def test_read_tag_history_success_requires_values_list_not_bare_array():
    """A bare array isn't valid structuredContent (fieldworks-adapters#2/#4)
    — the success path must be wrapped, and the conformance check must
    actually look for that wrapper rather than accept anything list-shaped."""
    report = await _run("conformant", connect_host="localhost", connect_port=1883)
    check = next(
        c
        for c in report.checks
        if c.name == "read_tag_history: returns VQT list or HISTORY_UNAVAILABLE"
    )
    assert check.passed
    assert "values" in check.message


# ── Known-tag checks (core#44, spec Part II "Adapter conformance suite") ─────

from fieldworks.adapters.conformance import (  # noqa: E402
    CHECK_DISCOVER,
    CHECK_HISTORY_KNOWN,
    CHECK_INVALID_VALUE,
    CHECK_READ_KNOWN,
    CHECK_SCAN,
    CHECK_TREE,
)

TAG = "Plant/WTP/Pump/RawWater_01/Flow"
KNOWN = (CHECK_READ_KNOWN, CHECK_HISTORY_KNOWN, CHECK_SCAN, CHECK_TREE)
LIVE = {"connect_host": "localhost", "connect_port": 1883}


def _checks(report):
    return {c.name: c for c in report.checks}


@pytest.mark.anyio
async def test_conformant_adapter_passes_known_tag_checks_from_discovery():
    checks = _checks(await _run("conformant", **LIVE))
    assert checks[CHECK_DISCOVER].passed
    assert "1 tags" in checks[CHECK_DISCOVER].message
    for name in KNOWN:
        assert checks[name].passed and not checks[name].skipped, checks[name]
    assert TAG in checks[CHECK_READ_KNOWN].message


@pytest.mark.anyio
async def test_empty_surface_skips_known_tag_checks_instead_of_failing():
    report = await _run("empty", **LIVE)
    checks = _checks(report)
    assert checks[CHECK_DISCOVER].passed
    assert "no tags" in checks[CHECK_DISCOVER].message
    for name in KNOWN:
        assert checks[name].skipped
        assert "discover_tags found no tags" in checks[name].message
    assert report.passed


@pytest.mark.anyio
async def test_malformed_descriptors_fail_discovery():
    check = _checks(await _run("malformed", **LIVE))[CHECK_DISCOVER]
    assert not check.passed
    assert "missing name" in check.message
    assert "writable is not a bool" in check.message


@pytest.mark.anyio
async def test_given_tag_runs_known_checks_and_catches_bad_data():
    checks = _checks(await _run("malformed", tag_id=TAG, **LIVE))
    read = checks[CHECK_READ_KNOWN]
    assert not read.passed
    assert "quality 'ok'" in read.message
    assert "not ISO 8601 UTC" in read.message
    assert "not ordered" in checks[CHECK_HISTORY_KNOWN].message
    assert not checks[CHECK_SCAN].passed
    assert not checks[CHECK_TREE].passed


@pytest.mark.anyio
async def test_invalid_value_check_is_opt_in():
    check = _checks(await _run("conformant", **LIVE))[CHECK_INVALID_VALUE]
    assert check.skipped
    assert "sends a real write" in check.message


@pytest.mark.anyio
async def test_out_of_range_write_must_be_refused():
    ok = _checks(await _run("conformant", write_tag_id=TAG, invalid_value=1e9, **LIVE))[
        CHECK_INVALID_VALUE
    ]
    assert ok.passed and not ok.skipped

    written = _checks(
        await _run("malformed", write_tag_id=TAG, invalid_value=1e9, **LIVE)
    )[CHECK_INVALID_VALUE]
    assert not written.passed
    assert "was WRITTEN" in written.message


@pytest.mark.anyio
async def test_no_connect_host_skips_every_new_check():
    checks = _checks(await _run("conformant"))
    for name in (CHECK_DISCOVER, *KNOWN, CHECK_INVALID_VALUE):
        assert checks[name].skipped


def test_vqt_timestamp_must_be_utc():
    from fieldworks.adapters.conformance import _vqt_problems

    vqt = {
        "tag_id": "t",
        "value": 1.0,
        "quality": "good",
        "timestamp": "2026-01-01T00:00:00+02:00",
        "units": "",
    }
    assert _vqt_problems(vqt) == [
        "timestamp '2026-01-01T00:00:00+02:00' is not ISO 8601 UTC"
    ]
    assert _vqt_problems({**vqt, "timestamp": "2026-01-01T00:00:00.000Z"}) == []


@pytest.mark.anyio
async def test_scan_needing_protocol_args_is_skipped_not_failed():
    """modbus-mcp's scan requires register_type/start_address/count; Part I
    defines no such parameters, so the suite can't invent them."""
    import mcp.types as types

    from fieldworks.adapters.conformance import ConformanceReport, _check_scan

    scan = types.Tool(
        name="scan",
        inputSchema={
            "type": "object",
            "required": ["register_type", "start_address", "count"],
        },
    )
    report = ConformanceReport()
    await _check_scan(report, None, [scan], None)  # never reaches the session
    (check,) = report.checks
    assert check.skipped
    assert "count, register_type, start_address" in check.message
    assert "--scan-args" in check.message
