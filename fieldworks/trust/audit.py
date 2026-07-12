"""Hash-chained, optionally-encrypted append-only audit log.

Every record embeds the hash of the previous line, so tampering with or
deleting a record breaks the chain from that point forward — `verify()`
detects this. Encryption (AES-256-GCM) is applied per record when a 32-byte
key is configured; otherwise records are written as plaintext JSON.

Requires the optional `trust` extra: pip install fieldworks-core[trust]
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def parse_audit_key(b64: str) -> bytes:
    """Decode a base64-encoded audit key, validating it's exactly 32 bytes."""
    key = base64.b64decode(b64)
    if len(key) != 32:
        raise ValueError(f"audit key must decode to exactly 32 bytes, got {len(key)}")
    return key


@dataclass
class AuditLogConfig:
    log_path: str | Path
    key: bytes | None = None


@dataclass
class VerifyResult:
    ok: bool
    record_count: int
    problems: list[str] = field(default_factory=list)


class AuditLog:
    """An instance owns one hash-chained log file. No import-time I/O —
    construction explicitly recovers chain state from an existing file."""

    def __init__(self, config: AuditLogConfig) -> None:
        if config.key is not None and len(config.key) != 32:
            raise ValueError(
                f"audit key must be exactly 32 bytes, got {len(config.key)}"
            )
        if config.key is None:
            warnings.warn(
                "AuditLog configured without a key — records will be written unencrypted",
                stacklevel=2,
            )
        self._log_path = Path(config.log_path)
        self._key = config.key
        self._lock = threading.Lock()
        self._seq = 0
        self._prev_hash = ""
        self._load_state()

    def _hash_line(self, line: str) -> str:
        return hashlib.sha256(line.encode()).hexdigest()

    def _encode(self, payload: str) -> str:
        if self._key:
            nonce = os.urandom(12)
            ct = AESGCM(self._key).encrypt(nonce, payload.encode(), None)
            return base64.urlsafe_b64encode(nonce + ct).decode().rstrip("=")
        return payload

    def _decode(self, line: str) -> str:
        if self._key:
            padded = line + "=" * (-len(line) % 4)
            raw = base64.urlsafe_b64decode(padded)
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(self._key).decrypt(nonce, ct, None).decode()
        return line

    def _load_state(self) -> None:
        """Recover seq/prev_hash from the last line of an existing log."""
        if not self._log_path.exists():
            return
        with open(self._log_path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        if not lines:
            return
        last_line = lines[-1]
        self._prev_hash = self._hash_line(last_line)
        try:
            payload = json.loads(self._decode(last_line))
            self._seq = payload.get("seq", 0)
        except Exception:
            pass  # corrupted last line — seq stays at 0, chain breaks on next write

    def log(self, event: str, **fields: Any) -> None:
        with self._lock:
            self._seq += 1
            record = {
                "seq": self._seq,
                "prev": self._prev_hash,
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **fields,
            }
            payload = json.dumps(record, separators=(",", ":"))
            line = self._encode(payload)
            self._prev_hash = self._hash_line(line)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read(self, limit: int = 500) -> list[dict]:
        if not self._log_path.exists():
            return []
        with self._lock:
            with open(self._log_path, encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(self._decode(line)))
            except Exception:
                entries.append({"error": "decryption_failed", "preview": line[:40]})
        return entries

    def rotate(self) -> Path | None:
        """Archive the current log and reset chain state. Returns the
        archive path, or None if there was nothing to archive."""
        with self._lock:
            archive_path: Path | None = None
            if self._log_path.exists() and self._log_path.stat().st_size > 0:
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                archive = self._log_path.with_name(f"{self._log_path.stem}.{ts}.jsonl")
                self._log_path.rename(archive)
                archive_path = archive
            self._seq = 0
            self._prev_hash = ""
        self.log("log_rotated", archived=str(archive_path) if archive_path else "")
        return archive_path

    def verify(self) -> VerifyResult:
        """Replay the hash chain, checking every record's `prev` against the
        hash of the record before it."""
        if not self._log_path.exists():
            return VerifyResult(ok=True, record_count=0)
        with open(self._log_path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        problems: list[str] = []
        prev_hash = ""
        for i, line in enumerate(lines, 1):
            try:
                payload = json.loads(self._decode(line))
            except Exception as exc:
                problems.append(f"record {i}: decrypt/parse error — {exc}")
                prev_hash = self._hash_line(line)
                continue

            expected = payload.get("prev", "")
            if expected != prev_hash:
                problems.append(
                    f"record {i} seq={payload.get('seq')}: chain broken "
                    f"(expected {prev_hash[:16]}, got {expected[:16]})"
                )
            prev_hash = self._hash_line(line)

        return VerifyResult(ok=not problems, record_count=len(lines), problems=problems)

    def decrypt_all(self) -> list[dict]:
        if self._key is None:
            raise ValueError("decrypt_all requires a key")
        if not self._log_path.exists():
            return []
        with open(self._log_path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        return [json.loads(self._decode(line)) for line in lines]
