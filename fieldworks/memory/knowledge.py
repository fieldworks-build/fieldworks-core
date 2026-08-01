"""Knowledge/RAG layer — DuckDB + VSS-backed document retrieval.

Ingests facility documentation (manuals, procedures, operating limits,
text-layer P&IDs) into chunked, embedded records and serves semantic
search over them. Storage reuses the same duckdb dependency as
AnalyticalClient; no separate vector DB service.

v1 document scope: .md, .txt, and text-layer .pdf only. Scanned/image-only
PDFs (no OCR) and CAD/image-format P&IDs are explicitly out of scope —
ingest_file() skips unsupported/unparseable files rather than raising, so
one bad file in a directory doesn't hard-fail the whole ingest.

No HNSW index in v1: DuckDB's HNSW index requires an experimental
persistence flag for on-disk databases. A brute-force array_cosine_distance
scan is correct and fast at facility-doc corpus scale (hundreds to low
thousands of chunks); revisit if a deployment's corpus grows much larger.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from fieldworks.memory.analytical import _IDENTIFIER_RE
from fieldworks.memory.chunking import chunk_text
from fieldworks.memory.embeddings import EmbeddingProvider

_SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


@dataclass
class KnowledgeConfig:
    """Configuration for a KnowledgeClient. No waterworks-specific defaults."""

    db_path: str | Path
    chunks_table: str = "knowledge_chunks"
    files_table: str = "knowledge_files"
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k_default: int = 5

    def __post_init__(self) -> None:
        for field_name in ("chunks_table", "files_table"):
            value = getattr(self, field_name)
            if not _IDENTIFIER_RE.match(value):
                raise ValueError(
                    f"{field_name}={value!r} is not a valid SQL identifier"
                    " (must match ^[A-Za-z_][A-Za-z0-9_]*$)"
                )


@dataclass
class IngestResult:
    files_scanned: int = 0
    files_ingested: int = 0
    files_skipped_unchanged: int = 0
    files_skipped_unsupported: int = 0
    chunks_written: int = 0


@dataclass
class KnowledgeExcerpt:
    text: str
    source: str
    equipment_ids: list[str] = field(default_factory=list)
    score: float = 0.0
    chunk_index: int = 0


class KnowledgeClient:
    """DuckDB+VSS-backed document ingestion and semantic retrieval."""

    def __init__(self, config: KnowledgeConfig, embedding_provider: EmbeddingProvider):
        self._config = config
        self._embedder = embedding_provider
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            db_path = Path(self._config.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_path))
            self._conn.execute("INSTALL vss")
            self._conn.execute("LOAD vss")
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._config.files_table} (
                path         VARCHAR PRIMARY KEY,
                content_hash VARCHAR NOT NULL,
                ingested_at  TIMESTAMPTZ NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._config.chunks_table} (
                id            VARCHAR PRIMARY KEY,
                source_path   VARCHAR NOT NULL,
                chunk_index   INTEGER NOT NULL,
                text          VARCHAR NOT NULL,
                equipment_ids VARCHAR[],
                embedding     FLOAT[{self._embedder.dimension}]
            )
        """)

    # ── Ingestion ──────────────────────────────────────────────────────────

    def ingest_directory(self, dir_path: str | Path) -> IngestResult:
        """Scan dir_path recursively and ingest each supported file, skipping
        files whose content hash matches what's already stored.
        """
        result = IngestResult()
        for path in sorted(Path(dir_path).rglob("*")):
            if not path.is_file():
                continue
            result.files_scanned += 1
            outcome = self._ingest_one(path)
            if outcome == "unsupported":
                result.files_skipped_unsupported += 1
            elif outcome == "unchanged":
                result.files_skipped_unchanged += 1
            else:
                result.files_ingested += 1
                result.chunks_written += outcome
        return result

    def ingest_file(
        self, path: str | Path, *, equipment_ids: list[str] | None = None
    ) -> IngestResult:
        """Ingest a single file. equipment_ids tags every chunk from this
        file for equipment-scoped retrieval.
        """
        result = IngestResult(files_scanned=1)
        outcome = self._ingest_one(Path(path), equipment_ids=equipment_ids)
        if outcome == "unsupported":
            result.files_skipped_unsupported = 1
        elif outcome == "unchanged":
            result.files_skipped_unchanged = 1
        else:
            result.files_ingested = 1
            result.chunks_written = outcome
        return result

    def _ingest_one(
        self, path: Path, *, equipment_ids: list[str] | None = None
    ) -> str | int:
        """Returns "unsupported", "unchanged", or the number of chunks written."""
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            return "unsupported"

        raw = path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()

        conn = self._get_conn()
        existing = conn.execute(
            f"SELECT content_hash FROM {self._config.files_table} WHERE path = ?",  # nosec B608 - files_table validated in KnowledgeConfig.__post_init__
            [str(path)],
        ).fetchone()
        if existing and existing[0] == content_hash:
            return "unchanged"

        text = _extract_text(path, raw)
        if text is None:
            return "unsupported"

        chunks = chunk_text(
            text,
            chunk_size=self._config.chunk_size,
            chunk_overlap=self._config.chunk_overlap,
        )
        if not chunks:
            return "unsupported"

        vectors = self._embedder.embed([c.text for c in chunks])

        conn.execute(
            f"DELETE FROM {self._config.chunks_table} WHERE source_path = ?",  # nosec B608 - chunks_table validated in KnowledgeConfig.__post_init__
            [str(path)],
        )
        conn.executemany(
            f"INSERT INTO {self._config.chunks_table} VALUES (?, ?, ?, ?, ?, ?)",  # nosec B608 - chunks_table validated in KnowledgeConfig.__post_init__
            [
                (
                    str(uuid.uuid4()),
                    str(path),
                    c.index,
                    c.text,
                    equipment_ids or [],
                    vec,
                )
                for c, vec in zip(chunks, vectors)
            ],
        )
        conn.execute(
            f"""
            INSERT INTO {self._config.files_table} VALUES (?, ?, ?)
            ON CONFLICT (path) DO UPDATE SET content_hash = EXCLUDED.content_hash,
                                              ingested_at = EXCLUDED.ingested_at
            """,  # nosec B608 - files_table validated in KnowledgeConfig.__post_init__
            [str(path), content_hash, datetime.now(timezone.utc)],
        )
        return len(chunks)

    # ── Retrieval ──────────────────────────────────────────────────────────

    def query(
        self,
        query: str,
        *,
        equipment_id: str | None = None,
        top_k: int | None = None,
    ) -> list[KnowledgeExcerpt]:
        """Semantic search over ingested chunks. equipment_id pre-filters to
        chunks tagged for that equipment instance; None searches all chunks.
        """
        conn = self._get_conn()
        k = top_k or self._config.top_k_default
        (vector,) = self._embedder.embed([query])

        where = ""
        params: list = [vector]
        if equipment_id:
            where = "WHERE list_contains(equipment_ids, ?)"
            params.append(equipment_id)
        params.append(k)

        rows = conn.execute(
            f"""
            SELECT text, source_path, chunk_index, equipment_ids,
                   array_cosine_distance(embedding, ?::FLOAT[{self._embedder.dimension}]) AS distance
            FROM {self._config.chunks_table}
            {where}
            ORDER BY distance ASC
            LIMIT ?
            """,  # nosec B608 - chunks_table validated in KnowledgeConfig.__post_init__
            params,
        ).fetchall()

        return [
            KnowledgeExcerpt(
                text=text,
                source=source_path,
                equipment_ids=list(equipment_ids or []),
                score=1.0 - distance,
                chunk_index=chunk_index,
            )
            for text, source_path, chunk_index, equipment_ids, distance in rows
        ]


def _extract_text(path: Path, raw: bytes) -> str | None:
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ImportError(
                "PDF ingestion requires the 'knowledge' extra:"
                " pip install fieldworks-core[knowledge]"
            ) from exc
        import io

        reader = PdfReader(io.BytesIO(raw))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return text if text.strip() else None
    return None
