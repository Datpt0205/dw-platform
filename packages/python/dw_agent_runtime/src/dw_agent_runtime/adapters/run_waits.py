"""`SqlRunWaits`: `RunWaitPort` over `platform.run_waits` (workflow-engine
R6.1-R6.6; ADR-0112 decision 4, ADR-0113 decision 4).

The one owner of a wait row and of its id. Every statement runs in the
caller's transaction (`PlatformUnitOfWork`), under its tenant's RLS: `open`
in the step's, beside what the step opens with its wait; `resolve` in a
decision's, so the decision, the wait and the run move together or not at
all. Neither names a tenant: the row takes its run's, which RLS shows only
to the run's own tenant, and the composite key refuses any other (R6.15).

`open` hands back the row already open, or already decided and not yet used,
for the step's `(node_id, iteration_path)`, so a step run again after a crash,
even one whose decision came in between, meets its own wait; otherwise the
next id, `n` counting the pair's closed rows.

`resolve` is two conditional writes, `WHERE status = 'open'` on the wait and
`WHERE status = 'waiting'` on the run: a wait no longer open is `stale_
interrupt`, so of two concurrent decisions exactly one wins; a run still
`running` (decided between its open and its park) is left to the park, which
reads the decision and queues it; any other run is `stale_interrupt` too.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import run_waits, worker_runs
from dw_agent_runtime.ports import WaitKind
from dw_kernel.errors import ConflictError
from dw_kernel.ports import IdGenerator
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWork
from dw_platform.application.ports import PlatformUnitOfWork

STALE_INTERRUPT: Final = "stale_interrupt"

# A row nobody has used yet: what `open` hands back instead of a new one.
_UNUSED: Final = ("open", "resolved")
_CLOSED: Final = ("resolved", "consumed", "cancelled")
_COLUMNS: Final = [
    "tenant_id",
    "id",
    "run_id",
    "interrupt_id",
    "node_id",
    "iteration_path",
    "kind",
    "status",
    "detail",
    "created_at",
]


def interrupt_id_of(node_id: str, iteration_path: str, n: int) -> str:
    """`wait:<node_id>:<iteration_path>:<n>` (`ck_run_waits_interrupt_id`)."""
    return f"wait:{node_id}:{iteration_path}:{n}"


def stale_interrupt(run_id: uuid.UUID, interrupt_id: str) -> ConflictError:
    return ConflictError(
        "the wait this decision is for is no longer open",
        details={
            "reason_code": STALE_INTERRUPT,
            "run_id": str(run_id),
            "interrupt_id": interrupt_id,
        },
    )


def session_of(uow: PlatformUnitOfWork) -> AsyncSession:
    """The SQL transaction behind `uow`: a wait is written in it, never in a
    transaction of its own."""
    if not isinstance(uow, SqlPlatformUnitOfWork):
        raise TypeError("a run's wait is written in a SQL unit of work")
    return uow.session


@dataclass(frozen=True)
class SqlRunWaits:
    ids: IdGenerator

    async def open(
        self,
        uow: PlatformUnitOfWork,
        run_id: uuid.UUID,
        node_id: str,
        iteration_path: str,
        kind: WaitKind,
        detail: Mapping[str, Any] | None = None,
    ) -> str:
        session = session_of(uow)
        pair = sa.and_(
            run_waits.c.run_id == run_id,
            run_waits.c.node_id == node_id,
            run_waits.c.iteration_path == iteration_path,
        )
        found = await self._unused(session, pair)
        if found is not None:
            return found
        closed = await session.scalar(
            sa.select(sa.func.count()).where(pair, run_waits.c.status.in_(_CLOSED))
        )
        interrupt_id = interrupt_id_of(node_id, iteration_path, int(closed or 0))
        # The run's own tenant, which RLS shows only to it: no tenant argument.
        source = sa.select(
            worker_runs.c.tenant_id,
            sa.literal(self.ids.new_uuid(), type_=run_waits.c.id.type),
            worker_runs.c.id,
            sa.literal(interrupt_id),
            sa.literal(node_id),
            sa.literal(iteration_path),
            sa.literal(kind),
            sa.literal("open"),
            sa.literal(dict(detail), type_=run_waits.c.detail.type)
            if detail is not None
            else sa.null(),
            sa.func.now(),
        ).where(worker_runs.c.id == run_id)
        inserted = await session.scalar(
            pg_insert(run_waits)
            .from_select(_COLUMNS, source)
            .on_conflict_do_nothing()
            .returning(run_waits.c.interrupt_id)
        )
        if inserted is not None:
            return str(inserted)
        # Another writer opened the pair's wait first (a step taken over), or
        # the run is not this tenant's: hand back what is there, or refuse.
        found = await self._unused(session, pair)
        if found is None:
            raise ConflictError("no run of this tenant to wait on", details={"run_id": str(run_id)})
        return found

    @staticmethod
    async def _unused(session: AsyncSession, pair: sa.ColumnElement[bool]) -> str | None:
        found = await session.scalar(
            sa.select(run_waits.c.interrupt_id)
            .where(pair, run_waits.c.status.in_(_UNUSED))
            .order_by(run_waits.c.created_at.desc())
            .limit(1)
        )
        return None if found is None else str(found)

    async def resolve(
        self,
        uow: PlatformUnitOfWork,
        run_id: uuid.UUID,
        interrupt_id: str,
        resolution: Mapping[str, Any],
    ) -> None:
        session = session_of(uow)
        resolved = await session.scalar(
            sa.update(run_waits)
            .where(
                run_waits.c.run_id == run_id,
                run_waits.c.interrupt_id == interrupt_id,
                run_waits.c.status == "open",
            )
            .values(status="resolved", resolution=dict(resolution), resolved_at=sa.func.now())
            .returning(run_waits.c.id)
        )
        if resolved is None:
            raise stale_interrupt(run_id, interrupt_id)
        queued = await session.scalar(
            sa.update(worker_runs)
            .where(worker_runs.c.id == run_id, worker_runs.c.status == RunStatus.WAITING.value)
            .values(
                status=RunStatus.QUEUED.value,
                available_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
            .returning(worker_runs.c.id)
        )
        if queued is not None:
            return
        # Decided between the wait's open and the run's park: the park reads
        # the decision and queues the run. Anything else is not waiting.
        status = await session.scalar(
            sa.select(worker_runs.c.status).where(worker_runs.c.id == run_id)
        )
        if status != RunStatus.RUNNING.value:
            raise stale_interrupt(run_id, interrupt_id)
