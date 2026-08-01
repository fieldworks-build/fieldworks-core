# fieldworks-core

Core components for the Fieldworks industrial AI framework.

- `fieldworks.topology` — load and validate `topology.yaml` (plant model schema, Part II)
- `fieldworks.agents` — `build_specialist_prompt()`, `build_specialists()`, `build_orchestrator_system()`
- `fieldworks.aggregator` — load and validate `aggregator.json` (connection model, Part II)
- `fieldworks.memory` — `GraphClient`/`AnalyticalClient`/`SpecialistMemory` (LadybugDB graph + DuckDB analytical + file-based specialist memory) and `KnowledgeClient` (DuckDB+VSS document retrieval/RAG over facility docs) — requires the `memory`/`knowledge` extras, see below
- `fieldworks.topology_builder` — MQTT/OPC-UA discovery and topology inference (`crawl_mqtt`, `crawl_opcua`, `infer_topology`)
- `fieldworks.trust` — propose/approve/execute intercept and hash-chained audit trail across the four trust modes

## Install

```bash
pip install fieldworks-core
```

### Optional extras

| Extra | Adds | Unlocks |
|---|---|---|
| `memory` | `ladybug`, `duckdb`, `influxdb-client`, `pytz` | `GraphClient`, `AnalyticalClient`, `SpecialistMemory`, `MemoryClient` |
| `knowledge` | `duckdb`, `fastembed`, `pypdf` | `KnowledgeClient`, `FastEmbedProvider` — document ingestion/retrieval (RAG) |
| `adapters` | `mcp>=2.0` | `fieldworks test-adapter` CLI conformance checks |
| `trust` | `cryptography` | Hash-chained, encrypted audit log |

`memory` and `knowledge` are independent — a docs-only deployment can `pip install fieldworks-core[knowledge]` without pulling in `ladybug`/`influxdb-client`.

```bash
pip install fieldworks-core[memory,knowledge]
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

Knowledge/RAG over facility documentation (`pip install fieldworks-core[knowledge]`):

```python
from fieldworks.memory import KnowledgeClient, KnowledgeConfig, FastEmbedProvider

knowledge = KnowledgeClient(
    KnowledgeConfig(db_path="knowledge.duckdb"),
    embedding_provider=FastEmbedProvider(),  # local ONNX, no API key
)
knowledge.ingest_directory("facility-docs/")  # .md, .txt, text-layer .pdf

excerpts = knowledge.query("what is the maximum flow rate for the intake pump?", top_k=3)
```

## CLI

```bash
fieldworks validate topology.yaml
fieldworks validate topology.yaml --aggregator aggregator.json
```
