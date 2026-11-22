"""Tests for the cross-plant orchestrator contract (fieldworks.agents.enterprise)."""

import pytest

from fieldworks.agents import (
    ENTERPRISE_TOOLS,
    build_enterprise_system,
    format_plant_status,
    format_plant_summary,
    format_plant_unknown,
    format_unknown_site,
    most_severe_status,
)
from fieldworks.enterprise import EnterpriseConfig


def _config(sites=True) -> EnterpriseConfig:
    return EnterpriseConfig.model_validate(
        {
            "enterprise": {"name": "Metro Water"},
            "regions": [
                {
                    "id": "metro",
                    "name": "Metro Region",
                    "sites": (
                        [
                            {
                                "site_id": "east",
                                "name": "Eastside",
                                "topology_file": "e.yaml",
                                "chat_ui_url": "http://e",
                            },
                            {
                                "site_id": "west",
                                "name": "Westside",
                                "topology_file": "w.yaml",
                                "chat_ui_url": "http://w",
                            },
                        ]
                        if sites
                        else []
                    ),
                }
            ],
        }
    )


def test_exactly_two_tools_and_no_write_or_proposal_tool():
    names = {t["name"] for t in ENTERPRISE_TOOLS}
    assert names == {"get_plant_status", "diagnose_plant"}
    for tool in ENTERPRISE_TOOLS:
        assert "site_id" in tool["input_schema"]["required"]


def test_system_prompt_lists_every_site_with_region():
    prompt = build_enterprise_system(_config())
    assert "Metro Water, a multi-plant enterprise" in prompt
    assert "  - east: Eastside (Metro Region)" in prompt
    assert "  - west: Westside (Metro Region)" in prompt


def test_system_prompt_kind_is_optional_and_plant_agnostic_by_default():
    assert "water utility" not in build_enterprise_system(_config())
    assert "Metro Water, a multi-plant water utility" in build_enterprise_system(
        _config(), kind="water utility"
    )


def test_system_prompt_with_no_sites():
    assert "(no sites registered in enterprise.yaml)" in build_enterprise_system(
        _config(sites=False)
    )


def test_system_prompt_states_part_v_limits():
    prompt = build_enterprise_system(_config())
    assert "cannot propose, approve or execute any action" in prompt
    assert "never report it as normal" in prompt
    assert "SUMMARY:" in prompt


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ([], "Normal"),
        (["Normal", "Normal"], "Normal"),
        (["Normal", "Anomaly Detected"], "Anomaly Detected"),
        (["Fault Detected", "Normal", "Anomaly Detected"], "Fault Detected"),
        (["Normal", "unknown"], "Anomaly Detected"),
        (["Fault Detected", "unknown"], "Fault Detected"),
    ],
)
def test_most_severe_status(statuses, expected):
    assert most_severe_status(statuses) == expected


def test_format_plant_summary_from_verdict():
    verdict = {
        "status": "Anomaly Detected",
        "overview": "Turbidity rising at intake.",
        "confidence": 0.8,
        "points": ["RawWater_01 vibration high"],
    }
    assert format_plant_summary("east", verdict, "ignored") == (
        "[east] Status: Anomaly Detected\n"
        "Overview: Turbidity rising at intake.\n"
        "Confidence: 0.8\n"
        "Key points:\n"
        "- RawWater_01 vibration high"
    )


def test_format_plant_summary_without_verdict_truncates_text():
    assert format_plant_summary("east", None, "  hello  ") == "[east] hello"
    assert (
        format_plant_summary("east", None, "x" * 50, max_chars=10)
        == "[east] " + "x" * 10
    )
    assert format_plant_summary("east", None, "") == "[east] (empty response)"


def test_format_plant_status_includes_as_of():
    assert format_plant_status("east", "Normal", "2026-11-22T10:00Z", "All good.") == (
        "[east] Status: Normal (as of 2026-11-22T10:00Z)\nAll good."
    )


def test_format_plant_unknown_never_reads_as_normal():
    msg = format_plant_unknown("east", "did not respond within 240s")
    assert msg.startswith("[east] Status unknown — did not respond within 240s.")
    assert "not confirmed normal" in msg


def test_format_unknown_site_lists_known():
    assert format_unknown_site("zzz", ["west", "east"]) == (
        "Error: unknown site_id 'zzz'. Known sites: east, west."
    )
    assert "(none registered)" in format_unknown_site("zzz", [])
