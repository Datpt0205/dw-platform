"""Integration: one worker drains every tenant's outbox, and only a worker can.

Proves against real Postgres what the unit tests cannot: the `worker_drain`
policy migration 0033 added is what lets a claim cross tenants, that flag dies
with its transaction rather than riding a pooled connection into the next
caller, and an event that keeps failing stops being claimed with its reason
still readable.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dw_kernel.ids import TenantId, WorkspaceId
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.outbox_drain import SqlOutboxDrain
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.outbox import OutboxEvent

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
# One migrated database serves the whole session, so each test claims its own
# event type rather than competing for rows another test left behind.
CLAIMED_TYPE = "test.outbox.claimed.v1"
EXHAUSTED_TYPE = "test.outbox.exhausted.v1"
RESIDUE_TYPE = "test.outbox.residue.v1"
UNSCOPED_TYPE = "test.outbox.unscoped.v1"
UNHANDLED_TYPE = "test.outbox.unhandled.v1"


class FixedClock:
    def now(self) -> datetime:
        return NOW


@pytest.fixture
async def pooled_app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """One connection, reused - so GUC residue would be visible if it existed."""
    engine = create_async_engine(db_urls.app, pool_size=1, max_overflow=0)
    yield engine
    await engine.dispose()


def _context(tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset(),
        plan_id="professional",
    )


def _event(context: AccessContext, *, event_type: str, occurred_at: datetime = NOW) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(context.tenant_id),
        workspace_id=WorkspaceId(context.workspace_id),
        event_type=event_type,
        schema_version="1.0",
        aggregate_id=uuid.uuid4(),
        occurred_at=occurred_at,
        payload={"name": "Cong ty CP Vi du"},
        actor_id=context.principal_id,
    )


async def _announce(
    factory: SqlPlatformUnitOfWorkFactory, context: AccessContext, event: OutboxEvent
) -> None:
    async with factory(context) as uow:
        await uow.outbox.add(event)
        await uow.commit()


async def _row(engine: AsyncEngine, event_id: uuid.UUID) -> sa.Row[tuple]:  # type: ignore[type-arg]
    """Read a row back as the migrator, which bypasses RLS by design."""
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.select(tables.outbox_events).where(tables.outbox_events.c.id == event_id)
            )
        ).one()


async def _due(engine: AsyncEngine, event_id: uuid.UUID) -> None:
    """The backoff passed, without waiting for it."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.update(tables.outbox_events)
            .where(tables.outbox_events.c.id == event_id)
            .values(available_at=sa.func.now() - sa.text("interval '1 second'"))
        )


async def test_the_drain_claims_across_tenants_and_settles_each_event(
    db_urls: DatabaseUrls, pooled_app_engine: AsyncEngine
) -> None:
    session_factory = async_sessionmaker(
        pooled_app_engine, class_=AsyncSession, expire_on_commit=False
    )
    factory = SqlPlatformUnitOfWorkFactory(session_factory)
    alpha = _context(uuid.uuid4(), uuid.uuid4())
    beta = _context(uuid.uuid4(), uuid.uuid4())

    first = _event(alpha, event_type=CLAIMED_TYPE, occurred_at=NOW - timedelta(minutes=2))
    second = _event(beta, event_type=CLAIMED_TYPE, occurred_at=NOW - timedelta(minutes=1))
    ignored = _event(alpha, event_type=UNHANDLED_TYPE)
    await _announce(factory, alpha, first)
    await _announce(factory, beta, second)
    await _announce(factory, alpha, ignored)

    drain = SqlOutboxDrain(session_factory=session_factory, clock=FixedClock())
    claimed = (
        await drain.claim_batch(
            event_types=[CLAIMED_TYPE],
            per_tenant_limit=10,
            tenant_limit=64,
            max_attempts=3,
            after_tenant=None,
        )
    ).events

    # Two tenants, one claim, oldest first. The third event has no handler and
    # must still be undelivered afterwards.
    assert [event.id for event in claimed] == [first.id, second.id]
    assert {event.tenant_id.value for event in claimed} == {alpha.tenant_id, beta.tenant_id}
    assert [event.attempts for event in claimed] == [1, 1]

    migrator = create_async_engine(db_urls.migrator)
    try:
        await drain.mark_processed(first.id)
        await drain.record_failure(second.id, error="account not found", max_attempts=3)

        settled = await _row(migrator, first.id)
        assert settled.processed_at == NOW
        assert settled.last_error is None

        failed = await _row(migrator, second.id)
        assert failed.processed_at is None
        assert failed.last_error == "account not found"

        untouched = await _row(migrator, ignored.id)
        assert untouched.attempts == 0
        assert untouched.processed_at is None

        # The delivered event is gone from the next round; the failed one is
        # back once its backoff has passed.
        await _due(migrator, second.id)
        again = (
            await drain.claim_batch(
                event_types=[CLAIMED_TYPE],
                per_tenant_limit=10,
                tenant_limit=64,
                max_attempts=3,
                after_tenant=None,
            )
        ).events
        assert [event.id for event in again] == [second.id]
        assert again[0].attempts == 2
    finally:
        await migrator.dispose()


