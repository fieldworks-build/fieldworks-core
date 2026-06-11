"""Load and validate aggregator.json — the FieldWorks connection model (Part II)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError


class ServerDef(BaseModel):
    name: str
    url: str
    include_tools: list[str] | None = None
    default_args: dict | None = None
    timeout_ms: int = 5000
    description: str | None = None


class AggregatorConfig(BaseModel):
    servers: list[ServerDef]

    def server_names(self) -> set[str]:
        return {s.name for s in self.servers}

    def get_server(self, name: str) -> ServerDef:
        for s in self.servers:
            if s.name == name:
                return s
        raise KeyError(name)


def load_aggregator_config(path: str | Path) -> AggregatorConfig:
    """Load aggregator.json and return a validated AggregatorConfig.

    The spec defines aggregator.json as a JSON array of server definitions.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file is not a JSON array or fails validation.
    """
    p = Path(path)
    with open(p) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"aggregator.json must be a JSON array of server definitions,"
            f" got {type(data).__name__}"
        )
    try:
        return AggregatorConfig(servers=[ServerDef.model_validate(s) for s in data])
    except ValidationError as exc:
        raise ValueError(f"Invalid aggregator.json:\n{exc}") from exc
