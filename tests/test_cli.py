"""Tests for the fieldworks CLI's --seed and test-adapter flags."""

import shlex
import subprocess
import sys
from pathlib import Path

_FAKE_ADAPTER = Path(__file__).parent / "fixtures" / "fake_adapter.py"
_FIELDWORKS_BIN = Path(sys.executable).parent / "fieldworks"


def test_run_validate_seed_prints_counts(wtp_topology_path, capsys):
    from fieldworks.cli import _run_validate

    _run_validate(wtp_topology_path, None, seed=True)
    out = capsys.readouterr().out
    assert "valid" in out
    assert "seed check ok" in out
    assert "equipment instances" in out


def test_run_validate_without_seed_flag_skips_seeding(wtp_topology_path, capsys):
    from fieldworks.cli import _run_validate

    _run_validate(wtp_topology_path, None, seed=False)
    out = capsys.readouterr().out
    assert "valid" in out
    assert "seed check" not in out


def test_run_test_adapter_conformant_passes():
    """Shells out to the real installed CLI. run_conformance() spawns the
    adapter as its own subprocess over stdio, which doesn't play well with
    pytest's in-process stdout/stderr capture (capsys/capfd) — running the
    whole thing as a subprocess sidesteps that entirely."""
    result = subprocess.run(
        [
            str(_FIELDWORKS_BIN),
            "test-adapter",
            "--command",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(_FAKE_ADAPTER))} conformant",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "[PASS] tool discovery: required tools present" in result.stdout
    assert "[SKIP] connect: establishes a connection" in result.stdout


def test_run_test_adapter_broken_exits_nonzero():
    result = subprocess.run(
        [
            str(_FIELDWORKS_BIN),
            "test-adapter",
            "--command",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(_FAKE_ADAPTER))} broken",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "[FAIL]" in result.stdout


def _test_adapter(mode: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            str(_FIELDWORKS_BIN),
            "test-adapter",
            "--command",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(_FAKE_ADAPTER))} {mode}",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_run_test_adapter_runs_the_invalid_value_check_when_asked():
    tag = "Plant/WTP/Pump/RawWater_01/Flow"
    result = _test_adapter(
        "conformant",
        "--host",
        "localhost",
        "--write-tag",
        tag,
        "--invalid-value",
        "1e9",
    )
    assert result.returncode == 0, result.stdout
    assert "[PASS] write_tag: out-of-range value maps to INVALID_VALUE" in result.stdout
    assert "[PASS] read_tag: known tag returns a valid VQT envelope" in result.stdout


def test_run_test_adapter_needs_both_write_flags():
    result = _test_adapter("conformant", "--write-tag", "t")
    assert result.returncode == 1
    assert "usage:" in result.stderr


def _enterprise(tmp_path, site_id="wtp-riverside-01"):
    import shutil

    shutil.copy(Path(__file__).parent / "fixtures" / "wtp_topology.yaml", tmp_path)
    path = tmp_path / "enterprise.yaml"
    path.write_text(
        "enterprise: {name: Metro}\n"
        "regions:\n"
        "  - id: metro\n"
        "    name: Metro\n"
        "    sites:\n"
        f"      - {{site_id: {site_id}, name: R, topology_file: wtp_topology.yaml,"
        " chat_ui_url: 'http://r'}\n"
    )
    return path


def test_validate_enterprise_valid(tmp_path, capsys):
    from fieldworks.cli import _run_validate_enterprise

    _run_validate_enterprise(_enterprise(tmp_path))
    assert "valid — Metro, 1 region(s), 1 site(s)" in capsys.readouterr().out


def test_validate_enterprise_site_id_mismatch_exits_nonzero(tmp_path, capsys):
    import pytest

    from fieldworks.cli import _run_validate_enterprise

    with pytest.raises(SystemExit) as exc:
        _run_validate_enterprise(_enterprise(tmp_path, site_id="other"))
    assert exc.value.code == 1
    assert "declares facility.site_id" in capsys.readouterr().err
