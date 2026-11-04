"""Administering the shared connections of a workspace (connections-and-vault
R1.15, R5.1-R5.3, R5.8, R5.10-R5.13, R5.18-R5.21; ADR-0115 decision 2; D11).

**Who may** (R5.18; ADR-0104 decision 5), one rule for every operation, read
from `platform.workspace_reach` and nothing recomputed: a connection whose
owning workspace the caller does not reach with `connections.read` is a 404,
another company's included (RLS hides it first); one they read and do not reach
with `connections.manage` is a 403 on a write, before anything is written or
opened. A create happens in the caller's working workspace, which must be in
their `connections.manage` reach.

**What** each write does, each in one transaction with its audit row, in the
owning workspace and in the caller's name:

- create: the row `active`, then every secret field the connector declares
  through the vault (`SecretStore.put`), all or nothing (R5.1);
- update: the name, and a new version of a declared secret field (a rotation,
  which stops no run, R5.17); never the status, scope, connector or account;
- disable: `active -> disabled` at once, one person (R5.5);
- enable: no status change, but a strict run-less `connections.enable`
  approval in the owning workspace, stamped `connections.manage`, opened only
  while someone but the caller could decide it (R5.10, R5.13); its decision is
  carried out by `ConnectionEnableSettler` on the worker (R5.12, R5.19);
- revoke for compromise: every version revoked and `compromised_at` stamped by
  `platform.revoke_connection_secrets`, one person, at once (R1.15);
- delete: refused while `ConnectionDependentsPort` counts a dependent; the
  envelopes go with the row by FK CASCADE (R5.8).

A secret value is never returned, logged or audited; an answer names the
fields and whether each still has a version that is not revoked (R5.2).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.secret import Secret
from dw_platform.application.access_context import AccessContext
from dw_platform.application.connections import (
    CONNECTIONS_MANAGE_SCOPE,
    CONNECTIONS_READ_SCOPE,
    Connection,
    ConnectorCatalogPort,
    UsabilityTx,
)
from dw_platform.application.effect_keys import EffectClaim, PendingEffect
from dw_platform.application.secrets import (
    SecretCaller,
    SecretEnvelopeDoorPort,
    SecretStore,
    SecretSubject,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest, decided_event_type
from dw_platform.domain.audit import AuditEvent

__all__ = [
    "CONNECTIONS_ENABLE",
    "CONNECTIONS_ENABLE_DECIDED",
    "ConnectionDependents",
    "ConnectionDependentsPort",
    "ConnectionDetail",
    "ConnectionEnableSettler",
    "ConnectionPatch",
    "ConnectionService",
    "ConnectionStorePort",
    "ConnectionTx",
    "DependentRef",
    "EnableDecision",
    "NewConnection",
    "NoConnectionDependents",
    "Revocation",
    "SecretFieldState",
]

CONNECTIONS_ENABLE = "connections.enable"
CONNECTIONS_ENABLE_DECIDED = decided_event_type(CONNECTIONS_ENABLE)

CREATED = "connection.created"
UPDATED = "connection.updated"
DISABLED = "connection.disabled"
ENABLED = "connection.enabled"
DELETED = "connection.deleted"
CREDENTIALS_REVOKED = "connection.credentials_revoked"

# The lane carrying out the decision, named in `details.lane` of the audit row
# standing in the decider's name (CLAUDE.md, lane audit).
SETTLING_LANE = "outbox"
RESOURCE = "connection"
SUBJECT_KIND = "connection"
SHARED_BY_WORKSPACE = "workspace"
NAME_MAX = 200


@dataclass(frozen=True, slots=True)
class DependentRef:
    kind: str
    id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class ConnectionDependents:
    """`total` counts every dependent; `visible` only those the caller reads
    (tenant-config R3.4, R3.7)."""

    total: int
    visible: tuple[DependentRef, ...] = ()


class ConnectionDependentsPort(Protocol):
    """Who uses a connection: answered by tenant-config/05 (`studio.dependencies`
    and the approved binding values). Raising stops a delete (closed)."""

    async def dependents(
        self, context: AccessContext, connection_id: uuid.UUID
    ) -> ConnectionDependents: ...


class NoConnectionDependents:
    """Until tenant-config/05 replaces it at the composition root: true then,
    since no binding set carries a connection value before it (DO-06)."""

    async def dependents(
        self, context: AccessContext, connection_id: uuid.UUID
    ) -> ConnectionDependents:
        return ConnectionDependents(total=0)


@dataclass(frozen=True, slots=True)
class SecretFieldState:
    """A declared secret field and whether a version of it is not revoked
    ("Đã cấu hình"); never its value."""

    field: str
    configured: bool


@dataclass(frozen=True, slots=True)
class ConnectionDetail:
    connection: Connection
    secret_fields: tuple[SecretFieldState, ...]
    pending_enable_approval_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class NewConnection:
    name: str
    connector_key: str
    connector_major: int
    external_account: str
    share_scope: str
    secrets: Mapping[str, Secret] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ConnectionPatch:
    name: str | None = None
    secrets: Mapping[str, Secret] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class Revocation:
    compromised_at: datetime
    versions: int


@dataclass(frozen=True, slots=True)
class EnableDecision:
    """A decided `connections.enable` approval, as its settlement reads it."""

    approval_id: uuid.UUID
    approved: bool
    decided_by: uuid.UUID
    requested_by: uuid.UUID
    connection_id: uuid.UUID | None
    created_at: datetime


class ConnectionTx(UsabilityTx, Protocol):
    """One transaction under one company's RLS, its principal bound for `reach`."""

    async def page(self, request: PageRequest, read_key: str) -> Sequence[Connection]:
        """Newest first, only connections whose owning workspace the principal
        reaches with `read_key`."""
        ...

    async def insert(self, row: Connection) -> None:
        """ConflictError `connection_exists` on `uq_connections_account_live`."""
        ...

    async def rename(self, connection_id: uuid.UUID, name: str) -> None: ...

    async def set_status(
        self,
        connection_id: uuid.UUID,
        status: str,
        *,
        enable_approval: uuid.UUID | None = None,
    ) -> None:
        """Through `platform.guard_connection_status()`; `enable_approval` is
        set as `app.connection_enable_approval` for this transaction."""
        ...

    async def delete(self, connection_id: uuid.UUID) -> None: ...

    async def revoke_secrets(self, connection_id: uuid.UUID) -> Revocation | None:
        """`platform.revoke_connection_secrets`; None when the company has no
        such connection."""
        ...

    async def pending_enable(self, connection_id: uuid.UUID) -> uuid.UUID | None: ...

    async def has_checker(self, key: str, proposer: uuid.UUID, workspace: uuid.UUID) -> bool:
        """Whether `platform.checker_candidates` names someone but `proposer`."""
        ...

    async def open_approval(self, request: ApprovalRequest) -> None:
        """Insert the request stamped with the database's clock read now, after
        every lock this transaction took (so after the row's `disabled_at`)."""
        ...

    async def enable_decision(self, approval_id: uuid.UUID) -> EnableDecision | None: ...

    async def claim(self, claim: EffectClaim) -> None: ...

    async def audit(self, event: AuditEvent) -> None: ...

    def secrets(self) -> SecretEnvelopeDoorPort: ...


