"""The egress client: every tenant-directed call leaves through it
(connections-and-vault R3; ADR-0115 decision 6).

`dw_connectors` never imports `dw_agent_runtime`, which depends on it: the
typed results are the kernel's (`dw_kernel.dispatch`), and the egress package
declares no error class of its own (R3.13).
"""

from dw_connectors.egress.client import EgressClient
from dw_connectors.egress.contracts import (
    AllowedHostRule,
    AllowedHostsPort,
    CatalogueHostsPort,
    EgressContext,
    EgressPort,
    EgressPurpose,
    EgressRequest,
    EgressResponse,
    NoCatalogueHosts,
    RedirectMode,
)

__all__ = [
    "AllowedHostRule",
    "AllowedHostsPort",
    "CatalogueHostsPort",
    "EgressClient",
    "EgressContext",
    "EgressPort",
    "EgressPurpose",
    "EgressRequest",
    "EgressResponse",
    "NoCatalogueHosts",
    "RedirectMode",
]
