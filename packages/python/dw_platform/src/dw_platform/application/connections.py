"""The shared connections of a workspace, and the one rule on using one
(connections-and-vault R5; ADR-0115 decision 2; DO-48).

`ConnectionUsability.connection_usable(connection, context, purpose)` is the
single answer to "may this run use this connection now". Its three callers are
elsewhere: binding review and run admission (tenant-config/05), and the egress
call of a connector action (ticket 05). A caller outside `dw_platform` declares
its own Protocol with this method and the composition root hands it this one.

The rule reads in a short transaction of its own, under the asking context's
company, on every call and through no cache, so a disable committed before the
question is always seen (R5.5). It reads no `platform.worker_runs` row, no run
manifest and no pinned secret version: the caller passes the principal, the
workspace and when the run was requested (ADR-0109 decision 6; V4.35). In
order, it answers false when:

1. the company has no such connection, a deleted one included
   (`connection_not_found`);
2. `purpose` is not `tool`, the one purpose P1 knows (`purpose_not_allowed`;
   R5.14); W2's model connections add a value here, no call site changes;
3. the status is not `active` (`connection_disabled`; R5.5);
4. the share scope is not `workspace`, or the connection belongs to another
   workspace than the context's (`connection_out_of_scope`; R5.4, R5.20);
5. there is no principal, or `platform.workspace_reach` does not give the
   principal `connections.use` in the context's workspace
   (`connection_use_denied`; R5.9): the depth has one owner;
6. at the egress call only (`credential_revoked`; R5.15, R5.16): the run's
   request time is unknown, the connector declares no secret fields here, a
   declared field has no version left that is not revoked (none left at all
   included), or the connection was revoked for compromise at or after the
   moment the run was requested. A rotation alone stops nothing (R5.17).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, get_args

from dw_platform.application.secrets import SecretVersionStatus

__all__ = [
    "CALL_SITES",
    "CONNECTIONS_MANAGE_SCOPE",
    "CONNECTIONS_READ_SCOPE",
    "CONNECTIONS_USE_SCOPE",
    "CallSite",
    "Connection",
    "ConnectionStatus",
    "ConnectionUsability",
    "ConnectorCatalogPort",
    "NoConnectorCatalog",
    "Usability",
    "UsabilityReason",
    "UsabilityStorePort",
    "UsabilityTx",
    "UsableContext",
]

# The three keys of the connections area (migration 388a31c46bdf), each read
# at the depth `platform.workspace_reach` gives it (ADR-0104 decision 5).
CONNECTIONS_READ_SCOPE = "connections.read"
CONNECTIONS_MANAGE_SCOPE = "connections.manage"
CONNECTIONS_USE_SCOPE = "connections.use"

ConnectionStatus = Literal["pending", "active", "needs_reauth", "disabled", "revoked"]
CallSite = Literal["binding_review", "run_admission", "egress"]
CALL_SITES: frozenset[str] = frozenset(get_args(CallSite))
UsabilityReason = Literal[
    "connection_not_found",
    "purpose_not_allowed",
    "connection_disabled",
    "connection_out_of_scope",
    "connection_use_denied",
    "credential_revoked",
]

# P1 knows tool calls only; W2's model connections add `model` (ADR-0118).
_USABLE_PURPOSES = frozenset({"tool"})
_SHARED_BY_WORKSPACE = "workspace"


@dataclass(frozen=True, slots=True)
class Connection:
    """One row of `platform.connections`, never a secret."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    owning_workspace_id: uuid.UUID
    name: str
    connector_key: str
    connector_major: int
    share_scope: str
    external_account: str | None
    status: str
    scopes: tuple[str, ...]
    last_used_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None
    compromised_at: datetime | None


class ConnectorCatalogPort(Protocol):
    """The secret fields a connector's manifest declares in its `auth`
    (declared by this consumer). None: the platform layer has no such
    connector, and nothing is created, rotated or used with it."""

    def secret_fields(self, connector_key: str, connector_major: int) -> frozenset[str] | None: ...


