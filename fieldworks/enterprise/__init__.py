"""Enterprise layer — multi-plant registry and federated read (spec Part V).

The plant-agnostic logic only. The MCP servers that expose it, the
cross-plant orchestrator's agentic loop and the transport to each plant
stay deployment code; fieldworks.agents.enterprise holds the orchestrator's
contract (prompt, tool schemas, answer formatting).
"""

from .federated import (
    FederatedResult,
    SiteUnavailable,
    UnknownSiteError,
    federated_read,
)
from .loader import load
from .schema import (
    EnterpriseConfig,
    EnterpriseInfo,
    RegionConfig,
    RegisteredSite,
    SiteConfig,
)
from .validator import validate

__all__ = [
    "load",
    "validate",
    "federated_read",
    "FederatedResult",
    "SiteUnavailable",
    "UnknownSiteError",
    "EnterpriseConfig",
    "EnterpriseInfo",
    "RegionConfig",
    "RegisteredSite",
    "SiteConfig",
]
