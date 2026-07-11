"""Tests for the Deadband agent contract."""


def test_deadband_tools_has_three_tools():
    from fieldworks.agents.deadband import DEADBAND_TOOLS

    names = {t["name"] for t in DEADBAND_TOOLS}
    assert names == {
        "verify_sustained",
        "get_trend_direction",
        "check_confidence_threshold",
    }


def test_deadband_tools_have_input_schema_shape():
    from fieldworks.agents.deadband import DEADBAND_TOOLS

    for tool in DEADBAND_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_severity_tiers_ordered_least_to_most_severe():
    from fieldworks.agents.deadband import SEVERITY_TIERS

    assert SEVERITY_TIERS == ("advisory", "warning", "critical")


def test_build_deadband_system_generic_without_facility_name():
    from fieldworks.agents.deadband import build_deadband_system

    prompt = build_deadband_system()
    assert "industrial process plant" in prompt
    assert "Deadband" in prompt


def test_build_deadband_system_includes_facility_name():
    from fieldworks.agents.deadband import build_deadband_system

    prompt = build_deadband_system("Riverside Water Treatment Plant")
    assert "Riverside Water Treatment Plant" in prompt


def test_build_deadband_system_mentions_all_three_tools():
    from fieldworks.agents.deadband import build_deadband_system

    prompt = build_deadband_system()
    assert "verify_sustained" in prompt
    assert "get_trend_direction" in prompt
    assert "check_confidence_threshold" in prompt


def test_check_confidence_threshold_above_threshold_escalates():
    from fieldworks.agents.deadband import check_confidence_threshold

    result = check_confidence_threshold(0.9, threshold=0.7)
    assert result == {"escalate": True, "confidence": 0.9, "threshold": 0.7}


def test_check_confidence_threshold_below_threshold_suppresses():
    from fieldworks.agents.deadband import check_confidence_threshold

    result = check_confidence_threshold(0.5, threshold=0.7)
    assert result["escalate"] is False


def test_check_confidence_threshold_default_threshold():
    from fieldworks.agents.deadband import check_confidence_threshold

    result = check_confidence_threshold(0.75)
    assert result["threshold"] == 0.7


def test_parse_decision_escalate():
    from fieldworks.agents.deadband import parse_decision

    escalate, reason = parse_decision(
        "Some analysis text.\nESCALATE: sustained and worsening trend"
    )
    assert escalate is True
    assert reason == "sustained and worsening trend"


def test_parse_decision_suppress():
    from fieldworks.agents.deadband import parse_decision

    escalate, reason = parse_decision("SUPPRESS: not sustained, improving")
    assert escalate is False
    assert reason == "not sustained, improving"


def test_parse_decision_no_marker_found():
    from fieldworks.agents.deadband import parse_decision

    escalate, reason = parse_decision("I am still thinking about this.")
    assert escalate is False
    assert reason == ""


def test_parse_decision_case_insensitive():
    from fieldworks.agents.deadband import parse_decision

    escalate, reason = parse_decision("escalate: lowercase marker")
    assert escalate is True
    assert reason == "lowercase marker"
