"""Tests for fieldworks.service_env.check_env_file / env_source."""

import io
import logging

import pytest

from fieldworks import service_env
from fieldworks.service_env import check_env_file, env_source
from fieldworks.service_logging import setup_logging


@pytest.fixture(autouse=True)
def _fresh_state():
    service_env._sources.clear()
    service_env._pending.clear()
    yield
    service_env._sources.clear()
    service_env._pending.clear()


def _env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_duplicate_key_names_every_line_and_the_one_that_wins(tmp_path):
    path = _env(
        tmp_path,
        "ANTHROPIC_API_KEY=sk-old\nOTHER=1\n# ANTHROPIC_API_KEY=commented\n"
        "export ANTHROPIC_API_KEY=sk-new\n",
    )
    warnings = check_env_file(path, environ={})
    assert warnings == [
        f"ANTHROPIC_API_KEY is set on lines 1, 4 of {path.resolve()}; "
        "only line 4 takes effect"
    ]
    assert env_source("ANTHROPIC_API_KEY") == f"{path.resolve()} line 4"


def test_last_line_wins_like_python_dotenv(tmp_path):
    dotenv = pytest.importorskip("dotenv")
    path = _env(tmp_path, "KEY=first\nKEY=second\n")
    check_env_file(path, environ={})
    assert dotenv.dotenv_values(path)["KEY"] == "second"
    assert env_source("KEY").endswith("line 2")


def test_shell_value_that_shadows_env_file_is_reported(tmp_path):
    path = _env(tmp_path, "ANTHROPIC_API_KEY=sk-from-file\n")
    warnings = check_env_file(path, environ={"ANTHROPIC_API_KEY": "sk-stale"})
    assert len(warnings) == 1
    assert "already set in the process environment" in warnings[0]
    assert "line 1" in warnings[0]
    assert env_source("ANTHROPIC_API_KEY") == "the process environment"


def test_matching_shell_value_is_not_a_problem(tmp_path):
    path = _env(tmp_path, 'PORT="8010"  # eastside\n')
    assert check_env_file(path, environ={"PORT": "8010"}) == []


def test_warnings_never_contain_values(tmp_path):
    path = _env(tmp_path, "SECRET=hunter2\nSECRET=hunter3\n")
    warnings = check_env_file(path, environ={"SECRET": "shell-secret"})
    assert warnings
    for message in warnings:
        assert "hunter" not in message and "shell-secret" not in message


def test_missing_file_is_fine(tmp_path):
    assert check_env_file(tmp_path / "nope.env") == []
    assert check_env_file(None) == []
    assert check_env_file("") == []


def test_warnings_before_logging_are_logged_by_setup_logging(tmp_path):
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers = []
    try:
        path = _env(tmp_path, "KEY=1\nKEY=2\n")
        check_env_file(path, environ={})
        assert service_env._pending  # held: nothing could log it yet
        console = io.StringIO()
        setup_logging(tmp_path / "server.py", "svc", console=console)
        assert not service_env._pending
        assert "KEY is set on lines 1, 2" in console.getvalue()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers, root.level = saved, level


def test_env_source_without_a_check_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("ONLY_IN_ENV", "x")
    monkeypatch.delenv("NOWHERE", raising=False)
    assert env_source("ONLY_IN_ENV") == "the process environment"
    assert env_source("NOWHERE") is None
