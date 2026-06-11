"""Load and parse topology.yaml into a validated TopologyConfig."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import TopologyConfig


def load(path: str | Path) -> TopologyConfig:
    """Load topology.yaml and return a validated TopologyConfig.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file fails schema validation.
    """
    p = Path(path)
    with open(p) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"topology.yaml must be a YAML mapping, got {type(data).__name__}")
    try:
        return TopologyConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid topology.yaml:\n{exc}") from exc
