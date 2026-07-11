"""LadybugDB graph layer — topology reads and dynamic-layer writes.

Package: pip install ladybug  ->  import ladybug as lb
(PyPI name is "ladybug", from https://ladybugdb.com/ — not "ladybug-client".)
Result iteration: list(result.rows_as_dict()) returns list[dict] with column
names as keys.

All values come from application-level identifiers (equipment IDs, session
IDs, diagnosis text, etc.) and are passed as `$param` bindings — never
interpolated into Cypher text. Table/column names in schema.cypher are
static and defined by the framework, not runtime input.
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ladybug as lb

_PACKAGED_SCHEMA_PATH = Path(__file__).parent / "schema.cypher"

# ISA-18.2 three-tier vocabulary — see fieldworks.agents.deadband.SEVERITY_TIERS.
# Highest tier wins when multiple FaultModes affect the same attribute.
_SEVERITY_RANK = {"advisory": 0, "warning": 1, "critical": 2}


@dataclass
class GraphConfig:
    """Configuration for a GraphClient.

    db_path: filesystem path to the LadybugDB database directory.
    schema_path: path to a schema.cypher defining the node/rel tables.
        Defaults to the framework schema shipped in fieldworks/memory/.
    """

    db_path: str | Path
    schema_path: str | Path | None = None


class GraphClient:
    """LadybugDB (Kuzu) client for the Fieldworks equipment/fault graph.

    One client per database. The connection is created lazily on first use
    and reused; a lock guards initialization only, not individual queries.
    """

    def __init__(self, config: GraphConfig):
        self._config = config
        self._db: lb.Database | None = None
        self._conn: lb.Connection | None = None
        self._lock = threading.Lock()

    def _get_conn(self) -> lb.Connection:
        with self._lock:
            if self._conn is None:
                db_path = Path(self._config.db_path)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self._db = lb.Database(str(db_path))
                self._conn = lb.Connection(self._db)
                self._maybe_create_schema(self._conn)
        return self._conn

    def _maybe_create_schema(self, conn: lb.Connection) -> None:
        """Create the graph schema (node/rel tables) if the database is empty.

        This creates structure only — it does not seed topology data. Use
        fieldworks.topology.seeder.seed_topology() to populate the static
        layer from a TopologyConfig.
        """
        try:
            result = conn.execute("MATCH (n:Facility) RETURN count(n) AS c")
            rows = list(result.rows_as_dict())
            count = rows[0]["c"] if rows else 0
        except Exception:
            count = 0
        if count == 0:
            schema_path = Path(self._config.schema_path or _PACKAGED_SCHEMA_PATH)
            self._execute_cypher_file(conn, schema_path)

    def load_cypher_file(self, path: str | Path) -> None:
        """Execute a .cypher script statement by statement against this client's database.

        The schema (node/rel tables) is loaded automatically on first
        connection. Call this directly to load an example seed file such as
        examples/waterworks/schema_seed.cypher.
        """
        self._execute_cypher_file(self._get_conn(), path)

    @staticmethod
    def _execute_cypher_file(conn: lb.Connection, path: str | Path) -> None:
        """Execute a .cypher script statement by statement.

        Two quirks require pre-processing before splitting on ';':

        1. Inline `//` comments — some lines have trailing comments that
           themselves contain ';' (e.g. "notes STRING // history; persists").
           Stripping all `//` comments first removes these spurious
           semicolons.

        2. Some seed-data lines have TWO CREATE clauses on one line
           separated by '; ' (semicolon + spaces, no newline). These two
           CREATEs share the preceding MATCH's variable scope and must be
           submitted as a single multi-clause query. Only same-line
           '; CREATE' is normalised to a newline — statement boundaries
           where the ';' ends a line are left alone.
        """
        cypher = Path(path).read_text()
        cypher = re.sub(r"//[^\n]*", "", cypher)
        cypher = re.sub(r";[^\S\n]+CREATE", "\nCREATE", cypher)

        for raw in cypher.split(";"):
            stmt = raw.strip()
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except Exception as exc:
                print(f"[fieldworks.memory.graph] cypher load: {exc!r}")

    # ── Read ──────────────────────────────────────────────────────────────

    def get_topology(self) -> list[dict]:
        conn = self._get_conn()
        result = conn.execute("""
            MATCH (area:ProcessArea)-[:CONTAINS_EQUIPMENT]->(e:Equipment)-[:IS_TYPE]->(t:EquipmentType)
            RETURN area.name AS area, area.id AS area_id,
                   e.id AS equipment, e.name AS equipment_name, e.notes AS notes,
                   t.id AS type_id, t.name AS type_name
            ORDER BY area.name, e.id
        """)
        return list(result.rows_as_dict())

    def get_specialist_context(self, area_id: str) -> list[dict]:
        """Flat rows for aggregate_specialist_query()."""
        conn = self._get_conn()
        result = conn.execute(
            """
            MATCH (area:ProcessArea {id: $area_id})-[:CONTAINS_EQUIPMENT]->(e:Equipment)
                  -[:IS_TYPE]->(t:EquipmentType)
            OPTIONAL MATCH (t)-[:DEFINES_ATTRIBUTE]->(attr:Attribute)
            OPTIONAL MATCH (t)-[:HAS_FAULT_MODE]->(fm:FaultMode)
            OPTIONAL MATCH (e)-[:BINDS_ATTRIBUTE {attribute_id: attr.id}]->(b:TagBinding)
            RETURN
                area.name AS process_area, area.specialist_prompt AS area_context,
                e.name AS equipment, e.notes AS equipment_notes, t.name AS equipment_type,
                attr.name AS attribute, attr.units AS units, attr.data_type AS data_type,
                attr.normal_range_min AS normal_min, attr.normal_range_max AS normal_max,
                attr.normal_state AS normal_state,
                attr.allowed_values AS allowed_values, attr.normal_values AS normal_values,
                b.tag_id AS tag_id, b.confidence AS binding_confidence,
                fm.name AS fault_mode, fm.severity AS fault_severity,
                fm.description AS fault_description
            ORDER BY e.name, attr.name
            """,
            {"area_id": area_id},
        )
        return list(result.rows_as_dict())

    def get_equipment_history(self, equipment_id: str, limit: int = 10) -> dict:
        conn = self._get_conn()

        inc = conn.execute(
            """
            MATCH (i:Incident)-[:INCIDENT_ON]->(e:Equipment {id: $equipment_id})
            OPTIONAL MATCH (i)-[:CONSISTENT_WITH]->(fm:FaultMode)
            RETURN i.timestamp AS ts, i.diagnosis AS diagnosis,
                   i.status AS status, i.confidence AS confidence,
                   i.outcome AS outcome, fm.name AS fault_mode
            ORDER BY i.timestamp DESC LIMIT $limit
            """,
            {"equipment_id": equipment_id, "limit": limit},
        )
        incidents = list(inc.rows_as_dict())

        obs = conn.execute(
            """
            MATCH (o:Observation)-[:OBSERVATION_ON]->(e:Equipment {id: $equipment_id})
            RETURN o.timestamp AS ts, o.text AS text,
                   o.confidence AS confidence, o.specialist AS specialist
            ORDER BY o.timestamp DESC LIMIT $limit
            """,
            {"equipment_id": equipment_id, "limit": limit},
        )
        observations = list(obs.rows_as_dict())

        dec = conn.execute(
            """
            MATCH (d:OperatorDecision)-[:DECISION_ON]->(e:Equipment {id: $equipment_id})
            RETURN d.action_type AS action_type, d.decision AS decision, count(*) AS count
            ORDER BY count DESC LIMIT 5
            """,
            {"equipment_id": equipment_id},
        )
        decisions = list(dec.rows_as_dict())

        return {
            "equipment_id": equipment_id,
            "incidents": incidents,
            "observations": observations,
            "decision_patterns": decisions,
        }

    def get_writable_attributes(self) -> list[dict]:
        conn = self._get_conn()
        result = conn.execute("""
            MATCH (e:Equipment)-[:BINDS_ATTRIBUTE]->(b:TagBinding)-[:BINDING_OF]->(a:Attribute {writable: true})
            RETURN e.id AS equipment_id, e.name AS equipment_name,
                   a.name AS attribute, b.tag_id AS tag_id,
                   a.requires_confirmation AS requires_confirmation,
                   a.write_limit_min AS write_limit_min,
                   a.write_limit_max AS write_limit_max
        """)
        return list(result.rows_as_dict())

    def get_severity_for_attribute(
        self,
        type_id: str,
        attr_id: str,
        condition: str | None = None,
    ) -> str | None:
        """Runtime severity lookup for a (equipment type, attribute) pair, via
        FaultMode.severity on the graph — replaces static alarm_lo/alarm_hi
        config, so severity is adjustable without a process restart.

        condition: "below_min" | "above_max" | None. When given, only
        FaultModes whose direction matches (or is "either") are considered —
        alarm severity is often asymmetric (e.g. a pump running low on flow
        may be critical while running high is merely advisory). None
        considers all FaultModes regardless of direction.

        Returns the highest-severity matching FaultMode, or None if none match.
        """
        from fieldworks.topology.seeder import attr_node_id

        conn = self._get_conn()
        result = conn.execute(
            """
            MATCH (t:EquipmentType {id: $type_id})-[:HAS_FAULT_MODE]->(fm:FaultMode)
                  -[:AFFECTS]->(a:Attribute {id: $attr_node_id})
            RETURN fm.severity AS severity, fm.direction AS direction
            """,
            {"type_id": type_id, "attr_node_id": attr_node_id(type_id, attr_id)},
        )
        severities = [
            r["severity"]
            for r in result.rows_as_dict()
            if condition is None or r["direction"] in ("either", condition)
        ]
        if not severities:
            return None
        return max(severities, key=lambda s: _SEVERITY_RANK.get(s, -1))

    def query_graph(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict]:
        """Read-only escape hatch. Rejects write operations."""
        upper = cypher.strip().upper()
        for kw in ("CREATE", "MERGE", "SET", "DELETE", "DETACH", "DROP"):
            if kw in upper:
                raise ValueError(
                    f"query_graph is read-only. Found '{kw}'. Use record_* methods to write."
                )
        conn = self._get_conn()
        return list(conn.execute(cypher, parameters).rows_as_dict())

    # ── Write ─────────────────────────────────────────────────────────────

    def execute_write(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict]:
        """Unguarded write escape hatch for framework-internal callers (e.g. the
        topology seeder). Unlike query_graph(), this permits CREATE/MERGE/etc.
        """
        conn = self._get_conn()
        return list(conn.execute(cypher, parameters).rows_as_dict())

    def record_incident(
        self,
        session_id: str,
        equipment_id: str,
        diagnosis: str,
        confidence: float,
        status: str,
        fault_mode_id: str | None = None,
    ) -> str:
        conn = self._get_conn()
        incident_id = str(uuid.uuid4())[:12]
        ts = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            CREATE (:Incident {
                id: $id, session_id: $session_id, timestamp: $ts,
                diagnosis: $diagnosis, confidence: $confidence,
                status: $status, outcome: 'monitoring'
            })
            """,
            {
                "id": incident_id,
                "session_id": session_id,
                "ts": ts,
                "diagnosis": diagnosis,
                "confidence": confidence,
                "status": status,
            },
        )
        conn.execute(
            """
            MATCH (i:Incident {id: $incident_id}), (e:Equipment {id: $equipment_id})
            CREATE (i)-[:INCIDENT_ON]->(e)
            """,
            {"incident_id": incident_id, "equipment_id": equipment_id},
        )
        if fault_mode_id:
            conn.execute(
                """
                MATCH (i:Incident {id: $incident_id}), (fm:FaultMode {id: $fault_mode_id})
                CREATE (i)-[:CONSISTENT_WITH]->(fm)
                """,
                {"incident_id": incident_id, "fault_mode_id": fault_mode_id},
            )
        return incident_id

    def record_observation(
        self,
        session_id: str,
        equipment_id: str,
        text: str,
        confidence: float,
        specialist: str,
    ) -> str:
        conn = self._get_conn()
        obs_id = str(uuid.uuid4())[:12]
        ts = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            CREATE (:Observation {
                id: $id, session_id: $session_id, timestamp: $ts,
                text: $text, confidence: $confidence, specialist: $specialist
            })
            """,
            {
                "id": obs_id,
                "session_id": session_id,
                "ts": ts,
                "text": text,
                "confidence": confidence,
                "specialist": specialist,
            },
        )
        conn.execute(
            """
            MATCH (o:Observation {id: $obs_id}), (e:Equipment {id: $equipment_id})
            CREATE (o)-[:OBSERVATION_ON]->(e)
            """,
            {"obs_id": obs_id, "equipment_id": equipment_id},
        )
        return obs_id

    def link_incident_precedes(
        self, incident_a_id: str, incident_b_id: str, hours_apart: float
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            MATCH (a:Incident {id: $a_id}), (b:Incident {id: $b_id})
            CREATE (a)-[:PRECEDES {hours_apart: $hours_apart}]->(b)
            """,
            {"a_id": incident_a_id, "b_id": incident_b_id, "hours_apart": hours_apart},
        )

    def seed_discovered_topology(
        self,
        facility_id: str,
        facility_name: str,
        instances: list[dict],
    ) -> dict:
        """Bulk-write a topology-builder discovered topology into LadybugDB.

        Creates Equipment, IS_TYPE, CONTAINS_EQUIPMENT, TagBinding, BINDS_ATTRIBUTE,
        and BINDING_OF nodes/relationships. Skips anything that already exists.
        instances: output of topology-builder inference.py infer_topology()
        """
        conn = self._get_conn()
        seeded = 0
        errors = 0

        result = conn.execute(
            "MATCH (f:Facility {id: $id}) RETURN count(f) AS c", {"id": facility_id}
        )
        if list(result.rows_as_dict())[0]["c"] == 0:
            conn.execute(
                """
                CREATE (:Facility {
                    id: $id, name: $name,
                    description: '', timezone: 'UTC', units_system: 'metric'
                })
                """,
                {"id": facility_id, "name": facility_name},
            )

        for inst in instances:
            try:
                eid = inst["instance_id"]
                type_id = inst.get("ladybug_type_id", "")
                area_id = inst.get("area_id", "")
                confidence = inst.get("confidence_level", "suspect")

                # ── Equipment node ────────────────────────────────────────
                result = conn.execute(
                    "MATCH (e:Equipment {id: $id}) RETURN count(e) AS c", {"id": eid}
                )
                if list(result.rows_as_dict())[0]["c"] == 0:
                    conn.execute(
                        """
                        CREATE (:Equipment {
                            id: $id, name: $id,
                            description: '', commissioned: date('2000-01-01'), notes: ''
                        })
                        """,
                        {"id": eid},
                    )

                # ── IS_TYPE ───────────────────────────────────────────────
                if type_id:
                    result = conn.execute(
                        """
                        MATCH (e:Equipment {id: $eid})-[:IS_TYPE]->(t:EquipmentType {id: $type_id})
                        RETURN count(e) AS c
                        """,
                        {"eid": eid, "type_id": type_id},
                    )
                    if list(result.rows_as_dict())[0]["c"] == 0:
                        try:
                            conn.execute(
                                """
                                MATCH (e:Equipment {id: $eid}), (t:EquipmentType {id: $type_id})
                                CREATE (e)-[:IS_TYPE]->(t)
                                """,
                                {"eid": eid, "type_id": type_id},
                            )
                        except Exception:
                            pass  # EquipmentType may not exist in a blank DB

                # ── CONTAINS_EQUIPMENT from ProcessArea ──────────────────
                if area_id:
                    result = conn.execute(
                        """
                        MATCH (a:ProcessArea {id: $area_id})-[:CONTAINS_EQUIPMENT]->(e:Equipment {id: $eid})
                        RETURN count(e) AS c
                        """,
                        {"area_id": area_id, "eid": eid},
                    )
                    if list(result.rows_as_dict())[0]["c"] == 0:
                        try:
                            conn.execute(
                                """
                                MATCH (a:ProcessArea {id: $area_id}), (e:Equipment {id: $eid})
                                CREATE (a)-[:CONTAINS_EQUIPMENT]->(e)
                                """,
                                {"area_id": area_id, "eid": eid},
                            )
                        except Exception:
                            pass  # ProcessArea may not exist in a blank DB

                # ── TagBindings ───────────────────────────────────────────
                for attr_name, attr_info in inst.get("attributes", {}).items():
                    try:
                        tag_id = attr_info["tag"]
                        safe_attr = (
                            attr_name.replace("/", "_")
                            .replace(" ", "_")
                            .replace("'", "")
                        )
                        bind_id = f"topo_{eid}_{safe_attr}"

                        result = conn.execute(
                            "MATCH (tb:TagBinding {id: $id}) RETURN count(tb) AS c",
                            {"id": bind_id},
                        )
                        if list(result.rows_as_dict())[0]["c"] == 0:
                            conn.execute(
                                """
                                CREATE (:TagBinding {
                                    id: $id, tag_id: $tag_id,
                                    confidence: $confidence, notes: ''
                                })
                                """,
                                {
                                    "id": bind_id,
                                    "tag_id": tag_id,
                                    "confidence": confidence,
                                },
                            )

                        attr_result = conn.execute(
                            """
                            MATCH (e:Equipment {id: $eid})-[:IS_TYPE]->(t:EquipmentType)
                                  -[:DEFINES_ATTRIBUTE]->(a:Attribute {name: $attr_name})
                            RETURN a.id AS attr_id
                            """,
                            {"eid": eid, "attr_name": attr_name},
                        )
                        attr_rows = list(attr_result.rows_as_dict())
                        attr_id_db = attr_rows[0]["attr_id"] if attr_rows else ""

                        result = conn.execute(
                            """
                            MATCH (e:Equipment {id: $eid})-[:BINDS_ATTRIBUTE]->(tb:TagBinding {id: $bind_id})
                            RETURN count(e) AS c
                            """,
                            {"eid": eid, "bind_id": bind_id},
                        )
                        if list(result.rows_as_dict())[0]["c"] == 0:
                            conn.execute(
                                """
                                MATCH (e:Equipment {id: $eid}), (tb:TagBinding {id: $bind_id})
                                CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: $attr_id}]->(tb)
                                """,
                                {"eid": eid, "bind_id": bind_id, "attr_id": attr_id_db},
                            )

                        if attr_id_db:
                            result = conn.execute(
                                """
                                MATCH (tb:TagBinding {id: $bind_id})-[:BINDING_OF]->(a:Attribute {id: $attr_id})
                                RETURN count(tb) AS c
                                """,
                                {"bind_id": bind_id, "attr_id": attr_id_db},
                            )
                            if list(result.rows_as_dict())[0]["c"] == 0:
                                conn.execute(
                                    """
                                    MATCH (tb:TagBinding {id: $bind_id}), (a:Attribute {id: $attr_id})
                                    CREATE (tb)-[:BINDING_OF]->(a)
                                    """,
                                    {"bind_id": bind_id, "attr_id": attr_id_db},
                                )
                    except Exception:
                        pass  # individual attribute binding failures don't fail the instance

                seeded += 1
            except Exception:
                errors += 1

        return {"seeded_count": seeded, "errors": errors}


