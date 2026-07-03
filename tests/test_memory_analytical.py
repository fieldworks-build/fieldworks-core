"""Tests for the DuckDB analytical client."""

import pytest


def test_schema_uses_configured_table_names(tmp_path):
    from fieldworks.memory.analytical import AnalyticalClient, AnalyticalConfig

    config = AnalyticalConfig(
        db_path=tmp_path / "analytical.duckdb",
        process_table="plant_process",
        fault_events_table="plant_fault_events",
    )
    client = AnalyticalClient(config)
    conn = client._get_conn()

    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert "plant_process" in tables
    assert "plant_fault_events" in tables
    assert "wtp_process" not in tables


def test_run_correlation_rejects_non_select(tmp_path):
    from fieldworks.memory.analytical import AnalyticalClient, AnalyticalConfig

    client = AnalyticalClient(AnalyticalConfig(db_path=tmp_path / "analytical.duckdb"))
    with pytest.raises(ValueError):
        client.run_correlation("DELETE FROM process")


def test_run_correlation_returns_rows(tmp_path):
    from fieldworks.memory.analytical import AnalyticalClient, AnalyticalConfig

    config = AnalyticalConfig(
        db_path=tmp_path / "analytical.duckdb", process_table="process"
    )
    client = AnalyticalClient(config)
    conn = client._get_conn()
    conn.execute(
        "INSERT INTO process VALUES ('2026-01-01 00:00:00+00', 'pump', 'RawWater_01', 'Flow', 210.5)"
    )

    rows = client.run_correlation(
        "SELECT * FROM process WHERE instance = 'RawWater_01'"
    )
    assert len(rows) == 1
    assert rows[0]["attribute"] == "Flow"
    assert rows[0]["value"] == 210.5


def test_rejects_invalid_table_identifier(tmp_path):
    from fieldworks.memory.analytical import AnalyticalConfig

    with pytest.raises(ValueError):
        AnalyticalConfig(
            db_path=tmp_path / "a.duckdb", process_table="process; DROP TABLE x"
        )


def test_two_clients_do_not_share_default_table_names(tmp_path):
    from fieldworks.memory.analytical import AnalyticalClient, AnalyticalConfig

    a = AnalyticalClient(
        AnalyticalConfig(db_path=tmp_path / "a.duckdb", process_table="plant_a_process")
    )
    b = AnalyticalClient(
        AnalyticalConfig(db_path=tmp_path / "b.duckdb", process_table="plant_b_process")
    )
    a_tables = {row[0] for row in a._get_conn().execute("SHOW TABLES").fetchall()}
    b_tables = {row[0] for row in b._get_conn().execute("SHOW TABLES").fetchall()}
    assert "plant_a_process" in a_tables
    assert "plant_b_process" in b_tables
    assert "plant_b_process" not in a_tables
