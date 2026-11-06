"""Integration: the outbox claim takes turns between companies (runtime-hardening
R10.6, G9, RH37; ticket 04).

On PostgreSQL as `dw_app` through `SqlOutboxDrain`, rows planted in bulk by
the migrator with `generate_series`, `occurred_at` and `available_at` stated
so `now()` never decides an order. Each test claims its own event type, so
rows another test left are never taken, and every event a claim returns is
marked processed before the next claim, so a test of many claims never runs
out of attempts.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

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

from dw_platform.adapters.persistence.outbox_drain import SqlOutboxDrain
from dw_platform.domain.outbox import OutboxClaim, OutboxEvent

pytestmark = pytest.mark.integration

EARLY = datetime(2026, 1, 1, tzinfo=UTC)
MAX_ATTEMPTS = 10

_PLANT = sa.text(
    """
    INSERT INTO platform.outbox_events (id, tenant_id, workspace_id, event_type,
        schema_version, aggregate_id, payload, occurred_at, available_at, attempts)
    SELECT gen_random_uuid(), :t, :t, :e, '1.0', gen_random_uuid(), '{}'::jsonb,
           CAST(:o AS timestamptz) + g * interval '1 millisecond',
           CAST(:a AS timestamptz) + g * interval '1 millisecond', 0
    FROM generate_series(1, :n) AS g
    """
)


class FixedClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def drain(db_urls: DatabaseUrls) -> AsyncIterator[SqlOutboxDrain]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield SqlOutboxDrain(async_sessionmaker(engine, class_=AsyncSession), FixedClock())
    await engine.dispose()


def kind() -> str:
    return f"test.outbox.fair.{uuid.uuid4().hex[:12]}.v1"


async def plant(
    migrator: AsyncEngine,
    tenant: uuid.UUID,
    event_type: str,
    count: int,
    *,
    occurred: datetime = EARLY,
    available: datetime | None = None,
) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            _PLANT,
            {
                "t": tenant,
                "e": event_type,
                "o": occurred,
                "a": available if available is not None else occurred,
                "n": count,
            },
        )


async def claim(
    drain: SqlOutboxDrain,
    event_types: Sequence[str],
    *,
    per_tenant: int = 8,
    tenants: int = 8,
    after: uuid.UUID | None = None,
) -> OutboxClaim:
    found = await drain.claim_batch(
        event_types=event_types,
        per_tenant_limit=per_tenant,
        tenant_limit=tenants,
        max_attempts=MAX_ATTEMPTS,
        after_tenant=after,
    )
    for event in found.events:
        await drain.mark_processed(event.id)
    return found


def tenants_of(events: Sequence[OutboxEvent]) -> list[uuid.UUID]:
    return [event.tenant_id.value for event in events]


def sorted_tenants(count: int) -> list[uuid.UUID]:
    return sorted(uuid.uuid4() for _ in range(count))


async def test_one_company_s_events_are_claimed_oldest_first(
    migrator: AsyncEngine, drain: SqlOutboxDrain
) -> None:
    """G9: within a claim, a company's events in `occurred_at` order."""
    event_type, tenant = kind(), uuid.uuid4()
    for offset in (3, 1, 2):
        await plant(migrator, tenant, event_type, 1, occurred=EARLY + timedelta(seconds=offset))
    found = await claim(drain, [event_type], per_tenant=3)
    assert [e.occurred_at for e in found.events] == sorted(e.occurred_at for e in found.events)
    assert [round((e.occurred_at - EARLY).total_seconds()) for e in found.events] == [1, 2, 3]


async def test_a_company_is_not_held_behind_another_company_s_backlog(
    migrator: AsyncEngine, drain: SqlOutboxDrain
) -> None:
    """RH37: 5,000 of C's events, all earlier than D's one, do not hold it."""
    event_type, c, d = kind(), uuid.uuid4(), uuid.uuid4()
    await plant(migrator, c, event_type, 5000)
    await plant(migrator, d, event_type, 1, occurred=EARLY + timedelta(hours=1))
    found = await claim(drain, [event_type], per_tenant=8, tenants=8)
    owners = tenants_of(found.events)
    assert owners.count(d) == 1 and owners.count(c) == 8
    assert set(owners) == {c, d}


async def test_companies_beyond_the_per_claim_cap_take_turns(
    migrator: AsyncEngine, drain: SqlOutboxDrain
) -> None:
    event_type = kind()
    c, e, f, d = sorted_tenants(4)
    for tenant in (c, e, f):
        await plant(migrator, tenant, event_type, 50)
    await plant(migrator, d, event_type, 1, occurred=EARLY + timedelta(hours=1))
    first = await claim(drain, [event_type], tenants=2)
    second = await claim(drain, [event_type], tenants=2, after=first.last_tenant)
    assert d in tenants_of(first.events) + tenants_of(second.events)


async def test_the_rotation_wraps_past_the_last_company(
    migrator: AsyncEngine, drain: SqlOutboxDrain
) -> None:
    event_type = kind()
    low, mid, high = sorted_tenants(3)
    for tenant in (low, mid):
        await plant(migrator, tenant, event_type, 3)
    found = await claim(drain, [event_type], tenants=2, after=high)
    assert set(tenants_of(found.events)) == {low, mid}


async def test_a_lone_company_is_drained_on_every_claim(
    migrator: AsyncEngine, drain: SqlOutboxDrain
) -> None:
    event_type, c = kind(), uuid.uuid4()
    await plant(migrator, c, event_type, 50)
    after: uuid.UUID | None = None
    for _ in range(3):
        found = await claim(drain, [event_type], after=after)
        assert tenants_of(found.events) == [c] * 8
        after = found.last_tenant


@pytest.mark.parametrize("why", ["backing_off", "type_nobody_delivers"])
async def test_a_company_with_nothing_this_process_can_take_takes_no_turn(
    migrator: AsyncEngine, drain: SqlOutboxDrain, why: str
) -> None:
    event_type = kind()
    c, d = sorted_tenants(2)
    if why == "backing_off":
        await plant(migrator, c, event_type, 5, available=datetime.now(UTC) + timedelta(hours=1))
    else:
        await plant(migrator, c, kind(), 5)
    await plant(migrator, d, event_type, 1, occurred=EARLY + timedelta(hours=1))
    found = await claim(drain, [event_type], tenants=1)
    assert tenants_of(found.events) == [d]


async def test_a_company_s_backing_off_and_dead_events_stay_out_of_its_claim(
    migrator: AsyncEngine, drain: SqlOutboxDrain
) -> None:
    """R10.1, R10.2 on the rows a chosen company gives: one due event is
    claimed, never the one backing off nor the dead one beside it."""
    event_type, c = kind(), uuid.uuid4()
    await plant(migrator, c, event_type, 1)
    await plant(
        migrator,
        c,
        event_type,
        1,
        occurred=EARLY - timedelta(hours=2),
        available=datetime.now(UTC) + timedelta(hours=1),
    )
    await plant(migrator, c, event_type, 1, occurred=EARLY - timedelta(hours=1))
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.outbox_events SET dead_at = now()"
                " WHERE tenant_id = :t AND event_type = :e AND occurred_at < :o"
                " AND available_at <= now()"
            ),
            {"t": c, "e": event_type, "o": EARLY},
        )
    found = await claim(drain, [event_type])
    assert [e.occurred_at > EARLY for e in found.events] == [True]
