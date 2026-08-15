"""Tests for the DuckDB+VSS knowledge/RAG client. Uses FakeEmbeddingProvider
throughout — no network, no model weights."""

import pytest


def _client(tmp_path, **config_kwargs):
    from fieldworks.memory.embeddings import FakeEmbeddingProvider
    from fieldworks.memory.knowledge import KnowledgeClient, KnowledgeConfig

    config = KnowledgeConfig(db_path=tmp_path / "knowledge.duckdb", **config_kwargs)
    return KnowledgeClient(config, FakeEmbeddingProvider(dimension=16))


def test_schema_uses_configured_table_names(tmp_path):
    client = _client(tmp_path, chunks_table="plant_chunks", files_table="plant_files")
    conn = client._get_conn()
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert "plant_chunks" in tables
    assert "plant_files" in tables


def test_rejects_invalid_table_identifier(tmp_path):
    from fieldworks.memory.knowledge import KnowledgeConfig

    with pytest.raises(ValueError):
        KnowledgeConfig(
            db_path=tmp_path / "a.duckdb", chunks_table="chunks; DROP TABLE x"
        )


def test_ingest_and_query_round_trip(tmp_path):
    client = _client(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "pump_manual.md").write_text(
        "# Pump Operating Limits\n\nThe RawWater pump must not exceed 250 GPM"
        " sustained flow. Cavitation risk increases above this threshold.\n\n"
        "# Unrelated Section\n\nContact facilities for scheduling."
    )

    result = client.ingest_directory(docs)
    assert result.files_ingested == 1
    assert result.chunks_written > 0

    excerpts = client.query("pump flow limit", top_k=1)
    assert len(excerpts) == 1
    assert "250 GPM" in excerpts[0].text
    assert excerpts[0].source.endswith("pump_manual.md")


def test_unsupported_extension_is_skipped_not_raised(tmp_path):
    client = _client(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "diagram.dwg").write_bytes(b"not a real cad file")
    (docs / "notes.txt").write_text("Chlorine dosing setpoint is 2.5 mg/L.")

    result = client.ingest_directory(docs)
    assert result.files_skipped_unsupported == 1
    assert result.files_ingested == 1


def test_unchanged_file_is_skipped_on_second_ingest(tmp_path):
    client = _client(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("Static content.")

    first = client.ingest_directory(docs)
    second = client.ingest_directory(docs)

    assert first.files_ingested == 1
    assert second.files_ingested == 0
    assert second.files_skipped_unchanged == 1


def test_changed_file_is_reingested(tmp_path):
    client = _client(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    doc_path = docs / "notes.txt"
    doc_path.write_text("Original content.")
    client.ingest_directory(docs)

    doc_path.write_text("Updated content with new information.")
    result = client.ingest_directory(docs)

    assert result.files_ingested == 1
    assert result.files_skipped_unchanged == 0

    conn = client._get_conn()
    rows = conn.execute(
        f"SELECT text FROM {client._config.chunks_table} WHERE source_path = ?",
        [str(doc_path)],
    ).fetchall()
    assert any("Updated content" in r[0] for r in rows)
    assert not any("Original content" in r[0] for r in rows)


def test_equipment_id_pre_filters_results(tmp_path):
    client = _client(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    pump_manual = docs / "pump.txt"
    pump_manual.write_text("Pump maximum flow rate is 250 GPM.")
    clarifier_manual = docs / "clarifier.txt"
    clarifier_manual.write_text("Clarifier surface loading rate limit is 800 GPD/sqft.")

    client.ingest_file(pump_manual, equipment_ids=["RawWater_01"])
    client.ingest_file(clarifier_manual, equipment_ids=["Clarifier_01"])

    excerpts = client.query("operating limit", equipment_id="RawWater_01", top_k=5)
    assert len(excerpts) == 1
    assert excerpts[0].source.endswith("pump.txt")


def test_query_with_no_equipment_id_searches_all_docs(tmp_path):
    client = _client(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Pump maximum flow rate is 250 GPM.")
    (docs / "b.txt").write_text("Clarifier surface loading rate limit is 800 GPD/sqft.")
    client.ingest_directory(docs)

    excerpts = client.query("operating limit", top_k=5)
    assert len(excerpts) == 2


def test_extension_directory_is_applied_before_install(tmp_path):
    ext_dir = tmp_path / "vendored-extensions"
    client = _client(tmp_path, extension_directory=ext_dir)

    conn = client._get_conn()
    assert conn.execute("SELECT current_setting('extension_directory')").fetchone()[
        0
    ] == str(ext_dir)
    assert any(p.name.startswith("vss") for p in ext_dir.rglob("*"))


def test_extension_directory_defaults_to_duckdb_default(tmp_path):
    client = _client(tmp_path)
    conn = client._get_conn()
    assert (
        conn.execute("SELECT current_setting('extension_directory')").fetchone()[0]
        == ""
    )
