"""The egress client as the API composes it (connections-and-vault R3;
ADR-0115 decision 6).

The one place `allow_private` and `require_https` are set, from the profile and
from nothing else: no environment variable of their own. Outside a deployed
profile a call may reach a private address (a provider mock on the dev host)
and plain `http`; deployed, neither (R3.2, R3.20). The Allowed hosts are read
from Postgres on every call, and no catalogue connector declares a host in W1.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_api.settings import ApiSettings
from dw_connectors.egress import EgressClient, NoCatalogueHosts
from dw_observability.telemetry import TelemetryPort
from dw_platform.adapters.persistence.egress_allowlist_repo import SqlAllowedHosts


def build_egress_client(
    settings: ApiSettings,
    session_factory: async_sessionmaker[AsyncSession],
    telemetry: TelemetryPort,
) -> EgressClient:
    return EgressClient(
        allowed_hosts=SqlAllowedHosts(session_factory),
        catalogue=NoCatalogueHosts(),
        allow_private=not settings.is_deployed,
        require_https=settings.is_deployed,
        telemetry=telemetry,
    )
