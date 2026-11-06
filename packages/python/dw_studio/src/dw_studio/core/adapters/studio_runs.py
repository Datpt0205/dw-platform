"""`SqlStudioRunStore`: `StudioRunStorePort` over `platform.worker_runs`, the
run manifest and the version rows it pins (workflow-engine/03 step 2, R4.11,
R6.14; ADR-0109 decision 7).

Every call is one transaction of `dw_app` under the run's tenant (RLS), so
another tenant's run is no run. `take` reads the claimed row `FOR UPDATE`,
then the root artifact `FOR SHARE` (so a `save_draft` of a draft root waits,
as at the door), then the manifest through `PinnedResolver.load`, which
hashes a draft's content again the way it was pinned: a draft changed since
leaves the run `blocked` with `incompatible_resume`, and nothing is compiled.
The plan the run's `RunContext` carries is the tenant's own, read here
(model-connections ticket 02, MEDIUM (a)).

`cancel_past_deadline` ends the run and audits `run.deadline_exceeded` as the
`studio_runs` lane in one transaction (CLAUDE.md, Agent and tool rules: a lane
acting on its own audits as itself).

Every call names the claim the `studio_runs` lane made (workflow-engine/04,
R5.5): a row is read and written only `WHERE lease_owner = :token`, so a
worker whose claim lapsed and was taken over reads `StudioLeaseLostError` and
writes nothing. A run leaves `running` with its claim cleared.

A run's waits (workflow-engine/05): `take` reads the ones not yet used, `open`
and `resolved`, in its transaction (R6.4). `park` locks them before it moves
the run, so a decision committed between the wait's open and the park is read
and queues the run instead of being lost, and a decision racing the park
waits for it and then finds the run `waiting` (R6.3); in the same transaction
the thread's checkpoints are compacted to the latest (R6.11). The waits a pass
resumed are `consumed` by the write that parks or ends it, never before, so a
worker that dies mid-pass loses no decision. `block` and a draft changed since
it was pinned leave the run `blocked` with audit `run.blocked` as
`system:studio_runs` (R6.5, R6.8, R6.14).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.checkpoint_compaction import compact_thread
from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import STUDIO_RUN, run_waits, worker_runs
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import RunWait, StudioLeaseLostError, StudioRun, StudioRunBlocked
from dw_agent_runtime.studio_lane import LANE
from dw_kernel.errors import ConfigError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.residency import parse_route_class
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.domain.audit import lane_audit_event
from dw_studio.core.adapters.run_intake import tenant_plan
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.adapters.tables import artifacts

DEADLINE_EXCEEDED: Final = "run.deadline_exceeded"
BLOCKED: Final = "run.blocked"
INCOMPATIBLE_RESUME: Final = "incompatible_resume"


@dataclass(frozen=True)
class SqlStudioRunStore:
    session_factory: async_sessionmaker[AsyncSession]
    ids: IdGenerator
    clock: UtcClock

    async def take(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> StudioRun | StudioRunBlocked:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            row = (
                await session.execute(
                    sa.select(worker_runs)
                    .where(_claimed(run_id, lease_token), STUDIO_RUN)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise StudioLeaseLostError(run_id)
            (
                await session.execute(
                    sa.select(artifacts.c.id)
                    .where(artifacts.c.id == row.artifact_id)
                    .with_for_update(read=True)
                )
            ).all()
            try:
                resolver = await PinnedResolver.load(
                    SqlRunManifestStore(session), str(row.run_manifest_hash)
                )
            except ConfigError as exc:
                if exc.details.get("reason") != "pinned_version_changed":
                    raise
                await self._blocked(
                    session, tenant_id, run_id, lease_token, INCOMPATIBLE_RESUME, None
                )
                return StudioRunBlocked(run_id, INCOMPATIBLE_RESUME)
            plan = await tenant_plan(session)
            root = resolver.root.artifact
            assert root is not None  # `load` refuses a root it cannot read
            return StudioRun(
                run_id=row.id,
                thread_id=row.thread_id,
                tenant_id=tenant_id,
                workspace_id=row.workspace_id,
                artifact_kind=row.artifact_kind,
                artifact_id=row.artifact_id,
                artifact_version_id=row.artifact_version_id,
                pinned_hash=str(resolver.root.content_hash),
                run_mode=row.run_mode,
                requested_by=row.requested_by,
                run_as_principal_id=row.run_as_principal_id,
                run_manifest_hash=str(row.run_manifest_hash),
                plan_id=plan or "",
                deadline_at=row.deadline_at,
                input=dict(row.input or {}),
                pinned_results=row.pinned_results,
                document=root.document,
                engine=dict(resolver.body.get("engine") or {}),
                version_no=root.version_no,
                trace_id=row.trace_id or str(run_id),
                # As admitted; NULL is a row admitted before the column.
                data_route_class=parse_route_class(row.data_route_class or "vn_only"),
                trigger_kind=row.trigger_kind or "",
                root_run_id=None if row.root_run_id == row.id else row.root_run_id,
                waits=await _unused_waits(session, run_id),
            )

    async def admitted(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str, deadline: timedelta
    ) -> datetime:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            # Set once, at the first take that passed dispatch; a take again
            # (after a wait, a requeue) keeps it (R5.22).
            found: datetime | None = await session.scalar(
                sa.update(worker_runs)
                .where(_claimed(run_id, lease_token))
                .values(
                    deadline_at=sa.func.coalesce(
                        worker_runs.c.deadline_at, sa.func.now() + sa.literal(deadline)
                    ),
                    updated_at=sa.func.now(),
                )
                .returning(worker_runs.c.deadline_at)
            )
        if found is None:
            raise StudioLeaseLostError(run_id)
        return found

    async def hold(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        lease_token: str,
        delay: timedelta,
        until: datetime | None = None,
    ) -> None:
        due: Any = sa.literal(until) if until is not None else sa.func.now() + sa.literal(delay)
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            await session.execute(
                sa.update(worker_runs)
                .where(_claimed(run_id, lease_token))
                .values(
                    status=RunStatus.QUEUED.value,
                    lease_owner=None,
                    lease_until=None,
                    available_at=due,
                    updated_at=sa.func.now(),
                )
            )

    async def finish(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        status: Literal["completed", "failed", "cancelled"],
        *,
        lease_token: str,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
        consumed: Sequence[str] = (),
    ) -> None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            left = await self._leave(
                session,
                run_id,
                lease_token,
                RunStatus(status),
                error=error,
                result=result,
                outcomes=outcomes,
            )
            if left is not None:
                await _consume(session, run_id, consumed)

    async def park(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        lease_token: str,
        thread_id: uuid.UUID,
        consumed: Sequence[str] = (),
    ) -> Literal["waiting", "queued"]:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            # The waits first, then the run: the order a decision takes them
            # in, so the two never deadlock, and one that resolved a wait
            # before this read is seen (R6.3).
            held = (
                await session.execute(
                    sa.select(run_waits.c.interrupt_id, run_waits.c.status)
                    .where(
                        run_waits.c.run_id == run_id,
                        run_waits.c.status.in_(("open", "resolved")),
                    )
                    .with_for_update()
                )
            ).all()
            await _consume(session, run_id, consumed)
            used = set(consumed)
            decided = any(r.status == "resolved" and r.interrupt_id not in used for r in held)
            status = RunStatus.QUEUED if decided else RunStatus.WAITING
            values: dict[str, Any] = {
                "status": status.value,
                "lease_owner": None,
                "lease_until": None,
                "updated_at": sa.func.now(),
            }
            if decided:
                values["available_at"] = sa.func.now()
            moved = await session.scalar(
                sa.update(worker_runs)
                .where(_claimed(run_id, lease_token))
                .values(**values)
                .returning(worker_runs.c.id)
            )
            if moved is None:
                raise StudioLeaseLostError(run_id)
            # R6.11 (DO-41): a waiting run holds its latest checkpoint only.
            await compact_thread(session, thread_id)
        return "queued" if decided else "waiting"

    async def block(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        lease_token: str,
        reason_code: str,
        details: Mapping[str, Any] | None = None,
    ) -> bool:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            return await self._blocked(
                session, tenant_id, run_id, lease_token, reason_code, details
            )

    async def _blocked(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        lease_token: str,
        reason_code: str,
        details: Mapping[str, Any] | None,
    ) -> bool:
        """`blocked` with `error.code` `reason_code` and its audit, in the
        caller's transaction (R6.5, R6.8, R6.14); its waits untouched."""
        error = {"code": reason_code, **(dict(details) if details else {})}
        workspace = await self._leave(session, run_id, lease_token, RunStatus.BLOCKED, error=error)
        if workspace is None:
            return False
        await SqlAuditRepository(session).append(
            lane_audit_event(
                lane=LANE,
                event_id=self.ids.new_uuid(),
                tenant_id=TenantId(tenant_id),
                workspace_id=WorkspaceId(workspace),
                action=BLOCKED,
                resource_type="worker_run",
                resource_id=str(run_id),
                occurred_at=self.clock.now(),
                details={"reason_code": reason_code, **(dict(details) if details else {})},
                run_id=run_id,
            )
        )
        return True

    async def cancel_past_deadline(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> bool:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            workspace = await self._leave(
                session,
                run_id,
                lease_token,
                RunStatus.CANCELLED,
                error={"code": "deadline_exceeded"},
            )
            if workspace is None:
                return False
            await SqlAuditRepository(session).append(
                lane_audit_event(
                    lane=LANE,
                    event_id=self.ids.new_uuid(),
                    tenant_id=TenantId(tenant_id),
                    workspace_id=WorkspaceId(workspace),
                    action=DEADLINE_EXCEEDED,
                    resource_type="worker_run",
                    resource_id=str(run_id),
                    occurred_at=self.clock.now(),
                    details={"reason_code": "deadline_exceeded"},
                    run_id=run_id,
                )
            )
            return True

    @staticmethod
    async def _leave(
        session: AsyncSession,
        run_id: uuid.UUID,
        lease_token: str,
        status: RunStatus,
        *,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
    ) -> uuid.UUID | None:
        """Move the claimed run out of `running`, its claim cleared; the
        workspace of the row moved, None when the claim was no longer held or
        the run had already left `running` (a kill's cancel)."""
        values: dict[str, Any] = {
            "status": status.value,
            "lease_owner": None,
            "lease_until": None,
            "outcomes": list(outcomes),
            "updated_at": sa.func.now(),
        }
        if error is not None:
            values["error"] = dict(error)
        if result is not None:
            values["result"] = dict(result)
        found: uuid.UUID | None = await session.scalar(
            sa.update(worker_runs)
            .where(_claimed(run_id, lease_token))
            .values(**values)
            .returning(worker_runs.c.workspace_id)
        )
        return found


async def _unused_waits(session: AsyncSession, run_id: uuid.UUID) -> tuple[RunWait, ...]:
    """The run's waits not yet used: `open`, and `resolved` not `consumed`."""
    rows = (
        await session.execute(
            sa.select(
                run_waits.c.interrupt_id,
                run_waits.c.node_id,
                run_waits.c.iteration_path,
                run_waits.c.kind,
                run_waits.c.status,
                run_waits.c.resolution,
            )
            .where(run_waits.c.run_id == run_id, run_waits.c.status.in_(("open", "resolved")))
            .order_by(run_waits.c.created_at, run_waits.c.interrupt_id)
        )
    ).all()
    return tuple(
        RunWait(
            interrupt_id=r.interrupt_id,
            node_id=r.node_id,
            iteration_path=r.iteration_path,
            kind=r.kind,
            status=r.status,
            resolution=r.resolution,
        )
        for r in rows
    )


async def _consume(session: AsyncSession, run_id: uuid.UUID, consumed: Sequence[str]) -> None:
    """The waits a pass resumed, `resolved` -> `consumed` (R6.4)."""
    if not consumed:
        return
    await session.execute(
        sa.update(run_waits)
        .where(
            run_waits.c.run_id == run_id,
            run_waits.c.interrupt_id.in_(list(consumed)),
            run_waits.c.status == "resolved",
        )
        .values(status="consumed")
    )


def _claimed(run_id: uuid.UUID, lease_token: str) -> sa.ColumnElement[bool]:
    """The run, while it is `running` under this claim (R5.5)."""
    return sa.and_(
        worker_runs.c.id == run_id,
        worker_runs.c.status == RunStatus.RUNNING.value,
        worker_runs.c.lease_owner == lease_token,
    )
