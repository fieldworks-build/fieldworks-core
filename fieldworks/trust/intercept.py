"""Propose/approve/execute interception contract — SUPERVISED trust mode.

An agent that wants to write to a process (change a setpoint, clear a fault)
calls `propose_action` instead of writing directly. The host application
intercepts that tool call before it reaches the target MCP server, presents it
to an operator, and only allows execution to proceed on approval.

This module defines the data shapes and the pending-decision registry — the
parts of that flow that are transport-independent. What stays application
specific:

- Matching a tool call's name against `PROPOSE_ACTION_TOOL`. Real deployments
  route tool calls through an MCP aggregator that namespaces tool names by
  server (e.g. "control__propose_action"), so the exact match expression is
  the app's job.
- Presenting the proposal to an operator (SSE push, polling, a CLI prompt —
  whatever the host's UI layer is) and eventually calling `resolve()`.
- Running the agent loop itself; `await_decision` just wraps the asyncio wait.

ADVISORY/COLLABORATIVE/AUTONOMOUS trust modes (recommend-only, threshold-only,
and no-intercept-but-log respectively) are not implemented here — this module
covers only the SUPERVISED intercept-every-write mechanism.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

PROPOSE_ACTION_TOOL = "propose_action"

PROPOSE_ACTION_SCHEMA: dict[str, Any] = {
    "name": PROPOSE_ACTION_TOOL,
    "description": (
        "Propose a control action requiring operator approval before "
        "execution. The host intercepts this call and presents it to the "
        "operator. This tool BLOCKS until the operator decides. After "
        "approval, call the appropriate execution tool."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": (
                    "Plain-language rationale, e.g. 'Reduce chlorine dose "
                    "from 3.5 to 2.8 L/h — current reading is elevated vs "
                    "turbidity trend'"
                ),
            },
            "action_type": {
                "type": "string",
                "description": "e.g. 'setpoint_adjustment', 'fault_clear'",
            },
            "target": {
                "type": "string",
                "description": "Equipment ID, e.g. 'Chlorine_01'",
            },
            "value": {
                "type": "string",
                "description": "New value for setpoint adjustments; omit for fault clears",
                "default": "",
            },
        },
        "required": ["description", "action_type", "target"],
    },
}


def generate_action_id() -> str:
    """A short, URL-safe identifier for a proposed action."""
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class ProposedAction:
    """A single propose_action call, captured for the approval flow."""

    action_id: str
    description: str
    action_type: str
    target: str
    value: str = ""

    @classmethod
    def from_tool_input(
        cls, args: dict[str, Any], action_id: str | None = None
    ) -> ProposedAction:
        return cls(
            action_id=action_id or generate_action_id(),
            description=args.get("description", ""),
            action_type=args.get("action_type", ""),
            target=args.get("target", ""),
            value=str(args.get("value", "")),
        )


def format_decision_result(action: ProposedAction, decision: str) -> str:
    """Synthesize the tool-result text injected back into the conversation."""
    if decision == "approved":
        return (
            f"Action approved by operator. "
            f"Proceed with {action.action_type or 'action'} "
            f"on {action.target or 'target'}."
        )
    return (
        f"Action denied by operator ({decision}). "
        f"No changes will be made to {action.target or 'target'}."
    )


class PendingActionRegistry:
    """Tracks in-flight action proposals awaiting an operator decision.

    Single-process, in-memory. If a deployment horizontally scales the
    conversation loop across workers, the worker that registers an action
    must also be the one that resolves it — session affinity is the host's
    responsibility, not this registry's.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}

    def register(self, action_id: str) -> asyncio.Future[str]:
        """Create and store a Future for the given action_id."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[action_id] = fut
        return fut

    def resolve(self, action_id: str, decision: str) -> bool:
        """Resolve a pending action with the operator's decision.

        Returns True if the action was found and resolved, False otherwise
        (unknown id, or already resolved/timed out).
        """
        fut = self._pending.pop(action_id, None)
        if not fut or fut.done():
            return False
        fut.set_result(decision)
        return True

    def pending_ids(self) -> list[str]:
        return list(self._pending.keys())

    async def await_decision(self, action_id: str, timeout: float) -> str:
        """Register `action_id` and block until resolved or timed out.

        Returns the resolved decision string, or "timed_out" if no decision
        arrives within `timeout` seconds.
        """
        fut = self.register(action_id)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(action_id, None)
            return "timed_out"
