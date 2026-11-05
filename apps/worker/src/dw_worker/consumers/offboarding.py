"""Tenant offboarding lane: claim a request, export, purge, report back.

The Postgres half (`SqlTenantOffboarding` in `dw_platform`) is catalog-driven
and knows nothing about Qdrant or object storage — both live behind ports
`dw_platform` may not import (import-linter's "Vector/object-storage SDKs
only inside knowledge adapters"). This is the composition root, so it is the
one place allowed to hold both halves at once: the generic Postgres rows, the
storage buckets and the two vector collections (knowledge chunks and the memory
ranker's points), orchestrated into one pass.

The bundle is written to an anonymous temporary file batch by batch and blob by
blob, then uploaded in parts (foundations-hardening R11.9): the lane holds one
batch of rows or one blob at a time, whatever the company's size. Discovery 09
measured the bundle built in memory at 9,143 bytes of peak per record, so a 1 GiB
worker was OOM-killed from about 95,000 records.

A pass has two phases, and the request row says which one it reached. Before
`purging` nothing is deleted, so a failure there is `failed`, for a person to
look at, and a dead worker's request is claimed again from the top under the
same `export_key` (one bundle per request, R11.18). From `purging` on, the
bundle is uploaded and the SQL purge may have committed: a failure keeps the
request `purging` with its error (R11.11), and the next claim resumes at the
purge with the same key instead of exporting an emptied company (R11.10). Every
step of the purge phase is safe to repeat: `purge_rows` deletes rows that may
already be gone, `delete_object`/`delete_by_tenant` delete what may already be
gone (and a store never created holds nothing, `ABSENT_STORE_RULE`), and the
second purge writes no second audit row (no workspace is left to write it
against). A live pass keeps its claim fresh (R11.17) so only a dead worker's
request is claimed again, and stops if it cannot (R11.19).
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import zipfile
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import IO, Any, BinaryIO, Protocol
from uuid import UUID

logger = logging.getLogger("dw_worker.offboarding")

# Not latency-sensitive - an operator just clicked a button that starts a
# process with a human on the other end of it, not a request waiting on a
# response. Five minutes keeps the poll cheap without keeping anyone wondering
# why nothing happened for the length of a coffee break.
INTERVAL_SECONDS = 300.0

# How often a live pass refreshes its claim (R11.17): one sixth of the
# platform's 30-minute stale window (`_STALE_CLAIM_MINUTES`), so two misses in
# a row still leave a third of the window before another worker may claim it.
HEARTBEAT_SECONDS = 300.0
_MISSED_HEARTBEATS = 2


class _ExportedTable(Protocol):
    """Structurally `dw_platform`'s `ExportedTable` — a frozen dataclass, so
    read-only properties here rather than plain attributes: a Protocol's
    plain attribute is implicitly settable, which a frozen dataclass can
    never satisfy no matter how exactly its field types match."""

    @property
    def schema(self) -> str: ...
    @property
    def table(self) -> str: ...
    @property
    def rows(self) -> list[dict[str, Any]]: ...


class _Claim(Protocol):
    """Structurally `dw_platform`'s `OffboardingClaim`."""

    @property
    def tenant_id(self) -> UUID: ...
    @property
    def request_id(self) -> UUID: ...
    @property
    def resume_export_key(self) -> str | None: ...


class OffboardingStorePort(Protocol):
    """Structurally `SqlTenantOffboarding` - declared here rather than
    imported, the same way every other consumer in this package names only
    the method it calls (see `reaper.py`'s `StaleReaperPort`)."""

    async def claim_requested(self) -> Sequence[_Claim]: ...

    def export_rows(self, tenant_id: UUID) -> AsyncIterator[_ExportedTable]: ...

    async def purge_rows(self, tenant_id: UUID) -> None: ...

    async def keep_claim(self, tenant_id: UUID) -> None: ...

    async def mark_status(
        self,
        tenant_id: UUID,
        status: str,
        *,
        export_key: str | None = None,
        error: str | None = None,
    ) -> None: ...


class BucketPort(Protocol):
    """Structurally the read-and-delete half of `dw_knowledge.ports.ObjectStoragePort`,
    one instance per bucket the lane empties (knowledge artifacts, feedback
    attachments). `dw_knowledge`'s adapter, pointed at each bucket in turn, is the
    one this lane uses; `dw_api`'s `MinioAttachmentStorage` does the same under
    other names, and reusing it would make `dw_worker` depend on `dw_api`, which
    this composition root does not do for anything else."""

    async def get_object(self, key: str) -> bytes: ...

    async def list_objects(self, prefix: str) -> list[str]: ...

    async def delete_object(self, key: str) -> None: ...


