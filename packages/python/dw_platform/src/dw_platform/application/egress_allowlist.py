"""The company's Allowed hosts: asked for by one person, approved by another,
removed by one (connections-and-vault R3.8-R3.12, R3.18, R3.19; ADR-0115
decision 6 and its 2026-10-24 amendment; D11).

- **Listing** (`GET`) and **asking** (`POST`) need `integrations.admin`, a
  tenant-depth key. Asking validates and normalizes the pattern (R3.8), then
  opens a run-less `egress.allowed_host` approval stamped `required_scope =
  integrations.admin`, and writes no row (R3.9). The type is strict, so its
  requester cannot decide it (`second_person_required`, R3.10, registered at
  both composition roots); and when nobody but the requester holds the key
  reaching the workspace they ask from, no approval is opened at all
  (`no_checker_available`, R3.12): one that nobody could decide would wait
  forever.
- **Settling** (`AllowedHostSettler`, on the worker, at the decision's outbox
  event): an approval inserts the row whose id is the approval's, `ON CONFLICT
  DO NOTHING`, and only a new row is audited `egress.allowlist.added`, in the
  decider's name with `details.lane = outbox` (R3.11). A replay adds nothing,
  not even after the row was removed; a second approval of a pattern that is
  already live adds nothing either. A rejection writes nothing: the decision's
  own `approval.decided` row is the trail.
- **Removing** (`DELETE`) is one person's, at once: `removed_at`, `removed_by`
  and `egress.allowlist.removed` in one transaction (R3.18). Another company's
  id, an unknown one and a row already removed are one 404; without the key,
  403 before anything is read (R3.19).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import AuthorizationPort
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.allowed_hosts import (
    AllowedHost,
    AllowedHostPurpose,
    normalize_allowed_host_pattern,
    normalize_ports,
)
from dw_platform.domain.approval import ApprovalRequest, decided_event_type
from dw_platform.domain.audit import AuditEvent

__all__ = [
    "ALLOWLIST_ADDED",
    "ALLOWLIST_REMOVED",
    "ALLOWLIST_REQUESTED",
    "EGRESS_ALLOWED_HOST",
    "EGRESS_ALLOWED_HOST_DECIDED",
    "INTEGRATIONS_ADMIN_SCOPE",
    "AllowedHostDecision",
    "AllowedHostRepositoryPort",
    "AllowedHostSettlement",
    "AllowedHostSettlementPort",
    "AllowedHostSettler",
    "EgressAllowlistService",
    "NewAllowedHost",
]

INTEGRATIONS_ADMIN_SCOPE = "integrations.admin"
EGRESS_ALLOWED_HOST = "egress.allowed_host"
EGRESS_ALLOWED_HOST_DECIDED = decided_event_type(EGRESS_ALLOWED_HOST)

ALLOWLIST_REQUESTED = "egress.allowlist.requested"
ALLOWLIST_ADDED = "egress.allowlist.added"
ALLOWLIST_REMOVED = "egress.allowlist.removed"

# The lane that carries out the decision, named in `details.lane` of the audit
# row standing in the decider's name (CLAUDE.md, lane audit).
SETTLING_LANE = "outbox"
_RESOURCE = "egress_allowed_host"


@dataclass(frozen=True, slots=True)
class NewAllowedHost:
    host_pattern: str
    purpose: AllowedHostPurpose
    ports: tuple[int, ...] = (443,)
    note: str | None = None


@dataclass(frozen=True, slots=True)
class AllowedHostDecision:
    """A decided `egress.allowed_host` approval, as its settlement reads it."""

    approval_id: uuid.UUID
    approved: bool
    decided_by: uuid.UUID
    requested_by: uuid.UUID
    workspace_id: uuid.UUID
    host_pattern: str
    ports: tuple[int, ...]
    purpose: str
    note: str | None


@dataclass(frozen=True, slots=True)
class AllowedHostSettlement:
    """What to write: the row (None for none) and the audit row that goes with
    it only if the row is new."""

    outcome: Literal["added", "already_present", "rejected"]
    row: AllowedHost | None = None
    audit: AuditEvent | None = None


class AllowedHostRepositoryPort(Protocol):
    async def list(self, context: AccessContext, request: PageRequest) -> Page[AllowedHost]:
        """The live rows of the caller's company, newest first."""
        ...

    async def open_request(
        self, context: AccessContext, request: ApprovalRequest, *, audit: AuditEvent
    ) -> bool:
        """Open the approval with `audit` in one transaction, only while someone
        but the requester could decide it (`platform.checker_candidates` for the
        stamped key and the requester's workspace); False, writing nothing,
        when nobody could."""
        ...

    async def remove(
        self,
        context: AccessContext,
        host_id: uuid.UUID,
        *,
        audit_for: Callable[[AllowedHost], AuditEvent],
    ) -> AllowedHost | None:
        """Stamp a live row removed by the caller, with its audit row, in one
        transaction; None when the company has no live row of that id."""
        ...


