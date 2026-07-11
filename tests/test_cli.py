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
