"""Cross-file enterprise.yaml validation (spec Part V, Validation).

load() has already enforced the structural rules. This checks what needs
each site's topology.yaml: that it exists, loads and validates as a
topology (Part II), and declares a facility.site_id equal to the site's
site_id — the one identifier that names a plant everywhere.
"""

from __future__ import annotations

from pathlib import Path

from fieldworks.topology.loader import load as load_topology
from fieldworks.topology.validator import ValidationResult
from fieldworks.topology.validator import validate as validate_topology

from .schema import EnterpriseConfig


def validate(config: EnterpriseConfig, base_dir: str | Path) -> ValidationResult:
    """Check every site's topology_file against the registry.

    Args:
        config: A loaded EnterpriseConfig.
        base_dir: Directory topology_file paths resolve against — the
            directory holding enterprise.yaml.

    Topology warnings are passed through prefixed with the site_id; topology
    errors make the enterprise invalid.
    """
    result = ValidationResult()
    base = Path(base_dir)
    for site_id, site in config.sites().items():
        path = Path(site.topology_file)
        if not path.is_absolute():
            path = base / path
        try:
            topology = load_topology(path)
        except FileNotFoundError:
            result.errors.append(
                f"site {site_id!r}: topology_file not found: {site.topology_file}"
            )
            continue
        except ValueError as exc:
            result.errors.append(
                f"site {site_id!r}: topology_file {site.topology_file} is not a"
                f" valid topology.yaml:\n{exc}"
            )
            continue

        if topology.facility.site_id != site_id:
            result.errors.append(
                f"site {site_id!r}: topology_file {site.topology_file} declares"
                f" facility.site_id {topology.facility.site_id!r}; the two must"
                " be equal"
            )

        topo_result = validate_topology(topology)
        result.errors.extend(f"site {site_id!r}: {e}" for e in topo_result.errors)
        result.warnings.extend(f"site {site_id!r}: {w}" for w in topo_result.warnings)
    return result
