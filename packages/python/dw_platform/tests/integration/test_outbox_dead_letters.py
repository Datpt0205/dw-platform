# ruff: noqa: F811  (the fixtures of test_outbox_drain are imported by name)
"""Integration: the outbox backs off, gives up, counts the dead and replays
them in an operator's name; run, approval and decision statuses are held to
their sets (runtime-hardening ticket 03: R9.3, R10.1-R10.5; RH26-RH29).

Every event type here is this file's own, so the cross-tenant drain and the
backlog read only what each test wrote.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from test_outbox_drain import (  # noqa: F401  (fixtures, used by name)
    NOW,
    _announce,
    _context,
    _due,
    _event,
    _row,
    pooled_app_engine,
)

from dw_kernel.ports import FixedClock
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.outbox_drain import SqlOutboxDrain
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.domain.approval import ApprovalStatus, DecisionOutcome

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[5]
MAX = 3


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _one(
    pooled_app_engine: AsyncEngine, event_type: str
) -> tuple[SqlOutboxDrain, uuid.UUID, async_sessionmaker[AsyncSession]]:
    sessions = async_sessionmaker(pooled_app_engine, class_=AsyncSession, expire_on_commit=False)
    context = _context(uuid.uuid4(), uuid.uuid4())
    event = _event(context, event_type=event_type)
    await _announce(SqlPlatformUnitOfWorkFactory(sessions), context, event)
    return SqlOutboxDrain(session_factory=sessions, clock=FixedClock(NOW)), event.id, sessions


async def _wait_seconds(migrator: AsyncEngine, event_id: uuid.UUID) -> float:
    async with migrator.connect() as conn:
        return float(
            await conn.scalar(
                sa.text(
                    "SELECT extract(epoch FROM available_at - now())"
                    " FROM platform.outbox_events WHERE id = :e"
                ),
                {"e": event_id},
            )
        )


def _type() -> str:
    return f"test.dead.{uuid.uuid4().hex[:8]}.v1"


async def test_a_failure_backs_off_exponentially_by_the_databases_clock(
    pooled_app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R10.1 (RH27): not claimed while `available_at` is ahead; claimed once
    it has passed; attempt n waits within [b, 1.2 b], b = min(30 * 2^(n-1),
    3600) seconds."""
    kind = _type()
    drain, event_id, _ = await _one(pooled_app_engine, kind)
    for n in (1, 2):
        claimed = await drain.claim_batch(event_types=[kind], limit=5, max_attempts=10)
        assert [e.id for e in claimed] == [event_id] and claimed[0].attempts == n
        await drain.record_failure(event_id, error="boom", max_attempts=10)
        wait = await _wait_seconds(migrator, event_id)
        base = min(30 * 2 ** (n - 1), 3600)
        assert base - 2 <= wait <= base * 1.2 + 1, (n, wait)
        assert await drain.claim_batch(event_types=[kind], limit=5, max_attempts=10) == []
        await _due(migrator, event_id)


