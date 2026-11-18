"""Checks for a Fieldworks service's .env file.

Services load settings with python-dotenv, which applies the *last* line for
a key and never overrides a variable already in the process environment.
Both rules fail silently: an extra ANTHROPIC_API_KEY line further down the
file, or a stale key exported in the shell, wins with no trace in the logs.
Call check_env_file() just before load_dotenv(), since afterwards the
environment no longer shows which values came from the shell:

    from dotenv import find_dotenv, load_dotenv
    from fieldworks.service_env import check_env_file

    check_env_file(find_dotenv())
    load_dotenv()

It logs a warning for each problem, naming keys and line numbers but never
values. Warnings issued before logging is configured are held until
fieldworks.service_logging.setup_logging() runs, so they reach the service's
log file. env_source() reports where a variable's value came from, for error
messages such as a rejected API key.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

# KEY=value, optionally prefixed by `export`; the value isn't parsed here.
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

_sources: dict[str, str] = {}
_pending: list[str] = []


def _value(raw: str) -> str:
    """The value as python-dotenv reads it, closely enough to compare: quoted
    text up to the closing quote, or unquoted text before a ` #` comment."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end > 0:
            return raw[1:end]
    return re.sub(r"\s+#.*$", "", raw)


def check_env_file(
    path: str | os.PathLike | None, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Warn about .env lines that won't take effect. Returns the warnings.

    Flags a key defined on more than one line (the last one wins) and a key
    already set to a different value in `environ` (default os.environ), which
    makes its .env line a no-op. A missing or empty `path` is not an error:
    services run fine on environment variables alone.
    """
    environ = os.environ if environ is None else environ
    if not path or not Path(path).is_file():
        return []
    path = Path(path).resolve()

    lines: dict[str, list[tuple[int, str]]] = {}
    for number, text in enumerate(path.read_text().splitlines(), start=1):
        match = _LINE.match(text)
        if match:
            lines.setdefault(match.group(1), []).append(
                (number, _value(match.group(2)))
            )

    warnings = []
    for key, entries in lines.items():
        last_line, last_value = entries[-1]
        if len(entries) > 1:
            numbers = ", ".join(str(n) for n, _ in entries)
            warnings.append(
                f"{key} is set on lines {numbers} of {path}; only line "
                f"{last_line} takes effect"
            )
        if key in environ:
            _sources[key] = "the process environment"
            if environ[key] != last_value:
                warnings.append(
                    f"{key} is already set in the process environment (for "
                    f"example exported in the shell), so line {last_line} of "
                    f"{path} is ignored"
                )
        else:
            _sources[key] = f"{path} line {last_line}"

    for message in warnings:
        _warn(message)
    return warnings


def env_source(name: str) -> str | None:
    """Where `name`'s value comes from, per the last check_env_file(): the
    process environment, or a .env path and line. None if unknown."""
    if name in _sources:
        return _sources[name]
    return "the process environment" if name in os.environ else None


def _warn(message: str) -> None:
    if logging.getLogger().handlers:
        logger.warning(message)
    else:
        _pending.append(message)


def flush_pending() -> None:
    """Log warnings held back because logging wasn't configured yet.
    setup_logging() calls this."""
    while _pending:
        logger.warning(_pending.pop(0))
