# ruff: noqa: F811  (the stack of test_approval_workspace is imported by name)
"""Integration: a code-defined worker's run after the Studio run columns
(workflow-engine ticket 02, R3.1): `SqlWorkerRunStore` names no root, the
trigger makes the run its own, at depth 0, with no Studio column, and the run
goes on as before (the demo graph pauses for its person's review).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

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

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrator(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def test_a_code_run_is_its_own_root_and_still_runs(
    migrator: AsyncEngine, stack: Stack
) -> None:
    run = make_run_context(workspace=WORKSPACE_A)
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    async with migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT status, root_run_id, parent_run_id, chain_depth, artifact_kind,"
                    " trigger_kind, priority FROM platform.worker_runs WHERE id = :r"
                ),
                {"r": run.run_id},
            )
        ).one()
    assert row.status == RunStatus.WAITING_APPROVAL.value
    assert (row.root_run_id, row.parent_run_id, row.chain_depth) == (run.run_id, None, 0)
    assert (row.artifact_kind, row.trigger_kind, row.priority) == (None, None, 0)