class NoConnectorCatalog:
    """W1, until ticket 05 wires the manifests (`smtp@1.0.0`: `{password}`):
    no connector is known, so every create is refused and every egress
    question answers `credential_revoked` (closed while missing)."""

    def secret_fields(self, connector_key: str, connector_major: int) -> frozenset[str] | None:
        return None


@dataclass(frozen=True, slots=True)
class UsableContext:
    """Who asks, for which run or value, and from where. Every field comes
    from the caller's verified run or review, never from a request body."""

    tenant_id: uuid.UUID
    # The principal the run acts for (`coalesce(run_as_principal_id,
    # requested_by)` of its run row, which `RunBindingsPort` reads; the manifest
    # names none), or the person proposing a binding value; None is refused.
    principal_id: uuid.UUID | None
    # The run's workspace, or the workspace of the value under review.
    workspace_id: uuid.UUID
    # Required, no default: only the egress call asks about the secrets.
    call_site: CallSite
    # `created_at` of the run's `platform.worker_runs` row; None at egress is
    # refused (closed while missing).
    run_requested_at: datetime | None

    def __post_init__(self) -> None:
        if self.call_site not in CALL_SITES:
            raise ValueError(f"not a call site: {self.call_site!r}")


@dataclass(frozen=True, slots=True)
class Usability:
    usable: bool
    reason: UsabilityReason | None = None


_USABLE = Usability(usable=True)


def _refused(reason: UsabilityReason) -> Usability:
    return Usability(usable=False, reason=reason)


class UsabilityTx(Protocol):
    """What the rule reads, inside one transaction under the context's company."""

    async def connection(self, connection_id: uuid.UUID, *, lock: bool) -> Connection | None: ...

    async def reach(self, key: str) -> frozenset[uuid.UUID]:
        """The workspaces `platform.workspace_reach` gives the transaction's
        principal with `key`; empty without a principal."""
        ...

    async def secret_versions(
        self, connection_id: uuid.UUID, secret_field: str
    ) -> Sequence[SecretVersionStatus]:
        """`platform.secret_status`: every version still held, never a value."""
        ...

    async def database_now(self) -> datetime:
        """The transaction's own `now()`, which the door functions compare with."""
        ...


class UsabilityStorePort(Protocol):
    def transaction(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None,
        principal_id: uuid.UUID | None,
    ) -> AbstractAsyncContextManager[UsabilityTx]: ...


@dataclass(frozen=True)
class ConnectionUsability:
    """The one rule (ADR-0115 decision 2), built once at a composition root."""

    store: UsabilityStorePort
    catalog: ConnectorCatalogPort

    async def connection_usable(
        self, connection: uuid.UUID, context: UsableContext, purpose: str
    ) -> Usability:
        async with self.store.transaction(
            context.tenant_id,
            workspace_id=context.workspace_id,
            principal_id=context.principal_id,
        ) as tx:
            row = await tx.connection(connection, lock=False)
            if row is None:
                return _refused("connection_not_found")
            if purpose not in _USABLE_PURPOSES:
                return _refused("purpose_not_allowed")
            if row.status != "active":
                return _refused("connection_disabled")
            if (
                row.share_scope != _SHARED_BY_WORKSPACE
                or row.owning_workspace_id != context.workspace_id
            ):
                return _refused("connection_out_of_scope")
            if context.principal_id is None or context.workspace_id not in await tx.reach(
                CONNECTIONS_USE_SCOPE
            ):
                return _refused("connection_use_denied")
            if context.call_site == "egress" and not await self._credentials_live(
                tx, row, context.run_requested_at
            ):
                return _refused("credential_revoked")
        return _USABLE

    async def _credentials_live(
        self, tx: UsabilityTx, row: Connection, run_requested_at: datetime | None
    ) -> bool:
        if run_requested_at is None:
            return False
        if row.compromised_at is not None and run_requested_at <= row.compromised_at:
            return False
        fields = self.catalog.secret_fields(row.connector_key, row.connector_major)
        if fields is None:
            return False
        now = await tx.database_now()
        for secret_field in sorted(fields):
            versions = await tx.secret_versions(row.id, secret_field)
            if not any(v.revoked_at is None or v.revoked_at > now for v in versions):
                return False
        return True
