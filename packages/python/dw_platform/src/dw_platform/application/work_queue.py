"""The queue people and Digital Workers share (digital-worker R3, R4; ADR-0128
decisions 6-7).

Every item has exactly one holder. A DW takes work in its mandate only, from a
payload its kind's schema accepts (R3.2, R3.3), once per `(dw, kind,
source_key)` (R3.4). The lane `dw_work` claims what is due (R3.6), a run moves
it while it waits (`record_wait`, `resume_claimed`) and ends it (`finish`), a
DW hands it to a person with a packet (R4), and that person closes it (R3.13).
Every move asks the one table in `dw_platform.domain.work_item` and is written
as a conditional UPDATE naming the states it may come from, so a write the table
does not hold cannot happen even when two callers race.

People reach the queue through an `AccessContext` and the rules of R3.5, R3.8,
R3.10, R3.11. The lane, a run and an intake reach it through a `WorkScope`: a
tenant and a workspace from a verified source (a claimed row, a stamped run, a
signed intake), never from a request body.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from dw_kernel.errors import DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.digital_workers import DW_READ
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.json_schema import problems
from dw_platform.application.ports import AuthorizationPort
from dw_platform.domain.audit import AuditEvent, lane_audit_event
from dw_platform.domain.digital_worker import DigitalWorker
from dw_platform.domain.work_item import (
    HandoffPacket,
    Mover,
    WorkItem,
    WorkStatus,
    check_transition,
    payload_hash,
    sources_of,
)

LANE = "dw_work"
# R3.9: work refused for the tenant's limit waits this long, and is not dropped.
LIMIT_BACKOFF = timedelta(minutes=5)
# R3.14: an item claimed this long ago whose run never appeared goes back.
STUCK_AFTER = timedelta(minutes=15)
# wf-lite R6.12: a claimed timer's `wake_at` moves this far ahead, a lease.
TIMER_LEASE = timedelta(minutes=15)

_RESOURCE = "work_item"


@dataclass(frozen=True, slots=True)
class WorkScope:
    """The tenant and workspace a queue operation runs under, from a verified
    source; what RLS is bound to."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID

    @classmethod
    def of(cls, context: AccessContext) -> WorkScope:
        return cls(tenant_id=context.tenant_id, workspace_id=context.workspace_id)


@dataclass(frozen=True, slots=True)
class NewWork:
    kind: str
    source_key: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Claimed:
    """An item the lane took: now `in_progress` under `run_id`, which the run
    must start with (R3.6, R3.14)."""

    item: WorkItem
    run_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class WorkListFilter:
    status: WorkStatus | None = None
    holder_kind: Literal["digital_worker", "person"] | None = None


class WorkKindSchemas(Protocol):
    """The JSON Schema of a kind of work, declared by whoever owns the DW's
    workflow (wf-lite reads it from the pinned pack). None: no schema, and the
    queue refuses the work (R3.3)."""

    def schema(
        self, *, workflow_key: str, workflow_version: str, kind: str
    ) -> Mapping[str, Any] | None: ...


class DwLookupPort(Protocol):
    async def digital_worker(self, scope: WorkScope, dw_id: uuid.UUID) -> DigitalWorker | None:
        """The DW under `scope`'s RLS, or None."""
        ...


class PersonCheckPort(Protocol):
    async def is_person_in(self, scope: WorkScope, user_id: uuid.UUID) -> bool:
        """Whether `user_id` is a human with a membership in the workspace."""
        ...


