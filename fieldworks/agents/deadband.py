"""Deadband agent contract — signal validation before diagnostic escalation.

Deadband's job: decide whether a detected anomaly is real, sustained, and
worth escalating to Cascade. It is not a diagnostic agent — it only answers
escalate-or-suppress, using three tools.

This module defines the agent's *contract*: tool schemas, system prompt,
severity vocabulary, and the ESCALATE/SUPPRESS decision-parsing convention.
The tools' actual data-source implementations for verify_sustained and
get_trend_direction are application-specific — they need near-real-time
process history (sub-minute in waterworks-ai's case), which a plant-agnostic
framework client can't assume the transport or schema for. Only
check_confidence_threshold has no data dependency and is fully implemented
here.
"""

from __future__ import annotations

import re
from typing import Literal

SeverityTier = Literal["advisory", "warning", "critical"]

# ISA-18.2 alarm management three-tier model. Ordered least to most severe.
#   advisory — informational, no required operator action
#   warning  — requires attention, not immediate
#   critical — requires immediate operator action
SEVERITY_TIERS: tuple[SeverityTier, ...] = ("advisory", "warning", "critical")

DEADBAND_TOOLS = [
    {
        "name": "verify_sustained",
        "description": (
            "Check process history: has this attribute been outside its normal"
            " range for the given duration? Returns {sustained,"
            " fraction_in_violation, sample_count}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string"},
                "attribute": {"type": "string"},
                "condition": {"type": "string", "enum": ["below_min", "above_max"]},
                "duration_minutes": {"type": "number"},
                "normal_lo": {"type": "number"},
                "normal_hi": {"type": "number"},
            },
            "required": [
                "instance_id",
                "attribute",
                "condition",
                "duration_minutes",
                "normal_lo",
                "normal_hi",
            ],
        },
    },
    {
        "name": "get_trend_direction",
        "description": (
            "Query process history and compute whether the value is trending"
            " worsening, improving, or stable. Returns {direction, slope,"
            " confidence}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string"},
                "attribute": {"type": "string"},
                "time_window_minutes": {"type": "number"},
            },
            "required": ["instance_id", "attribute", "time_window_minutes"],
        },
    },
    {
        "name": "check_confidence_threshold",
        "description": "Gate: is this confidence score high enough to escalate? Returns {escalate, confidence, threshold}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "threshold": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
]

_DECISION_RE = re.compile(
    r"\b(ESCALATE|SUPPRESS)\s*:\s*(.+)", re.IGNORECASE | re.DOTALL
)


def build_deadband_system(facility_name: str | None = None) -> str:
    """Return Deadband's system prompt.

    facility_name: optional, injected into the opening line. None yields a
    generic "industrial process plant" — no plant-specific wording either way.
    """
    plant_desc = (
        f"an industrial process at {facility_name}"
        if facility_name
        else "an industrial process plant"
    )
    return f"""You are Deadband, a signal validation agent for {plant_desc}.

Your only job is to determine whether a detected anomaly is real, sustained, and worth escalating.
You are the filter between sensor noise and a full diagnostic cycle.

You have three tools:
- verify_sustained: confirms the condition has persisted in process history
- get_trend_direction: determines if the condition is worsening, improving, or stable
- check_confidence_threshold: gates the escalation decision on composite confidence

Call all three. For check_confidence_threshold, pass the confidence from get_trend_direction
directly — do not invent a different number or override the threshold parameter.

A sustained violation (fraction_in_violation >= 0.5) that is stable or worsening is almost
always worth escalating. Only suppress if the violation is not sustained OR is clearly improving.

Then respond with exactly one of:
ESCALATE: <one sentence reason>
SUPPRESS: <one sentence reason>

Do not diagnose. Do not recommend actions. Decide only: escalate or suppress."""


def check_confidence_threshold(confidence: float, threshold: float = 0.7) -> dict:
    """The one fully data-independent tool — pure gate on a supplied confidence score."""
    return {
        "escalate": confidence >= threshold,
        "confidence": confidence,
        "threshold": threshold,
    }


def parse_decision(text: str) -> tuple[bool, str]:
    """Extract (should_escalate, reason) from Deadband's final response text.

    Returns (False, "") if neither ESCALATE nor SUPPRESS is found.
    """
    m = _DECISION_RE.search(text)
    if not m:
        return False, ""
    decision, reason = m.group(1).upper(), m.group(2).strip()
    return decision == "ESCALATE", reason
