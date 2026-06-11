"""Static topology validator — checks constraints that produce warnings, not errors.

The Pydantic schema (schema.py) handles structural validation and raises on hard
errors (missing required fields, bad cross-references, invalid severity values).
This module adds the softer checks the spec calls out as warnings:

  - Tag bindings that cover all type attributes (missing = warn, not fail).
  - normal_range.min < max is a hard error in the schema but listed here for
    completeness in case it's ever relaxed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import TopologyConfig


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def __bool__(self) -> bool:
        return self.valid


def validate(topology: TopologyConfig, aggregator_server_names: set[str] | None = None) -> ValidationResult:
    """Run soft validation against an already-loaded TopologyConfig.

    Args:
        topology: A loaded and structurally valid TopologyConfig.
        aggregator_server_names: If provided, also validates historian.source
            against this set (corresponds to --aggregator flag in the CLI).

    Returns:
        ValidationResult with any warnings. Errors here indicate logic bugs in
        the caller — structural errors are caught by load().
    """
    result = ValidationResult()

    # Tag binding completeness — warn on missing, never fail.
    for inst in topology.equipment_instances:
        try:
            eq_type = topology.get_equipment_type(inst.type_id)
        except KeyError:
            # Already caught as a hard error by the schema; skip.
            continue
        attr_ids = {a.id for a in eq_type.attributes}
        bound_ids = set(inst.tag_bindings.keys())
        for missing in sorted(attr_ids - bound_ids):
            result.warnings.append(
                f"instance '{inst.id}': attribute '{missing}' has no tag binding"
                f" (not instrumented)"
            )

    # historian.source cross-reference (only when aggregator is available).
    if aggregator_server_names is not None and topology.historian.source is not None:
        if topology.historian.source not in aggregator_server_names:
            result.errors.append(
                f"historian.source '{topology.historian.source}' not found in"
                f" aggregator server names: {sorted(aggregator_server_names)}"
            )

    return result