class WorkQueueRepositoryPort(Protocol):
    async def insert(
        self,
        scope: WorkScope,
        item: WorkItem,
        *,
        audit: AuditEvent | None,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        """Insert `item`, or return the item already holding its `(tenant, dw,
        kind, source_key)` without writing anything (R3.4). ``effect`` is
        claimed first in the same transaction."""
        ...

    async def get(self, scope: WorkScope, item_id: uuid.UUID) -> WorkItem | None: ...

    async def page(
        self, scope: WorkScope, request: PageRequest, where: WorkListFilter
    ) -> Page[WorkItem]: ...

    async def move(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        sources: frozenset[WorkStatus],
        target: WorkStatus,
        values: Mapping[str, object],
        audit: AuditEvent | None,
        effect: PendingEffect | None = None,
    ) -> WorkItem | None:
        """Set `target` and `values` on the item when its status is one of
        `sources`, with `audit` in the same transaction; None when it is not."""
        ...

    async def due_scopes(self, *, limit: int) -> list[WorkScope]:
        """`platform.dw_work_scopes_due`: the scopes with work due or stuck,
        ids only, across tenants."""
        ...

    async def claim_due(
        self,
        scope: WorkScope,
        *,
        limit: int,
        audit_of: Callable[[WorkItem, uuid.UUID], AuditEvent],
    ) -> list[Claimed]:
        """Take up to `limit` open, due items of operating DWs that have a
        Business Owner, `FOR UPDATE SKIP LOCKED`, the DW row `FOR SHARE`; move
        each to `in_progress` with its run id (kept, or new) and its audit
        event in the same transaction (R3.6, R3.7, R1.12)."""
        ...

    async def release_stuck(self, scope: WorkScope, *, older_than: timedelta) -> int:
        """Move back to `open` every `in_progress` item untouched for
        `older_than` whose run id has no run row, keeping the run id (R3.14)."""
        ...

    async def by_run(self, scope: WorkScope, run_id: uuid.UUID) -> WorkItem | None:
        """The item a run works on, or None (a run that is not a DW's)."""
        ...

    async def due_timer_scopes(self, *, limit: int) -> list[WorkScope]:
        """`platform.dw_timer_scopes_due`: ids only, across tenants."""
        ...

    async def claim_timers(
        self, scope: WorkScope, *, limit: int, lease: timedelta
    ) -> list[WorkItem]:
        """Take up to `limit` items `waiting_timer` whose `wake_at` has passed,
        of an operating DW, `FOR UPDATE SKIP LOCKED`, and push their `wake_at`
        `lease` ahead in the same transaction (wf-lite R6.12): a lane that dies
        after the claim leaves the item due again after the lease."""
        ...


def _not_found() -> NotFoundError:
    return NotFoundError("no such work item")


def _refused(message: str, reason_code: str, **details: object) -> DomainError:
    return DomainError(message, details={"reason_code": reason_code, **details})


@dataclass(frozen=True)
class WorkQueue:
    repo: WorkQueueRepositoryPort
    workers: DwLookupPort
    people: PersonCheckPort
    schemas: WorkKindSchemas
    authz: AuthorizationPort
    clock: UtcClock
    id_generator: IdGenerator

    # ------------------------------------------------------------ intake --

    async def enqueue(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        work: NewWork,
        *,
        actor: uuid.UUID | None = None,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        """R3.1-R3.4. `actor` is the person who put the work in by hand; an
        intake with no person audits nothing here (its own lane does)."""
        worker = await self.workers.digital_worker(scope, dw_id)
        if worker is None:
            raise NotFoundError("no such digital worker")
        if worker.state in ("draft", "retired"):
            raise _refused("this digital worker takes no work", "dw_not_accepting_work")
        config = worker.configuration
        if work.kind not in config.work_kinds:
            raise _refused(
                "this kind of work is outside the DW's mandate", "work_kind_outside_mandate"
            )
        schema = self.schemas.schema(
            workflow_key=config.workflow_key,
            workflow_version=config.workflow_version,
            kind=work.kind,
        )
        found = (
            ["no schema is declared for this kind"]
            if schema is None
            else (problems(schema, dict(work.payload)))
        )
        if found:
            raise _refused("the payload does not match its kind", "payload_invalid", problems=found)
        if not 1 <= len(work.source_key) <= 255 or not work.source_key.strip():
            raise _refused("a source key has 1 to 255 characters", "source_key_invalid")

        now = self.clock.now()
        item = WorkItem(
            id=self.id_generator.new_uuid(),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            dw_id=dw_id,
            kind=work.kind,
            source_key=work.source_key,
            payload=dict(work.payload),
            payload_hash=payload_hash(work.payload),
            holder_kind="digital_worker",
            holder_id=dw_id,
            status="open",
            available_at=now,
            run_id=None,
            wake_at=None,
            handoff=None,
            error=None,
            created_at=now,
            updated_at=now,
            closed_at=None,
        )
        audit = (
            None
            if actor is None
            else self._event(scope, actor, "work_item.enqueued", item.id, {"kind": work.kind})
        )
        stored = await self.repo.insert(scope, item, audit=audit, effect=effect)
        if stored.payload_hash != item.payload_hash:
            raise _refused(
                "this source key already carried a different payload", "source_key_reused"
            )
        return stored

    async def require_work_assigner(
        self, context: AccessContext, dw_id: uuid.UUID
    ) -> DigitalWorker:
        """R3.10: 404 for a DW the caller may not read, 403 `not_work_assigner`
        for anyone but its Work Assigner. The check a route declares for its
        idempotency key, too."""
        worker = await self._readable_worker(context, dw_id)
        if context.principal_id != worker.people.work_assigner_id:
            raise PermissionDeniedError(
                "only the DW's work assigner gives it work by hand",
                details={"reason_code": "not_work_assigner"},
            )
        return worker

    async def enqueue_by_person(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        work: NewWork,
        *,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        await self.require_work_assigner(context, dw_id)
        return await self.enqueue(
            WorkScope.of(context), dw_id, work, actor=context.principal_id, effect=effect
        )

    # ------------------------------------------------------------- reads --

    async def page(
        self, context: AccessContext, request: PageRequest, where: WorkListFilter
    ) -> Page[WorkItem]:
        """R3.5: every item of the workspace, people's and DWs', without
        payload or packet."""
        await self.authz.require(context=context, action=DW_READ, resource_type=_RESOURCE)
        listed = await self.repo.page(WorkScope.of(context), request, where)
        return listed.map_items(_without_contents)

    async def get(self, context: AccessContext, item_id: uuid.UUID) -> WorkItem:
        """R3.11: payload and packet only for the holder and the DW's four
        people. 404 for a caller without `dw.read`, as for an unknown id."""
        await self._require_read(context)
        scope = WorkScope.of(context)
        item = await self.repo.get(scope, item_id)
        if item is None:
            raise _not_found()
        if self._is_holder(context, item):
            return item
        worker = await self.workers.digital_worker(scope, item.dw_id)
        people = worker.people if worker is not None else None
        named = (
            {
                people.business_owner_id,
                people.technical_owner_id,
                people.work_assigner_id,
                people.validator_id,
            }
            if people is not None
            else set()
        )
        return item if context.principal_id in named else _without_contents(item)

    # ------------------------------------------------------------ people --

    async def require_holder(self, context: AccessContext, item_id: uuid.UUID) -> WorkItem:
        """R3.8: 404 for an item the caller may not read, 403 `not_holder` for
        anyone but who holds it."""
        await self._require_read(context)
        item = await self.repo.get(WorkScope.of(context), item_id)
        if item is None:
            raise _not_found()
        if not self._is_holder(context, item):
            raise PermissionDeniedError(
                "only who holds the work closes it", details={"reason_code": "not_holder"}
            )
        return item

    async def complete(
        self,
        context: AccessContext,
        item_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        """R3.8, R3.13."""
        item = await self.require_holder(context, item_id)
        scope = WorkScope.of(context)
        check_transition(item.status, "done", "holder")
        return await self._move(
            scope,
            item,
            "done",
            "holder",
            {"closed_at": self.clock.now()},
            self._event(scope, context.principal_id, "work_item.completed", item.id, {}),
            effect=effect,
        )

    # ----------------------------------------------------------- the DW --

    async def hand_off(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        to_user: uuid.UUID,
        packet: Mapping[str, object],
    ) -> WorkItem:
        """R4.1-R4.3. `to_user` is chosen by the workflow's code (the Validator
        or a DW parameter), never by a model's output."""
        handoff = HandoffPacket.of(packet)
        item = await self.repo.get(scope, item_id)
        if item is None:
            raise _not_found()
        if item.holder_kind != "digital_worker":
            raise _refused("only a DW's own work is handed off", "invalid_transition")
        check_transition(item.status, "handed_off", "hand_off")
        if not await self.people.is_person_in(scope, to_user):
            raise _refused("work is handed to a person of this workspace", "handoff_target_invalid")
        worker = await self.workers.digital_worker(scope, item.dw_id)
        if worker is None:
            raise _not_found()
        return await self._move(
            scope,
            item,
            "handed_off",
            "hand_off",
            {
                "holder_kind": "person",
                "holder_id": to_user,
                "handoff": handoff.as_dict(),
                "wake_at": None,
            },
            self._event(
                scope,
                worker.principal_user_id,
                "work_item.handed_off",
                item.id,
                {"to": str(to_user)},
            ),
        )

    # ------------------------------------------------------------- lane --

    async def due_scopes(self, *, limit: int) -> list[WorkScope]:
        return await self.repo.due_scopes(limit=limit)

    async def claim_for_lane(self, scope: WorkScope, *, limit: int) -> list[Claimed]:
        return await self.repo.claim_due(
            scope,
            limit=limit,
            audit_of=lambda item, run_id: self.lane_event(
                scope, "work_item.claimed", item.id, {"run_id": str(run_id)}
            ),
        )

    async def release_stuck(self, scope: WorkScope) -> int:
        return await self.repo.release_stuck(scope, older_than=STUCK_AFTER)

    async def by_run(self, scope: WorkScope, run_id: uuid.UUID) -> WorkItem | None:
        return await self.repo.by_run(scope, run_id)

    async def due_timer_scopes(self, *, limit: int) -> list[WorkScope]:
        return await self.repo.due_timer_scopes(limit=limit)

    async def claim_timers(self, scope: WorkScope, *, limit: int) -> list[WorkItem]:
        return await self.repo.claim_timers(scope, limit=limit, lease=TIMER_LEASE)

    async def release_for_limit(self, scope: WorkScope, item_id: uuid.UUID) -> WorkItem:
        """R3.9: back to `open`, due again in five minutes, run id kept."""
        return await self._move_by_id(
            scope,
            item_id,
            "open",
            "lane",
            {"available_at": self.clock.now() + LIMIT_BACKOFF},
            self.lane_event(scope, "work_item.deferred_for_limit", item_id, {}),
        )

    async def fail_start(self, scope: WorkScope, item_id: uuid.UUID, code: str) -> WorkItem:
        """R3.15: a refusal other than the limit fails the item, with its code."""
        return await self._move_by_id(
            scope,
            item_id,
            "failed",
            "runner",
            {"error": code[:500], "closed_at": self.clock.now()},
            self.lane_event(scope, "work_item.start_failed", item_id, {"code": code[:500]}),
        )

    # -------------------------------------------------------------- run --

    async def record_wait(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        target: Literal["waiting_approval", "waiting_timer"],
        wake_at: datetime | None = None,
    ) -> WorkItem:
        return await self._move_by_id(scope, item_id, target, "runner", {"wake_at": wake_at}, None)

    async def resume_claimed(self, scope: WorkScope, item_id: uuid.UUID) -> WorkItem:
        return await self._move_by_id(
            scope, item_id, "in_progress", "runner", {"wake_at": None}, None
        )

    async def finish(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        outcome: Literal["done", "failed"],
        error: str | None = None,
    ) -> WorkItem:
        values: dict[str, object] = {"closed_at": self.clock.now()}
        if error is not None:
            values["error"] = error[:500]
        return await self._move_by_id(scope, item_id, outcome, "runner", values, None)

    # ---------------------------------------------------------- helpers --

    async def _move_by_id(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        target: WorkStatus,
        mover: Mover,
        values: Mapping[str, object],
        audit: AuditEvent | None,
    ) -> WorkItem:
        item = await self.repo.get(scope, item_id)
        if item is None:
            raise _not_found()
        check_transition(item.status, target, mover)
        return await self._move(scope, item, target, mover, values, audit)

    async def _move(
        self,
        scope: WorkScope,
        item: WorkItem,
        target: WorkStatus,
        mover: Mover,
        values: Mapping[str, object],
        audit: AuditEvent | None,
        *,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        moved = await self.repo.move(
            scope,
            item.id,
            sources=sources_of(target, mover),
            target=target,
            values=values,
            audit=audit,
            effect=effect,
        )
        if moved is None:
            # Someone moved it first: answer by what it is now.
            current = await self.repo.get(scope, item.id)
            check_transition(current.status if current else item.status, target, mover)
            raise _refused("the work item changed meanwhile; try again", "invalid_transition")
        return moved

    async def _readable_worker(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        await self._require_read(context, not_found=NotFoundError("no such digital worker"))
        worker = await self.workers.digital_worker(WorkScope.of(context), dw_id)
        if worker is None:
            raise NotFoundError("no such digital worker")
        return worker

    async def _require_read(
        self, context: AccessContext, *, not_found: NotFoundError | None = None
    ) -> None:
        try:
            await self.authz.require(context=context, action=DW_READ, resource_type=_RESOURCE)
        except PermissionDeniedError:
            raise (not_found or _not_found()) from None

    @staticmethod
    def _is_holder(context: AccessContext, item: WorkItem) -> bool:
        return item.holder_kind == "person" and item.holder_id == context.principal_id

    def _event(
        self,
        scope: WorkScope,
        actor: uuid.UUID,
        action: str,
        item_id: uuid.UUID,
        details: Mapping[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(scope.tenant_id),
            workspace_id=WorkspaceId(scope.workspace_id),
            actor_id=UserId(actor),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(item_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )

    def lane_event(
        self, scope: WorkScope, action: str, item_id: uuid.UUID, details: Mapping[str, object]
    ) -> AuditEvent:
        """An event the `dw_work` lane writes as itself (ADR 0011)."""
        return lane_audit_event(
            lane=LANE,
            event_id=self.id_generator.new_uuid(),
            tenant_id=TenantId(scope.tenant_id),
            workspace_id=WorkspaceId(scope.workspace_id),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(item_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )


def _without_contents(item: WorkItem) -> WorkItem:
    return replace(item, payload={}, handoff=None)


@dataclass(frozen=True)
class InMemoryWorkKindSchemas:
    """`WorkKindSchemas` from a fixed map `(workflow_key, kind) -> schema`, the
    version ignored: for tests, and for a deployment with no pack yet, where it
    is empty and every payload is refused (R3.3). wf-lite/01 wires the reader of
    the pinned pack."""

    schemas: Mapping[tuple[str, str], Mapping[str, Any]]

    def schema(
        self, *, workflow_key: str, workflow_version: str, kind: str
    ) -> Mapping[str, Any] | None:
        return self.schemas.get((workflow_key, kind))


__all__: Sequence[str] = [
    "LANE",
    "LIMIT_BACKOFF",
    "STUCK_AFTER",
    "TIMER_LEASE",
    "Claimed",
    "DwLookupPort",
    "InMemoryWorkKindSchemas",
    "NewWork",
    "PersonCheckPort",
    "WorkKindSchemas",
    "WorkListFilter",
    "WorkQueue",
    "WorkQueueRepositoryPort",
    "WorkScope",
]
