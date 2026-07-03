"""File-based specialist memory — one markdown file per specialist.

Specialists read at session start, append at session end. Safe for
concurrent asyncio access within a single-threaded event loop (each append
opens its own file handle in append mode).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class SpecialistMemory:
    """Per-specialist persistent memory backed by markdown files on disk."""

    def __init__(self, memory_dir: str | Path):
        self._memory_dir = Path(memory_dir)

    def _path(self, specialist: str) -> Path:
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        return self._memory_dir / f"{specialist}.md"

    def get(self, specialist: str) -> str:
        """Return accumulated memory for a specialist, or "" if none exists."""
        p = self._path(specialist)
        return p.read_text() if p.exists() else ""

    def append(self, specialist: str, content: str) -> None:
        """Append a timestamped entry to a specialist's memory file."""
        p = self._path(specialist)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(p, "a") as f:
            f.write(f"\n## {ts}\n{content.strip()}\n")
