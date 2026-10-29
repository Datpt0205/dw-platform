"""Knowledge ingest consumer: drains the durable upload queue (B5).

Per tick: claim due jobs → fetch the staged bytes → parse (an API call for
everything but plaintext) → hand the extracted text to the gateway (chunk →
embed → index) → mark done, or requeue with backoff until the budget is spent.

A finished job is also the moment a file on a CRM record stops being bytes and
starts being something that can be quoted. That is the news the lead scorer
waits for, and this is the only place in the system that knows it happened -
which is why the announcement lives at the end of this lane rather than at the
upload, tens of seconds earlier, when nothing could yet be read.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from dw_knowledge.gateway import IngestDocumentCommand
from dw_knowledge.ingest_jobs import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_JOB_TIMEOUT_SECONDS,
    DEFAULT_LEASE_SECONDS,
    IngestJob,
)
from dw_platform.application.access_context import AccessContext
from dw_worker.composition import IngestComponents

logger = logging.getLogger("dw_worker.ingest")


def _context_for(job: IngestJob) -> AccessContext:
    # A system context scoped to the job's tenant/workspace. The gateway only
    # uses tenant/workspace/principal for storage keys + RLS; no scopes needed.
    return AccessContext(
        tenant_id=job.tenant_id,
        workspace_id=job.workspace_id,
        principal_id=job.created_by,
        roles=frozenset({"system"}),
        scopes=frozenset(),
        clearance="internal",
        plan_id="system",
    )


async def _process(job: IngestJob, components: IngestComponents) -> None:
    data = await components.object_storage.get_object(job.storage_key)
    parsed = await components.parser.parse(data, job.content_type, job.filename)
    if not parsed.text.strip():
        # The one sentence a person reads on the file row, so it says what the
        # file is rather than what the code did: an empty parse means either an
        # unreadable file or one the reader had to give up on, and both leave
        # the user with the same next move.
        raise ValueError("the file has no text that could be read out of it")
    result = await components.gateway.ingest_document(
        IngestDocumentCommand(
            title=job.title,
            content=parsed.text,
            # Dropping this here would undo the whole point of setting it at
            # enqueue: the document would fall back to title-keyed identity and
            # overwrite whatever else shares its name.
            identity_key=job.identity_key,
            domain=job.domain,
            classification=job.classification,
            source_version=job.source_version,
            content_type="text/markdown",
            scope=job.scope,
            # Metadata set at enqueue reaches the document and its vector
            # payload; losing it here would leave the chunks unfilterable.
            extra=job.extra,
            acl_principals=job.acl_principals,
        ),
        _context_for(job),
    )
    # The parser's warnings travel with the job. `extraction_incomplete` has
    # been produced since the gateway parser shipped and read by nobody, so a
    # document that stops halfway was indexed exactly like a whole one and every
    # later answer about the missing half was "not in the file".
    await components.job_store.mark_done(
        job,
        document_id=result.document_id,
        chunk_count=result.chunk_count,
        warnings=parsed.warnings,
    )
    logger.info(
        "ingested job=%s document=%s chunks=%d", job.id, result.document_id, result.chunk_count
    )


def build_ingest_consumer(
    components: IngestComponents,
    *,
    batch_size: int = 1,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    job_timeout_seconds: float = DEFAULT_JOB_TIMEOUT_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> Callable[[], Awaitable[None]]:
    """Return a consumer callable draining up to ``batch_size`` jobs per tick.

    The jobs run concurrently, not one after another. Sequentially, a single slow
    file - a long recording waiting on a remote transcription API - held the only
    worker task and every other tenant's uploads queued behind it.

    A job may outlive its lease many times over: a four-hour customer meeting is
    a real recording, and the budget for one is measured in tens of minutes. What
    keeps a second worker off it is the heartbeat below, not a lease long enough
    to cover the worst case - a lease that long would also mean a killed worker
    strands the file for that long.
    """
    if heartbeat_seconds >= lease_seconds:
        # The invariant that replaced "timeout < lease". A heartbeat slower than
        # the lease renews nothing: the lease lapses between beats, a second
        # worker claims the job, and the same file is parsed and billed twice.
        raise ValueError("heartbeat_seconds must be shorter than lease_seconds")

    async def _beat(job: IngestJob) -> None:
        """Hold the claim until the work is done or this task is cancelled."""
        while True:
            await asyncio.sleep(heartbeat_seconds)
            if not await components.job_store.renew_lease(job, lease_seconds=lease_seconds):
                # Somebody else owns the row now. Stop beating and say so; the
                # work in flight is theirs to finish, not ours to abandon.
                logger.warning("ingest job %s lost its lease while running", job.id)
                return

    async def drain_one() -> None:
        job = await components.job_queue.claim_next(lease_seconds=lease_seconds)
        if job is None:
            return
        beat = asyncio.create_task(_beat(job))
        try:
            await asyncio.wait_for(_process(job, components), timeout=job_timeout_seconds)
        except TimeoutError:
            logger.warning("ingest job %s timed out after %ss", job.id, job_timeout_seconds)
            await components.job_store.mark_failed(
                job, error=f"job exceeded {job_timeout_seconds}s"
            )
        except Exception as exc:  # record failure, keep draining the queue
            logger.exception("ingest job %s failed", job.id)
            await components.job_store.mark_failed(job, error=f"{type(exc).__name__}: {exc}")
        finally:
            beat.cancel()

    async def consume() -> None:
        await asyncio.gather(*(drain_one() for _ in range(batch_size)))

    return consume
