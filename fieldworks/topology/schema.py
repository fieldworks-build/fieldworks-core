"""Pydantic models for topology.yaml — the FieldWorks plant model schema (Part II)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, model_validator

# ---------------------------------------------------------------------------
# facility
# ---------------------------------------------------------------------------


class FacilityConfig(BaseModel):
    name: str
    site_id: str
    description: str | None = None
    timezone: str
    units_system: str = "metric"


# ---------------------------------------------------------------------------
# process_areas
# ---------------------------------------------------------------------------


class ProcessArea(BaseModel):
    id: str
    name: str
    description: str
    specialist_prompt: str | None = None


# ---------------------------------------------------------------------------
# equipment_types — attributes
# ---------------------------------------------------------------------------


class NormalRange(BaseModel):
    min: float
    max: float
    description: str | None = None

    @model_validator(mode="after")
    def min_lt_max(self) -> NormalRange:
        if self.min >= self.max:
            raise ValueError(
                f"normal_range.min ({self.min}) must be less than max ({self.max})"
            )
        return self


class AttributeDef(BaseModel):
    id: str
    name: str
    description: str | None = None
    units: str
    normal_range: NormalRange
    writable: bool = False


# ---------------------------------------------------------------------------
# equipment_types — fault_modes
# ---------------------------------------------------------------------------


class FaultMode(BaseModel):
    id: str
    name: str
    description: str
    severity: Literal["advisory", "warning", "critical"]
    affected_attributes: list[str]


# ---------------------------------------------------------------------------
# equipment_types
# ---------------------------------------------------------------------------


class EquipmentType(BaseModel):
    id: str
    name: str
    description: str
    attributes: list[AttributeDef]
    fault_modes: list[FaultMode]

    @model_validator(mode="after")
    def _fault_attributes_exist(self) -> EquipmentType:
        attr_ids = {a.id for a in self.attributes}
        for fm in self.fault_modes:
            for attr_id in fm.affected_attributes:
                if attr_id not in attr_ids:
                    raise ValueError(
                        f"fault_mode '{fm.id}' references unknown attribute '{attr_id}'"
                    )
        return self


# ---------------------------------------------------------------------------
# equipment_instances — tag bindings (simple string or expanded form)
# ---------------------------------------------------------------------------


class TagBinding(BaseModel):
    tag_id: str
    confidence: Literal["verified", "inferred", "suspect"] = "verified"
    notes: str | None = None


def _coerce_tag_binding(v: object) -> object:
    """Accept plain strings as verified bindings."""
    if isinstance(v, str):
        return {"tag_id": v, "confidence": "verified"}
    return v


TagBindingValue = Annotated[TagBinding, BeforeValidator(_coerce_tag_binding)]


# ---------------------------------------------------------------------------
# equipment_instances
# ---------------------------------------------------------------------------


class EquipmentInstance(BaseModel):
    id: str
    name: str
    type_id: str
    process_area_id: str
    description: str | None = None
    tag_bindings: dict[str, TagBindingValue]
    commissioned: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# historian
# ---------------------------------------------------------------------------


class HistorianConfig(BaseModel):
    default_lookback_hours: int
    max_lookback_days: int
    resolution_seconds: int | None = None
    source: str | None = None


# ---------------------------------------------------------------------------
# TopologyConfig — root model with cross-reference validation
# ---------------------------------------------------------------------------


class TopologyConfig(BaseModel):
    facility: FacilityConfig
    process_areas: list[ProcessArea]
    equipment_types: list[EquipmentType]
    equipment_instances: list[EquipmentInstance]
    historian: HistorianConfig

    @model_validator(mode="after")
    def _cross_references(self) -> TopologyConfig:
        type_ids = {et.id for et in self.equipment_types}
        area_ids = {pa.id for pa in self.process_areas}
        for inst in self.equipment_instances:
            if inst.type_id not in type_ids:
                raise ValueError(
                    f"instance '{inst.id}' references unknown type_id '{inst.type_id}'"
                )
            if inst.process_area_id not in area_ids:
                raise ValueError(
                    f"instance '{inst.id}' references unknown process_area_id"
                    f" '{inst.process_area_id}'"
                )
        return self

    # ------------------------------------------------------------------
    # Convenience lookups
    # ------------------------------------------------------------------

    def get_equipment_type(self, type_id: str) -> EquipmentType:
        for et in self.equipment_types:
            if et.id == type_id:
                return et
        raise KeyError(type_id)

    def get_process_area(self, area_id: str) -> ProcessArea:
        for pa in self.process_areas:
            if pa.id == area_id:
                return pa
        raise KeyError(area_id)

    def instances_in_area(self, area_id: str) -> list[EquipmentInstance]:
        return [i for i in self.equipment_instances if i.process_area_id == area_id]
