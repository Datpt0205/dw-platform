"""Integration: the Send floor in the ToolExecutor the API's composition root
builds, on a real database (compliance-pdpl ticket 04; R3.12, CP25).

The executor is the root's own (`container.runtime.tool_executor`), the one
every `tool.call` step of the API's graphs holds, with the shipped
`email.send` the root registered. Without consent the call is refused by the
floor (`blocked:no_consent`, not `send_floor_unavailable`), which runs once:
one `blocked` row and one `marketing.send_refused`. Without
`UNSUBSCRIBE_SIGNING_SECRET` in the `test` profile the root builds no floor
and every message is `blocked:send_floor_unavailable`, the SMTP server called
never, consent or not (ADR-0124 decision 2). The worker's root has its own
test (`apps/worker/tests/integration/test_worker_send_floor_root.py`).
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
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.wflite.versions import TenantWorkflowGraphs
from dw_api.bootstrap.container import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.settings import ApiSettings

pytestmark = pytest.mark.integration


@pytest.fixture
async def engines(api_db: DatabaseUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    app = create_async_engine(api_db.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


def api_container(api_db: DatabaseUrls, *, signing_secret: str) -> ApiContainer:
    return build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret="integration-secret-0123456789abcdef",
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
            # The dev mailbox, so the root builds its SMTP sender.
            smtp_host="mailpit",
            unsubscribe_signing_secret=signing_secret,
        )
    )


def the_roots_executor(container: ApiContainer) -> ToolExecutor:
    """The root's executor, and the one its graphs' `tool.call` steps hold."""
    seam, runner = container.runtime, container.runner
    assert seam is not None and runner is not None
    graphs = runner.run_graphs
    assert isinstance(graphs, TenantWorkflowGraphs)
    assert graphs.ports.executor is seam.tool_executor
    return seam.tool_executor


async def test_the_apis_executor_asks_the_floor_once(
    api_db: DatabaseUrls,
    engines: tuple[AsyncEngine, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.12 (CP25): registered in R2.6's place, the real policy; a send
    without consent is the floor's `no_consent`, one row and one event."""
    migrator, _ = engines
    smtp = fake_smtp(monkeypatch)
    container = api_container(api_db, signing_secret=SIGNING_SECRET)
    try:
        executor = the_roots_executor(container)
        assert_floor_registered(executor, wired=True)
        run = await a_company(migrator)
        assert await send_email(executor, run, an_address()) == "blocked:no_consent"
    finally:
        await container.shutdown()
    trail = await call_trail(migrator, run)
    assert trail.log == [("blocked", "no_consent")]
    assert trail.refused_events == 1
    assert trail.executions == ["refused"]
    assert smtp.sent == []


async def test_without_a_signing_secret_the_api_sends_no_message(
    api_db: DatabaseUrls,
    engines: tuple[AsyncEngine, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.12 (CP25), tools-and-skills R2.8: no secret in the `test` profile,
    no floor; a lead with consent is still not mailed."""
    migrator, app = engines
    smtp = fake_smtp(monkeypatch)
    container = api_container(api_db, signing_secret="")
    try:
        executor = the_roots_executor(container)
        assert_floor_registered(executor, wired=False)
        run = await a_company(migrator)
        address = an_address()
        await grant_consent(app, run, address)
        assert await send_email(executor, run, address) == "blocked:send_floor_unavailable"
    finally:
        await container.shutdown()
    trail = await call_trail(migrator, run)
    assert trail.log == []
    assert trail.refused_events == 0
    assert trail.executions == ["refused"]  # no `dispatched` row
    assert smtp.sent == []
