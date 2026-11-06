"""Outbox dispatcher: turn a committed domain event into the effect it announced.

Per tick: claim a batch of undelivered events of the types this process knows how
to handle, run each one's effect, and mark it delivered. Delivery is at-least-once
- the attempt is counted at claim time and the row is marked afterwards - so every
handler wired here has to be idempotent.

**No effect is wired today, deliberately.** Research-on-account-created and
re-score-on-lead-evidence both used to live here, and both were removed rather
than switched off: an event says what happened, never who caused it, so a
A bulk import announced 1,666 created records exactly as loudly as a
salesperson typing one name, and each announcement bought a paid search call.
Both effects remain available on demand through their own endpoints, and lead
scoring now starts when someone opens the lead. A setting would have left the
backlog one boolean away from running; deleting the handlers means turning it
back on is a code change, reviewed like one.

An event whose type has no handler is not claimed at all, so the events the CRM
keeps announcing accumulate unread rather than being drained into nothing - a
handler added later finds its history intact instead of a table of rows already
marked delivered. To wire one, pass ``{EVENT_TYPE: handler}`` to
``build_outbox_consumer`` from ``dw_worker.main``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping

from dw_kernel.ports import UtcClock
from dw_observability.metrics import (
    DW_OUTBOX_BACKLOG_SIZE,
    DW_OUTBOX_DEAD_LETTERS,
    DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS,
)
from dw_observability.telemetry import TelemetryPort
from dw_platform.application.ports import OutboxDrainPort
from dw_platform.domain.outbox import OutboxEvent

logger = logging.getLogger("dw_worker.outbox")

EventHandler = Callable[[OutboxEvent], Awaitable[str]]
"""Deliver one event and say in a few words what it did, for the log."""

_ERROR_LIMIT = 500


class UndeliverableEventError(Exception):
    """The event cannot be delivered as written, and retrying will not help."""


async def _deliver(
    event: OutboxEvent, handler: EventHandler, drain: OutboxDrainPort, max_attempts: int
) -> None:
    try:
        outcome = await handler(event)
    except UndeliverableEventError as exc:
        # A retry cannot fix the event itself: it is given up on at once, with
        # its reason, instead of spending every attempt (runtime-hardening R10.2).
        logger.error("outbox event %s (%s) is undeliverable: %s", event.id, event.event_type, exc)
        await drain.record_failure(
            event.id,
            error=str(exc)[:_ERROR_LIMIT],
            max_attempts=max_attempts,
            undeliverable=True,
        )
        return
    except Exception as exc:
        logger.exception("outbox event %s (%s) failed", event.id, event.event_type)
        await drain.record_failure(
            event.id,
            error=f"{type(exc).__name__}: {exc}"[:_ERROR_LIMIT],
            max_attempts=max_attempts,
        )
        return
    await drain.mark_processed(event.id)
    logger.info("outbox event %s (%s): %s", event.id, event.event_type, outcome)


def build_outbox_consumer(
    drain: OutboxDrainPort,
    handlers: Mapping[str, EventHandler],
    *,
    batch_size: int,
    tenants_per_tick: int,
    max_attempts: int,
    telemetry: TelemetryPort,
    clock: UtcClock,
) -> Callable[[], Awaitable[None]]:
    """Return a consumer that dispatches, each tick, at most ``batch_size``
    events of each of at most ``tenants_per_tick`` companies, taken in turn
    (runtime-hardening R10.6): the rotation's cursor lives in this closure,
    handed to each claim and moved to the ``last_tenant`` it returns. It lives
    only in this process: a restart begins the rotation again, and R10.6's
    bound still holds.

    Reports backlog size and the oldest pending event's age every tick, for
    the same ``event_types`` this process actually claims — an event type
    nobody handles here is correctly invisible to both, the same as it is to
    ``claim_batch``.
    """
    event_types = sorted(handlers)

    after_tenant: uuid.UUID | None = None

    async def consume() -> None:
        nonlocal after_tenant
        claimed = await drain.claim_batch(
            event_types=event_types,
            per_tenant_limit=batch_size,
            tenant_limit=tenants_per_tick,
            max_attempts=max_attempts,
            after_tenant=after_tenant,
        )
        after_tenant = claimed.last_tenant
        for event in claimed.events:
            await _deliver(event, handlers[event.event_type], drain, max_attempts)

        backlog = await drain.backlog(event_types=event_types)
        telemetry.set_gauge(DW_OUTBOX_BACKLOG_SIZE, backlog.pending, {})
        telemetry.set_gauge(DW_OUTBOX_DEAD_LETTERS, backlog.dead, {})
        age_seconds = (
            (clock.now() - backlog.oldest_pending_at).total_seconds()
            if backlog.oldest_pending_at is not None
            else 0.0
        )
        telemetry.set_gauge(DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS, age_seconds, {})

    return consume