# ── Module-level helpers ─────────────────────────────────────────────────


def aggregate_specialist_query(rows: list[dict]) -> dict:
    """Collapse get_specialist_context() flat join rows into structured context.

    The flat join produces one row per equipment x attribute x fault_mode;
    the same fault mode appears once per attribute it AFFECTS. The
    fault_mode dedup guard is critical — without it the specialist prompt
    lists the same fault mode multiple times.
    """
    if not rows:
        return {}
    area_name = rows[0]["process_area"]
    area_context = rows[0]["area_context"]
    equipment: dict[str, dict] = {}
    for row in rows:
        eq = row["equipment"]
        if eq not in equipment:
            equipment[eq] = {
                "name": eq,
                "type": row["equipment_type"],
                "notes": row["equipment_notes"],
                "attributes": {},
                "fault_modes": {},
            }
        if row["attribute"]:
            equipment[eq]["attributes"][row["attribute"]] = {
                "units": row["units"],
                "data_type": row["data_type"],
                "normal_min": row["normal_min"],
                "normal_max": row["normal_max"],
                "normal_state": row["normal_state"],
                "allowed_values": row["allowed_values"],
                "normal_values": row["normal_values"],
                "tag_id": row["tag_id"],
                "confidence": row["binding_confidence"],
            }
        if row["fault_mode"] and row["fault_mode"] not in equipment[eq]["fault_modes"]:
            equipment[eq]["fault_modes"][row["fault_mode"]] = {
                "severity": row["fault_severity"],
                "description": row["fault_description"],
            }
    return {
        "area": area_name,
        "context": area_context,
        "equipment": list(equipment.values()),
    }
