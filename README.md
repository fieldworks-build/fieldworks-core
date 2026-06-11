# fieldworks-core

Core components for the Fieldworks industrial AI framework.

- `fieldworks.topology` — load and validate `topology.yaml` (plant model schema, Part II)
- `fieldworks.agents` — `build_specialist_prompt()`, `build_specialists()`, `build_orchestrator_system()`
- `fieldworks.aggregator` — load and validate `aggregator.json` (connection model, Part II)

## Install

```bash
pip install fieldworks-core
```

## Usage

```python
from fieldworks.topology import load, validate
from fieldworks.agents import build_specialist_prompt, build_specialists

topology = load("topology.yaml")
result = validate(topology)
if result.warnings:
    for w in result.warnings:
        print(f"warning: {w}")

specialists = build_specialists(topology)
```

## CLI

```bash
fieldworks validate topology.yaml
fieldworks validate topology.yaml --aggregator aggregator.json
```
