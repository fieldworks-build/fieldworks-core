"""Memory layer — LadybugDB graph, DuckDB analytical, and specialist memory.

Requires the optional `memory` extra: pip install fieldworks-core[memory]
"""

from fieldworks.memory.analytical import AnalyticalClient, AnalyticalConfig
from fieldworks.memory.graph import GraphClient, GraphConfig, aggregate_specialist_query
from fieldworks.memory.specialist import SpecialistMemory

__all__ = [
    "AnalyticalClient",
    "AnalyticalConfig",
    "GraphClient",
    "GraphConfig",
    "aggregate_specialist_query",
    "SpecialistMemory",
]
