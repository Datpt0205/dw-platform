# ruff: noqa: F811  (the stack of test_approval_workspace is imported by name)
"""Integration: a run's mode on its row, kept on resume, and a simulated tool
call recorded with its audit or not at all, on real PostgreSQL (tenant-config
ticket 03: R4.1, R4.3, R4.5, R5.1, R5.2; TC9-TC11).

The runner, store, checkpointer and approval flow are the real ones over the
demo graph of `test_approval_workspace` (prepare, a person's review,
dispatch).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from runtime_harness import TENANT_A, WORKSPACE_A, RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_approval_workspace import (  # noqa: F401  (fixtures, used by name)
    Stack,
    _member,
    stack,
    worker_config,
)

from dw_agent_runtime.adapters.run_store import RunStatus, resume_context
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrator(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _row(migrator: AsyncEngine, run_id: uuid.UUID) -> tuple[str, dict[str, object]]:
    async with migrator.connect() as conn:
        mode = await conn.scalar(
            sa.text("SELECT run_mode FROM platform.worker_runs WHERE id = :r"), {"r": run_id}
        )
        details = await conn.scalar(
            sa.text(
                "SELECT details FROM platform.audit_events WHERE action = 'run.started'"
                " AND run_id = :r"
            ),
            {"r": run_id},
        )
    return str(mode), dict(details)


async def test_the_row_holds_a_mode_from_the_set_and_never_a_default(
    migrator: AsyncEngine, stack: Stack
) -> None:
    """R4.1 (TC9): NOT NULL, a CHECK, no DEFAULT."""
    run = make_run_context(workspace=WORKSPACE_A)
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    for value, error in ((None, "null value"), ("dry", "ck_worker_runs_run_mode")):
        async with migrator.begin() as conn:
            with pytest.raises(Exception, match=error):
                await conn.execute(
                    sa.text("UPDATE platform.worker_runs SET run_mode = :m WHERE id = :r"),
                    {"m": value, "r": run.run_id},
                )
    async with migrator.connect() as conn:
        default = await conn.scalar(
            sa.text(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_schema = 'platform' AND table_name = 'worker_runs'"
                " AND column_name = 'run_mode'"
            )
        )
    assert default is None


@pytest.mark.parametrize("mode", ["live", "simulate"])
async def test_the_runner_records_the_contexts_own_mode(
    migrator: AsyncEngine, stack: Stack, mode: str
) -> None:
    """R4.3: the row and the `run.started` audit read the context, never a
    constant: a `simulate` context is a `simulate` row."""
    run = make_run_context(workspace=WORKSPACE_A).model_copy(update={"run_mode": mode})
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    row_mode, details = await _row(migrator, run.run_id)
    assert (row_mode, details["run_mode"]) == (mode, mode)


async def test_a_simulated_run_resumes_simulated_in_another_runner(
    urls: RuntimeUrls, worker_config: Path, stack: Stack
) -> None:
    """R4.5 (TC10): the mode is read back from the row, whichever process
    resumes the run."""
    run = make_run_context(workspace=WORKSPACE_A).model_copy(update={"run_mode": "simulate"})
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    record = await stack.run_store.get(run, run.run_id)
    assert record.status is RunStatus.WAITING_APPROVAL and record.run_mode == "simulate"
    assert resume_context(record, tenant_id=TENANT_A, channel="web").run_mode == "simulate"
    other = Stack(urls.app, worker_config)
    try:
        assert record.approval_request_id is not None
        await other.approvals.decide(
            approval_id=record.approval_request_id,
            approve=True,
            comment="ok",
            context=_member(WORKSPACE_A),
            authorization=ScopeAuthorizationService(),
        )
        (resumed,) = other.recorder.resumed_with
        assert resumed.run_mode == "simulate"
    finally:
        await other.dispose()


def _store(urls: RuntimeUrls) -> tuple[AsyncEngine, SqlToolExecutionStore]:
    engine = create_async_engine(urls.app, poolclass=NullPool)
    return engine, SqlToolExecutionStore(async_sessionmaker(engine, expire_on_commit=False))


async def _record(
    store: SqlToolExecutionStore, run_id: uuid.UUID, status: str, audit: AuditEvent | None
) -> uuid.UUID:
    execution = uuid.uuid4()
    now = datetime.now(UTC)
    await store.record(
        make_run_context(workspace=WORKSPACE_A, run_id=run_id),
        execution_id=execution,
        tool_name="demo.write",
        tool_version="1.0.0",
        status=status,
        input_hash="h",
        output_hash=None,
        output={"simulated": True},
        idempotency_key=None,
        error=None,
        attempts=0,
        started_at=now,
        finished_at=now,
        audit=audit,
    )
    return execution


def _audit(run_id: uuid.UUID, tenant: uuid.UUID = TENANT_A) -> AuditEvent:
    return AuditEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(tenant),
        workspace_id=WorkspaceId(WORKSPACE_A),
        actor_id=UserId(uuid.uuid4()),
        action="tool.simulated",
        resource_type="tool",
        resource_id="demo.write@1.0.0",
        run_id=run_id,
        policy_decision="simulate",
        details={"run_mode": "simulate", "reason": "not_simulate_safe"},
        occurred_at=datetime.now(UTC),
    )


async def test_the_status_set_takes_simulated_beside_every_value_written_today(
    urls: RuntimeUrls, migrator: AsyncEngine, stack: Stack
) -> None:
    """R5.1 (TC11): `simulated`, `dispatched`, `outcome_unknown`, `refused`
    are taken; anything else is refused by the CHECK."""
    run = make_run_context(workspace=WORKSPACE_A)
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    engine, store = _store(urls)
    try:
        for status in ("simulated", "refused", "outcome_unknown"):
            await _record(store, run.run_id, status, None)
        with pytest.raises(Exception, match="ck_tool_executions_status"):
            await _record(store, run.run_id, "bogus", None)
    finally:
        await engine.dispose()
    async with migrator.connect() as conn:
        definition = await conn.scalar(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_tool_executions_status'"
            )
        )
    for value in ("succeeded", "failed", "dispatched", "outcome_unknown", "refused", "simulated"):
        assert f"'{value}'" in str(definition), value


async def test_a_simulated_row_is_written_with_its_audit_or_not_at_all(
    urls: RuntimeUrls, migrator: AsyncEngine, stack: Stack
) -> None:
    """R5.2 (TC11): the audit is the row's own transaction. An audit the
    database refuses (another tenant's, under this tenant's RLS) takes the
    row with it."""
    run = make_run_context(workspace=WORKSPACE_A)
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    engine, store = _store(urls)
    try:
        kept = await _record(store, run.run_id, "simulated", _audit(run.run_id))
        with pytest.raises(Exception):  # noqa: B017 - the database's own refusal
            await _record(store, run.run_id, "simulated", _audit(run.run_id, uuid.uuid4()))
    finally:
        await engine.dispose()
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM platform.tool_executions"
                    " WHERE run_id = :r AND status = 'simulated'"
                ),
                {"r": run.run_id},
            )
        ).scalars()
        audits = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.audit_events"
                " WHERE run_id = :r AND action = 'tool.simulated'"
            ),
            {"r": run.run_id},
        )
    assert list(rows) == [kept] and audits == 1
