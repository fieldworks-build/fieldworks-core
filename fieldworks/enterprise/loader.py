"""Load enterprise.yaml into a validated EnterpriseConfig."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import EnterpriseConfig


def load(path: str | Path) -> EnterpriseConfig:
    """Load enterprise.yaml and return a structurally valid EnterpriseConfig.

    A site missing a required field is an error, never a site to skip:
    silently dropping a plant would leave every cross-plant answer quietly
    incomplete (spec Part V, Validation). Cross-file checks against each
    site's topology_file are validator.validate()'s job; a conformant
    deployment runs both, as `fieldworks validate-enterprise` does.

    Cheap enough to call per request — it reads one small YAML file and
    opens no topology files — so a host can pick up a newly registered
    site without restarting.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file fails schema validation.
    """
    p = Path(path)
    with open(p) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"enterprise.yaml must be a YAML mapping, got {type(data).__name__}"
        )
    try:
        return EnterpriseConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid enterprise.yaml:\n{exc}") from exc
