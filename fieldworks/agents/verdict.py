"""Verdict blocks — the agent layer's output contract (spec Part III, Verdict Blocks).

Every Specialist (and the Historian) ends its response with a FINDINGS block;
Cascade opens an overview with a SUMMARY block. The blocks carry the status
the rest of the system acts on: equipment and area status, incident records,
graph incidents, and cross-plant answers (Part V).

The templates the prompts embed and the one parser for them live together
here, so they can't drift apart (waterworks-ai gh-25: five hand-written
parsers had). Pure text, no dependencies, no model provider.

Host behavior stays in the host: detecting a block while a response streams
(call parse(text, final=False) on the text so far), and the follow-up call
that obtains a missing FINDINGS block.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal, TypedDict

# Ordered least to most severe.
STATUSES: tuple[str, ...] = ("Normal", "Anomaly Detected", "Fault Detected")

FINDINGS_BLOCK = """FINDINGS:
Status: Normal | Anomaly Detected | Fault Detected
Confidence: 0.0–1.0
Key observations:
- [bullet points]"""

SUMMARY_BLOCK = """SUMMARY:
Status: Normal | Anomaly Detected | Fault Detected
Overview: [one or two plain-language sentences]
Key points:
- [bullet points — omit the list entirely if there is nothing notable]"""

FINDINGS_INSTRUCTION = f"""── Output format ──────────────────────────────────────────────────────────────
End your response with this block exactly:
{FINDINGS_BLOCK}"""

SUMMARY_INSTRUCTION = f"""── Synthesis output format ────────────────────────────────────────────────────
START every status overview with this block, before any detailed breakdown —
the findings are already in front of you, so lead with the conclusion:
{SUMMARY_BLOCK}

Status is the single most severe status among everything covered. Detailed
reasoning, tables and recommendations belong after this block, never before
it — it must not be pushed to the end, where a response length limit could
cut it off.

Omit this block for a conversational follow-up that is not a fresh status
overview."""


class Verdict(TypedDict):
    kind: Literal["findings", "summary"]
    status: str
    """Canonical spelling when it matches one of STATUSES; otherwise the
    model's text, verbatim — which is_known_status() reports as unknown."""
    confidence: float | None
    overview: str | None
    points: list[str]
    block: str
    """The exact substring parsed, so a reader holding the same text can
    show the rest without repeating the block."""


def is_known_status(status: str) -> bool:
    return status in STATUSES


def most_severe_status(statuses: Iterable[str]) -> str:
    """The most severe of the given statuses, by STATUSES order.

    An unrecognized status — including an agent or plant with no verdict —
    is unknown, and unknown ranks at least "Anomaly Detected": it is never
    quietly Normal. An empty input is Normal.
    """
    worst = 0
    floor = STATUSES.index("Anomaly Detected")
    for status in statuses:
        rank = STATUSES.index(status) if status in STATUSES else floor
        worst = max(worst, rank)
    return STATUSES[worst]


# Labels as models actually write them: optionally bolded ("**Status:**"),
# any case, with a stray blank line before the bullet list.
_B = r"\**"  # optional markdown bold around a label


def _label(name: str) -> str:
    return rf"^[ \t]*{_B}{name}{_B}:{_B}[ \t]*"


_HEADER = re.compile(rf"^[ \t]*{_B}(FINDINGS|SUMMARY){_B}:{_B}[ \t]*$", re.I | re.M)
_STATUS = re.compile(_label("Status") + r"(.+)$", re.I | re.M)
_CONFIDENCE = re.compile(_label("Confidence") + r"([0-9]*\.?[0-9]+)", re.I | re.M)
_OVERVIEW = re.compile(_label("Overview") + r"(.+)$", re.I | re.M)
_POINTS = re.compile(_label(r"Key (?:points|observations)") + r"$", re.I | re.M)
_BULLET = re.compile(r"^[ \t]*[-*•][ \t]+(.+)$")


def _status(raw: str) -> str:
    cleaned = raw.strip().strip("*").strip().rstrip(".").strip()
    for status in STATUSES:
        if cleaned.lower() == status.lower():
            return status
    return cleaned


def parse(text: str, final: bool = True) -> Verdict | None:
    """The last complete FINDINGS or SUMMARY block in `text`, or None.

    While a response is still streaming (final=False) a block only counts
    once a blank line follows it, so a half-written bullet list isn't
    reported; at the end of the response (final=True) the end of the text
    closes it too. The returned "block" is the exact substring parsed, so a
    reader holding the same text can show the rest without it.
    """
    text = text.replace("\r\n", "\n")
    for header in reversed(list(_HEADER.finditer(text))):
        verdict = _parse_block(text, header, final)
        if verdict is not None:
            return verdict
    return None


def _parse_block(text: str, header: re.Match, final: bool) -> Verdict | None:
    kind = header.group(1).lower()
    lines = text[header.end() :].split("\n")[1:]
    fields: dict[str, str] = {}
    points: list[str] = []
    in_points = False
    consumed = 0  # lines belonging to the block
    closed = False
    for i, line in enumerate(lines):
        if not line.strip():
            # One blank line may sit between the fields and the bullet list.
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not points and not in_points and _POINTS.match(nxt):
                consumed = i + 1
                continue
            closed = True
            break
        if in_points:
            bullet = _BULLET.match(line)
            if not bullet:
                closed = True
                break
            points.append(bullet.group(1).strip())
        elif m := _STATUS.match(line):
            fields["status"] = m.group(1)
        elif m := _CONFIDENCE.match(line):
            fields["confidence"] = m.group(1)
        elif m := _OVERVIEW.match(line):
            fields["overview"] = m.group(1).strip().strip("*").strip()
        elif _POINTS.match(line):
            in_points = True
        else:
            closed = True
            break
        consumed = i + 1

    if "status" not in fields or not (closed or final):
        return None
    if kind == "findings" and "confidence" not in fields:
        return None
    if kind == "summary" and "overview" not in fields:
        return None

    start = header.start()
    end = header.end() + sum(len(line) + 1 for line in lines[:consumed])
    end = min(end, len(text))
    return {
        "kind": kind,
        "status": _status(fields["status"]),
        "confidence": float(fields["confidence"]) if "confidence" in fields else None,
        "overview": fields.get("overview"),
        "points": points,
        "block": text[start:end].rstrip("\n"),
    }
