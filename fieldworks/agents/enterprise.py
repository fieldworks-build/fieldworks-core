"""Cross-plant orchestrator contract (spec Part V, The Cross-Plant Orchestrator).

The orchestrator is Cascade-shaped, with plants in place of specialists. It
has exactly two tools, each scoped to one plant by site_id, and no other
way to learn anything about a plant. This module defines its contract: the
tool schemas, the system prompt, and how a plant's answer is reported back
to it. The agentic loop, the model provider and the transport to each plant
stay in the host, as they do for Cascade and Deadband — fieldworks-core
depends on no model provider.

What the orchestrator must not do is structural, not prompted: the host
gives it these two tools and nothing else — no aggregator URL, no adapter
or store credentials, no write or proposal tool.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fieldworks.enterprise.schema import EnterpriseConfig

# Ordered least to most severe. The overall status of a cross-plant answer
# is the most severe status among the plants checked.
PLANT_STATUSES: tuple[str, ...] = ("Normal", "Anomaly Detected", "Fault Detected")

_SITE_ID_PARAM = {
    "type": "string",
    "description": "Plant identifier from enterprise.yaml.",
}

ENTERPRISE_TOOLS = [
    {
        "name": "get_plant_status",
        "description": (
            "Get one plant's last periodic status check: a status level, a"
            " short narrative and the time it was produced. Fast, because the"
            " plant computes it in the background, but can be stale. Use for"
            " overview and status questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"site_id": _SITE_ID_PARAM},
            "required": ["site_id"],
        },
    },
    {
        "name": "diagnose_plant",
        "description": (
            "Ask one plant's own multi-agent diagnostic system a question and"
            " return its synthesized summary. Always current, but runs a live"
            " diagnosis at the plant, so it is slow. Use for drill-down into a"
            " specific issue, or when a fresh check is asked for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": _SITE_ID_PARAM,
                "query": {
                    "type": "string",
                    "description": "Natural-language diagnostic question for that plant.",
                },
            },
            "required": ["site_id", "query"],
        },
    },
]

SUMMARY_BLOCK = """SUMMARY:
Status: Normal | Anomaly Detected | Fault Detected
Overview: [one or two plain-language sentences covering every plant you checked]
Key points:
- [one bullet per plant with anything notable — omit the list entirely if there is nothing notable]"""


def build_enterprise_system(config: "EnterpriseConfig", *, kind: str = "") -> str:
    """System prompt for the cross-plant orchestrator.

    Args:
        config: The loaded enterprise registry; every registered site is
            listed with its region.
        kind: Optional plain-language description of the enterprise, e.g.
            "water utility". Plant-agnostic by default.
    """
    sites = config.sites()
    if sites:
        site_lines = "\n".join(
            f"  - {site_id}: {site.name} ({site.region_name})"
            for site_id, site in sorted(sites.items())
        )
    else:
        site_lines = "  (no sites registered in enterprise.yaml)"
    described = f"{config.enterprise.name}, a multi-plant {kind or 'enterprise'}"

    return f"""You are the enterprise-level diagnostics coordinator for {described}.
Each plant runs its own complete diagnostic system. You have no direct access
to any plant's sensors, historian or controls — you have exactly two tools,
both scoped to one plant at a time via site_id:

  get_plant_status(site_id)       The plant's last periodic status check.
                                  Near-instant. Can be stale; each answer says
                                  when it was produced.
  diagnose_plant(site_id, query)  A fresh, live diagnosis by that plant's own
                                  agents. Always current, but slow.

Registered plants:
{site_lines}

Default to get_plant_status for overview questions ("what's the status", "is
everything okay", "any issues right now"). Use diagnose_plant only when the
question needs real drill-down: investigating specific equipment, verifying
something get_plant_status flagged, or when a fresh check is asked for. If a
plant has no status check recorded yet, use diagnose_plant for that plant.

For a question about one plant, call one tool once for that plant. For a
cross-plant question, call a tool once per relevant plant, then synthesize a
single answer that attributes every finding to its site_id.

Never state a plant's status without calling a tool for it — you have no
other source of truth. A plant that errors or times out has an UNKNOWN
status: say so, and never report it as normal. When you answer from
get_plant_status, say that each status is the plant's last periodic check
and give its time.

You cannot propose, approve or execute any action at any plant. If a plant's
answer mentions an action awaiting approval, that decision belongs to the
plant's own operators; report it, don't act on it.

── Diagnostic output format ──────────────────────────────────────────────────

Start every status-overview response with this block, before any per-plant
detail:

{SUMMARY_BLOCK}

Status must be the single most severe status among every plant checked: one
plant at "Fault Detected" makes the overall Status "Fault Detected" even if
every other plant is Normal. A plant whose status is unknown makes the
overall Status at least "Anomaly Detected", and the Overview must name it.
Per-plant reasoning comes after the block, never before it.

Omit the block for follow-up conversational replies that are not a fresh
status overview."""


def most_severe_status(statuses: Iterable[str]) -> str:
    """The most severe of the given plant statuses, by PLANT_STATUSES order.

    An unrecognized status (including an unknown plant) counts as at least
    "Anomaly Detected" — an unknown is never quietly Normal.
    """
    worst = 0
    for status in statuses:
        rank = (
            PLANT_STATUSES.index(status)
            if status in PLANT_STATUSES
            else PLANT_STATUSES.index("Anomaly Detected")
        )
        worst = max(worst, rank)
    return PLANT_STATUSES[worst]


def format_plant_summary(
    site_id: str, verdict: dict | None, text: str, *, max_chars: int = 2000
) -> str:
    """A diagnose_plant answer, as the orchestrator sees it.

    Uses the plant's parsed SUMMARY/FINDINGS verdict when it sent one
    (keys: status, overview, confidence, points); otherwise the plant's
    raw text, truncated, for conversational replies without a block.
    """
    if verdict is None:
        body = text.strip()[:max_chars] or "(empty response)"
        return f"[{site_id}] {body}"
    lines = [f"Status: {verdict['status']}"]
    if verdict.get("overview"):
        lines.append(f"Overview: {verdict['overview']}")
    if verdict.get("confidence") is not None:
        lines.append(f"Confidence: {verdict['confidence']}")
    if verdict.get("points"):
        lines.append("Key points:")
        lines.extend(f"- {p}" for p in verdict["points"])
    return f"[{site_id}] " + "\n".join(lines)


def format_plant_status(
    site_id: str, status_level: str, as_of: str, narrative: str
) -> str:
    """A get_plant_status answer, as the orchestrator sees it."""
    return f"[{site_id}] Status: {status_level} (as of {as_of})\n{narrative}"


def format_plant_unknown(site_id: str, reason: str) -> str:
    """Report a plant that failed, timed out or couldn't be reached.

    The wording is the contract: the orchestrator must read this as an
    unknown status, never as a quiet plant.
    """
    return (
        f"[{site_id}] Status unknown — {reason}. Treat this plant's status as"
        " unknown, not confirmed normal."
    )


def format_unknown_site(site_id: str, known: Iterable[str]) -> str:
    """Reply for a site_id that isn't registered."""
    listed = ", ".join(sorted(known)) or "(none registered)"
    return f"Error: unknown site_id {site_id!r}. Known sites: {listed}."
