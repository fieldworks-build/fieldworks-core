"""Tests for fieldworks.service_logging.setup_logging (fieldworks-core#40)."""

import io
import logging
from contextlib import contextmanager

from fieldworks.service_logging import setup_logging


@contextmanager
def bare_root_logger():
    """basicConfig only configures a root logger with no handlers, and pytest's
    logging plugin adds its own at the start of the test body — after any
    fixture runs — so strip them inside the test and restore after."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers = []
    try:
        yield root
    finally:
        for h in root.handlers:
            h.close()
        root.handlers, root.level = saved, level


def _rotating_handler(root):
    return next(h for h in root.handlers if hasattr(h, "maxBytes"))


def test_logs_to_file_next_to_the_service_and_to_the_console(tmp_path):
    service = tmp_path / "some-mcp" / "server.py"
    service.parent.mkdir()
    console = io.StringIO()

    with bare_root_logger() as root:
        path = setup_logging(service, "some_mcp", console=console)
        logging.getLogger("some.module").info("hello")
        handler = _rotating_handler(root)
        rotation = (handler.maxBytes, handler.backupCount)

    assert path == tmp_path / "some-mcp" / "logs" / "some_mcp.log"
    line = path.read_text().strip()
    assert line.endswith("INFO some.module: hello")
    assert console.getvalue().strip() == line
    assert rotation == (5 * 1024 * 1024, 3)


def test_rotation_is_env_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("FIELDWORKS_LOG_MAX_BYTES", "1024")
    monkeypatch.setenv("FIELDWORKS_LOG_BACKUPS", "7")

    with bare_root_logger() as root:
        setup_logging(tmp_path / "server.py", "svc", console=io.StringIO())
        handler = _rotating_handler(root)
        rotation = (handler.maxBytes, handler.backupCount)

    assert rotation == (1024, 7)


def test_second_call_keeps_the_first_setup(tmp_path):
    with bare_root_logger() as root:
        first = setup_logging(tmp_path / "server.py", "first", console=io.StringIO())
        setup_logging(tmp_path / "server.py", "second", console=io.StringIO())
        files = [h.baseFilename for h in root.handlers if hasattr(h, "maxBytes")]

    assert files == [str(first)]