async def test_the_last_attempt_and_an_undeliverable_event_are_given_up_on(
    pooled_app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R10.2 (RH28): `dead_at` at the last attempt, and at once for an
    undeliverable event; neither is claimed again."""
    kind = _type()
    drain, event_id, _ = await _one(pooled_app_engine, kind)
    for _ in range(MAX):
        await _due(migrator, event_id)
        assert await drain.claim_batch(event_types=[kind], limit=5, max_attempts=MAX)
        await drain.record_failure(event_id, error="boom", max_attempts=MAX)
    assert (await _row(migrator, event_id)).dead_at is not None
    await _due(migrator, event_id)
    assert await drain.claim_batch(event_types=[kind], limit=5, max_attempts=MAX) == []

    kind = _type()
    drain, event_id, _ = await _one(pooled_app_engine, kind)
    assert await drain.claim_batch(event_types=[kind], limit=5, max_attempts=MAX)
    await drain.record_failure(event_id, error="no actor", max_attempts=MAX, undeliverable=True)
    row = await _row(migrator, event_id)
    assert row.dead_at is not None and row.attempts == 1


async def test_an_event_that_died_during_its_last_delivery_is_given_up_on_at_the_claim(
    pooled_app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R10.2, R10.3 (RH28): attempts spent, neither processed nor dead (the
    process died mid-delivery): the next claim sets `dead_at`, hands it to no
    handler, and the gauge's count is 1; the backlog does not count it."""
    kind = _type()
    drain, event_id, _ = await _one(pooled_app_engine, kind)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.update(tables.outbox_events)
            .where(tables.outbox_events.c.id == event_id)
            .values(attempts=MAX)
        )
    before = await drain.backlog(event_types=[kind])
    assert (before.pending, before.dead) == (1, 0)
    assert await drain.claim_batch(event_types=[kind], limit=5, max_attempts=MAX) == []
    assert (await _row(migrator, event_id)).dead_at is not None
    after = await drain.backlog(event_types=[kind])
    assert (after.pending, after.dead) == (0, 1)


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "replay_dead_outbox", REPO / "scripts" / "replay_dead_outbox.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_dead_outbox"] = module
    spec.loader.exec_module(module)
    return module


async def _operator(migrator: AsyncEngine) -> str:
    user, email = uuid.uuid4(), f"ops-{uuid.uuid4().hex[:8]}@platform.test"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.users).values(
                id=user, subject=f"ops-{user}", email=email, display_name="Ops"
            )
        )
        await conn.execute(sa.insert(tables.platform_operators).values(user_id=user))
    return email


async def _dead(pooled_app_engine: AsyncEngine, migrator: AsyncEngine) -> tuple[uuid.UUID, Any]:
    kind = _type()
    drain, event_id, sessions = await _one(pooled_app_engine, kind)
    assert await drain.claim_batch(event_types=[kind], limit=5, max_attempts=MAX)
    await drain.record_failure(event_id, error="x", max_attempts=MAX, undeliverable=True)
    return event_id, sessions


async def _audits(migrator: AsyncEngine, event_id: uuid.UUID) -> list[uuid.UUID]:
    async with migrator.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT actor_id FROM platform.audit_events"
                        " WHERE action = 'platform.outbox.replayed' AND resource_id = :r"
                    ),
                    {"r": str(event_id)},
                )
            ).scalars()
        )


