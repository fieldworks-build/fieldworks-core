"""Composite facade bundling graph + file-based specialist memory.

build_specialist_prompt(..., memory_client=...) takes one of these rather
than a GraphClient and a SpecialistMemory separately, so the prompt builder
has a single optional dependency to check for None.
"""

from __future__ import annotations

from dataclasses import dataclass

from fieldworks.memory.graph import GraphClient
from fieldworks.memory.specialist import SpecialistMemory

_MAX_INCIDENTS_PER_INSTANCE = 3


@dataclass
class MemoryClient:
    graph: GraphClient
    specialist_memory: SpecialistMemory

    def get_context(self, area_id: str, instance_ids: list[str]) -> str:
        """Return prependable text combining accumulated specialist memory and
        recent incident history for the given area's equipment. "" if neither
        source has anything to contribute.
        """
        sections: list[str] = []

        memory_text = self.specialist_memory.get(area_id).strip()
        if memory_text:
            sections.append(
                "── Accumulated knowledge from prior sessions ──\n" + memory_text
            )

        incident_lines: list[str] = []
        for instance_id in instance_ids:
            history = self.graph.get_equipment_history(
                instance_id, limit=_MAX_INCIDENTS_PER_INSTANCE
            )
            for inc in history["incidents"]:
                incident_lines.append(
                    f"  - {instance_id} [{inc['ts']}] {inc['status']}"
                    f" (confidence {inc['confidence']}): {inc['diagnosis']}"
                )
        if incident_lines:
            sections.append(
                "── Recent incident history ──\n" + "\n".join(incident_lines)
            )

        return "\n\n".join(sections)
