"""Tests for file-based specialist memory."""


def test_get_returns_empty_string_when_no_file(tmp_path):
    from fieldworks.memory.specialist import SpecialistMemory

    mem = SpecialistMemory(tmp_path)
    assert mem.get("intake") == ""


def test_append_then_get_roundtrips(tmp_path):
    from fieldworks.memory.specialist import SpecialistMemory

    mem = SpecialistMemory(tmp_path)
    mem.append("intake", "Raw water turbidity trending up.")
    content = mem.get("intake")
    assert "Raw water turbidity trending up." in content


def test_append_includes_timestamp_header(tmp_path):
    from fieldworks.memory.specialist import SpecialistMemory

    mem = SpecialistMemory(tmp_path)
    mem.append("intake", "Finding one.")
    content = mem.get("intake")
    assert "## " in content
    assert "UTC" in content


def test_multiple_appends_accumulate(tmp_path):
    from fieldworks.memory.specialist import SpecialistMemory

    mem = SpecialistMemory(tmp_path)
    mem.append("treatment", "First finding.")
    mem.append("treatment", "Second finding.")
    content = mem.get("treatment")
    assert "First finding." in content
    assert "Second finding." in content


def test_specialists_have_independent_files(tmp_path):
    from fieldworks.memory.specialist import SpecialistMemory

    mem = SpecialistMemory(tmp_path)
    mem.append("intake", "Intake note.")
    mem.append("distribution", "Distribution note.")
    assert "Intake note." in mem.get("intake")
    assert "Intake note." not in mem.get("distribution")
    assert "Distribution note." in mem.get("distribution")


def test_creates_memory_dir_if_missing(tmp_path):
    from fieldworks.memory.specialist import SpecialistMemory

    memory_dir = tmp_path / "nested" / "specialist-memory"
    mem = SpecialistMemory(memory_dir)
    mem.append("intake", "Note.")
    assert memory_dir.exists()