class ExportSinkPort(Protocol):
    """The export bucket: a bundle too large to hold is uploaded from a file, in
    parts (R11.9), and a resumed pass asks whether its bundle is still there
    before it deletes anything (R11.10). Structurally
    `MinioObjectStorageAdapter`; `ObjectStoragePort` has no caller that streams."""

    async def put_stream(self, key: str, data: BinaryIO, length: int, content_type: str) -> str: ...

    async def has_object(self, key: str) -> bool: ...


class VectorPurgePort(Protocol):
    """Structurally `dw_knowledge.ports.VectorIndexPort.delete_by_tenant`, and
    `dw_memory.ranking.MemoryVectorPurgePort.delete_by_tenant`."""

    async def delete_by_tenant(self, tenant_id: UUID) -> None: ...


class PurgeUnfinishedError(Exception):
    """A step failed after the request reached `purging` (R11.11): the request
    stays there, with this key, for the next claim to resume."""

    def __init__(self, export_key: str) -> None:
        super().__init__(export_key)
        self.export_key = export_key


class ClaimLostError(Exception):
    """The pass could not refresh its claim twice in a row (R11.19), so another
    worker may hold the request by now: the pass stops and writes nothing more."""


@dataclass(frozen=True)
class _Listed:
    artifacts: list[str]
    attachments: list[str]


def _json_default(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"cannot export a {type(value).__name__}")


def export_key_for(claim: _Claim) -> str:
    """One bundle per request (R11.18): a pass of the same request run again
    after a dead worker overwrites the bundle it left, never adds a second."""
    return f"{claim.tenant_id}/offboarding-{claim.request_id}.zip"


@dataclass(frozen=True)
class TenantOffboardingLane:
    """One tenant's export-then-purge, holding every port the pass needs."""

    store: OffboardingStorePort
    artifacts: BucketPort
    exports: ExportSinkPort
    attachments: BucketPort
    vector_index: VectorPurgePort
    # The memory ranker's collection. The SQL purge deletes `memory.items`, and
    # each row's point is an embedding of its content; leaving them would keep
    # the departed tenant's text in the one store this pass never named. No
    # default: `None` is the composition root saying there is no vector store.
    memory_vectors: VectorPurgePort | None
    heartbeat_seconds: float = HEARTBEAT_SECONDS

    async def run(self, claim: _Claim) -> None:
        """The pass beside a task that keeps its claim fresh; whichever ends
        first ends both. A pass that loses its claim raises `ClaimLostError`."""
        work = asyncio.create_task(self._pass(claim))
        keep = asyncio.create_task(self._keep_claim(claim.tenant_id))
        try:
            await asyncio.wait({work, keep}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work, keep):
                task.cancel()
            await asyncio.gather(work, keep, return_exceptions=True)
        if not work.cancelled():
            work.result()
            return
        keep.result()

    async def _keep_claim(self, tenant_id: UUID) -> None:
        missed = 0
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                await self.store.keep_claim(tenant_id)
            except Exception:
                missed += 1
                logger.exception("offboarding for tenant %s could not refresh its claim", tenant_id)
                if missed >= _MISSED_HEARTBEATS:
                    raise ClaimLostError(
                        f"the claim was not refreshed {missed} times in a row"
                    ) from None
            else:
                missed = 0

    async def _pass(self, claim: _Claim) -> None:
        tenant_id = claim.tenant_id
        if claim.resume_export_key is not None:
            await self._purge(tenant_id, claim.resume_export_key, listed=None)
            return
        export_key = export_key_for(claim)
        listed = await self._export(tenant_id, export_key)
        await self.store.mark_status(tenant_id, "exporting", export_key=export_key)
        # Only once `put_stream` has returned: `purging` means the bundle is there.
        await self.store.mark_status(tenant_id, "purging", export_key=export_key)
        await self._purge(tenant_id, export_key, listed=listed)

    async def _list(self, tenant_id: UUID) -> _Listed:
        # Two different key shapes, both tenant-prefixed but not the same way:
        # knowledge artifacts key as `{tenant_id}/{workspace_id}/...`
        # (dw_knowledge's KnowledgeGateway), feedback attachments as
        # `feedback/{tenant_id}/{workspace_id}/...`
        # (dw_platform.application.feedback_dto.attachment_key) - checked
        # against both call sites rather than assumed, since one wrong prefix
        # here means silently exporting and purging nothing for that bucket.
        return _Listed(
            artifacts=await self.artifacts.list_objects(f"{tenant_id}/"),
            attachments=await self.attachments.list_objects(f"feedback/{tenant_id}/"),
        )

    async def _export(self, tenant_id: UUID, export_key: str) -> _Listed:
        listed = await self._list(tenant_id)
        # Anonymous: unlinked at creation on Linux, so a worker killed mid-write
        # leaves nothing on disk. The worker's root filesystem is writable disk,
        # not tmpfs (`infra/compose/docker-compose.yml`), so only the file's page
        # cache, which the kernel reclaims, counts against the 1 GiB.
        with tempfile.TemporaryFile() as spool:
            await write_bundle(spool, self.store.export_rows(tenant_id), self._blobs(listed))
            length = spool.tell()
            spool.seek(0)
            await self.exports.put_stream(export_key, spool, length, "application/zip")
        return listed

    async def _blobs(self, listed: _Listed) -> AsyncIterator[tuple[str, bytes]]:
        """One blob at a time; each is bounded by the 50 MiB upload limit."""
        for key in listed.artifacts:
            yield f"blobs/artifacts/{key}", await self.artifacts.get_object(key)
        for key in listed.attachments:
            yield f"blobs/attachments/{key}", await self.attachments.get_object(key)

    async def _purge(self, tenant_id: UUID, export_key: str, *, listed: _Listed | None) -> None:
        try:
            if listed is None:
                # Resuming: deleting is not undone, so the bundle is looked for first.
                if not await self.exports.has_object(export_key):
                    raise RuntimeError(f"the bundle {export_key} is not in the export bucket")
                listed = await self._list(tenant_id)
            await self.store.purge_rows(tenant_id)
            for key in listed.artifacts:
                await self.artifacts.delete_object(key)
            for key in listed.attachments:
                await self.attachments.delete_object(key)
            await self.vector_index.delete_by_tenant(tenant_id)
            if self.memory_vectors is not None:
                await self.memory_vectors.delete_by_tenant(tenant_id)
            await self.store.mark_status(tenant_id, "completed", export_key=export_key)
        except Exception as exc:
            raise PurgeUnfinishedError(export_key) from exc


