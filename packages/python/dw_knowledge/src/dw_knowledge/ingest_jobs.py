"""Durable ingest-job queue (B5).

The API ``enqueue``s a job (raw file already in object storage) and returns 202;
the worker ``claim_next``s one, runs parse→chunk→embed→index via the gateway, then
``mark_done``/``mark_failed``. Tenant isolation is enforced by RLS: enqueue/get run
under ``app.tenant_id``; the cross-tenant drain scan runs under ``app.worker_drain``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge import tables
from dw_knowledge.contracts import SEARCH_FILTER_KEYS
from dw_platform.application.access_context import AccessContext

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_WORKER_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")

# How long a claim is held before another worker may take the job back. This is
# a LIVENESS window, not a work budget: the consumer renews it on a heartbeat
# while it is still working, so the job may run far longer than one lease and a
# worker that is killed still loses its claim within one lease rather than
# holding the file hostage for the whole budget.
#
# Sizing a one-shot lease for the slowest possible job was the earlier design,
# and it forced the two numbers into an invariant - timeout < lease - that
# capped every upload at the shortest lease anybody was willing to wait out. A
# customer meeting runs three or four hours; that cap made those unprocessable.
DEFAULT_LEASE_SECONDS = 900

# How often the consumer pushes the lease forward. A third of the lease, so two
# consecutive misses - a slow database, a container paused by the scheduler -
# still leave a third of the window to recover in before another worker treats
# the job as abandoned.
DEFAULT_HEARTBEAT_SECONDS = 300.0

# The worker gives up on a job at this point, and this is the number that bounds
# real work. Sized for the longest genuine input: a four-hour meeting recording
# is roughly 230MB at 128kbps stereo, which is a few minutes to send to the
# transcription API, about ten for it to transcribe at ~30x realtime, and then
# chunking and embedding a fifty-thousand-word transcript. Forty-five minutes is
# that with room to spare.
DEFAULT_JOB_TIMEOUT_SECONDS = 2700.0

# Long enough that a provider hiccup has passed, short enough that a user
# watching the upload sees it finish: 30s, 60s, 120s across the default three
# attempts.
DEFAULT_RETRY_BACKOFF_SECONDS = 30

# The error column is Text; the cap keeps one pathological provider traceback
# from making the row unreadable in a status list.
_MAX_ERROR_CHARS = 2000


class EnqueueIngestCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = "application/octet-stream"
    # See identity.py. A queue caller that files documents against records must
    # set this, or two records with a same-named file collapse into one document.
    identity_key: str | None = Field(default=None, min_length=1)
    domain: str = "shared"
    classification: str = "internal"
    source_version: str = "1"
    scope: str = "tenant"
    # Carried through the queue so the worker can hand the same business
    # metadata to IngestDocumentCommand; same whitelist, same reason.
    extra: tuple[tuple[str, str], ...] = ()
    # Who may retrieve the result. The queue had no way to narrow this, so every
    # document the worker produced was readable by the whole tenant regardless
    # of what the uploader could see.
    acl_principals: tuple[str, ...] = ("tenant:*",)

    @field_validator("extra")
    @classmethod
    def _extra_keys_are_whitelisted(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        unknown = sorted({key for key, _ in value} - SEARCH_FILTER_KEYS)
        if unknown:
            raise ValueError(
                f"unknown ingest metadata key(s): {unknown}. Allowed: {sorted(SEARCH_FILTER_KEYS)}"
            )
        return value


@dataclass(frozen=True)
class IngestJob:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    created_by: uuid.UUID
    title: str
    identity_key: str | None
    domain: str
    classification: str
    source_version: str
    scope: str
    filename: str
    content_type: str
    storage_key: str
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_until: datetime | None
    error: str | None
    document_id: uuid.UUID | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime
    extra: tuple[tuple[str, str], ...] = ()
    acl_principals: tuple[str, ...] = ("tenant:*",)
    # Non-empty on a job that finished with something to say about the file -
    # today only `extraction_incomplete`, from a parser that read part of it.
    warnings: tuple[str, ...] = ()


def _row_to_job(row: sa.Row[Any]) -> IngestJob:
    return IngestJob(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        created_by=row.created_by,
        title=row.title,
        identity_key=row.identity_key,
        domain=row.domain,
        classification=row.classification,
        source_version=row.source_version,
        scope=row.scope,
        filename=row.filename,
        content_type=row.content_type,
        storage_key=row.storage_key,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        available_at=row.available_at,
        lease_until=row.lease_until,
        error=row.error,
        document_id=row.document_id,
        chunk_count=row.chunk_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
        extra=tuple((key, str(value)) for key, value in (row.extra or {}).items()),
        acl_principals=tuple(row.acl_principals or ()),
        warnings=tuple(row.warnings or ()),
    )


@dataclass
class IngestJobStore:
    """CRUD over ``knowledge.ingest_jobs`` with RLS-correct tenant context.

    Every method runs under one tenant's ``app.tenant_id``. The cross-tenant
    claim is ``IngestJobQueue``'s, a class of its own because it sets the drain:
    the API builds this store to enqueue, and only the worker builds the queue
    (foundations-hardening R2.6).
    """

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    id_generator: IdGenerator
    retry_backoff_seconds: float = field(default=DEFAULT_RETRY_BACKOFF_SECONDS)

    async def enqueue(
        self,
        command: EnqueueIngestCommand,
        context: AccessContext,
        *,
        storage_key: str,
        job_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        job_id = job_id or self.id_generator.new_uuid()
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            await session.execute(
                sa.insert(tables.ingest_jobs).values(
                    id=job_id,
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    created_by=context.principal_id,
                    title=command.title,
                    identity_key=command.identity_key,
                    domain=command.domain,
                    classification=command.classification,
                    source_version=command.source_version,
                    scope=command.scope,
                    filename=command.filename,
                    content_type=command.content_type,
                    storage_key=storage_key,
                    status="queued",
                    attempts=0,
                    # From the injected clock, not the column default: the claim
                    # predicate compares this against the same clock, and one
                    # column written by two clocks makes claim order depend on
                    # skew between the app host and the database.
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                    extra=dict(command.extra),
                    acl_principals=list(command.acl_principals),
                )
            )
        return job_id

    async def get(self, job_id: uuid.UUID, context: AccessContext) -> IngestJob | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            row = (
                await session.execute(
                    sa.select(tables.ingest_jobs).where(tables.ingest_jobs.c.id == job_id)
                )
            ).one_or_none()
            return _row_to_job(row) if row is not None else None

    async def latest_for_sources(
        self, source_versions: Sequence[str], context: AccessContext
    ) -> dict[str, uuid.UUID]:
        """The newest job per `source_version`, for a batch of them.

        A caller that holds a record and wants to know whether the file behind
        it was ever read has only the record's own id: the job id is returned
        once, at enqueue, and nothing persists it. Re-uploading the same name
        supersedes the previous job under the same identity key, so "newest per
        source" is the answer rather than "the one job".

        Batched because the caller is a list screen; one query per row would be
        a page of round trips to say "still reading".
        """
        wanted = [str(item) for item in source_versions if item]
        if not wanted:
            return {}
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            rows = (
                await session.execute(
                    sa.select(
                        tables.ingest_jobs.c.source_version,
                        tables.ingest_jobs.c.id,
                    )
                    .where(tables.ingest_jobs.c.source_version.in_(wanted))
                    .order_by(
                        tables.ingest_jobs.c.source_version,
                        tables.ingest_jobs.c.created_at.desc(),
                    )
                )
            ).all()
        newest: dict[str, uuid.UUID] = {}
        for source_version, job_id in rows:
            newest.setdefault(str(source_version), job_id)
        return newest

    async def renew_lease(
        self, job: IngestJob, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> bool:
        """Push this job's lease forward while the worker is still on it.

        The whole reason a long job is safe: `claim_next` treats a lapsed lease
        as an abandoned job, so without this a four-hour transcription would be
        claimed a second time fifteen minutes in and the file transcribed twice.

        False means the row is no longer ours to renew - it has been settled, or
        a worker that stalled past its lease had the job reclaimed underneath it.
        `attempts` is what tells those apart: `claim_next` increments it on every
        claim, so a renewal carrying the count this worker was handed matches
        only while this worker still owns the row. Without that predicate a woken
        stalled worker would push the NEW owner's lease forward, and the job
        would be held open for ever by two workers each sure it was theirs.
        """
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(job.tenant_id)})
            renewed = (
                await session.execute(
                    sa.update(tables.ingest_jobs)
                    .where(
                        tables.ingest_jobs.c.id == job.id,
                        tables.ingest_jobs.c.status == "processing",
                        tables.ingest_jobs.c.attempts == job.attempts,
                    )
                    .values(lease_until=now + timedelta(seconds=lease_seconds), updated_at=now)
                    .returning(tables.ingest_jobs.c.id)
                )
            ).one_or_none()
        return renewed is not None

    async def mark_done(
        self,
        job: IngestJob,
        *,
        document_id: uuid.UUID,
        chunk_count: int,
        warnings: tuple[str, ...] = (),
    ) -> None:
        """Finished. `warnings` is what to tell a person about a file that was
        read but not read whole - the job succeeded, so `error` is the wrong
        column for it and `status` stays `done`."""
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(job.tenant_id)})
            await session.execute(
                sa.update(tables.ingest_jobs)
                .where(tables.ingest_jobs.c.id == job.id)
                .values(
                    status="done",
                    document_id=document_id,
                    chunk_count=chunk_count,
                    error=None,
                    warnings=list(warnings),
                    lease_until=None,
                    updated_at=self.clock.now(),
                )
            )

    async def mark_failed(self, job: IngestJob, *, error: str) -> None:
        """Put the job back in the queue, or give up once its attempts run out.

        Failure used to be terminal on the first try, which made every transient
        provider timeout a permanently broken upload that only a human re-upload
        could fix.
        """
        now = self.clock.now()
        exhausted = job.attempts >= job.max_attempts
        values: dict[str, Any] = {
            "error": error[:_MAX_ERROR_CHARS],
            "lease_until": None,
            "updated_at": now,
        }
        if exhausted:
            values["status"] = "failed"
        else:
            values["status"] = "queued"
            values["available_at"] = now + self._backoff(job.attempts)

        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(job.tenant_id)})
            await session.execute(
                sa.update(tables.ingest_jobs)
                .where(tables.ingest_jobs.c.id == job.id)
                .values(**values)
            )

    def _backoff(self, attempts: int) -> timedelta:
        """Exponential, so a provider that is rate-limiting us is not hammered."""
        return timedelta(seconds=self.retry_backoff_seconds * (2 ** (attempts - 1)))


@dataclass
class IngestJobQueue:
    """The worker's claim of the next job across every tenant, under the drain."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock

    async def claim_next(self, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> IngestJob | None:
        """Take the next claimable job, hold it under a lease, and return it.

        Claimable means queued and due, OR already processing under a lease that
        has expired. Without that second arm a worker killed mid-job left its row
        in ``processing`` for ever: nothing ever selected it again, and the file
        the user uploaded simply never finished, with no error to show them.

        ``FOR UPDATE SKIP LOCKED`` keeps concurrent workers off the same row. The
        cross-tenant scan is authorised by the ``app.worker_drain`` GUC; the
        claiming UPDATE runs under the job's own ``app.tenant_id``.
        """
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_WORKER_DRAIN)
            claimable = sa.or_(
                sa.and_(
                    tables.ingest_jobs.c.status == "queued",
                    tables.ingest_jobs.c.available_at <= now,
                ),
                sa.and_(
                    tables.ingest_jobs.c.status == "processing",
                    tables.ingest_jobs.c.lease_until.is_not(None),
                    tables.ingest_jobs.c.lease_until < now,
                ),
            )
            row = (
                await session.execute(
                    sa.select(tables.ingest_jobs)
                    .where(claimable)
                    .order_by(tables.ingest_jobs.c.available_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).one_or_none()
            if row is None:
                return None
            # The claiming UPDATE must satisfy tenant_isolation → set app.tenant_id.
            await session.execute(_SET_TENANT, {"tenant_id": str(row.tenant_id)})
            # RETURNING, so the caller sees the state it is actually working in.
            # Returning the pre-update row reported the job as still queued and
            # its attempt count one short, and mark_failed reads that count to
            # decide whether anything is left to retry.
            claimed = (
                await session.execute(
                    sa.update(tables.ingest_jobs)
                    .where(tables.ingest_jobs.c.id == row.id)
                    .values(
                        status="processing",
                        attempts=row.attempts + 1,
                        lease_until=now + timedelta(seconds=lease_seconds),
                        updated_at=now,
                    )
                    .returning(tables.ingest_jobs)
                )
            ).one()
            return _row_to_job(claimed)