class AllowedHostSettlementPort(Protocol):
    async def settle(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[AllowedHostDecision], AllowedHostSettlement],
    ) -> AllowedHostSettlement:
        """Read the decided approval, write what `settle` decides in the same
        transaction: the row `ON CONFLICT DO NOTHING`, and its audit only when
        the row is new (the settlement then says `already_present`).
        NotFoundError when no decided approval of that id is there."""
        ...


@dataclass(frozen=True)
class EgressAllowlistService:
    repo: AllowedHostRepositoryPort
    authz: AuthorizationPort
    clock: UtcClock
    id_generator: IdGenerator

    async def _require(self, context: AccessContext, resource_id: str | None = None) -> None:
        await self.authz.require(
            context=context,
            action=INTEGRATIONS_ADMIN_SCOPE,
            resource_type=_RESOURCE,
            resource_id=resource_id,
        )

    async def list(self, context: AccessContext, request: PageRequest) -> Page[AllowedHost]:
        await self._require(context)
        return await self.repo.list(context, request)

    async def propose(self, context: AccessContext, new: NewAllowedHost) -> uuid.UUID:
        """R3.8, R3.9, R3.12: the approval's id, nothing written but it."""
        await self._require(context)
        pattern = normalize_allowed_host_pattern(new.host_pattern)
        ports = normalize_ports(new.ports)
        approval_id = self.id_generator.new_uuid()
        # What a reviewer reads and the handler writes: the normalized form.
        payload: dict[str, object] = {
            "host_pattern": pattern,
            "ports": list(ports),
            "purpose": new.purpose,
            "note": new.note,
        }
        opened = await self.repo.open_request(
            context,
            ApprovalRequest(
                id=approval_id,
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(context.workspace_id),
                approval_type=EGRESS_ALLOWED_HOST,
                requested_by=UserId(context.principal_id),
                reason=f"{pattern} ({new.purpose})",
                payload=payload,
                required_scope=INTEGRATIONS_ADMIN_SCOPE,
            ),
            audit=self._event(
                context,
                ALLOWLIST_REQUESTED,
                approval_id,
                {"host_pattern": pattern, "ports": list(ports), "purpose": new.purpose},
            ),
        )
        if not opened:
            raise ConflictError(
                "nobody but the requester could approve this host",
                details={"reason_code": "no_checker_available"},
            )
        return approval_id

    async def remove(self, context: AccessContext, host_id: uuid.UUID) -> None:
        """R3.18, R3.19."""
        await self._require(context, str(host_id))
        removed = await self.repo.remove(
            context,
            host_id,
            audit_for=lambda row: self._event(
                context,
                ALLOWLIST_REMOVED,
                row.id,
                {
                    "host_pattern": row.host_pattern,
                    "ports": list(row.ports),
                    "purpose": row.purpose,
                },
            ),
        )
        if removed is None:
            raise NotFoundError("allowed host not found", details={"id": str(host_id)})

    def _event(
        self,
        context: AccessContext,
        action: str,
        resource_id: uuid.UUID,
        details: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(resource_id),
            occurred_at=self.clock.now(),
            details=details,
        )


@dataclass(frozen=True)
class AllowedHostSettler:
    """R3.11, on the worker, where the decision's outbox event arrives."""

    repo: AllowedHostSettlementPort
    clock: UtcClock
    id_generator: IdGenerator

    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> AllowedHostSettlement:
        """Idempotent by the approval's id: a redelivered decision adds nothing."""
        return await self.repo.settle(
            scope, approval_id, lambda decision: self._settlement(scope, decision)
        )

    def _settlement(self, scope: WorkScope, decision: AllowedHostDecision) -> AllowedHostSettlement:
        if not decision.approved:
            return AllowedHostSettlement("rejected")
        now = self.clock.now()
        row = AllowedHost(
            id=decision.approval_id,
            host_pattern=decision.host_pattern,
            ports=decision.ports,
            purpose=decision.purpose,
            note=decision.note,
            owning_workspace_id=decision.workspace_id,
            created_by=decision.requested_by,
            created_at=now,
        )
        audit = AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(scope.tenant_id),
            workspace_id=WorkspaceId(decision.workspace_id),
            # A lane carrying out one person's decision audits that person.
            actor_id=UserId(decision.decided_by),
            action=ALLOWLIST_ADDED,
            resource_type=_RESOURCE,
            resource_id=str(decision.approval_id),
            occurred_at=now,
            details={
                "host_pattern": decision.host_pattern,
                "ports": list(decision.ports),
                "purpose": decision.purpose,
                "approval_id": str(decision.approval_id),
                "requested_by": str(decision.requested_by),
                "lane": SETTLING_LANE,
            },
        )
        return AllowedHostSettlement("added", row=row, audit=audit)
