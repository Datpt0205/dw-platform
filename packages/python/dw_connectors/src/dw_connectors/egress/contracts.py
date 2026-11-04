"""What a caller hands the egress client, and what it gets back
(connections-and-vault R3; ADR-0115 decision 6).

The client opens no secret and asks no question about a connection: the caller
(the connection's broker, ticket 04; `SmtpEgress` and the manifest handler,
ticket 05) has done both before it calls, and names on the request the secret
values it placed in a header or the body, so the client can scrub them from
what it returns, raises and logs.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from dw_kernel.run_mode import RunMode

__all__ = [
    "AllowedHostRule",
    "AllowedHostsPort",
    "CatalogueHostsPort",
    "EgressContext",
    "EgressPort",
    "EgressPurpose",
    "EgressRequest",
    "EgressResponse",
    "NoCatalogueHosts",
    "RedirectMode",
]

EgressPurpose = Literal["connector", "oauth", "http_tool", "mcp", "webhook", "model"]
"""Why the call leaves. `connector` and `oauth` go only to a catalogue
connector's manifest hosts (R3.17); every other purpose goes only to the
company's Allowed hosts (R3.7)."""

RedirectMode = Literal["none", "same_origin", "revalidate"]
"""`none`, the default: a 3xx ends the call. `same_origin`: followed while it
stays on the scheme, host and port it started on. `revalidate`: followed
anywhere the checks of the first step admit, each step checked again."""


@dataclass(frozen=True)
class EgressContext:
    """Who the call is for and under what run. `run_mode` and `purpose` have no
    default: a caller that cannot say them must not call (tenant-config R5.4)."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    run_id: uuid.UUID | None
    run_mode: RunMode
    purpose: EgressPurpose
    connector_key: str | None = None
    connection_id: uuid.UUID | None = None
    # A read-only action may run outside `live` (tenant-config R5.5); only the
    # tool's own declaration sets it, never the call's arguments.
    simulate_safe: bool = False


@dataclass(frozen=True)
class EgressRequest:
    """One call. `secret_values` are the values the caller put in a header or
    the body; they are scrubbed from the response, errors and logs, and never
    logged themselves (nor are the headers or body, which carry them)."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    content: bytes | None = field(default=None, repr=False)
    # The tool's own `timeout_seconds`: the whole call, every redirect included.
    timeout_seconds: float = 30.0
    redirect: RedirectMode = "none"
    secret_values: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class EgressResponse:
    """A 2xx read in full within the 2 MiB cap, the call's secrets scrubbed."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes = field(repr=False)
    url: str


class EgressPort(Protocol):
    """The one door to tenant-directed traffic: an `EgressResponse`, or exactly
    one of `NotDispatchedError`, `RejectedError`, `OutcomeUnknownError`."""

    async def send(self, context: EgressContext, request: EgressRequest) -> EgressResponse: ...


class AllowedHostRule(Protocol):
    """One live row of `platform.egress_allowed_hosts`, as the client reads it."""

    @property
    def host_pattern(self) -> str: ...

    @property
    def ports(self) -> Sequence[int]: ...

    @property
    def purpose(self) -> str: ...


class AllowedHostsPort(Protocol):
    """Declared here, satisfied by the platform's table (R3.7, R3.21)."""

    async def live(self, tenant_id: uuid.UUID) -> Sequence[AllowedHostRule]:
        """Every row of the tenant whose `removed_at` is NULL, read on every
        call: a removal takes effect at the next one (R3.18)."""
        ...


class CatalogueHostsPort(Protocol):
    """The hosts a catalogue connector's platform-layer manifest declares
    (`egress_hosts`, R3.17). Declared by the client that reads it."""

    def egress_hosts(self, connector_key: str) -> frozenset[str]: ...


@dataclass(frozen=True)
class NoCatalogueHosts:
    """W1's answer: no connector declares a host yet, so every `connector` and
    `oauth` call is refused until the first HTTP connector binds its manifest's
    `egress_hosts` (W2, spec "Ngoài phạm vi")."""

    def egress_hosts(self, connector_key: str) -> frozenset[str]:
        return frozenset()