async def test_an_operator_replays_a_dead_event_with_one_audit_row(
    pooled_app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R10.4 (RH29): back on the queue, no attempts spent, one audit row in
    the operator's name; replaying it again changes nothing (exit 2)."""
    script = _script()
    email = await _operator(migrator)
    event_id, sessions = await _dead(pooled_app_engine, migrator)
    assert await script.replay(sessions, email, [event_id]) == 0
    row = await _row(migrator, event_id)
    assert row.dead_at is None and row.attempts == 0
    async with migrator.connect() as conn:
        operator = await conn.scalar(
            sa.select(tables.users.c.id).where(tables.users.c.email == email)
        )
    assert await _audits(migrator, event_id) == [operator]
    assert await script.replay(sessions, email, [event_id]) == 2
    assert len(await _audits(migrator, event_id)) == 1


async def test_a_failed_audit_leaves_the_event_dead(
    pooled_app_engine: AsyncEngine, migrator: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10.4: the audit is the replay's own transaction."""
    script = _script()
    email = await _operator(migrator)
    event_id, sessions = await _dead(pooled_app_engine, migrator)

    def foreign(event: Any, operator: uuid.UUID) -> Any:
        # Another tenant's row: RLS refuses it inside the replay's transaction.
        from dataclasses import replace

        return replace(script._audit(event, operator), tenant_id=script.TenantId(uuid.uuid4()))

    monkeypatch.setattr(script, "_audit", foreign)
    with pytest.raises(Exception):  # noqa: B017 - the database's own refusal
        await script.replay(sessions, email, [event_id])
    assert (await _row(migrator, event_id)).dead_at is not None
    assert await _audits(migrator, event_id) == []


async def test_someone_who_is_not_a_platform_operator_replays_nothing(
    pooled_app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R10.5 (RH29)."""
    script = _script()
    event_id, sessions = await _dead(pooled_app_engine, migrator)
    assert await script.replay(sessions, "nobody@platform.test", [event_id]) == 1
    assert (await _row(migrator, event_id)).dead_at is not None
    assert await _audits(migrator, event_id) == []


# ---- R9.3 (RH26): statuses held to their sets ------------------------------

_CHECKS = {
    "ck_worker_runs_status": "platform.worker_runs",
    "ck_approval_requests_status": "platform.approval_requests",
    "ck_approval_decisions_outcome": "platform.approval_decisions",
}


async def _check_values(migrator: AsyncEngine, name: str) -> set[str]:
    async with migrator.connect() as conn:
        definition = await conn.scalar(
            sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        )
    import re

    return set(re.findall(r"'([a-z_]+)'::text", str(definition)))


async def test_each_status_check_is_its_enums_set(migrator: AsyncEngine) -> None:
    """A value added to an enum and not to its CHECK (or the reverse) is red."""
    from dw_agent_runtime.adapters.run_store import RunStatus

    assert await _check_values(migrator, "ck_worker_runs_status") == {s.value for s in RunStatus}
    assert await _check_values(migrator, "ck_approval_requests_status") == {
        s.value for s in ApprovalStatus
    }
    assert await _check_values(migrator, "ck_approval_decisions_outcome") == {
        s.value for s in DecisionOutcome
    }


async def test_a_status_outside_the_set_is_refused(migrator: AsyncEngine) -> None:
    """R9.3 (RH26): a run, an approval and a decision, each written valid,
    then given `bogus`: the CHECK refuses each. All rolled back."""
    t, w, run, request, user = (uuid.uuid4() for _ in range(5))
    async with migrator.connect() as conn:
        tx = await conn.begin()
        try:

            async def run_sql(sql: str, **values: Any) -> None:
                await conn.execute(sa.text(sql), values)

            await run_sql(
                "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)",
                t=t,
                s=f"ck-{t.hex[:12]}",
            )
            await run_sql(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'm', 'm')",
                w=w,
                t=t,
            )
            await run_sql(
                "INSERT INTO platform.worker_runs (run_mode, id, thread_id, tenant_id,"
                " workspace_id, worker_id, worker_version, graph_version, requested_by)"
                " VALUES ('live', :r, :r, :t, :w, 'demo', '1.0.0', '1.0.0', :u)",
                r=run,
                t=t,
                w=w,
                u=user,
            )
            await run_sql(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by) VALUES (:a, :t, :w, 'demo.x', :u)",
                a=request,
                t=t,
                w=w,
                u=user,
            )
            await run_sql(
                "INSERT INTO platform.approval_decisions (id, request_id, tenant_id, workspace_id,"
                " decided_by, outcome, comment, decided_at)"
                " VALUES (:d, :a, :t, :w, :u, 'approved', '', now())",
                d=uuid.uuid4(),
                a=request,
                t=t,
                w=w,
                u=user,
            )
            for table, column, name, key in (
                ("platform.worker_runs", "status", "ck_worker_runs_status", run),
                ("platform.approval_requests", "status", "ck_approval_requests_status", request),
                (
                    "platform.approval_decisions",
                    "outcome",
                    "ck_approval_decisions_outcome",
                    request,
                ),
            ):
                where = "request_id" if table.endswith("decisions") else "id"
                savepoint = await conn.begin_nested()
                with pytest.raises(Exception, match=name):
                    await run_sql(
                        f"UPDATE {table} SET {column} = 'bogus' WHERE {where} = :k", k=key
                    )
                await savepoint.rollback()
        finally:
            await tx.rollback()
