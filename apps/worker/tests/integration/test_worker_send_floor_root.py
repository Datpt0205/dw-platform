"""Integration: the Send floor in the ToolExecutor the worker's composition
root builds, on a real database (compliance-pdpl ticket 04; R3.12, CP25).

`build_wflite_runtime` is the worker's root for the graphs its `dw_work` and
`dw_timers` lanes run; the executor tested is the one its `tool.call` steps
hold, with the shipped `email.send` the root registered. The worker is where
a lead's mail is sent, so its executor is tested on its own, not inferred
from the API's (`apps/api/tests/integration/test_api_send_floor_root.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pg_test_db import DatabaseUrls
from send_floor_root import (
    SIGNING_SECRET,
    a_company,
    an_address,
    assert_floor_registered,
    call_trail,
    fake_smtp,
    grant_consent,
    send_email,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.wflite.catalog import load_shipped_packs
from dw_agent_runtime.wflite.versions import TenantWorkflowGraphs
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_observability.telemetry import NullTelemetry
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.work_queue import WorkQueue
from dw_worker.composition import CONFIGS, build_wflite_runtime
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.integration


@pytest.fixture
async def engines(worker_db: DatabaseUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(worker_db.migrator, poolclass=NullPool)
    app = create_async_engine(worker_db.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


def the_roots_executor(
    app: AsyncEngine, worker_db: DatabaseUrls, *, signing_secret: str
) -> ToolExecutor:
    """As `dw_worker.main` builds the wf-lite runtime; the executor its
    graphs' `tool.call` steps hold."""
    sessions = async_sessionmaker(app, expire_on_commit=False)
    packs = load_shipped_packs(CONFIGS)
    clock, ids = SystemClock(), Uuid4Generator()
    runtime = build_wflite_runtime(
        WorkerSettings(
            profile="test",
            database_url=worker_db.app,
            model_provider="mock",
            # The dev mailbox, so the root builds its SMTP sender.
            smtp_host="mailpit",
            unsubscribe_signing_secret=signing_secret,
        ),
        sessions,
        packs=packs,
        queue=WorkQueue(
            repo=SqlWorkQueueRepository(sessions),
            workers=SqlDigitalWorkerRepository(sessions),
            people=SqlDwMembershipCheck(sessions),
            schemas=packs,
            authz=ScopeAuthorizationService(),
            clock=clock,
            id_generator=ids,
        ),
        clock=clock,
        ids=ids,
        telemetry=NullTelemetry(),
        run_control=OpenRunControl(),
    )
    graphs = runtime.runner.run_graphs
    assert isinstance(graphs, TenantWorkflowGraphs)
    executor = graphs.ports.executor
    assert isinstance(executor, ToolExecutor)
    return executor


async def test_the_workers_executor_asks_the_floor_once(
    worker_db: DatabaseUrls,
    engines: tuple[AsyncEngine, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.12 (CP25): registered in R2.6's place, the real policy; a send
    without consent is the floor's `no_consent`, one row and one event."""
    migrator, app = engines
    smtp = fake_smtp(monkeypatch)
    executor = the_roots_executor(app, worker_db, signing_secret=SIGNING_SECRET)
    assert_floor_registered(executor, wired=True)
    run = await a_company(migrator)
    assert await send_email(executor, run, an_address()) == "blocked:no_consent"
    trail = await call_trail(migrator, run)
    assert trail.log == [("blocked", "no_consent")]
    assert trail.refused_events == 1
    assert trail.executions == ["refused"]
    assert smtp.sent == []


async def test_without_a_signing_secret_the_worker_sends_no_message(
    worker_db: DatabaseUrls,
    engines: tuple[AsyncEngine, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.12 (CP25), tools-and-skills R2.8: no secret in the `test` profile,
    no floor; a lead with consent is still not mailed."""
    migrator, app = engines
    smtp = fake_smtp(monkeypatch)
    executor = the_roots_executor(app, worker_db, signing_secret="")
    assert_floor_registered(executor, wired=False)
    run = await a_company(migrator)
    address = an_address()
    await grant_consent(app, run, address)
    assert await send_email(executor, run, address) == "blocked:send_floor_unavailable"
    trail = await call_trail(migrator, run)
    assert trail.log == []
    assert trail.refused_events == 0
    assert trail.executions == ["refused"]  # no `dispatched` row
    assert smtp.sent == []
