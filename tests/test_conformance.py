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
    assert names["read_tag: unknown tag_id maps to TAG_NOT_FOUND"].passed
    assert names["write_tag: rejected write maps to an error code"].passed
    assert names["read_tag_history: returns VQT list or HISTORY_UNAVAILABLE"].passed


@pytest.mark.anyio
async def test_broken_adapter_fails_read_tag_error_code():
    report = await _run("broken", connect_host="localhost", connect_port=1883)
    check = next(
        c
        for c in report.checks
        if c.name == "read_tag: unknown tag_id maps to TAG_NOT_FOUND"
    )
    assert not check.passed
