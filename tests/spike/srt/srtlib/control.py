"""The harness side: submit runs, decide approvals, resolve holds, cancel a
run tree, start and kill worker processes, and read what happened.

Decisions and cancellations are written the way ADR-0113 has them: the wait,
its approvals and the run row in one transaction, then a NOTIFY.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess  # nosec B404 - starts this interpreter on the spike's own entry
import sys
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .db import REPO_ROOT, TENANTS, Urls

ENTRY = Path(__file__).resolve().parents[1] / "run_srt.py"
TERMINAL = ("completed", "failed", "cancelled", "dead_lettered")


@dataclass
class Proc:
    name: str
    popen: subprocess.Popen[bytes]
    log: Path

    def kill(self) -> float:
        """A real death: TerminateProcess on Windows, SIGKILL elsewhere."""
        at = time.time()
        self.popen.kill()
        self.popen.wait(30)
        return at

    def stop(self, timeout: float = 60) -> int | None:
        if self.popen.poll() is None:
            if sys.platform == "win32":
                # CTRL_BREAK reaches the worker's own process group only.
                import signal

                self.popen.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.popen.terminate()
        try:
            return self.popen.wait(timeout)
        except subprocess.TimeoutExpired:
            self.popen.kill()
            return self.popen.wait(30)


@dataclass
class Harness:
    urls: Urls
    logdir: Path
    migrator: AsyncEngine = field(init=False)
    procs: list[Proc] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Pooled, as an endpoint's would be: question 2 times the receipt.
        self.migrator = create_async_engine(self.urls.migrator, pool_size=4, max_overflow=4)
        self.logdir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- workers --

    def start(
        self,
        name: str,
        *,
        env: dict[str, str] | None = None,
        args: Sequence[str] = (),
        tag: str = "",
    ) -> Proc:
        log = self.logdir / f"{tag}{name}.jsonl"
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        popen = subprocess.Popen(
            [sys.executable, str(ENTRY), "worker", "--id", name, "--log", str(log), *args],
            env={**os.environ, **(env or {})},
            cwd=REPO_ROOT,
            stdout=open(self.logdir / f"{tag}{name}.out", "ab"),  # noqa: SIM115
            stderr=subprocess.STDOUT,
            creationflags=creation,
        )
        proc = Proc(name, popen, log)
        self.procs.append(proc)
        return proc

    def stop_all(self) -> None:
        for proc in self.procs:
            proc.stop(30)
        self.procs.clear()

    # ------------------------------------------------------------- runs --

    async def submit(
        self,
        workflow: str,
        *,
        tenant: str = "A",
        run_input: dict[str, Any] | None = None,
        compiler: str = "c1",
        saver: str = "current",
        alternate: bool = False,
        max_steps: int | None = None,
        status: str = "queued",
        priority: int = 0,
        run_id: str | None = None,
    ) -> str:
        from .workflows import WORKFLOWS

        run_id = run_id or str(uuid.uuid4())
        tenant_id, workspace_id = TENANTS[tenant]
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO srt.runs (id, tenant_id, workspace_id, workflow, compiler, saver,"
                    " input, status, alternate, max_steps, priority, received_at, root_run_id)"
                    " VALUES (:id, :t, :w, :wf, :c, :s, CAST(:i AS jsonb), :st, :alt, :m, :p,"
                    " clock_timestamp(), :id)"
                ),
                {
                    "id": run_id,
                    "t": tenant_id,
                    "w": workspace_id,
                    "wf": workflow,
                    "c": compiler,
                    "s": saver,
                    "i": json.dumps(run_input or {}),
                    "st": status,
                    "alt": alternate,
                    "m": max_steps or WORKFLOWS[workflow].limits.max_steps,
                    "p": priority,
                },
            )
            await conn.execute(sa.text("SELECT pg_notify('srt_runs', :t)"), {"t": str(tenant_id)})
        return run_id

    async def run(self, run_id: str) -> dict[str, Any]:
        async with self.migrator.connect() as conn:
            row = (
                (await conn.execute(sa.text("SELECT * FROM srt.runs WHERE id = :r"), {"r": run_id}))
                .mappings()
                .one()
            )
        return dict(row)

    async def wait_for(
        self,
        run_ids: Iterable[str],
        statuses: Sequence[str] = TERMINAL,
        timeout: float = 120,
        interval: float = 0.2,
    ) -> dict[str, str]:
        ids = list(run_ids)
        deadline = time.time() + timeout
        found: dict[str, str] = {}
        while time.time() < deadline:
            async with self.migrator.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT id::text, status FROM srt.runs"
                            " WHERE id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": ids},
                    )
                ).all()
            found = {r.id: r.status for r in rows}
            if len(found) == len(ids) and all(s in statuses for s in found.values()):
                return found
            await asyncio.sleep(interval)
        raise TimeoutError(f"runs not in {statuses}: {found}")

    async def open_wait(self, run_id: str, timeout: float = 120) -> dict[str, Any]:
        await self.wait_for([run_id], ("waiting", *TERMINAL), timeout)
        async with self.migrator.connect() as conn:
            row = (
                (
                    await conn.execute(
                        sa.text(
                            "SELECT * FROM srt.waits WHERE run_id = :r AND status = 'open'"
                            " ORDER BY opened_at DESC LIMIT 1"
                        ),
                        {"r": run_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise AssertionError(f"no open wait on {run_id}: {await self.run(run_id)}")
        return dict(row)

    async def decide(self, run_id: str, approved: bool = True, timeout: float = 120) -> str:
        """Every assignee decides; the wait resolves on the last approval or
        the first rejection (`all`), and the run goes back to the queue."""
        wait = await self.open_wait(run_id, timeout)
        assert wait["kind"] == "approval", wait
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE srt.approvals SET status = :s, closed_at = now() WHERE wait_id = :w"
                ),
                {"s": "approved" if approved else "rejected", "w": wait["id"]},
            )
            await self._resume(conn, run_id, wait, {"approved": approved})
        return str(wait["interrupt_id"])

    async def resolve(
        self, run_id: str, action: str, output: dict[str, Any] | None = None, timeout: float = 120
    ) -> dict[str, Any]:
        wait = await self.open_wait(run_id, timeout)
        async with self.migrator.begin() as conn:
            await self._resume(conn, run_id, wait, {"action": action, "output": output or {}})
        return wait

    async def _resume(self, conn: Any, run_id: str, wait: dict[str, Any], value: Any) -> None:
        await conn.execute(
            sa.text(
                "UPDATE srt.waits SET status = 'resolved', closed_at = now(),"
                " resolution = CAST(:v AS jsonb) WHERE id = :w"
            ),
            {"v": json.dumps(value), "w": wait["id"]},
        )
        await conn.execute(
            sa.text(
                "UPDATE srt.runs SET status = 'queued', available_at = now(),"
                " resume = CAST(:v AS jsonb) WHERE id = :r AND status = 'waiting'"
            ),
            {"v": json.dumps({wait["interrupt_id"]: value}), "r": run_id},
        )
        await conn.execute(sa.text("SELECT pg_notify('srt_runs', 'x')"))

    async def cancel(self, root_run_id: str) -> float:
        """The tree, its open waits and approvals, in one transaction."""
        async with self.migrator.begin() as conn:
            rows = (
                (
                    await conn.execute(
                        sa.text(
                            "WITH RECURSIVE tree AS (SELECT id FROM srt.runs WHERE id = :r"
                            " UNION ALL SELECT c.id FROM srt.runs c"
                            " JOIN tree ON c.parent_run_id = tree.id)"
                            " UPDATE srt.runs SET status = 'cancelled', finished_at = now()"
                            " WHERE id IN (SELECT id FROM tree)"
                            " AND status NOT IN"
                            " ('completed', 'failed', 'cancelled', 'dead_lettered')"
                            " RETURNING id::text"
                        ),
                        {"r": root_run_id},
                    )
                )
                .scalars()
                .all()
            )
            await conn.execute(
                sa.text(
                    "UPDATE srt.waits SET status = 'cancelled', closed_at = now()"
                    " WHERE run_id = ANY(CAST(:ids AS uuid[])) AND status = 'open'"
                ),
                {"ids": list(rows)},
            )
            await conn.execute(
                sa.text(
                    "UPDATE srt.approvals SET status = 'cancelled', closed_at = now()"
                    " WHERE run_id = ANY(CAST(:ids AS uuid[])) AND status = 'pending'"
                ),
                {"ids": list(rows)},
            )
            await conn.execute(sa.text("SELECT pg_notify('srt_cancel', :p)"), {"p": ",".join(rows)})
            committed = (
                await conn.execute(sa.text("SELECT extract(epoch FROM now())"))
            ).scalar_one()
        return float(committed)

    async def fix_provider(self, provider: str) -> None:
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO srt.provider_fixed VALUES (:p) ON CONFLICT DO NOTHING"),
                {"p": provider},
            )

    # ------------------------------------------------------------ reads --

    async def rows(self, statement: str, **values: Any) -> list[dict[str, Any]]:
        async with self.migrator.connect() as conn:
            result = await conn.execute(sa.text(statement), values)
            return [dict(r) for r in result.mappings().all()]

    async def trace(self, run_id: str) -> list[dict[str, Any]]:
        return await self.rows(
            "SELECT node, step_id, kind, iteration_path, worker, seq, status, attempt,"
            " extract(epoch FROM started_at) AS started, extract(epoch FROM ended_at) AS ended"
            " FROM srt.run_steps WHERE run_id = :r ORDER BY id",
            r=run_id,
        )

    async def applied(self, run_id: str) -> dict[str, int]:
        rows = await self.rows(
            "SELECT step_id, count(*) AS n FROM srt.provider_applied WHERE run_id = :r"
            " GROUP BY step_id",
            r=run_id,
        )
        return {r["step_id"]: int(r["n"]) for r in rows}

    async def records(self, run_id: str) -> dict[str, int]:
        rows = await self.rows(
            "SELECT split_part(effect_key, ':', 3) AS step, effect_key, count(*) AS n"
            " FROM srt.records WHERE run_id = :r GROUP BY effect_key",
            r=run_id,
        )
        return {r["effect_key"].split(":", 2)[2]: int(r["n"]) for r in rows}

    async def dispose(self) -> None:
        await self.migrator.dispose()


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
