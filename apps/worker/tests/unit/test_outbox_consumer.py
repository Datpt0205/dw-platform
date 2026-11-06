"""What the outbox dispatcher does with an event, and what this worker refuses
to wire to one.

Two different things are under test here. The first is the dispatch machinery
itself - claim, deliver, mark, record a failure - which is generic and stays.
The second is a standing guarantee about this particular host: it owns no
handler of its own, so every effect hanging off an event is wired by the
composition root that wants it. That second guarantee is the one worth a test.
Deleting code is easy to undo by accident, and the failure mode it prevents is
expensive and silent - a bulk import announcing 1,666 created records, each
buying a paid model call nobody asked for.

The event types below are invented for this file. The dispatcher routes by key
and knows nothing about what an event means, so naming a real context's event
here would tie the platform's test to a package it does not have.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import FixedClock
from dw_observability.metrics import DW_OUTBOX_BACKLOG_SIZE, DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.domain.outbox import OutboxBacklog, OutboxClaim, OutboxEvent
from dw_worker.consumers.outbox import (
    EventHandler,
    UndeliverableEventError,
    build_outbox_consumer,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = uuid.UUID("22222222-2222-2222-2222-222222222222")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
AGGREGATE = uuid.UUID("44444444-4444-4444-4444-444444444444")

HANDLED_TYPE = "demo.record.created.v1"
OTHER_TYPE = "demo.record.updated.v1"


class FakeDrain:
    """Hands out its events by the claim's contract and records what the
    dispatcher did with them (runtime-hardening R10.6): companies with a due
    event in `tenant_id` order from the first after `after_tenant`, wrapping
    round up to `after_tenant` itself, at most `tenant_limit` of them and at
    most `per_tenant_limit` events of each, oldest first; `last_tenant` the
    last company served."""

    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events
        self.claims: list[tuple[tuple[str, ...], int, int]] = []
        self.cursors: list[uuid.UUID | None] = []
        self.processed: list[uuid.UUID] = []
        self.failures: list[tuple[uuid.UUID, str]] = []
        # Which failures were given up on at once (runtime-hardening R10.2).
        self.undeliverable: list[uuid.UUID] = []
        self.dead = 0

    async def claim_batch(
        self,
        *,
        event_types: Sequence[str],
        per_tenant_limit: int,
        tenant_limit: int,
        max_attempts: int,
        after_tenant: uuid.UUID | None,
    ) -> OutboxClaim:
        self.claims.append((tuple(event_types), per_tenant_limit, max_attempts))
        self.cursors.append(after_tenant)
        matching = [event for event in self.events if event.event_type in set(event_types)]
        due = sorted({event.tenant_id.value for event in matching})
        if after_tenant is not None:
            due = [t for t in due if t > after_tenant] + [t for t in due if t <= after_tenant]
        chosen = due[:tenant_limit]
        claimed: list[OutboxEvent] = []
        for tenant in chosen:
            own = sorted(
                (e for e in matching if e.tenant_id.value == tenant), key=lambda e: e.occurred_at
            )
            claimed += own[:per_tenant_limit]
        self.events = [event for event in self.events if event not in claimed]
        claimed.sort(key=lambda e: e.occurred_at)
        return OutboxClaim(events=claimed, last_tenant=chosen[-1] if chosen else None)

    async def mark_processed(self, event_id: uuid.UUID) -> None:
        self.processed.append(event_id)

    async def record_failure(
        self, event_id: uuid.UUID, *, error: str, max_attempts: int, undeliverable: bool = False
    ) -> None:
        self.failures.append((event_id, error))
        if undeliverable:
            self.undeliverable.append(event_id)
            self.dead += 1

    async def backlog(self, *, event_types: Sequence[str]) -> OutboxBacklog:
        remaining = [event for event in self.events if event.event_type in set(event_types)]
        if not remaining:
            return OutboxBacklog(pending=0, oldest_pending_at=None, dead=self.dead)
        oldest = min(event.occurred_at for event in remaining)
        return OutboxBacklog(pending=len(remaining), oldest_pending_at=oldest, dead=self.dead)


def event(event_type: str = HANDLED_TYPE) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        event_type=event_type,
        schema_version="1.0",
        aggregate_id=AGGREGATE,
        occurred_at=NOW,
        payload={"name": "Cong ty CP Vi du", "country": "VN"},
        actor_id=ACTOR,
    )


def consumer_over(drain: FakeDrain, handlers: dict[str, EventHandler]):
    return build_outbox_consumer(
        drain,  # type: ignore[arg-type]
        handlers,
        batch_size=5,
        tenants_per_tick=8,
        max_attempts=2,
        telemetry=RecordingTelemetry(),
        clock=FixedClock(NOW),
    )


# ---------------------------------------------------------------------------
# The dispatch machinery.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_delivered_event_is_marked_processed() -> None:
    one = event()
    drain = FakeDrain([one])

    async def handle(_: OutboxEvent) -> str:
        return "did the thing"

    await consumer_over(drain, {HANDLED_TYPE: handle})()

    assert drain.processed == [one.id]
    assert drain.failures == []


@pytest.mark.asyncio
async def test_the_dispatcher_asks_only_for_types_it_can_handle() -> None:
    """An event nobody handles is never claimed, so its attempt count stays put.

    This is what lets a handler added months later find its history intact
    rather than a table of rows already marked delivered into nothing.
    """
    unhandled = event(OTHER_TYPE)
    drain = FakeDrain([unhandled])

    async def handle(_: OutboxEvent) -> str:
        return "ok"

    await consumer_over(drain, {HANDLED_TYPE: handle})()

    assert drain.claims == [((HANDLED_TYPE,), 5, 2)]
    assert drain.processed == []
    assert drain.events == [unhandled]


@pytest.mark.asyncio
async def test_an_empty_handler_map_claims_nothing_at_all() -> None:
    """The shape this worker actually runs in.

    With no handler wired the dispatcher must not claim a batch "just in case".
    Claiming would burn an attempt on every event in the outbox and, worse,
    a bug in the empty case could drain the whole table into nothing.
    """
    waiting = event()
    drain = FakeDrain([waiting])

    await consumer_over(drain, {})()

    assert drain.claims == [((), 5, 2)]
    assert drain.processed == []
    assert drain.failures == []
    assert drain.events == [waiting]


@pytest.mark.asyncio
async def test_an_undeliverable_event_is_recorded_and_left_undelivered() -> None:
    one = event()
    drain = FakeDrain([one])

    async def handle(_: OutboxEvent) -> str:
        raise UndeliverableEventError("event has no actor to act as")

    await consumer_over(drain, {HANDLED_TYPE: handle})()

    assert drain.processed == []
    assert drain.failures == [(one.id, "event has no actor to act as")]
    # Given up on at once, not left to spend every attempt (R10.2).
    assert drain.undeliverable == [one.id]


@pytest.mark.asyncio
async def test_one_failing_event_does_not_stop_the_rest_of_the_batch() -> None:
    first, second = event(), event()
    drain = FakeDrain([first, second])

    async def handle(incoming: OutboxEvent) -> str:
        if incoming.id == first.id:
            raise RuntimeError("boom")
        return "ok"

    await consumer_over(drain, {HANDLED_TYPE: handle})()

    assert drain.processed == [second.id]
    assert [event_id for event_id, _ in drain.failures] == [first.id]
    assert "RuntimeError: boom" in drain.failures[0][1]


@pytest.mark.asyncio
async def test_backlog_gauges_report_what_the_batch_size_left_behind() -> None:
    """Ops hardening Phase 5: `batch_size=1` claims only one of two, so the
    gauge must report the one left over — not zero, and not two.
    """
    older, newer = event(), event()
    drain = FakeDrain([older, newer])
    telemetry = RecordingTelemetry()
    consume = build_outbox_consumer(
        drain,  # type: ignore[arg-type]
        {HANDLED_TYPE: lambda _: _ok()},
        batch_size=1,
        tenants_per_tick=8,
        max_attempts=2,
        telemetry=telemetry,
        clock=FixedClock(NOW + timedelta(minutes=5)),
    )

    await consume()

    assert len(drain.processed) == 1
    [(_, size, _)] = [g for g in telemetry.gauges if g[0] == DW_OUTBOX_BACKLOG_SIZE]
    assert size == 1
    [(_, age, _)] = [g for g in telemetry.gauges if g[0] == DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS]
    assert age == 300.0


@pytest.mark.asyncio
async def test_backlog_gauges_report_zero_age_when_nothing_is_pending() -> None:
    one = event()
    drain = FakeDrain([one])
    telemetry = RecordingTelemetry()
    consume = build_outbox_consumer(
        drain,  # type: ignore[arg-type]
        {HANDLED_TYPE: lambda _: _ok()},
        batch_size=5,
        tenants_per_tick=8,
        max_attempts=2,
        telemetry=telemetry,
        clock=FixedClock(NOW + timedelta(hours=1)),
    )

    await consume()

    assert drain.processed == [one.id]
    [(_, size, _)] = [g for g in telemetry.gauges if g[0] == DW_OUTBOX_BACKLOG_SIZE]
    assert size == 0
    [(_, age, _)] = [g for g in telemetry.gauges if g[0] == DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS]
    assert age == 0.0


async def _ok() -> str:
    return "ok"


# ---------------------------------------------------------------------------
# What this host refuses to wire.
# ---------------------------------------------------------------------------


def test_the_dispatcher_still_owns_no_handlers_of_its_own() -> None:
    """The deletion, asserted rather than trusted to review.

    ``build_handlers`` — the registry that switched effects on and off as a set
    — and the auto-research effect on a created account are still gone. The
    dispatcher stays a dispatcher: a caller passes it the handlers it wants, so
    turning an effect on is a visible code change at a composition root rather
    than a boolean somebody flips on a production host.
    """
    import dw_worker.consumers.outbox as module

    for gone in ("build_handlers", "build_account_created_handler"):
        assert not hasattr(module, gone), f"{gone} is back; the auto effect was deleted on purpose"


# ---------------------------------------------------------------------------
# runtime-hardening R10.6: the rotation's cursor goes from claim to claim.
# ---------------------------------------------------------------------------


def event_of(tenant: uuid.UUID) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(tenant),
        workspace_id=WorkspaceId(WORKSPACE),
        event_type=HANDLED_TYPE,
        schema_version="1.0",
        aggregate_id=AGGREGATE,
        occurred_at=NOW,
        payload={},
        actor_id=ACTOR,
    )


@pytest.mark.asyncio
async def test_the_dispatcher_hands_the_rotation_cursor_to_the_next_claim() -> None:
    first, second, third = sorted(uuid.uuid4() for _ in range(3))
    drain = FakeDrain([event_of(t) for t in (first, second, third) for _ in range(2)])
    consume = build_outbox_consumer(
        drain,  # type: ignore[arg-type]
        {HANDLED_TYPE: lambda event: _noted()},
        batch_size=1,
        tenants_per_tick=2,
        max_attempts=2,
        telemetry=RecordingTelemetry(),
        clock=FixedClock(NOW),
    )
    await consume()
    await consume()
    assert drain.cursors == [None, second]


async def _noted() -> str:
    return "noted"
