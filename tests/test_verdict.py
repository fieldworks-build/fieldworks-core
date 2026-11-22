"""fieldworks.agents.verdict — the FINDINGS/SUMMARY output contract (spec Part III).

Parser cases ported from waterworks-ai's tests/test_verdict.py, including the
gh-25 inputs: a model that bolds its labels and leaves a blank line before
"Key points:" used to parse in one place and not another.
"""

import pytest

from fieldworks.agents import verdict

SUMMARY = (
    "SUMMARY:\n"
    "Status: Fault Detected\n"
    "Overview: RawWater_01 shows suction starvation.\n"
    "Key points:\n"
    "- Flow near zero\n"
    "- Pressure dropping\n"
    "\n"
    "Detailed reasoning follows..."
)
FINDINGS = (
    "Checked the pump.\n\n"
    "FINDINGS:\n"
    "Status: Anomaly Detected\n"
    "Confidence: 0.72\n"
    "Key observations:\n"
    "- Vibration elevated\n"
    "- Flow steady"
)


def test_summary_block():
    v = verdict.parse(SUMMARY)
    assert v["kind"] == "summary"
    assert v["status"] == "Fault Detected"
    assert v["overview"] == "RawWater_01 shows suction starvation."
    assert v["points"] == ["Flow near zero", "Pressure dropping"]
    assert v["confidence"] is None
    assert v["block"] == SUMMARY.split("\n\n")[0]


def test_findings_block():
    v = verdict.parse(FINDINGS)
    assert (v["kind"], v["status"], v["confidence"]) == (
        "findings",
        "Anomaly Detected",
        0.72,
    )
    assert v["points"] == ["Vibration elevated", "Flow steady"]
    assert v["block"] == FINDINGS[FINDINGS.index("FINDINGS:") :]


@pytest.mark.parametrize(
    "text",
    [
        # gh-25: bold labels and a blank line before the list
        "SUMMARY:\n**Status:** Fault Detected\n**Overview:** Starving.\n\n"
        "**Key points:**\n- Flow near zero\n\nMore",
        "SUMMARY:\n**Status: Fault Detected**\n**Overview: Starving.**\n"
        "Key points:\n- Flow near zero\n",
        "**SUMMARY:**\nstatus: fault detected.\noverview: Starving.\n"
        "key points:\n* Flow near zero\n",
        "SUMMARY:\r\nStatus: Fault Detected\r\nOverview: Starving.\r\n"
        "Key points:\r\n- Flow near zero\r\n",
    ],
    ids=["bold-labels-blank-line", "bold-lines", "lowercase-star-bullets", "crlf"],
)
def test_formatting_variants_parse_the_same(text):
    v = verdict.parse(text)
    assert (v["status"], v["overview"], v["points"]) == (
        "Fault Detected",
        "Starving.",
        ["Flow near zero"],
    )


def test_summary_without_points():
    v = verdict.parse("SUMMARY:\nStatus: Normal\nOverview: Quiet.\n\nRest of answer.")
    assert v["points"] == [] and v["overview"] == "Quiet."


def test_unknown_status_is_kept_verbatim():
    v = verdict.parse("SUMMARY:\nStatus: Degraded\nOverview: Hmm.\n")
    assert v["status"] == "Degraded"


@pytest.mark.parametrize(
    "text",
    [
        "Just chatting, nothing to report.",
        "SUMMARY:\nOverview: no status line\n",
        "FINDINGS:\nStatus: Normal\nKey observations:\n- missing confidence\n",
        "SUMMARY:\nStatus: Normal\n",  # no overview
    ],
)
def test_incomplete_or_absent_blocks(text):
    assert verdict.parse(text) is None


def test_last_block_wins():
    first = "FINDINGS:\nStatus: Normal\nConfidence: 0.5\nKey observations:\n- a\n\n"
    v = verdict.parse(first + FINDINGS)
    assert v["status"] == "Anomaly Detected"


def test_streaming_waits_for_the_block_to_close():
    open_list = "SUMMARY:\nStatus: Normal\nOverview: Ok.\nKey points:\n- partial"
    assert verdict.parse(open_list, final=False) is None
    assert verdict.parse(open_list, final=True)["points"] == ["partial"]
    assert verdict.parse(open_list + "\n\nMore", final=False)["points"] == ["partial"]


def test_parsed_verdict_has_no_stream_event_fields():
    """The {"type": "verdict"} event wrapper is the host's stream shape."""
    assert "type" not in verdict.parse(SUMMARY)


@pytest.mark.parametrize(
    "status,known",
    [("Normal", True), ("Fault Detected", True), ("Degraded", False), ("", False)],
)
def test_is_known_status(status, known):
    assert verdict.is_known_status(status) is known


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ([], "Normal"),
        (["Normal", "Anomaly Detected"], "Anomaly Detected"),
        (["Fault Detected", "Normal"], "Fault Detected"),
        (["Normal", "Degraded"], "Anomaly Detected"),  # unknown is never Normal
    ],
)
def test_most_severe_status(statuses, expected):
    assert verdict.most_severe_status(statuses) == expected


def test_templates_round_trip_through_the_parser():
    """A model that fills in the templates literally produces a verdict."""
    findings = verdict.FINDINGS_BLOCK.replace(
        "Normal | Anomaly Detected | Fault Detected", "Normal"
    ).replace("0.0–1.0", "0.9")
    summary = verdict.SUMMARY_BLOCK.replace(
        "Normal | Anomaly Detected | Fault Detected", "Normal"
    )
    assert verdict.parse(findings)["kind"] == "findings"
    assert verdict.parse(summary)["kind"] == "summary"


def test_specialist_prompt_ends_with_the_findings_instruction(wtp_topology):
    from fieldworks.agents import build_specialist_prompt

    area = wtp_topology.process_areas[0].id
    prompt = build_specialist_prompt(area, wtp_topology)
    assert prompt.endswith(verdict.FINDINGS_BLOCK)
    assert prompt.count("FINDINGS:") == 1


def test_orchestrator_prompt_carries_the_summary_instruction(wtp_topology):
    from fieldworks.agents import build_orchestrator_system, build_specialists

    prompt = build_orchestrator_system(build_specialists(wtp_topology), wtp_topology)
    assert verdict.SUMMARY_BLOCK in prompt
    assert prompt.count("SUMMARY:") == 1


def test_enterprise_prompt_uses_the_shared_summary_template():
    from fieldworks.agents import build_enterprise_system
    from fieldworks.enterprise import EnterpriseConfig

    config = EnterpriseConfig.model_validate(
        {"enterprise": {"name": "E"}, "regions": []}
    )
    assert verdict.SUMMARY_BLOCK in build_enterprise_system(config)
