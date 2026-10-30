"""The signed lead intake (leadcare R2): a website form puts a lead into a
Digital Worker's queue without a user account.

The door's whole authority is a signature: HMAC-SHA256 of
`<timestamp>.<event_id>.<raw body>` under the DW's intake key, which is itself
HMAC-SHA256 of the DW's id under the server's `INTAKE_SIGNING_SECRET`, derived,
never stored (R2.4). A missing or wrong signature, a DW that does not exist or
is `draft` or `retired`, or a timestamp more than 300 seconds off the server's
clock is one and the same `signature_invalid`, and nothing is written (R2.2).

Only then is the body read: `consent.granted` must be `true`, else
`consent_missing`, before the lead's schema is asked (R2.3); the work goes in
through `WorkQueue.enqueue` with the event id as its source key, so the same
event again answers the same item and a different body under it is refused
(R2.9); the item, `work_item.received` as the `intake` lane and the lead's
consent record are one transaction (R2.10, R2.13). The tenant and workspace are
the DW row's, never anything the body says (R2.1, LCP4).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from dw_kernel.errors import DomainError, PermissionDeniedError, UnauthenticatedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.digital_workers import DigitalWorkerService
from dw_platform.application.marketing_send import ConsentLedger
from dw_platform.application.work_queue import NewWork, WorkQueue, WorkScope
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.work_item import WorkItem

LEAD_KIND = "marketing.lead"
MAX_SKEW_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024
MIN_SECRET_BYTES = 32


@dataclass(frozen=True)
class IntakeScope:
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    state: str


class IntakeScopePort(Protocol):
    async def scope_of(self, dw_id: uuid.UUID) -> IntakeScope | None:
        """`platform.intake_worker_scope`: three columns, before any context."""
        ...


class ScopedAuditPort(Protocol):
    async def append(self, scope: WorkScope, event: AuditEvent) -> None: ...


@dataclass(frozen=True)
class IntakeKeys:
    secret: bytes

    @property
    def configured(self) -> bool:
        return len(self.secret) >= MIN_SECRET_BYTES

    def key_for(self, dw_id: uuid.UUID) -> str:
        return hmac.new(self.secret, str(dw_id).encode(), hashlib.sha256).hexdigest()

    def signature(self, dw_id: uuid.UUID, timestamp: str, event_id: str, body: bytes) -> str:
        message = f"{timestamp}.{event_id}.".encode() + body
        return hmac.new(self.key_for(dw_id).encode(), message, hashlib.sha256).hexdigest()


def _signature_invalid() -> UnauthenticatedError:
    # One answer for every reason a call is not trusted (R2.2).
    return UnauthenticatedError(
        "the signature is not valid", details={"reason_code": "signature_invalid"}
    )


@dataclass(frozen=True)
class LeadIntake:
    keys: IntakeKeys
    scopes: IntakeScopePort
    queue: WorkQueue
    consents: ConsentLedger
    clock: UtcClock

    async def receive(
        self,
        *,
        worker: str | None,
        event_id: str | None,
        timestamp: str | None,
        signature: str | None,
        body: bytes,
    ) -> WorkItem:
        dw_id, scope = await self._trusted(worker, event_id, timestamp, signature, body)
        assert event_id is not None
        try:
            lead = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise DomainError(
                "the body is not JSON", details={"reason_code": "payload_invalid"}
            ) from exc
        if not isinstance(lead, dict):
            raise DomainError(
                "the body is not an object", details={"reason_code": "payload_invalid"}
            )
        consent = lead.get("consent")
        if not (isinstance(consent, Mapping) and consent.get("granted") is True):
            raise DomainError(
                "the lead gave no consent", details={"reason_code": "consent_missing"}
            )
        work_scope = WorkScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)
        record = self.consents.row(
            work_scope,
            subject=str(lead.get("email", "")),
            channel="email",
            state="granted",
            source="intake",
            notice_version=str(consent.get("text_version", ""))[:64] or "unknown",
            evidence_ref=event_id,
        )
        return await self.queue.enqueue(
            work_scope,
            dw_id,
            NewWork(kind=LEAD_KIND, source_key=event_id, payload=lead),
            intake=record,
        )

    async def _trusted(
        self,
        worker: str | None,
        event_id: str | None,
        timestamp: str | None,
        signature: str | None,
        body: bytes,
    ) -> tuple[uuid.UUID, IntakeScope]:
        if not (worker and event_id and timestamp and signature):
            raise _signature_invalid()
        try:
            dw_id = uuid.UUID(worker)
            sent_at = int(timestamp)
        except ValueError:
            raise _signature_invalid() from None
        scope = await self.scopes.scope_of(dw_id)
        expected = self.keys.signature(dw_id, timestamp, event_id, body)
        # The signature is compared whatever else is wrong, so a call learns
        # nothing from how long the answer took.
        matches = hmac.compare_digest(expected, signature)
        skew = abs(self.clock.now().timestamp() - sent_at)
        if (
            not matches
            or scope is None
            or scope.state not in ("operating", "paused")
            or skew > MAX_SKEW_SECONDS
        ):
            raise _signature_invalid()
        return dw_id, scope


@dataclass(frozen=True)
class IntakeKeyReader:
    """`GET /v1/digital-workers/{id}/intake-key` (R2.4, R2.8, R2.11): the DW's
    intake key for its Business Owner or Technical Owner, read on the record."""

    keys: IntakeKeys
    workers: DigitalWorkerService
    audit: ScopedAuditPort
    clock: UtcClock
    ids: IdGenerator

    async def read(self, context: AccessContext, dw_id: uuid.UUID) -> str:
        worker = await self.workers.require_owner(context, dw_id)
        if not self.keys.configured:
            raise PermissionDeniedError(
                "intake is not configured", details={"reason_code": "intake_unconfigured"}
            )
        scope = WorkScope(tenant_id=worker.tenant_id, workspace_id=worker.workspace_id)
        await self.audit.append(
            scope,
            AuditEvent(
                id=self.ids.new_uuid(),
                tenant_id=TenantId(worker.tenant_id),
                workspace_id=WorkspaceId(worker.workspace_id),
                actor_id=UserId(context.principal_id),
                action="dw.intake_key.read",
                resource_type="digital_worker",
                resource_id=str(dw_id),
                occurred_at=self.clock.now(),
                details={},
            ),
        )
        return self.keys.key_for(dw_id)
