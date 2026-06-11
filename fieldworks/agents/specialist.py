"""Specialist prompt generation from topology.

build_specialist_prompt() is the stable public API across v0.1 and v0.2.
v0.2 will add memory_client= for LadybugDB enrichment without changing the
existing call signature.
"""

from __future__ import annotations

from fieldworks.topology.schema import EquipmentInstance, TagBinding, TopologyConfig


def build_specialist_prompt(
    area_id: str,
    topology: TopologyConfig,
    *,
    extra_context: str | None = None,
) -> str:
    """Return the system prompt for the Specialist agent responsible for area_id.

    Args:
        area_id: The process area ID (matches process_areas[].id in topology.yaml).
        topology: Loaded and validated TopologyConfig.
        extra_context: Optional additional context injected after the area description.
            In v0.2 this will be populated from LadybugDB memory.

    Returns:
        A fully rendered system prompt string.
    """
    area = topology.get_process_area(area_id)
    instances = topology.instances_in_area(area_id)
    facility = topology.facility

    lines: list[str] = [
        f"You are a Specialist agent for the {area.name} at {facility.name}.",
        "",
        f"Your process area: {area.description}",
    ]

    if area.specialist_prompt:
        lines += ["", area.specialist_prompt]

    if extra_context:
        lines += ["", extra_context]

    lines += ["", "## Equipment in this area", ""]

    for inst in instances:
        eq_type = topology.get_equipment_type(inst.type_id)
        lines.append(f"### {inst.name} ({inst.id})")
        lines.append(f"Type: {eq_type.name} — {eq_type.description}")
        if inst.commissioned:
            lines.append(f"Commissioned: {inst.commissioned}")
        if inst.notes:
            lines.append(f"Notes: {inst.notes}")
        lines.append("")

        lines.append("Monitored attributes:")
        for attr in eq_type.attributes:
            binding = inst.tag_bindings.get(attr.id)
            if binding is None:
                lines.append(f"  - {attr.name}: NOT INSTRUMENTED on this unit")
            else:
                qualifier = _binding_qualifier(binding)
                writable_note = " (writable)" if attr.writable else ""
                lines.append(
                    f"  - {attr.name} ({attr.units}){writable_note}:"
                    f" normal {attr.normal_range.min}–{attr.normal_range.max}{qualifier}"
                )
        lines.append("")

        lines.append(f"Known fault modes for {eq_type.name}:")
        for fm in eq_type.fault_modes:
            lines.append(f"  [{fm.severity.upper()}] {fm.name}: {fm.description}")
        lines.append("")

    lines += [
        "Diagnose using the available data. For any attribute marked NOT INSTRUMENTED,",
        "state explicitly that the equipment lacks that sensor and adjust your diagnostic",
        "scope accordingly. Do not invent readings for unbound attributes.",
    ]

    return "\n".join(lines)


def build_specialists(topology: TopologyConfig) -> list[dict]:
    """Return one specialist config dict per process area.

    Each dict has: area_id, area_name, instance_ids, system_prompt.
    """
    return [
        {
            "area_id": area.id,
            "area_name": area.name,
            "instance_ids": [i.id for i in topology.instances_in_area(area.id)],
            "system_prompt": build_specialist_prompt(area.id, topology),
        }
        for area in topology.process_areas
    ]


def build_orchestrator_system(
    specialists: list[dict],
    topology: TopologyConfig,
) -> str:
    """Return the Cascade (orchestrator) system prompt.

    Args:
        specialists: Output of build_specialists().
        topology: Loaded and validated TopologyConfig.
    """
    facility = topology.facility
    area_lines = "\n".join(
        f"  - {s['area_name']} (area_id: {s['area_id']},"
        f" instances: {', '.join(s['instance_ids'])})"
        for s in specialists
    )
    return (
        f"You are Cascade, the orchestrator for {facility.name}.\n"
        f"\n"
        f"Facility: {facility.description or facility.name}\n"
        f"Timezone: {facility.timezone}\n"
        f"\n"
        f"You have {len(specialists)} Specialist agent(s) available, one per process area:\n"
        f"{area_lines}\n"
        f"\n"
        f"Route each diagnostic query to the Specialist(s) responsible for the relevant"
        f" process area(s). Synthesize their findings into a single coherent response."
        f" Do not duplicate tool calls already made by Specialists."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _binding_qualifier(binding: TagBinding) -> str:
    if binding.confidence == "verified" and not binding.notes:
        return ""
    parts = []
    if binding.confidence != "verified":
        parts.append(f"confidence: {binding.confidence}")
    if binding.notes:
        parts.append(binding.notes)
    return " [" + "; ".join(parts) + "]"
