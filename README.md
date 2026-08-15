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

### Air-gapped deployment

`KnowledgeClient` hits the network on first use for two things: DuckDB's
`vss` extension (fetched from DuckDB's extension repository) and
`FastEmbedProvider`'s ONNX model weights (fetched from Hugging Face Hub,
~130MB for the default model). Both cache locally after the first fetch, so
a deployment that pre-warms the cache while online never needs egress at
runtime.

Pre-fetch once, online:

```bash
python -c "
from fastembed import TextEmbedding
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='./vendor/fastembed')
"
python -c "
import duckdb
con = duckdb.connect()
con.execute(\"SET extension_directory = './vendor/duckdb-extensions'\")
con.execute('INSTALL vss')
"
```

Bake `./vendor/` into the deployment image, then point the client at it at
runtime:

```python
knowledge = KnowledgeClient(
    KnowledgeConfig(
        db_path="knowledge.duckdb",
        extension_directory="./vendor/duckdb-extensions",
    ),
    embedding_provider=FastEmbedProvider(
        cache_dir="./vendor/fastembed",
    ),
)
```

Set `HF_HUB_OFFLINE=1` in the runtime environment to make the no-network
guarantee explicit — fastembed respects it and fails loudly instead of
attempting a network call if the cache is somehow cold.

No HNSW index in v1: DuckDB's HNSW index requires an experimental
persistence flag for on-disk databases. A brute-force `array_cosine_distance`
scan is correct and fast at facility-doc corpus scale (hundreds to low
thousands of chunks); revisit if a deployment's corpus grows much larger.

## CLI

```bash
fieldworks validate topology.yaml
fieldworks validate topology.yaml --aggregator aggregator.json
```

## Gotcha: MCP server `lifespan=` runs per SSE session, not per process

If you build an `MCPServer` (from the upstream `mcp` SDK) with a `lifespan=`
context manager for one-time startup work — seeding a graph, starting a
background sync task, ingesting docs — guard it. Under the SSE transport,
`Server.run()` re-enters `lifespan` on every new connection, not once at
process start. A client that opens a fresh SSE session per tool call (a
common pattern) re-runs your "startup" code on every call, and if that
includes `asyncio.create_task(...)`, the tasks are never cancelled and leak
without bound.

Guard with a module-level flag:

```python
_started = False

@asynccontextmanager
async def _lifespan(server: MCPServer) -> AsyncIterator[None]:
    global _started
    if not _started:
        _started = True
        ...  # one-time startup work
    yield
```

This bit [fieldworks-core#34](https://github.com/fieldworks-build/fieldworks-core/issues/34):
memory-mcp accumulated one `AnalyticalClient.sync_loop()` task per SSE
session, degrading to DuckDB lock contention after enough tool calls.
`fieldworks-core` doesn't wrap `MCPServer` itself today, so there's no
framework-level code to patch — this note exists so the guard lands by
default whenever `memory-mcp`'s `server.py` is extracted into
`fieldworks/memory/`. (`mcp-aggregator` was checked and is not exposed: it
never passes `lifespan=` to the low-level `Server`, and its Starlette-level
`lifespan=` runs once per process via the real ASGI lifespan protocol, not
per connection.)
