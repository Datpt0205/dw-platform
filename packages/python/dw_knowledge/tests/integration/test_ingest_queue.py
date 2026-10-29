"""Lease and retry on the ingest queue, against real Postgres.

Written against the database rather than a fake because every rule here is
expressed in SQL - the claim predicate, `FOR UPDATE SKIP LOCKED`, and the RLS
policies the drain scan has to satisfy. A fake would assert that the Python
reads the way it was written, which is not the thing that was broken.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from runtime_harness import RuntimeUrls
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.ports import IdGenerator, UtcClock, Uuid4Generator
from dw_knowledge.ingest_jobs import EnqueueIngestCommand, IngestJobQueue, IngestJobStore
from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.integration

TENANT = uuid.UUID(int=0xDD00)
WORKSPACE = uuid.UUID(int=0xDD01)
NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)

ContextFactory = Callable[..., AccessContext]


class MovableClock(UtcClock):
    """Time has to move for a lease to expire; sleeping for it is not a test."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@pytest.fixture
async def queue(
    urls: RuntimeUrls,
) -> AsyncIterator[tuple[IngestJobStore, IngestJobQueue, MovableClock]]:
    # The table is emptied per test on purpose: claim_next scans across tenants
    # by design, so a job another test left behind is a job this one can claim.
    # Truncating runs as the migrator, the only role allowed past RLS.
    migrator = create_async_engine(urls.migrator, poolclass=NullPool)
    async with migrator.begin() as connection:
        await connection.execute(sa.text("TRUNCATE knowledge.ingest_jobs"))
    await migrator.dispose()

    engine = create_async_engine(urls.app, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    clock = MovableClock(NOW)
    ids: IdGenerator = Uuid4Generator()
    yield (
        IngestJobStore(
            session_factory=sessions,
            clock=clock,
            id_generator=ids,
            retry_backoff_seconds=30.0,
        ),
        IngestJobQueue(session_factory=sessions, clock=clock),
        clock,
    )
    await engine.dispose()


def _command(title: str) -> EnqueueIngestCommand:
    return EnqueueIngestCommand(title=title, filename=f"{title}.pdf")


async def _enqueue(store: IngestJobStore, context: AccessContext, title: str) -> uuid.UUID:
    return await store.enqueue(_command(title), context, storage_key=f"uploads/{title}")


async def test_a_stranded_job_is_reclaimed_once_its_lease_expires(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    """The crash case. Nothing used to select a row left in `processing`.

    A worker killed between claim and mark left the user's upload unfinished
    for ever, with no error anywhere to explain it.
    """
    store, claims, clock = queue
    context = make_context(TENANT, WORKSPACE)
    job_id = await _enqueue(store, context, "stranded")

    claimed = await claims.claim_next(lease_seconds=60)
    assert claimed is not None and claimed.id == job_id
    assert claimed.status == "processing", "the caller must see the state it works in"
    assert claimed.attempts == 1, "attempts must be post-increment, mark_failed reads it"

    # The worker dies here. While the lease holds, nobody else may take it.
    clock.advance(30)
    assert await claims.claim_next(lease_seconds=60) is None

    clock.advance(31)
    reclaimed = await claims.claim_next(lease_seconds=60)
    assert reclaimed is not None and reclaimed.id == job_id
    assert reclaimed.attempts == 2


async def test_a_four_hour_recording_keeps_its_claim_past_the_lease(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    """The use case that broke the old design: a customer meeting runs hours.

    The lease is a liveness window, not a work budget. A job that renews it on a
    heartbeat may run far longer than one lease, and a second worker must not be
    able to claim it however long that takes - two workers on one recording means
    the same file transcribed and billed twice.
    """
    store, claims, clock = queue
    context = make_context(TENANT, WORKSPACE)
    job_id = await _enqueue(store, context, "four-hour-meeting")

    claimed = await claims.claim_next(lease_seconds=60)
    assert claimed is not None and claimed.id == job_id

    # Four hours of work, beating every 20 seconds against a 60 second lease.
    for _ in range(4 * 60 * 3):
        clock.advance(20)
        assert await store.renew_lease(claimed, lease_seconds=60) is True
        assert await claims.claim_next(lease_seconds=60) is None, "nobody else may take it"

    await store.mark_done(claimed, document_id=uuid.uuid4(), chunk_count=512)
    assert await claims.claim_next(lease_seconds=60) is None, "a finished job is not claimable"


async def test_a_beat_that_arrives_after_the_job_was_taken_says_so(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    """False is the signal the worker stops beating on.

    A worker that paused long enough to lose its lease must not keep pushing the
    row forward under the new owner - that would hold the job open for ever with
    two workers each believing it is theirs.
    """
    store, claims, clock = queue
    context = make_context(TENANT, WORKSPACE)
    await _enqueue(store, context, "stolen")

    first = await claims.claim_next(lease_seconds=60)
    assert first is not None

    clock.advance(61)
    second = await claims.claim_next(lease_seconds=60)
    assert second is not None and second.id == first.id, "the lapsed lease was reclaimed"

    # The stalled worker wakes up. The row is still `processing` and still has
    # its id, so only the attempt count can tell it the job moved on.
    assert await store.renew_lease(first, lease_seconds=60) is False, "it is not ours any more"
    assert await store.renew_lease(second, lease_seconds=60) is True, "it is the new owner's"

    await store.mark_done(second, document_id=uuid.uuid4(), chunk_count=1)
    assert await store.renew_lease(second, lease_seconds=60) is False, "a settled job is nobody's"


async def test_a_failure_is_retried_until_the_budget_runs_out(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    """Failure used to be terminal on the first attempt.

    One transient provider timeout permanently broke an upload that a retry
    seconds later would have completed.
    """
    store, claims, clock = queue
    context = make_context(TENANT, WORKSPACE)
    job_id = await _enqueue(store, context, "flaky")

    for attempt in range(1, 4):
        claimed = await claims.claim_next(lease_seconds=60)
        assert claimed is not None, f"attempt {attempt} should have been claimable"
        assert claimed.attempts == attempt
        await store.mark_failed(claimed, error="provider timed out")
        # Backoff is exponential, so time must pass before the next attempt.
        clock.advance(30 * 2**attempt)

    assert await claims.claim_next(lease_seconds=60) is None, "the budget is spent"
    settled = await store.get(job_id, context)
    assert settled is not None
    assert settled.status == "failed"
    assert settled.error == "provider timed out"


async def test_a_retry_waits_for_its_backoff(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    """Otherwise a failing job spins against the provider that just refused it."""
    store, claims, clock = queue
    context = make_context(TENANT, WORKSPACE)
    await _enqueue(store, context, "backoff")

    claimed = await claims.claim_next(lease_seconds=60)
    assert claimed is not None
    await store.mark_failed(claimed, error="rate limited")

    assert await claims.claim_next(lease_seconds=60) is None, "not due yet"
    clock.advance(31)
    assert await claims.claim_next(lease_seconds=60) is not None


async def test_two_workers_never_claim_the_same_job(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    store, claims, _clock = queue
    context = make_context(TENANT, WORKSPACE)
    first_id = await _enqueue(store, context, "one")
    second_id = await _enqueue(store, context, "two")

    first = await claims.claim_next(lease_seconds=60)
    second = await claims.claim_next(lease_seconds=60)
    assert first is not None and second is not None
    assert {first.id, second.id} == {first_id, second_id}
    assert await claims.claim_next(lease_seconds=60) is None


async def test_a_done_job_releases_its_lease(
    queue: tuple[IngestJobStore, IngestJobQueue, MovableClock], make_context: ContextFactory
) -> None:
    """A finished job must not be reclaimable, however long the process lives."""
    store, claims, clock = queue
    context = make_context(TENANT, WORKSPACE)
    await _enqueue(store, context, "finished")

    claimed = await claims.claim_next(lease_seconds=60)
    assert claimed is not None
    await store.mark_done(claimed, document_id=uuid.uuid4(), chunk_count=3)

    clock.advance(3600)
    assert await claims.claim_next(lease_seconds=60) is None

    settled = await store.get(claimed.id, context)
    assert settled is not None and settled.status == "done"
    assert settled.lease_until is None
