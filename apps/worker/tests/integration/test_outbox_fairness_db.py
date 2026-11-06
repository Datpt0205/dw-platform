"""The `outbox` lane takes turns between companies, on PostgreSQL
(runtime-hardening R10.6, RH37; ticket 04): S-RT question 3 in small.

Company C has 5,000 due events, all of them earlier than company D's one. The
real `SqlOutboxDrain` behind the real `build_outbox_consumer`, eight events a
company and eight companies a tick: D's event is delivered at the first tick,
where a claim in one `occurred_at` order needed 625.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.ports import SystemClock
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.adapters.persistence.outbox_drain import SqlOutboxDrain
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import build_outbox_consumer

pytestmark = pytest.mark.integration

EARLY = datetime(2026, 1, 1, tzinfo=UTC)

_PLANT = sa.text(
    """
    INSERT INTO platform.outbox_events (id, tenant_id, workspace_id, event_type,
        schema_version, aggregate_id, payload, occurred_at, available_at, attempts)
    SELECT gen_random_uuid(), :t, :t, :e, '1.0', gen_random_uuid(), '{}'::jsonb,
           CAST(:o AS timestamptz) + g * interval '1 millisecond',
           CAST(:o AS timestamptz) + g * interval '1 millisecond', 0
    FROM generate_series(1, :n) AS g
    """
)


@pytest.fixture
async def engines(worker_db: DatabaseUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(worker_db.migrator, poolclass=NullPool)
    app = create_async_engine(worker_db.app, poolclass=NullPool)
    yield migrator, app
    await app.dispose()
    await migrator.dispose()


async def test_a_company_behind_another_company_s_backlog_is_delivered_at_the_first_tick(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    migrator, app = engines
    event_type = f"test.outbox.fairness.{uuid.uuid4().hex[:12]}.v1"
    c, d = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(_PLANT, {"t": c, "e": event_type, "o": EARLY, "n": 5000})
        await conn.execute(
            _PLANT, {"t": d, "e": event_type, "o": EARLY + timedelta(hours=1), "n": 1}
        )
    delivered: list[OutboxEvent] = []

    async def handler(event: OutboxEvent) -> Any:
        delivered.append(event)
        return "noted"

    consume = build_outbox_consumer(
        SqlOutboxDrain(async_sessionmaker(app, class_=AsyncSession), SystemClock()),
        {event_type: handler},
        batch_size=8,
        tenants_per_tick=8,
        max_attempts=3,
        telemetry=RecordingTelemetry(),
        clock=SystemClock(),
    )
    await consume()
    assert [e.tenant_id.value for e in delivered].count(d) == 1
