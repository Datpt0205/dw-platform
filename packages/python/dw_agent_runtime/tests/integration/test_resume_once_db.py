# ruff: noqa: F811  (the stack of test_approval_workspace is imported by name)
"""Integration: a waiting run is resumed once, and a resume that dies leaves
nothing stuck (runtime-hardening ticket 03: R9.1, R9.2; RH25, G5).

The real runner, store and checkpointer over the demo graph of
`test_approval_workspace` (prepare, a person's review, dispatch).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from runtime_harness import WORKSPACE_A, RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from test_approval_workspace import (  # noqa: F401  (fixtures, used by name)
    Stack,
    stack,
    worker_config,
)

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import ConflictError

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrator(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _paused(stack: Stack, thread: uuid.UUID | None = None) -> RunContext:
    run = make_run_context(workspace=WORKSPACE_A, thread_id=thread)
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    assert (await stack.run_store.get(run, run.run_id)).status is RunStatus.WAITING_APPROVAL
    return run


async def _resumed_audits(migrator: AsyncEngine, run_id: uuid.UUID) -> int:
    async with migrator.connect() as conn:
        return int(
            await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.audit_events"
                    " WHERE action = 'run.resumed' AND run_id = :r"
                ),
                {"r": run_id},
            )
            or 0
        )


async def _twice(stack: Stack, run: RunContext) -> list[Any]:
    payload = {"approved": True, "comment": "ok"}
    return await asyncio.gather(
        *(
            stack.runner.resume(run_context=run, run_id=run.run_id, resume_payload=payload)
            for _ in range(2)
        ),
        return_exceptions=True,
    )


@pytest.mark.parametrize("waiting", ["waiting_approval", "waiting_timer"])
async def test_two_resumes_of_one_run_run_its_graph_once(
    stack: Stack, migrator: AsyncEngine, waiting: str
) -> None:
    """R9.2 (RH25): one resume runs, the other is a 409 and audits nothing,
    from either wait."""
    run = await _paused(stack)
    if waiting == "waiting_timer":
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE platform.worker_runs SET status = 'waiting_timer' WHERE id = :r"),
                {"r": run.run_id},
            )
    outcomes = await _twice(stack, run)
    assert sorted(type(o).__name__ for o in outcomes) == ["ConflictError", "NoneType"]
    assert await _resumed_audits(migrator, run.run_id) == 1
    assert (await stack.run_store.get(run, run.run_id)).status is RunStatus.COMPLETED


async def test_a_resume_that_stopped_after_taking_the_run_does_not_hold_its_thread(
    stack: Stack, migrator: AsyncEngine
) -> None:
    """R9.1 (RH25): a process that died after `begin_resume` leaves the run
    `running`; past the stale window the thread's next turn is taken, not
    told an approval is pending. Without the compare-and-set the run stays
    `waiting_approval` and the turn is refused."""
    thread = uuid.uuid4()
    run = await _paused(stack, thread)
    await stack.run_store.begin_resume(run, run.run_id, waiting=RunStatus.WAITING_APPROVAL)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.worker_runs SET updated_at = now() - interval '2 hours'"
                " WHERE id = :r"
            ),
            {"r": run.run_id},
        )
    later = make_run_context(workspace=WORKSPACE_A, thread_id=thread)
    await stack.runner.start(run_context=later, input_payload={"subject": "y"})
    assert (await stack.run_store.get(later, later.run_id)).status is RunStatus.WAITING_APPROVAL


async def test_a_cancelled_resume_is_recorded_failed_and_raised(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9.1: past `begin_resume`, a cancellation leaves the run `failed` with
    `ResumeInterrupted`, never `running`, and the cancellation goes on."""
    run = await _paused(stack)

    class Cancelling:
        async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
            raise asyncio.CancelledError

    monkeypatch.setattr(stack.runner, "_graph", lambda worker_id, graph_version: Cancelling())
    with pytest.raises(asyncio.CancelledError):
        await stack.runner.resume(
            run_context=run, run_id=run.run_id, resume_payload={"approved": True}
        )
    record = await stack.run_store.get(run, run.run_id)
    assert record.status is RunStatus.FAILED
    assert (record.error or {}).get("type") == "ResumeInterrupted"


async def test_a_resume_of_a_run_not_waiting_is_refused(stack: Stack) -> None:
    run = await _paused(stack)
    await stack.run_store.begin_resume(run, run.run_id, waiting=RunStatus.WAITING_APPROVAL)
    with pytest.raises(ConflictError):
        await stack.run_store.begin_resume(run, run.run_id, waiting=RunStatus.WAITING_APPROVAL)