class ConnectionStorePort(Protocol):
    def transaction(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None,
        principal_id: uuid.UUID | None,
    ) -> AbstractAsyncContextManager[ConnectionTx]: ...


def _position(row: Connection) -> CursorPosition:
    return CursorPosition(sort_value=row.created_at, tiebreaker=row.id)


def _invalid(message: str, reason: str, **details: object) -> DomainError:
    return DomainError(message, details={"reason_code": reason, **details})


def _text(value: str, what: str, *, limit: int | None = None) -> str:
    """Trimmed at both ends; empty is refused, so R5.21's unique cannot be
    walked around with NULL or blanks."""
    trimmed = value.strip()
    if not trimmed:
        raise _invalid(f"{what} is required", f"{what}_required")
    if limit is not None and len(trimmed) > limit:
        raise _invalid(f"{what} is too long", f"{what}_too_long", max_length=limit)
    return trimmed


@dataclass(frozen=True)
class ConnectionService:
    store: ConnectionStorePort
    secrets: SecretStore
    catalog: ConnectorCatalogPort
    dependents_port: ConnectionDependentsPort
    clock: UtcClock
    id_generator: IdGenerator

    # ---- who may ------------------------------------------------------------

    def _tx(self, context: AccessContext) -> AbstractAsyncContextManager[ConnectionTx]:
        return self.store.transaction(
            context.tenant_id,
            workspace_id=context.workspace_id,
            principal_id=context.principal_id,
        )

    @staticmethod
    async def _readable(tx: ConnectionTx, connection_id: uuid.UUID, *, lock: bool) -> Connection:
        row = await tx.connection(connection_id, lock=lock)
        if row is None or row.owning_workspace_id not in await tx.reach(CONNECTIONS_READ_SCOPE):
            raise NotFoundError("connection not found", details={"id": str(connection_id)})
        return row

    @staticmethod
    async def _writable(tx: ConnectionTx, row: Connection) -> None:
        if row.owning_workspace_id not in await tx.reach(CONNECTIONS_MANAGE_SCOPE):
            raise PermissionDeniedError(
                "you may read this connection and not change it",
                details={"action": CONNECTIONS_MANAGE_SCOPE},
            )

    @staticmethod
    async def _may_create(tx: ConnectionTx, context: AccessContext) -> None:
        if context.workspace_id not in await tx.reach(CONNECTIONS_MANAGE_SCOPE):
            raise PermissionDeniedError(
                "you may not create a connection here",
                details={"action": CONNECTIONS_MANAGE_SCOPE},
            )

    async def check_create(self, context: AccessContext) -> None:
        """The create's own question, for an idempotent retry (app-standards R2.30)."""
        async with self._tx(context) as tx:
            await self._may_create(tx, context)

    async def check_write(self, context: AccessContext, connection_id: uuid.UUID) -> None:
        """404 for a connection the caller cannot read, 403 for one they cannot change."""
        async with self._tx(context) as tx:
            await self._writable(tx, await self._readable(tx, connection_id, lock=False))

    # ---- reads ----------------------------------------------------------------

    async def list(self, context: AccessContext, request: PageRequest) -> Page[Connection]:
        async with self._tx(context) as tx:
            rows = await tx.page(request, CONNECTIONS_READ_SCOPE)
        return build_page(list(rows), request=request, position_of=_position)

    async def get(self, context: AccessContext, connection_id: uuid.UUID) -> ConnectionDetail:
        async with self._tx(context) as tx:
            row = await self._readable(tx, connection_id, lock=False)
            return await self._detail(tx, row)

    async def dependents(
        self, context: AccessContext, connection_id: uuid.UUID
    ) -> ConnectionDependents:
        async with self._tx(context) as tx:
            await self._readable(tx, connection_id, lock=False)
        return await self.dependents_port.dependents(context, connection_id)

    async def _detail(self, tx: ConnectionTx, row: Connection) -> ConnectionDetail:
        declared = self.catalog.secret_fields(row.connector_key, row.connector_major) or frozenset()
        now = await tx.database_now()
        states = []
        for secret_field in sorted(declared):
            versions = await tx.secret_versions(row.id, secret_field)
            states.append(
                SecretFieldState(
                    field=secret_field,
                    configured=any(v.revoked_at is None or v.revoked_at > now for v in versions),
                )
            )
        return ConnectionDetail(
            connection=row,
            secret_fields=tuple(states),
            pending_enable_approval_id=await tx.pending_enable(row.id),
        )

    # ---- writes ---------------------------------------------------------------

    def _declared(self, connector_key: str, connector_major: int) -> frozenset[str]:
        declared = self.catalog.secret_fields(connector_key, connector_major)
        if declared is None:
            raise _invalid(
                "no such connector",
                "connector_unknown",
                connector_key=connector_key,
                connector_major=connector_major,
            )
        return declared

    async def create(
        self, context: AccessContext, new: NewConnection, *, effect: PendingEffect | None = None
    ) -> uuid.UUID:
        """R5.1, R5.20, R5.21: the new connection's id."""
        name = _text(new.name, "name", limit=NAME_MAX)
        account = _text(new.external_account, "external_account")
        if new.share_scope != SHARED_BY_WORKSPACE:
            raise _invalid(
                "a connection is shared by its workspace only",
                "share_scope_not_allowed",
                share_scope=new.share_scope,
            )
        declared = self._declared(new.connector_key, new.connector_major)
        given = frozenset(new.secrets)
        if given != declared:
            raise _invalid(
                "the secret fields do not match the connector's",
                "secret_fields_mismatch",
                missing=sorted(declared - given),
                unexpected=sorted(given - declared),
            )
        connection_id = self.id_generator.new_uuid()
        now = self.clock.now()
        async with self._tx(context) as tx:
            await self._may_create(tx, context)
            if effect is not None:
                await tx.claim(effect.of(connection_id))
            await tx.insert(
                Connection(
                    id=connection_id,
                    tenant_id=context.tenant_id,
                    owning_workspace_id=context.workspace_id,
                    name=name,
                    connector_key=new.connector_key,
                    connector_major=new.connector_major,
                    share_scope=SHARED_BY_WORKSPACE,
                    external_account=account,
                    status="active",
                    scopes=(),
                    last_used_at=None,
                    created_by=context.principal_id,
                    created_at=now,
                    updated_at=now,
                    disabled_at=None,
                    compromised_at=None,
                )
            )
            versions = await self._put_secrets(tx, context, connection_id, new.secrets)
            await tx.audit(
                self._event(
                    context,
                    CREATED,
                    connection_id,
                    context.workspace_id,
                    {
                        "name": name,
                        "connector_key": new.connector_key,
                        "connector_major": new.connector_major,
                        "external_account": account,
                        "share_scope": SHARED_BY_WORKSPACE,
                        "secret_fields": versions,
                    },
                )
            )
        return connection_id

    async def _put_secrets(
        self,
        tx: ConnectionTx,
        context: AccessContext,
        connection_id: uuid.UUID,
        values: Mapping[str, Secret],
    ) -> dict[str, int]:
        """Each field a new version in this transaction; the version numbers,
        never the values."""
        door = tx.secrets()
        subject = SecretSubject(SUBJECT_KIND, connection_id)
        caller = SecretCaller.person(context)
        return {
            secret_field: await self.secrets.put(
                door, caller, subject, secret_field, values[secret_field]
            )
            for secret_field in sorted(values)
        }

    async def update(
        self,
        context: AccessContext,
        connection_id: uuid.UUID,
        patch: ConnectionPatch,
        *,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """The name and a rotation of declared secret fields; any status but
        `revoked`."""
        name = None if patch.name is None else _text(patch.name, "name", limit=NAME_MAX)
        if name is None and not patch.secrets:
            raise _invalid("nothing to change", "nothing_to_change")
        async with self._tx(context) as tx:
            row = await self._readable(tx, connection_id, lock=False)
            await self._writable(tx, row)
            if row.status == "revoked":
                raise ConflictError(
                    "a revoked connection does not change",
                    details={"reason_code": "connection_revoked"},
                )
            if patch.secrets:
                declared = self._declared(row.connector_key, row.connector_major)
                unexpected = sorted(frozenset(patch.secrets) - declared)
                if unexpected:
                    raise _invalid(
                        "the connector declares no such secret field",
                        "secret_fields_mismatch",
                        missing=[],
                        unexpected=unexpected,
                    )
            if effect is not None:
                await tx.claim(effect.of(connection_id))
            changed: list[str] = []
            details: dict[str, object] = {}
            if patch.secrets:
                rotated = await self._put_secrets(tx, context, connection_id, patch.secrets)
                changed.append("secrets")
                details["secret_fields"] = rotated
            if name is not None and name != row.name:
                await tx.rename(connection_id, name)
                changed.append("name")
                details["name"] = {"from": row.name, "to": name}
            if changed:
                await tx.audit(
                    self._event(
                        context,
                        UPDATED,
                        connection_id,
                        row.owning_workspace_id,
                        {"changed": changed, **details},
                    )
                )
        return connection_id

    async def disable(
        self,
        context: AccessContext,
        connection_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """R5.5: one person, at once."""
        async with self._tx(context) as tx:
            row = await self._readable(tx, connection_id, lock=True)
            await self._writable(tx, row)
            if row.status != "active":
                raise ConflictError(
                    "only an active connection is disabled",
                    details={"reason_code": "connection_not_active", "status": row.status},
                )
            if effect is not None:
                await tx.claim(effect.of(connection_id))
            await tx.set_status(connection_id, "disabled")
            await tx.audit(
                self._event(
                    context, DISABLED, connection_id, row.owning_workspace_id, {"from": row.status}
                )
            )
        return connection_id

    async def request_enable(
        self,
        context: AccessContext,
        connection_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """R5.10, R5.13: the approval's id; the status stays `disabled`."""
        approval_id = self.id_generator.new_uuid()
        async with self._tx(context) as tx:
            row = await self._readable(tx, connection_id, lock=True)
            await self._writable(tx, row)
            if row.status != "disabled":
                raise ConflictError(
                    "only a disabled connection is enabled",
                    details={"reason_code": "connection_not_disabled", "status": row.status},
                )
            pending = await tx.pending_enable(connection_id)
            if pending is not None:
                raise ConflictError(
                    "a request to enable this connection is already waiting",
                    details={"reason_code": "enable_pending", "approval_id": str(pending)},
                )
            # The owning workspace: where `checker_candidates` looks and where
            # the approval is decided (`ApproveAndResumeService._visible`).
            if not await tx.has_checker(
                CONNECTIONS_MANAGE_SCOPE, context.principal_id, row.owning_workspace_id
            ):
                raise ConflictError(
                    "nobody but the requester could approve enabling this connection",
                    details={"reason_code": "no_checker_available"},
                )
            if effect is not None:
                await tx.claim(effect.of(approval_id))
            await tx.open_approval(
                ApprovalRequest(
                    id=approval_id,
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(row.owning_workspace_id),
                    approval_type=CONNECTIONS_ENABLE,
                    requested_by=UserId(context.principal_id),
                    reason=f"{row.name} ({row.connector_key})",
                    payload={"connection_id": str(connection_id)},
                    required_scope=CONNECTIONS_MANAGE_SCOPE,
                )
            )
        return approval_id

    async def revoke_credentials(
        self,
        context: AccessContext,
        connection_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """R1.15: every version revoked and `compromised_at` stamped, one person."""
        async with self._tx(context) as tx:
            row = await self._readable(tx, connection_id, lock=False)
            await self._writable(tx, row)
            if effect is not None:
                await tx.claim(effect.of(connection_id))
            revoked = await tx.revoke_secrets(connection_id)
            if revoked is None:
                raise NotFoundError("connection not found", details={"id": str(connection_id)})
            await tx.audit(
                self._event(
                    context,
                    CREDENTIALS_REVOKED,
                    connection_id,
                    row.owning_workspace_id,
                    {
                        "compromised_at": revoked.compromised_at.isoformat(),
                        "versions_revoked": revoked.versions,
                    },
                )
            )
        return connection_id

    async def delete(self, context: AccessContext, connection_id: uuid.UUID) -> None:
        """R5.8: refused while anything depends on it; the port failing stops it."""
        async with self._tx(context) as tx:
            row = await self._readable(tx, connection_id, lock=True)
            await self._writable(tx, row)
            found = await self.dependents_port.dependents(context, connection_id)
            if found.total > 0:
                raise ConflictError(
                    "the connection is in use",
                    details={"reason_code": "connection_in_use", "dependents": found.total},
                )
            await tx.delete(connection_id)
            await tx.audit(
                self._event(
                    context,
                    DELETED,
                    connection_id,
                    row.owning_workspace_id,
                    {
                        "name": row.name,
                        "connector_key": row.connector_key,
                        "external_account": row.external_account,
                    },
                )
            )

    def _event(
        self,
        context: AccessContext,
        action: str,
        connection_id: uuid.UUID,
        owning_workspace_id: uuid.UUID,
        details: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            # The connection's workspace, not the caller's working one.
            workspace_id=WorkspaceId(owning_workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type=RESOURCE,
            resource_id=str(connection_id),
            occurred_at=self.clock.now(),
            details=details,
        )


SettlementOutcome = Literal["enabled", "rejected", "gone", "not_disabled", "stale"]


@dataclass(frozen=True)
class ConnectionEnableSettler:
    """R5.12, R5.19, on the worker, where the decision's outbox event arrives.

    Idempotent by the approval's id: a replay meets a connection no longer
    `disabled` and writes nothing. A request opened before the connection's
    latest move into `disabled` (it was enabled another way and disabled again)
    writes nothing either; the trigger would refuse it too, and this check is
    what ends the handler without an error for the outbox to retry."""

    store: ConnectionStorePort
    clock: UtcClock
    id_generator: IdGenerator

    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> SettlementOutcome:
        async with self.store.transaction(
            scope.tenant_id, workspace_id=scope.workspace_id, principal_id=None
        ) as tx:
            decision = await tx.enable_decision(approval_id)
            if decision is None or decision.connection_id is None:
                raise NotFoundError(
                    "no decided connections.enable approval of that id",
                    details={"approval_id": str(approval_id)},
                )
            if not decision.approved:
                return "rejected"
            row = await tx.connection(decision.connection_id, lock=True)
            if row is None:
                return "gone"
            if row.status != "disabled":
                return "not_disabled"
            if row.disabled_at is None or decision.created_at <= row.disabled_at:
                return "stale"
            await tx.set_status(row.id, "active", enable_approval=approval_id)
            await tx.audit(
                AuditEvent(
                    id=self.id_generator.new_uuid(),
                    tenant_id=TenantId(scope.tenant_id),
                    workspace_id=WorkspaceId(row.owning_workspace_id),
                    # A lane carrying out one person's decision audits that person.
                    actor_id=UserId(decision.decided_by),
                    action=ENABLED,
                    resource_type=RESOURCE,
                    resource_id=str(row.id),
                    occurred_at=self.clock.now(),
                    details={
                        "approval_id": str(approval_id),
                        "requested_by": str(decision.requested_by),
                        "lane": SETTLING_LANE,
                    },
                )
            )
        return "enabled"
