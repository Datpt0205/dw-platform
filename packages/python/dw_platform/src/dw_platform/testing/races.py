"""Two or three real connections racing writes, for the database's own locks.

The shape of `test_service_principals_db.py`'s `_race`: the first side writes
and holds its transaction open; each later side runs in a task until it waits
on a lock (`pg_stat_activity`, read as the superuser) or is done; then the
first side commits and the others finish. No fixed sleep: a side that never
waits is seen as done, not timed out. A `40P01` is counted apart from a
refusal, because a deadlock and a rule's refusal are different answers.

Used by tenant-rbac 13 and 14 (`test_last_owner_races.py`,
`test_owner_count_races.py`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

Write = Callable[[AsyncConnection], Coroutine[Any, Any, None]]


def cause(error: BaseException | None) -> Any:
    """The driver's own exception behind SQLAlchemy's."""
    return getattr(getattr(error, "orig", None), "__cause__", None)


def sqlstate(error: BaseException | None) -> str | None:
    return getattr(cause(error), "sqlstate", None)


async def blocked(admin: AsyncEngine, pid: int) -> bool:
    async with admin.connect() as conn:
        waiting = await conn.scalar(
            sa.text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        )
    return bool(waiting == "Lock")


async def backend_pid(conn: AsyncConnection) -> int:
    return int(await conn.scalar(sa.text("SELECT pg_backend_pid()")))


async def until_waiting(
    admin: AsyncEngine, pid: int, task: asyncio.Task[Any], *, seconds: float = 10.0
) -> bool:
    """True once the connection waits on a lock; False if the task is done first."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not task.done() and asyncio.get_running_loop().time() < deadline:
        if await blocked(admin, pid):
            return True
        await asyncio.sleep(0.05)
    return False


@dataclass
class Raced:
    first: BaseException | None = None
    second: BaseException | None = None
    second_waited: bool = False
    second_done_before_commit: bool = False

    @property
    def deadlocks(self) -> int:
        return sum(sqlstate(e) == "40P01" for e in (self.first, self.second))


async def race(engine: AsyncEngine, admin: AsyncEngine, first: Write, second: Write) -> Raced:
    """`first` writes and holds; `second` starts until it waits or is done;
    `first` commits; `second` finishes and commits."""
    out = Raced()
    async with engine.connect() as one, engine.connect() as two:
        await one.begin()
        await first(one)
        await two.begin()
        pid = await backend_pid(two)
        later = asyncio.create_task(second(two))
        out.second_waited = await until_waiting(admin, pid, later)
        out.second_done_before_commit = later.done()
        try:
            await one.commit()
        except DBAPIError as error:
            out.first = error
            await one.rollback()
        try:
            await later
            await two.commit()
        except DBAPIError as error:
            out.second = error
            await two.rollback()
    return out


async def waiting_pair(
    engine: AsyncEngine, admin: AsyncEngine, holder: Write, a: Write, b: Write
) -> list[BaseException | None]:
    """Three sides: `holder` writes and holds; `a` and `b`, each on its own
    connection, run until they wait on a lock; `holder` commits; both finish.
    Returns [a's error, b's error]."""
    errors: list[BaseException | None] = [None, None]
    async with engine.connect() as h, engine.connect() as c1, engine.connect() as c2:
        await h.begin()
        await holder(h)

        async def side(conn: AsyncConnection, write: Write, slot: int) -> None:
            try:
                await write(conn)
                await conn.commit()
            except DBAPIError as error:
                errors[slot] = error
                await conn.rollback()

        tasks = []
        for slot, (conn, write) in enumerate(((c1, a), (c2, b))):
            await conn.begin()
            pid = await backend_pid(conn)
            task = asyncio.create_task(side(conn, write, slot))
            if not await until_waiting(admin, pid, task):
                raise AssertionError(f"side {slot} did not wait on the holder")
            tasks.append(task)
        await h.commit()
        await asyncio.gather(*tasks)
    return errors


async def interleaved(
    engine: AsyncEngine, admin: AsyncEngine, first: Write, middle: Write, last: Write
) -> list[BaseException]:
    """A's `first` statement; `middle` on another connection until it waits;
    A's `last` statement and commit. Every error of either side."""
    errors: list[BaseException] = []
    async with engine.connect() as a, engine.connect() as m:
        await a.begin()
        await first(a)
        await m.begin()
        pid = await backend_pid(m)

        async def go() -> None:
            try:
                await middle(m)
                await m.commit()
            except DBAPIError as error:
                errors.append(error)
                await m.rollback()

        task = asyncio.create_task(go())
        if not await until_waiting(admin, pid, task):
            raise AssertionError("the middle side did not wait")
        try:
            await last(a)
            await a.commit()
        except DBAPIError as error:
            errors.append(error)
            await a.rollback()
        await task
    return errors