def _write_rows(entry: IO[bytes], rows: list[dict[str, Any]], first: bool) -> None:
    text = "\n".join(json.dumps(row, default=_json_default, ensure_ascii=False) for row in rows)
    entry.write((text if first else "\n" + text).encode("utf-8"))


async def write_bundle(
    out: BinaryIO,
    batches: AsyncIterable[_ExportedTable],
    blobs: AsyncIterable[tuple[str, bytes]],
) -> None:
    """The bundle, written into `out` as it arrives (R11.9): one ndjson entry
    per table, each batch encoded and written, then dropped; then each blob.
    Encoding and compression run in a thread, so the worker's other lanes keep
    their event loop. A table's batches arrive together (`export_rows` reads
    one table at a time); a table arriving twice is refused rather than written
    as a second entry of the same name."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        written: set[str] = set()
        current: tuple[str, IO[bytes]] | None = None
        first = True
        try:
            async for batch in batches:
                if not batch.rows:
                    continue
                name = f"tables/{batch.schema}.{batch.table}.ndjson"
                if current is None or current[0] != name:
                    if name in written:
                        raise ValueError(f"{name} arrived in two runs of batches")
                    if current is not None:
                        current[1].close()
                    written.add(name)
                    # Zip64 from the start: a table's entry can pass 2 GiB, and
                    # its size is not known when the entry is opened.
                    current = (name, zf.open(name, "w", force_zip64=True))
                    first = True
                await asyncio.to_thread(_write_rows, current[1], batch.rows, first)
                first = False
        finally:
            if current is not None:
                current[1].close()
        async for name, data in blobs:
            await asyncio.to_thread(zf.writestr, name, data)


async def _report(
    lane: TenantOffboardingLane,
    tenant_id: UUID,
    status: str,
    export_key: str | None,
    cause: BaseException,
) -> None:
    try:
        await lane.store.mark_status(
            tenant_id, status, export_key=export_key, error=f"{type(cause).__name__}: {cause}"[:500]
        )
    except Exception:
        logger.exception(
            "offboarding for tenant %s failed AND could not record the failure", tenant_id
        )


def build_offboarding_consumer(lane: TenantOffboardingLane) -> Callable[[], Awaitable[None]]:
    """One tenant failing does not stop the others claimed on the same tick.
    A failure before `purging` is `failed`, left for a human to look at rather
    than retried forever; one after it keeps `purging` with its error, for the
    next claim to resume (R11.11). The request row (never purged - see
    `SqlTenantOffboarding._NEVER_PURGE`) is where either is visible. A pass that
    lost its claim writes nothing: another worker may own the row by now. Only
    `Exception` is caught, so a worker shut down mid-pass leaves the row as it
    was, for the stale claim to pick up.
    """

    async def consume() -> None:
        for claim in await lane.store.claim_requested():
            tenant_id = claim.tenant_id
            try:
                await lane.run(claim)
            except ClaimLostError:
                logger.exception("offboarding for tenant %s lost its claim", tenant_id)
            except PurgeUnfinishedError as exc:
                logger.exception("offboarding for tenant %s stopped while purging", tenant_id)
                await _report(lane, tenant_id, "purging", exc.export_key, exc.__cause__ or exc)
            except Exception as exc:
                logger.exception("offboarding failed for tenant %s", tenant_id)
                await _report(lane, tenant_id, "failed", None, exc)

    return consume
