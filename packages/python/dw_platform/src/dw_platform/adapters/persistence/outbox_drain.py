"""The worker's side of the outbox: cross-tenant, one batch at a time.

This is the only place in the platform package that reads rows without a tenant
scope, and it says so out loud. A dispatcher drains every tenant's outbox on one
connection, so it sets ``app.worker_drain`` instead of ``app.tenant_id`` and
relies on the policy migration 0033 added.

Delivery is at-least-once by design: the attempt is counted when the row is
claimed, the effect runs outside this transaction, and ``mark_processed`` lands
afterwards. A process that dies between the two retries the event, which is why
every effect wired to this drain has to be idempotent. Marking first would give
at-most-once and lose the effect instead, and losing it is the worse failure -
nothing downstream would ever notice.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.repositories import SqlAuditRepository, outbox_from_row
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxBacklog, OutboxClaim

# SET LOCAL semantics (third argument true) so the flag dies with the
# transaction. Session-wide it would ride the pooled connection back into the
# pool and hand the next caller a connection that can read every tenant.
_ENABLE_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")
_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

# The companies with an undelivered row, found by a skip scan over
# `ix_outbox_events_due_by_tenant` (one probe a company, whatever its backlog),
# kept when one probe finds a due row of a type this process delivers, then
# taken in rotation: from the first company after the caller's cursor, wrapping
# round to the smallest and up to the cursor itself (runtime-hardening R10.6).
# The predicate `processed_at IS NULL AND dead_at IS NULL` is the index's own,
# word for word, or the planner does not use it.
_DUE_TENANTS = text(
    """
    WITH RECURSIVE pending AS (
        (SELECT o.tenant_id FROM platform.outbox_events o
         WHERE o.processed_at IS NULL AND o.dead_at IS NULL
         ORDER BY o.tenant_id LIMIT 1)
        UNION ALL
        SELECT (SELECT o.tenant_id FROM platform.outbox_events o
                WHERE o.processed_at IS NULL AND o.dead_at IS NULL
                  AND o.tenant_id > p.tenant_id
                ORDER BY o.tenant_id LIMIT 1)
        FROM pending p WHERE p.tenant_id IS NOT NULL
    )
    SELECT p.tenant_id FROM pending p
    WHERE p.tenant_id IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM platform.outbox_events o
          WHERE o.processed_at IS NULL AND o.dead_at IS NULL
            AND o.tenant_id = p.tenant_id
            AND o.available_at <= now()
            AND o.event_type = ANY(CAST(:types AS text[]))
      )
    ORDER BY coalesce(p.tenant_id <= CAST(:after AS uuid), false), p.tenant_id
    LIMIT :limit
    """
)

# Each chosen company's due rows, its oldest first, each company its own
# LIMIT and its own `SKIP LOCKED` lock (G9, R10.1).
_DUE_ROWS = text(
    """
    SELECT d.id, d.attempts
    FROM unnest(CAST(:tenants AS uuid[])) AS t(tenant_id)
    CROSS JOIN LATERAL (
        SELECT o.id, o.attempts FROM platform.outbox_events o
        WHERE o.processed_at IS NULL AND o.dead_at IS NULL
          AND o.tenant_id = t.tenant_id
          AND o.available_at <= now()
          AND o.event_type = ANY(CAST(:types AS text[]))
        ORDER BY o.available_at, o.occurred_at
        LIMIT :per_tenant
        FOR UPDATE SKIP LOCKED
    ) AS d
    """
)

_ERROR_LIMIT = 2000
_MAX_BACKOFF_SECONDS = 3600
_JITTER = 0.2


@dataclass(frozen=True)
class SqlOutboxDrain:
    """Implements ``OutboxDrainPort``."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock

    async def claim_batch(
        self,
        *,
        event_types: Sequence[str],
        per_tenant_limit: int,
        tenant_limit: int,
        max_attempts: int,
        after_tenant: uuid.UUID | None,
    ) -> OutboxClaim:
        if not event_types:
            return OutboxClaim(events=[], last_tenant=None)
        e = tables.outbox_events
        async with self.session_factory() as session, session.begin():
            await session.execute(_ENABLE_DRAIN)
            # The companies with a due event, in rotation order (R10.6).
            chosen = [
                row.tenant_id
                for row in await session.execute(
                    _DUE_TENANTS,
                    {
                        "types": list(event_types),
                        "after": after_tenant,
                        "limit": tenant_limit,
                    },
                )
            ]
            if not chosen:
                return OutboxClaim(events=[], last_tenant=None)
            # Each one's oldest due rows, its own lock; a row another
            # dispatcher holds is skipped.
            candidates = (
                await session.execute(
                    _DUE_ROWS,
                    {
                        "tenants": chosen,
                        "types": list(event_types),
                        "per_tenant": per_tenant_limit,
                    },
                )
            ).all()
            last = chosen[-1]
            # Out of attempts and still undelivered: the process died during
            # its last delivery, or it ran out before `dead_at` existed. It is
            # given up on here rather than hidden from the claim, the backlog
            # and the dead-letter gauge alike (R10.2).
            spent = [row.id for row in candidates if row.attempts >= max_attempts]
            if spent:
                await session.execute(
                    sa.update(e).where(e.c.id.in_(spent)).values(dead_at=sa.func.now())
                )
            claimed = [row.id for row in candidates if row.attempts < max_attempts]
            if not claimed:
                return OutboxClaim(events=[], last_tenant=last)
            rows = await session.execute(
                sa.update(e)
                .where(e.c.id.in_(claimed))
                .values(attempts=e.c.attempts + 1)
                .returning(e)
            )
            events = [outbox_from_row(row) for row in rows]
            # Ordering is lost by the UPDATE ... RETURNING, and the dispatcher
            # delivers in the order the events happened (G9).
            events.sort(key=lambda event: event.occurred_at)
            return OutboxClaim(events=events, last_tenant=last)

    async def mark_processed(self, event_id: uuid.UUID) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_ENABLE_DRAIN)
            await session.execute(
                sa.update(tables.outbox_events)
                .where(
                    tables.outbox_events.c.id == event_id,
                    tables.outbox_events.c.processed_at.is_(None),
                )
                .values(processed_at=self.clock.now(), last_error=None)
            )

    async def record_failure(
        self,
        event_id: uuid.UUID,
        *,
        error: str,
        max_attempts: int,
        undeliverable: bool = False,
    ) -> None:
        e = tables.outbox_events
        # Attempt n (already counted by the claim) waits min(30 * 2^(n-1),
        # 3600) seconds plus up to a fifth more, so a tenant's failing handler
        # does not retry in step with every other's (R10.1).
        backoff = sa.func.least(30 * sa.func.power(2, e.c.attempts - 1), _MAX_BACKOFF_SECONDS)
        given_up = sa.literal(undeliverable) | (e.c.attempts >= max_attempts)
        async with self.session_factory() as session, session.begin():
            await session.execute(_ENABLE_DRAIN)
            await session.execute(
                sa.update(e)
                .where(e.c.id == event_id)
                .values(
                    last_error=error[:_ERROR_LIMIT],
                    available_at=sa.func.now()
                    + backoff * (1 + sa.func.random() * _JITTER) * sa.text("interval '1 second'"),
                    dead_at=sa.case((given_up, sa.func.now()), else_=e.c.dead_at),
                )
            )

    async def backlog(self, *, event_types: Sequence[str]) -> OutboxBacklog:
        if not event_types:
            return OutboxBacklog(pending=0, oldest_pending_at=None)
        e = tables.outbox_events
        async with self.session_factory() as session, session.begin():
            await session.execute(_ENABLE_DRAIN)
            row = (
                await session.execute(
                    sa.select(
                        sa.func.count().label("pending"),
                        sa.func.min(tables.outbox_events.c.occurred_at).label("oldest"),
                    ).where(
                        e.c.processed_at.is_(None),
                        e.c.dead_at.is_(None),
                        e.c.event_type.in_(list(event_types)),
                    )
                )
            ).one()
            dead = (
                await session.execute(
                    sa.select(sa.func.count()).where(
                        e.c.processed_at.is_(None),
                        e.c.dead_at.is_not(None),
                        e.c.event_type.in_(list(event_types)),
                    )
                )
            ).scalar_one()
            return OutboxBacklog(pending=row.pending, oldest_pending_at=row.oldest, dead=dead)


