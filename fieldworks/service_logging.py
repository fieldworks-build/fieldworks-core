"""Logging setup for Fieldworks services.

Every reference service logs the same way: a logs/ directory next to the
service, a rotating file, and the console, in one format. Call once at
startup, before anything logs:

    from fieldworks.service_logging import setup_logging

    setup_logging(__file__, "audit_mcp")

Rotation defaults to 5 MB x 3 backups; FIELDWORKS_LOG_MAX_BYTES and
FIELDWORKS_LOG_BACKUPS override it. Both are read on each call, not at import.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


def setup_logging(
    service_file: str | Path,
    log_name: str,
    *,
    level: int = logging.INFO,
    console: TextIO | None = None,
) -> Path:
    """Log to <service dir>/logs/<log_name>.log and to the console.

    `service_file` is the calling module's __file__. `console` defaults to
    stderr; pass sys.stdout for a service whose wrapper (e.g. NSSM on
    Windows) captures stdout and stderr to separate files. Returns the log
    path.

    Uses logging.basicConfig, so it does nothing if the root logger already
    has handlers — a second call, or one after something else configured
    logging, leaves the first setup in place.
    """
    log_dir = Path(service_file).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{log_name}.log"
    formatter = logging.Formatter(FORMAT, datefmt=DATEFMT)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=int(os.environ.get("FIELDWORKS_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)),
        backupCount=int(os.environ.get("FIELDWORKS_LOG_BACKUPS", DEFAULT_BACKUP_COUNT)),
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(console or sys.stderr)
    console_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[console_handler, file_handler])
    return log_path
