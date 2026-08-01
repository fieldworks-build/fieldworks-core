"""Memory layer — LadybugDB graph, DuckDB analytical/knowledge, and
specialist memory.

Two independent optional extras:
  pip install fieldworks-core[memory]     # GraphClient, AnalyticalClient, SpecialistMemory, MemoryClient
  pip install fieldworks-core[knowledge]  # KnowledgeClient, FastEmbedProvider

Each submodule import is isolated so installing one extra without the
other doesn't break `from fieldworks.memory import ...` — a docs-only
deployment shouldn't need ladybug/influxdb-client, and a graph/analytical
deployment shouldn't need fastembed/pypdf.
"""

__all__: list[str] = []

try:
    from fieldworks.memory.analytical import AnalyticalClient, AnalyticalConfig

    __all__ += ["AnalyticalClient", "AnalyticalConfig"]
except ImportError:
    pass

try:
    from fieldworks.memory.graph import (
        GraphClient,
        GraphConfig,
        aggregate_specialist_query,
    )

    __all__ += ["GraphClient", "GraphConfig", "aggregate_specialist_query"]
except ImportError:
    pass

try:
    from fieldworks.memory.specialist import SpecialistMemory

    __all__ += ["SpecialistMemory"]
except ImportError:
    pass

if "GraphClient" in __all__ and "SpecialistMemory" in __all__:
    from fieldworks.memory.client import MemoryClient

    __all__ += ["MemoryClient"]

try:
    from fieldworks.memory.embeddings import (
        EmbeddingProvider,
        FakeEmbeddingProvider,
        FastEmbedProvider,
    )

    __all__ += ["EmbeddingProvider", "FakeEmbeddingProvider", "FastEmbedProvider"]
except ImportError:
    pass

try:
    from fieldworks.memory.knowledge import KnowledgeClient, KnowledgeConfig

    __all__ += ["KnowledgeClient", "KnowledgeConfig"]
except ImportError:
    pass
