"""Tests for fieldworks.trust.intercept."""

import asyncio

import pytest

from fieldworks.trust.intercept import (
    PendingActionRegistry,
    ProposedAction,
    format_decision_result,
)


@pytest.mark.anyio
async def test_register_creates_future_tracked_in_pending_ids():
    registry = PendingActionRegistry()
    registry.register("abc123")
    assert registry.pending_ids() == ["abc123"]


@pytest.mark.anyio
async def test_resolve_sets_result_and_clears_pending():
    registry = PendingActionRegistry()
    fut = registry.register("abc123")
    assert registry.resolve("abc123", "approved") is True
    assert registry.pending_ids() == []
    assert fut.result() == "approved"


@pytest.mark.anyio
async def test_resolve_unknown_or_already_done_returns_false():
    registry = PendingActionRegistry()
    assert registry.resolve("nope", "approved") is False

    registry.register("abc123")
    registry.resolve("abc123", "approved")
    assert registry.resolve("abc123", "denied") is False


@pytest.mark.anyio
async def test_await_decision_times_out_returns_timed_out_and_clears_pending():
    registry = PendingActionRegistry()
    decision = await registry.await_decision("abc123", timeout=0.05)
    assert decision == "timed_out"
    assert registry.pending_ids() == []


@pytest.mark.anyio
async def test_await_decision_returns_resolved_decision_before_timeout():
    registry = PendingActionRegistry()

    async def resolve_soon():
        await asyncio.sleep(0.01)
        registry.resolve("abc123", "approved")

    task = asyncio.create_task(resolve_soon())
    decision = await registry.await_decision("abc123", timeout=5.0)
    await task
    assert decision == "approved"


def test_format_decision_result_wording_for_approved_vs_denied():
    action = ProposedAction(
        action_id="abc123",
        description="Reduce chlorine dose",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
    )
    approved = format_decision_result(action, "approved")
    assert "approved by operator" in approved
    assert "setpoint_adjustment" in approved
    assert "Chlorine_01" in approved

    denied = format_decision_result(action, "denied")
    assert "denied by operator (denied)" in denied
    assert "No changes will be made to Chlorine_01" in denied


def test_proposed_action_from_tool_input_defaults_value_to_empty_string():
    action = ProposedAction.from_tool_input(
        {
            "description": "Clear fault",
            "action_type": "fault_clear",
            "target": "RawWater_01",
        },
        action_id="abc123",
    )
    assert action.value == ""
    assert action.action_id == "abc123"
