"""A prototype `studio_runs` lane (workflow-engine/04's shape): fair claim per
tenant under RLS, a lease token per claim with a heartbeat, a reaper with
backoff and a dead letter, NOTIFY to wake, and every write of a run fenced by
its token. One `Worker` is one OS process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TextIO

import asyncpg
import sqlalchemy as sa
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dw_agent_runtime.adapters.checkpoint import allowlisted_serializer

from . import savers
from .compiler import (
    LeaseLostError,
    LimitExceededError,
    Lowering,
    RunCancelledError,
    RunCtx,
    StepFailedError,
    interrupt_of,
)
from .door import Crash, Door, Provider
from .savers import _BIND_FUSED, BlobSaver, FencedSaver
from .workflows import WORKFLOWS

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")


@dataclass
class Settings:
    worker: str
    app_url: str
    provider_url: str
    lot: int = 8
    lease: float = 60.0
    heartbeat: float = 15.0
    reaper: float = 5.0
    poll: float = 1.0
    fence: str = "fused"
    notify: bool = True
    cancel: str = "notify"  # or "heartbeat": W1 has no cross-process cancel channel
    recursion_limit: int = 10_000
    durability: str = "sync"
    only_run: str | None = None
    pool: int = 10
    max_concurrency: int = 10
    dispatch_log: bool = True
    log_path: str | None = None


@dataclass
class StepRow:
    id: int
    seq: int | None
    status: str


class Lane:
    """`LanePort`: the wrapper's fenced writes."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _fenced(self, session: AsyncSession, ctx: RunCtx) -> None:
        row = (
            await session.execute(
                sa.text(_BIND_FUSED),
                {
                    "tenant_id": ctx.tenant_id,
                    "workspace_id": ctx.workspace_id,
                    "run": ctx.run_id,
                    "token": ctx.token,
                },
            )
        ).one()
        if not row.held:
            raise LeaseLostError(ctx.run_id)

    async def step_started(
        self, ctx: RunCtx, node: str, step_id: str | None, kind: str, path: str, counted: bool
    ) -> StepRow:
        async with self.sessions() as session, session.begin():
            if counted:
                # The counter's UPDATE is the fence (`WHERE lease_owner`). A
                # `FOR SHARE` before it in the same transaction deadlocks two
                # parallel lanes upgrading their share lock (measured, T1).
                await session.execute(_SET_TENANT, {"t": ctx.tenant_id})
                row = (
                    await session.execute(
                        sa.text(
                            "WITH c AS (UPDATE srt.runs SET steps_started = steps_started + 1"
                            " WHERE id = CAST(:r AS uuid) AND lease_owner = :tok"
                            " RETURNING steps_started, status)"
                            " INSERT INTO srt.run_steps (tenant_id, run_id, node, step_id, kind,"
                            " iteration_path, worker, seq) SELECT :t, :r, :node, :step, :kind,"
                            " :path, :w, c.steps_started FROM c"
                            " RETURNING id, seq, (SELECT status FROM c) AS status"
                        ),
                        {
                            "r": ctx.run_id,
                            "tok": ctx.token,
                            "t": ctx.tenant_id,
                            "node": node,
                            "step": step_id,
                            "kind": kind,
                            "path": path,
                            "w": ctx.worker,
                        },
                    )
                ).first()
                if row is None:
                    raise LeaseLostError(ctx.run_id)
                return StepRow(row.id, row.seq, row.status)
            await self._fenced(session, ctx)
            row = (
                await session.execute(
                    sa.text(
                        "INSERT INTO srt.run_steps (tenant_id, run_id, node, step_id, kind,"
                        " iteration_path, worker) VALUES (:t, :r, :node, :step, :kind, :path, :w)"
                        " RETURNING id"
                    ),
                    {
                        "r": ctx.run_id,
                        "t": ctx.tenant_id,
                        "node": node,
                        "step": step_id,
                        "kind": kind,
                        "path": path,
                        "w": ctx.worker,
                    },
                )
            ).one()
            return StepRow(row.id, None, "running")

    async def step_ended(self, ctx: RunCtx, record_id: int, status: str, attempt: int) -> None:
        async with self.sessions() as session, session.begin():
            await self._fenced(session, ctx)
            await session.execute(
                sa.text(
                    "UPDATE srt.run_steps SET status = :s, attempt = :a,"
                    " ended_at = clock_timestamp() WHERE id = :id"
                ),
                {"s": status, "a": attempt, "id": record_id},
            )

    async def lease_ok(self, ctx: RunCtx) -> None:
        async with self.sessions() as session, session.begin():
            await self._fenced(session, ctx)

    async def spawn_child(
        self, ctx: RunCtx, key: str, workflow: str, run_input: Mapping[str, Any]
    ) -> str:
        child = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
        async with self.sessions() as session, session.begin():
            await self._fenced(session, ctx)
            await session.execute(
                sa.text(
                    "INSERT INTO srt.runs (id, tenant_id, workspace_id, workflow, input, status,"
                    " parent_run_id, root_run_id, depth, alternate, received_at)"
                    " SELECT CAST(:c AS uuid), tenant_id, workspace_id, :wf, CAST(:inp AS jsonb),"
                    " 'blocked', id, coalesce(root_run_id, id), depth + 1, alternate, now()"
                    " FROM srt.runs WHERE id = CAST(:r AS uuid) ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "c": child,
                    "wf": workflow,
                    "inp": json.dumps({**ctx.run_input, **dict(run_input)}),
                    "r": ctx.run_id,
                },
            )
        return child

    async def audit(self, ctx: RunCtx, action: str, details: Mapping[str, Any]) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": ctx.tenant_id})
            await session.execute(
                sa.text(
                    "INSERT INTO srt.audit (tenant_id, run_id, action, details)"
                    " VALUES (:t, :r, :a, CAST(:d AS jsonb))"
                ),
                {"t": ctx.tenant_id, "r": ctx.run_id, "a": action, "d": json.dumps(dict(details))},
            )


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.engine = create_async_engine(
            settings.app_url, pool_size=settings.pool, max_overflow=settings.pool, pool_timeout=30
        )
        self.sessions = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.provider_engine = create_async_engine(
            settings.provider_url, pool_size=4, max_overflow=8
        )
        self.crash = Crash.from_env()
        self.door = Door(
            self.sessions,
            Provider(self.provider_engine),
            self.crash,
            dispatch_log=settings.dispatch_log,
        )
        self.lane = Lane(self.sessions)
        self.serde = allowlisted_serializer(())
        self.graphs: OrderedDict[tuple[str, str, str], Any] = OrderedDict()
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.wake = asyncio.Event()
        self.stopping = False
        self._log: TextIO | None = (
            open(settings.log_path, "a", encoding="utf-8")  # noqa: SIM115 - the process's log
            if settings.log_path
            else None
        )
        self.crash.log = self.log

    # -------------------------------------------------------------- log --

    def log(self, event: str, **fields: Any) -> None:
        if self._log is None:
            return
        record = {"t": time.time(), "w": self.s.worker, "pid": os.getpid(), "e": event, **fields}
        self._log.write(json.dumps(record, default=str) + "\n")
        self._log.flush()

    # ------------------------------------------------------------ graphs --

    def graph(self, workflow: str, compiler: str, saver: str) -> Any:
        key = (workflow, compiler, saver)
        found = self.graphs.get(key)
        if found is not None:
            self.graphs.move_to_end(key)
            return found
        checkpointer: Any
        if saver in ("blob", "blobp"):
            checkpointer = BlobSaver(
                self.sessions, self.serde, self.s.fence, prune_writes=saver == "blobp"
            )
        else:
            checkpointer = FencedSaver(self.sessions, self.serde, self.s.fence)
        compiled = (
            Lowering(WORKFLOWS[workflow], compiler).build().compile(checkpointer=checkpointer)
        )
        self.graphs[key] = compiled
        if len(self.graphs) > 256:
            self.graphs.popitem(last=False)
        return compiled

    # ------------------------------------------------------------- loop --

    async def run(self, until: float | None = None) -> None:
        listener = await asyncpg.connect(self.s.app_url.replace("+asyncpg", ""))
        if self.s.notify:
            await listener.add_listener("srt_runs", lambda *_: self.wake.set())
        if self.s.cancel == "notify":
            await listener.add_listener("srt_cancel", self._on_cancel)
        self.log("started", settings={k: v for k, v in vars(self.s).items() if "url" not in k})
        reaper = asyncio.create_task(self._reap_loop())
        try:
            while not self.stopping:
                if until is not None and time.time() > until:
                    break
                try:
                    await self._claim_cycle()
                except Exception as exc:  # a lane cycle fails, the lane goes on
                    # Measured (T5 stress): a PoolTimeout here used to end the
                    # worker, leaving every queued run to nobody.
                    self.log("claim_error", error=repr(exc)[:300])
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), self.s.poll)
                self.wake.clear()
        finally:
            reaper.cancel()
            await self._release_all()
            await listener.close()
            await self.engine.dispose()
            await self.provider_engine.dispose()
            self.log("stopped")

    def _on_cancel(self, conn: Any, pid: int, channel: str, payload: str) -> None:
        for run_id in payload.split(","):
            task = self.tasks.get(run_id)
            if task is not None:
                self.log("cancel_notified", run=run_id)
                task.cancel("run_cancelled")

    async def _claim_cycle(self) -> None:
        free = self.s.lot - len(self.tasks)
        if free <= 0:
            return
        async with self.sessions() as session, session.begin():
            tenants = [
                str(t)
                for t in (
                    await session.execute(sa.text("SELECT srt.scopes_due(:n)"), {"n": free})
                ).scalars()
            ]
        if not tenants:
            return
        share = max(1, math.ceil(free / len(tenants)))
        for tenant in tenants:
            if len(self.tasks) >= self.s.lot:
                break
            take = min(share, self.s.lot - len(self.tasks))
            async with self.sessions() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": tenant})
                rows = (
                    (
                        await session.execute(
                            sa.text(
                                "WITH picked AS MATERIALIZED (SELECT id FROM srt.runs"
                                " WHERE status = 'queued'"
                                " AND available_at <= now()"
                                " AND (CAST(:only AS uuid) IS NULL OR id = CAST(:only AS uuid))"
                                " AND (NOT alternate OR last_worker IS DISTINCT FROM :w"
                                "      OR available_at < now() - interval '20 seconds')"
                                " ORDER BY priority, available_at, created_at, id LIMIT :n"
                                " FOR UPDATE SKIP LOCKED)"
                                # `id IN (SELECT ... LIMIT n FOR UPDATE SKIP LOCKED)`
                                # became a nested-loop semi join whose inner side
                                # was rescanned: one cycle claimed 9,300 rows (q3).
                                " UPDATE srt.runs r SET status = 'running',"
                                " lease_owner = :w || ':' || gen_random_uuid()::text,"
                                " lease_until = now() + make_interval(secs => :lease),"
                                " last_worker = :w, claims = r.claims + 1"
                                " FROM picked WHERE r.id = picked.id RETURNING r.*"
                            ),
                            {
                                "w": self.s.worker,
                                "lease": self.s.lease,
                                "n": take,
                                "only": self.s.only_run,
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
            for row in rows:
                run_id = str(row["id"])
                self.log("claimed", run=run_id, token=row["lease_owner"], claims=row["claims"])
                self.tasks[run_id] = asyncio.create_task(self._execute(dict(row)))

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(self.s.reaper)
            try:
                await self._reap()
            except Exception as exc:
                self.log("reaper_error", error=repr(exc))

    async def _reap(self) -> None:
        async with self.sessions() as session, session.begin():
            tenants = [
                str(t)
                for t in (await session.execute(sa.text("SELECT srt.orphans_due(50)"))).scalars()
            ]
        for tenant in tenants:
            async with self.sessions() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": tenant})
                rows = (
                    await session.execute(
                        sa.text(
                            "UPDATE srt.runs SET"
                            " status = CASE WHEN attempt >= 4 THEN 'dead_lettered'"
                            " ELSE 'queued' END,"
                            " attempt = attempt + 1, lease_owner = NULL, lease_until = NULL,"
                            " available_at = now() + least(power(2, attempt) * 5, 600)"
                            "   * (1 + random() * 0.1) * interval '1 second'"
                            " WHERE status = 'running' AND lease_until < now()"
                            " RETURNING id, status, attempt"
                        )
                    )
                ).all()
                await session.execute(sa.text("SELECT pg_notify('srt_runs', :t)"), {"t": tenant})
            for row in rows:
                self.log("reaped", run=str(row.id), status=row.status, attempt=row.attempt)

    async def _release_all(self) -> None:
        """An orderly stop gives every lease back, `attempt` unchanged."""
        for task in list(self.tasks.values()):
            task.cancel("worker_stopping")
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    # -------------------------------------------------------------- run --

    async def _execute(self, row: dict[str, Any]) -> None:
        run_id = str(row["id"])
        token = str(row["lease_owner"])
        ctx = RunCtx(
            run_id=run_id,
            tenant_id=str(row["tenant_id"]),
            workspace_id=str(row["workspace_id"]),
            token=token,
            worker=self.s.worker,
            lane=self.lane,
            door=self.door,
            crash=self.crash,
            run_input=dict(row["input"] or {}),
            max_steps=int(row["max_steps"]),
            depth=int(row["depth"]),
            compiler=str(row["compiler"]),
        )
        heartbeat = asyncio.create_task(self._heartbeat(ctx))
        outcome = "?"
        try:
            outcome = await self._invoke(ctx, row)
        except asyncio.CancelledError:
            outcome = "cancelled_locally"
            await asyncio.shield(self._stopped(ctx))
        except LeaseLostError:
            outcome = "lease_lost"
        finally:
            heartbeat.cancel()
            self.tasks.pop(run_id, None)
            self.wake.set()  # a slot is free: claim again now, not at the next poll
            self.log(
                "run_ended",
                run=run_id,
                outcome=outcome,
                fence_rejected=savers.STATS["fence_rejected"],
            )
            if self.s.only_run == run_id and outcome not in ("waiting",):
                self.stopping = True

    async def _stopped(self, ctx: RunCtx) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": ctx.tenant_id})
            released = await session.execute(
                sa.text(
                    "UPDATE srt.runs SET stopped_at = clock_timestamp(),"
                    " status = CASE WHEN status = 'running' THEN 'queued' ELSE status END,"
                    " lease_owner = NULL, lease_until = NULL"
                    " WHERE id = CAST(:r AS uuid) AND lease_owner = :tok RETURNING status"
                ),
                {"r": ctx.run_id, "tok": ctx.token},
            )
            self.log("released", run=ctx.run_id, status=[r.status for r in released])

    async def _heartbeat(self, ctx: RunCtx) -> None:
        while True:
            await asyncio.sleep(self.s.heartbeat)
            async with self.sessions() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": ctx.tenant_id})
                row = (
                    await session.execute(
                        sa.text(
                            "UPDATE srt.runs SET lease_until = now() + make_interval(secs => :l)"
                            " WHERE id = CAST(:r AS uuid) AND lease_owner = :tok RETURNING status"
                        ),
                        {"l": self.s.lease, "r": ctx.run_id, "tok": ctx.token},
                    )
                ).first()
            if row is None or (row.status == "cancelled" and self.s.cancel == "heartbeat"):
                self.log("heartbeat_stops_run", run=ctx.run_id, status=row and row.status)
                task = self.tasks.get(ctx.run_id)
                if task is not None:
                    task.cancel("heartbeat")
                return

    async def _invoke(self, ctx: RunCtx, row: dict[str, Any]) -> str:
        graph = self.graph(str(row["workflow"]), str(row["compiler"]), str(row["saver"]))
        config: dict[str, Any] = {
            "configurable": {
                "thread_id": ctx.run_id,
                "tenant_id": ctx.tenant_id,
                "workspace_id": ctx.workspace_id,
                "srt_run": ctx.run_id,
                "srt_token": ctx.token,
            },
            "recursion_limit": self.s.recursion_limit,
            "max_concurrency": self.s.max_concurrency,
        }
        resume = row.get("resume")
        start: Any
        if resume is not None:
            start = Command(resume=resume)
        elif int(row["claims"]) > 1:
            snapshot = await graph.aget_state(config)
            start = None if snapshot.values else {"input": ctx.run_input}
        else:
            start = {"input": ctx.run_input}
        try:
            result = await graph.ainvoke(start, config, context=ctx, durability=self.s.durability)
        except LimitExceededError:
            return await self._finish(ctx, "failed", error="limit_exceeded")
        except StepFailedError as exc:
            return await self._finish(ctx, "failed", error=exc.code)
        except RunCancelledError:
            await self._stopped(ctx)
            return "cancelled"
        except GraphRecursionError:
            return await self._finish(ctx, "failed", error="recursion_limit")
        except (LeaseLostError, asyncio.CancelledError):
            raise
        except Exception as exc:
            self.log("run_error", run=ctx.run_id, error=repr(exc)[:500])
            return await self._finish(ctx, "failed", error=type(exc).__name__)
        pending = interrupt_of(result)
        if pending is not None:
            return await self._park(ctx, *pending)
        return await self._finish(ctx, "completed", result=_trim(result))

    async def _park(self, ctx: RunCtx, interrupt_id: str, value: dict[str, Any]) -> str:
        kind = str(value.get("wait", "approval"))
        wait_id = uuid.uuid4()
        async with self.sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": ctx.tenant_id})
            moved = (
                await session.execute(
                    sa.text(
                        "UPDATE srt.runs SET status = 'waiting', lease_owner = NULL,"
                        " lease_until = NULL, resume = NULL WHERE id = CAST(:r AS uuid)"
                        " AND lease_owner = :tok AND status = 'running' RETURNING id"
                    ),
                    {"r": ctx.run_id, "tok": ctx.token},
                )
            ).first()
            if moved is None:
                raise LeaseLostError(ctx.run_id)
            await session.execute(
                sa.text(
                    "INSERT INTO srt.waits (id, tenant_id, run_id, step_id, kind, status,"
                    " interrupt_id, payload) VALUES (:id, :t, :r, :s, :k, 'open', :i,"
                    " CAST(:p AS jsonb))"
                ),
                {
                    "id": wait_id,
                    "t": ctx.tenant_id,
                    "r": ctx.run_id,
                    "s": str(value.get("step_id", "?")),
                    "k": kind,
                    "i": interrupt_id,
                    "p": json.dumps(value, default=str),
                },
            )
            if kind == "approval":
                for assignee in value.get("assignees") or ["approver"]:
                    await session.execute(
                        sa.text(
                            "INSERT INTO srt.approvals (id, tenant_id, wait_id, run_id, assignee,"
                            " status) VALUES (gen_random_uuid(), :t, :w, :r, :a, 'pending')"
                        ),
                        {"t": ctx.tenant_id, "w": wait_id, "r": ctx.run_id, "a": assignee},
                    )
            if kind == "child_run":
                await session.execute(
                    sa.text(
                        "UPDATE srt.runs SET status = 'queued', available_at = now()"
                        " WHERE id = CAST(:c AS uuid) AND status = 'blocked'"
                    ),
                    {"c": str(value.get("child_run_id"))},
                )
                await session.execute(
                    sa.text("SELECT pg_notify('srt_runs', :t)"), {"t": ctx.tenant_id}
                )
        self.log("parked", run=ctx.run_id, kind=kind, interrupt=interrupt_id)
        return "waiting"

    async def _finish(
        self,
        ctx: RunCtx,
        status: str,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> str:
        async with self.sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": ctx.tenant_id})
            row = (
                await session.execute(
                    sa.text(
                        "UPDATE srt.runs SET status = :s, error = :e, result = CAST(:res AS jsonb),"
                        " finished_at = clock_timestamp(), lease_owner = NULL, lease_until = NULL,"
                        " resume = NULL WHERE id = CAST(:r AS uuid) AND lease_owner = :tok"
                        " AND status = 'running' RETURNING parent_run_id"
                    ),
                    {
                        "s": status,
                        "e": error,
                        "res": json.dumps(result or {}, default=str),
                        "r": ctx.run_id,
                        "tok": ctx.token,
                    },
                )
            ).first()
            if row is None:
                raise LeaseLostError(ctx.run_id)
            if row.parent_run_id is not None:
                wait = (
                    await session.execute(
                        sa.text(
                            "UPDATE srt.waits SET status = 'resolved', closed_at = now(),"
                            " resolution = CAST(:res AS jsonb) WHERE run_id = :p"
                            " AND status = 'open'"
                            " AND kind = 'child_run' AND payload->>'child_run_id' = :c"
                            " RETURNING interrupt_id"
                        ),
                        {
                            "p": row.parent_run_id,
                            "c": ctx.run_id,
                            "res": json.dumps({"child_status": status}),
                        },
                    )
                ).first()
                if wait is not None:
                    resume = {wait.interrupt_id: {"child_status": status, "result": result or {}}}
                    await session.execute(
                        sa.text(
                            "UPDATE srt.runs SET status = 'queued', available_at = now(),"
                            " resume = CAST(:res AS jsonb) WHERE id = :p AND status = 'waiting'"
                        ),
                        {"p": row.parent_run_id, "res": json.dumps(resume, default=str)},
                    )
                    await session.execute(
                        sa.text("SELECT pg_notify('srt_runs', :t)"), {"t": ctx.tenant_id}
                    )
        self.log("finished", run=ctx.run_id, status=status, error=error)
        return status


def _trim(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in result.items()
        if k.startswith("out__") and isinstance(v, dict) and len(json.dumps(v, default=str)) < 2000
    }