@dataclass(frozen=True, slots=True)
class DeadEvent:
    """What an operator's replay needs of a dead event: never its payload."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: str


@dataclass(frozen=True)
class SqlDeadLetters:
    """An operator's replay of dead events (runtime-hardening R10.4, R10.5;
    `scripts/replay_dead_outbox.py`). Here, beside the drain, because finding
    one by id reads across tenants (`app.worker_drain`, which only the
    registered modules set); the replay itself runs under the event's own
    tenant, with its audit row in the same transaction."""

    session_factory: async_sessionmaker[AsyncSession]

    async def find(self, event_id: uuid.UUID) -> DeadEvent | None:
        e = tables.outbox_events
        async with self.session_factory() as session, session.begin():
            await session.execute(_ENABLE_DRAIN)
            row = (
                await session.execute(
                    sa.select(e.c.id, e.c.tenant_id, e.c.workspace_id, e.c.event_type).where(
                        e.c.id == event_id, e.c.dead_at.is_not(None), e.c.processed_at.is_(None)
                    )
                )
            ).first()
        if row is None:
            return None
        return DeadEvent(row.id, row.tenant_id, row.workspace_id, row.event_type)

    async def replay(self, event: DeadEvent, audit: AuditEvent) -> bool:
        """Back to the queue (`dead_at` cleared, no attempts spent, due now)
        with `audit`, both or neither; False when it is not dead any more."""
        e = tables.outbox_events
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(event.tenant_id)})
            back = (
                await session.execute(
                    sa.update(e)
                    .where(e.c.id == event.id, e.c.dead_at.is_not(None))
                    .values(dead_at=None, attempts=0, available_at=sa.func.now())
                    .returning(e.c.id)
                )
            ).first()
            if back is None:
                return False
            await SqlAuditRepository(session).append(audit)
        return True
