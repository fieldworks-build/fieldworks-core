"""DuckDB analytical layer — InfluxDB materialization pipeline + query tool.

One DuckDB connection is shared across the sync loop and query tool; both
must run in the same process so DuckDB's single-writer constraint is
satisfied.

Table names, the InfluxDB measurement filter, and the bucket/org are all
config-driven — this module has no plant-specific defaults. Table/column
identifiers in the generated SQL come from AnalyticalConfig (deployment
config set by the operator), not from runtime request input, so f-string
interpolation of those names is safe; SQL parameter binding is used for
row values.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb
from influxdb_client import InfluxDBClient

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class AnalyticalConfig:
    """Configuration for an AnalyticalClient. No waterworks-specific defaults."""

    db_path: str | Path
    process_table: str = "process"
    fault_events_table: str = "fault_events"
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = ""
    influxdb_org: str = ""
    influxdb_bucket: str = ""
    influxdb_measurement: str = "process"
    sync_window_days: int = 90
    sync_interval_seconds: int = 3600

    def __post_init__(self) -> None:
        for field_name in ("process_table", "fault_events_table"):
            value = getattr(self, field_name)
            if not _IDENTIFIER_RE.match(value):
                raise ValueError(
                    f"{field_name}={value!r} is not a valid SQL identifier"
                    " (must match ^[A-Za-z_][A-Za-z0-9_]*$)"
                )


class AnalyticalClient:
    """DuckDB-backed analytical layer synced from an InfluxDB source."""

    def __init__(self, config: AnalyticalConfig):
        self._config = config
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            db_path = Path(self._config.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_path))
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._config.process_table} (
                time        TIMESTAMPTZ NOT NULL,
                type        VARCHAR,
                instance    VARCHAR,
                attribute   VARCHAR,
                value       DOUBLE
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._config.fault_events_table} (
                time     TIMESTAMPTZ NOT NULL,
                target   VARCHAR,
                mode     VARCHAR
            )
        """)

    def _sync_from_influxdb(self) -> None:
        """Pull the configured sync window from InfluxDB into DuckDB.

        Replaces the rolling window rather than appending, so re-running the
        sync after a gap doesn't leave stale duplicate rows.
        """
        client = InfluxDBClient(
            url=self._config.influxdb_url,
            token=self._config.influxdb_token,
            org=self._config.influxdb_org,
        )
        try:
            conn = self._get_conn()
            flux = f"""
from(bucket: "{self._config.influxdb_bucket}")
  |> range(start: -{self._config.sync_window_days}d)
  |> filter(fn: (r) => r._measurement == "{self._config.influxdb_measurement}")
  |> pivot(rowKey:["_time","type","instance"], columnKey: ["attribute"], valueColumn: "_value")
"""
            tables = client.query_api().query(flux)
            rows = []
            for table in tables:
                for record in table.records:
                    for attr, val in record.values.items():
                        if attr.startswith("_") or not isinstance(val, (int, float)):
                            continue
                        rows.append(
                            (
                                record.get_time(),
                                record.values.get("type"),
                                record.values.get("instance"),
                                attr,
                                float(val),
                            )
                        )
            if rows:
                # process_table is validated against _IDENTIFIER_RE in
                # AnalyticalConfig.__post_init__; row values are bound below.
                conn.execute(
                    f"DELETE FROM {self._config.process_table}"  # nosec B608
                    f" WHERE time > NOW() - INTERVAL '{self._config.sync_window_days} days'"
                )
                conn.executemany(
                    f"INSERT INTO {self._config.process_table} VALUES (?, ?, ?, ?, ?)",  # nosec B608
                    rows,
                )
            print(f"[fieldworks.memory.analytical] sync complete: {len(rows)} rows")
        finally:
            client.close()

    async def sync_loop(self) -> None:
        """Background task — sync InfluxDB -> DuckDB on the configured interval."""
        while True:
            try:
                await asyncio.to_thread(self._sync_from_influxdb)
            except Exception as exc:
                print(
                    f"[fieldworks.memory.analytical] sync error"
                    f" (will retry in {self._config.sync_interval_seconds}s): {exc}"
                )
            await asyncio.sleep(self._config.sync_interval_seconds)

    def run_correlation(self, sql: str) -> list[dict]:
        """Read-only analytical query against DuckDB. SELECT only."""
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("run_correlation accepts SELECT queries only.")
        conn = self._get_conn()
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
