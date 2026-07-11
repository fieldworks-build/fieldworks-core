"""Seed a fresh LadybugDB from a validated TopologyConfig.

Unlike GraphClient.seed_discovered_topology() — which incrementally merges
partial data from topology-builder's discovery flow — this seeds a whole
plant model in one pass, unconditionally. Intended for a fresh or temp
database (e.g. `fieldworks validate --seed`), not a live one.

Attribute and FaultMode ids are scoped to an equipment type in topology.yaml,
but Attribute/FaultMode are global-primary-key node tables in the graph. Two
equipment types can legally reuse an id like "pressure", so node ids here are
namespaced as f"{type_id}::{attr_id}" to avoid collisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fieldworks.topology.schema import TopologyConfig

if TYPE_CHECKING:
    from fieldworks.memory.graph import GraphClient


def _attr_node_id(type_id: str, attr_id: str) -> str:
    return f"{type_id}::{attr_id}"


def _fault_node_id(type_id: str, fault_id: str) -> str:
    return f"{type_id}::{fault_id}"


def _binding_node_id(instance_id: str, attr_key: str) -> str:
    return f"{instance_id}::{attr_key}"


def seed_topology(topology: TopologyConfig, graph_client: "GraphClient") -> dict:
    """Seed graph_client's database from topology. Returns node/rel counts."""
    counts = {
        "facility": 0,
        "process_areas": 0,
        "equipment_types": 0,
        "attributes": 0,
        "fault_modes": 0,
        "equipment_instances": 0,
        "tag_bindings": 0,
    }

    facility = topology.facility
    graph_client.execute_write(
        """
        CREATE (:Facility {
            id: $id, name: $name, description: $description,
            timezone: $timezone, units_system: $units_system
        })
        """,
        {
            "id": facility.site_id,
            "name": facility.name,
            "description": facility.description or "",
            "timezone": facility.timezone,
            "units_system": facility.units_system,
        },
    )
    counts["facility"] = 1

    for area in topology.process_areas:
        graph_client.execute_write(
            """
            CREATE (:ProcessArea {
                id: $id, name: $name, description: $description,
                specialist_prompt: $specialist_prompt
            })
            """,
            {
                "id": area.id,
                "name": area.name,
                "description": area.description,
                "specialist_prompt": area.specialist_prompt or "",
            },
        )
        graph_client.execute_write(
            """
            MATCH (f:Facility {id: $facility_id}), (a:ProcessArea {id: $area_id})
            CREATE (f)-[:CONTAINS_AREA]->(a)
            """,
            {"facility_id": facility.site_id, "area_id": area.id},
        )
        counts["process_areas"] += 1

    for eq_type in topology.equipment_types:
        graph_client.execute_write(
            """
            CREATE (:EquipmentType {id: $id, name: $name, description: $description})
            """,
            {
                "id": eq_type.id,
                "name": eq_type.name,
                "description": eq_type.description,
            },
        )
        counts["equipment_types"] += 1

        for attr in eq_type.attributes:
            attr_node_id = _attr_node_id(eq_type.id, attr.id)
            graph_client.execute_write(
                """
                CREATE (:Attribute {
                    id: $id, name: $name, description: $description, units: $units,
                    normal_range_min: $normal_range_min, normal_range_max: $normal_range_max,
                    normal_range_desc: $normal_range_desc, writable: $writable,
                    requires_confirmation: false, write_limit_min: 0.0, write_limit_max: 0.0
                })
                """,
                {
                    "id": attr_node_id,
                    "name": attr.name,
                    "description": attr.description or "",
                    "units": attr.units,
                    "normal_range_min": attr.normal_range.min,
                    "normal_range_max": attr.normal_range.max,
                    "normal_range_desc": attr.normal_range.description or "",
                    "writable": attr.writable,
                },
            )
            graph_client.execute_write(
                """
                MATCH (t:EquipmentType {id: $type_id}), (a:Attribute {id: $attr_id})
                CREATE (t)-[:DEFINES_ATTRIBUTE]->(a)
                """,
                {"type_id": eq_type.id, "attr_id": attr_node_id},
            )
            counts["attributes"] += 1

        for fault in eq_type.fault_modes:
            fault_node_id = _fault_node_id(eq_type.id, fault.id)
            graph_client.execute_write(
                """
                CREATE (:FaultMode {
                    id: $id, name: $name, description: $description, severity: $severity
                })
                """,
                {
                    "id": fault_node_id,
                    "name": fault.name,
                    "description": fault.description,
                    "severity": fault.severity,
                },
            )
            graph_client.execute_write(
                """
                MATCH (t:EquipmentType {id: $type_id}), (fm:FaultMode {id: $fault_id})
                CREATE (t)-[:HAS_FAULT_MODE]->(fm)
                """,
                {"type_id": eq_type.id, "fault_id": fault_node_id},
            )
            for attr_id in fault.affected_attributes:
                graph_client.execute_write(
                    """
                    MATCH (fm:FaultMode {id: $fault_id}), (a:Attribute {id: $attr_id})
                    CREATE (fm)-[:AFFECTS]->(a)
                    """,
                    {
                        "fault_id": fault_node_id,
                        "attr_id": _attr_node_id(eq_type.id, attr_id),
                    },
                )
            counts["fault_modes"] += 1

    for inst in topology.equipment_instances:
        graph_client.execute_write(
            """
            CREATE (:Equipment {
                id: $id, name: $name, description: $description,
                commissioned: date($commissioned), notes: $notes
            })
            """,
            {
                "id": inst.id,
                "name": inst.name,
                "description": inst.description or "",
                "commissioned": inst.commissioned or "2000-01-01",
                "notes": inst.notes or "",
            },
        )
        graph_client.execute_write(
            """
            MATCH (e:Equipment {id: $inst_id}), (t:EquipmentType {id: $type_id})
            CREATE (e)-[:IS_TYPE]->(t)
            """,
            {"inst_id": inst.id, "type_id": inst.type_id},
        )
        graph_client.execute_write(
            """
            MATCH (a:ProcessArea {id: $area_id}), (e:Equipment {id: $inst_id})
            CREATE (a)-[:CONTAINS_EQUIPMENT]->(e)
            """,
            {"area_id": inst.process_area_id, "inst_id": inst.id},
        )
        counts["equipment_instances"] += 1

        for attr_key, binding in inst.tag_bindings.items():
            bind_node_id = _binding_node_id(inst.id, attr_key)
            attr_node_id = _attr_node_id(inst.type_id, attr_key)
            graph_client.execute_write(
                """
                CREATE (:TagBinding {
                    id: $id, tag_id: $tag_id, confidence: $confidence, notes: $notes
                })
                """,
                {
                    "id": bind_node_id,
                    "tag_id": binding.tag_id,
                    "confidence": binding.confidence,
                    "notes": binding.notes or "",
                },
            )
            graph_client.execute_write(
                """
                MATCH (e:Equipment {id: $inst_id}), (tb:TagBinding {id: $bind_id})
                CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: $attr_id}]->(tb)
                """,
                {
                    "inst_id": inst.id,
                    "bind_id": bind_node_id,
                    "attr_id": attr_node_id,
                },
            )
            graph_client.execute_write(
                """
                MATCH (tb:TagBinding {id: $bind_id}), (a:Attribute {id: $attr_id})
                CREATE (tb)-[:BINDING_OF]->(a)
                """,
                {"bind_id": bind_node_id, "attr_id": attr_node_id},
            )
            counts["tag_bindings"] += 1

    return counts