async def test_an_event_that_keeps_failing_stops_being_claimed(
    db_urls: DatabaseUrls, pooled_app_engine: AsyncEngine
) -> None:
    session_factory = async_sessionmaker(
        pooled_app_engine, class_=AsyncSession, expire_on_commit=False
    )
    factory = SqlPlatformUnitOfWorkFactory(session_factory)
    context = _context(uuid.uuid4(), uuid.uuid4())
    event = _event(context, event_type=EXHAUSTED_TYPE)
    await _announce(factory, context, event)

    drain = SqlOutboxDrain(session_factory=session_factory, clock=FixedClock())
    migrator = create_async_engine(db_urls.migrator)
    try:
        for attempt in range(2):
            await _due(migrator, event.id)
            claimed = (
                await drain.claim_batch(
                    event_types=[EXHAUSTED_TYPE],
                    per_tenant_limit=10,
                    tenant_limit=64,
                    max_attempts=2,
                    after_tenant=None,
                )
            ).events
            assert [item.id for item in claimed] == [event.id], f"attempt {attempt}"
            await drain.record_failure(event.id, error="still broken", max_attempts=2)
        await _due(migrator, event.id)
        exhausted = (
            await drain.claim_batch(
                event_types=[EXHAUSTED_TYPE],
                per_tenant_limit=10,
                tenant_limit=64,
                max_attempts=2,
                after_tenant=None,
            )
        ).events
        assert exhausted == []
        # R10.2: given up on at its last attempt, and counted as dead only.
        assert (await _row(migrator, event.id)).dead_at is not None
        backlog = await drain.backlog(event_types=[EXHAUSTED_TYPE])
        assert (backlog.pending, backlog.dead) == (0, 1)
    finally:
        await migrator.dispose()


async def test_the_drain_flag_does_not_survive_its_transaction(
    pooled_app_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(
        pooled_app_engine, class_=AsyncSession, expire_on_commit=False
    )
    factory = SqlPlatformUnitOfWorkFactory(session_factory)
    alpha = _context(uuid.uuid4(), uuid.uuid4())
    beta = _context(uuid.uuid4(), uuid.uuid4())
    mine = _event(alpha, event_type=RESIDUE_TYPE)
    theirs = _event(beta, event_type=RESIDUE_TYPE)
    await _announce(factory, alpha, mine)
    await _announce(factory, beta, theirs)

    drain = SqlOutboxDrain(session_factory=session_factory, clock=FixedClock())
    assert (
        len(
            (
                await drain.claim_batch(
                    event_types=[RESIDUE_TYPE],
                    per_tenant_limit=10,
                    tenant_limit=64,
                    max_attempts=3,
                    after_tenant=None,
                )
            ).events
        )
        == 2
    )

    # Same pooled connection, now as an ordinary tenant-scoped caller.
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(alpha.tenant_id)},
        )
        visible = (await session.execute(sa.select(tables.outbox_events.c.id))).scalars().all()
    assert mine.id in visible
    assert theirs.id not in visible


async def test_without_the_flag_nothing_is_visible(pooled_app_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(
        pooled_app_engine, class_=AsyncSession, expire_on_commit=False
    )
    factory = SqlPlatformUnitOfWorkFactory(session_factory)
    context = _context(uuid.uuid4(), uuid.uuid4())
    event = _event(context, event_type=UNSCOPED_TYPE)
    await _announce(factory, context, event)

    async with session_factory() as session, session.begin():
        visible = (
            (
                await session.execute(
                    sa.select(tables.outbox_events.c.id).where(
                        tables.outbox_events.c.id == event.id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert visible == []
