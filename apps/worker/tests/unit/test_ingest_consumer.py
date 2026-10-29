"""What the ingest lane does with a job, and what it records when it cannot.

Storing bytes takes milliseconds; parsing and embedding them takes tens of
seconds, and the lane has to survive every way that can go wrong: a file read
only in part, one the parser refuses outright, a recording that takes longer
than a lease. These tests pin what the job row says afterwards in each case,
because that row is what an upload screen shows a person.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import InfrastructureError
from dw_knowledge.attachments import ATTACHMENT_DOMAIN, attachment_scope_of
from dw_knowledge.gateway import IngestDocumentCommand, IngestedDocument
from dw_knowledge.ingest_jobs import IngestJob
from dw_knowledge.ports import ParsedDocument
from dw_platform.application.access_context import AccessContext
from dw_worker.composition import IngestComponents
from dw_worker.consumers.ingest import build_ingest_consumer

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
ACTOR = uuid.uuid4()
LEAD = uuid.uuid4()
ACCOUNT = uuid.uuid4()
INDEXED = uuid.uuid4()

LEASE_SECONDS = 60
# Longer than the lease on purpose: a four-hour recording is the point of the
# heartbeat, and the consumer must accept a budget the lease could never cover.
JOB_TIMEOUT_SECONDS = 600.0
# Shorter than the lease, which is the invariant build_ingest_consumer enforces.
HEARTBEAT_SECONDS = 0.01


def _job(*, domain: str = ATTACHMENT_DOMAIN, scope: str | None = None) -> IngestJob:
    now = datetime.now(UTC)
    extra = (("attachment_scope", scope),) if scope is not None else ()
    return IngestJob(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        title="bien-ban-hop-12-08.pdf",
        identity_key=f"lead:{LEAD}:bien-ban-hop-12-08.pdf",
        domain=domain,
        classification="internal",
        source_version=str(uuid.uuid4()),
        scope="tenant",
        filename="bien-ban-hop-12-08.pdf",
        content_type="application/pdf",
        storage_key="staging/bien-ban-hop-12-08.pdf",
        status="running",
        attempts=1,
        max_attempts=3,
        available_at=now,
        lease_until=now,
        error=None,
        document_id=None,
        chunk_count=None,
        created_at=now,
        updated_at=now,
        extra=extra,
    )


@dataclass
class _FakeJobStore:
    job: IngestJob | None
    done: list[uuid.UUID] = field(default_factory=list)
    warnings: list[tuple[str, ...]] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    renewals: list[uuid.UUID] = field(default_factory=list)
    still_ours: bool = True

    async def claim_next(self, *, lease_seconds: int) -> IngestJob | None:
        claimed, self.job = self.job, None
        return claimed

    async def mark_done(
        self,
        job: IngestJob,
        *,
        document_id: uuid.UUID,
        chunk_count: int,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.done.append(job.id)
        self.warnings.append(warnings)

    async def mark_failed(self, job: IngestJob, *, error: str) -> None:
        self.failed.append(error)

    async def renew_lease(self, job: IngestJob, *, lease_seconds: int) -> bool:
        self.renewals.append(job.id)
        return self.still_ours


@dataclass
class _FakeGateway:
    async def ingest_document(
        self, command: IngestDocumentCommand, context: AccessContext
    ) -> IngestedDocument:
        return IngestedDocument(document_id=INDEXED, chunk_count=4, storage_key=command.title)


@dataclass
class _FakeParser:
    text: str = "ngân sách CNTT năm nay khoảng 20 tỷ"
    warnings: tuple[str, ...] = ()
    # A file the parser cannot make sense of at all — a truncated PDF, a
    # renamed archive. Raising is what the real parsers do.
    raises: Exception | None = None

    def supports(self, content_type: str, filename: str) -> bool:
        return True

    async def parse(self, data: bytes, content_type: str, filename: str) -> ParsedDocument:
        if self.raises is not None:
            raise self.raises
        return ParsedDocument(text=self.text, warnings=self.warnings)


@dataclass
class _SlowParser(_FakeParser):
    """A stand-in for a long recording: slow enough for the beat to fire."""

    async def parse(self, data: bytes, content_type: str, filename: str) -> ParsedDocument:
        await asyncio.sleep(HEARTBEAT_SECONDS * 4)
        return await super().parse(data, content_type, filename)


@dataclass
class _FakeStorage:
    async def get_object(self, key: str) -> bytes:
        return b"%PDF-1.7"


def _drain(
    job: IngestJob | None,
    *,
    parser: _FakeParser | None = None,
) -> tuple[_FakeJobStore, IngestComponents]:
    store = _FakeJobStore(job=job)
    components = IngestComponents(
        engine=None,  # type: ignore[arg-type]
        gateway=_FakeGateway(),  # type: ignore[arg-type]
        job_store=store,  # type: ignore[arg-type]
        job_queue=store,  # type: ignore[arg-type]
        parser=parser or _FakeParser(),  # type: ignore[arg-type]
        object_storage=_FakeStorage(),  # type: ignore[arg-type]
    )
    return store, components


async def _run(components: IngestComponents, *, heartbeat_seconds: float = 30.0) -> None:
    consume = build_ingest_consumer(
        components,
        lease_seconds=LEASE_SECONDS,
        job_timeout_seconds=JOB_TIMEOUT_SECONDS,
        heartbeat_seconds=heartbeat_seconds,
    )
    await consume()


async def test_a_file_read_only_in_part_records_what_the_parser_said() -> None:
    """The job succeeds, so `error` is the wrong place and silence is worse.

    A document that stops halfway indexes exactly like a whole one, and every
    later question about the missing half answers "not in the file" - which
    reads as the document not saying it. The warning has been produced since the
    gateway parser shipped and read by nobody until now.
    """
    store, components = _drain(
        _job(scope=attachment_scope_of("lead", LEAD)),
        parser=_FakeParser(warnings=("extraction_incomplete",)),
    )

    await _run(components)

    assert len(store.done) == 1 and store.failed == []
    assert store.warnings == [("extraction_incomplete",)]


async def test_a_file_read_whole_records_no_warning() -> None:
    store, components = _drain(_job(scope=attachment_scope_of("lead", LEAD)))

    await _run(components)

    assert store.warnings == [()]


async def test_a_corrupt_file_fails_loudly_and_keeps_its_reason() -> None:
    """US-04 AC3. The upload succeeded and the read did not, and the person who
    uploaded it has to be able to tell those apart.

    The reason is stored on the job rather than only logged: a file that
    silently never became readable is indistinguishable, from the lead page,
    from one nobody has got to yet.
    """
    store, components = _drain(
        _job(scope=attachment_scope_of("lead", LEAD)),
        parser=_FakeParser(raises=InfrastructureError("tệp PDF hỏng, không đọc được trang nào")),
    )

    await _run(components)

    assert store.done == []
    assert len(store.failed) == 1
    assert "tệp PDF hỏng" in store.failed[0]


async def test_a_hard_to_hear_recording_is_indexed_like_any_other() -> None:
    """The transcript-confidence gate is gone, and this is what its absence means.

    A recording used to be thrown away whole when the recogniser reported it was
    unsure about more than 40% of the segments. Nobody could say what that
    number meant for a given file, and the cost of being wrong was one-sided:
    the meeting the INTENT axis is scored from, refused. A rough transcript is
    now evidence like any other, and how much to trust it is the scorer's call -
    the same call it already makes on a note nobody scored at all.
    """
    store, components = _drain(
        _job(scope=attachment_scope_of("lead", LEAD)),
        parser=_FakeParser(text="ngân sách khoảng tám tỷ, anh Dũng phụ trách"),
    )

    await _run(components)

    assert store.failed == []
    assert len(store.done) == 1


# ------------------------------------------------------------- long files --


async def test_a_job_budget_longer_than_the_lease_is_allowed() -> None:
    """The cap that made a four-hour meeting unprocessable is gone.

    `job_timeout_seconds` used to have to be shorter than the lease, so the
    longest file the system could accept was the shortest lease anybody would
    wait out. The heartbeat is what keeps the claim now, so the budget is free.
    """
    store, components = _drain(_job())

    await _run(components)

    assert store.failed == [], "a long budget is not a configuration error"


async def test_the_consumer_refuses_a_heartbeat_slower_than_the_lease() -> None:
    """The invariant that replaced it. A beat after the lease renews nothing."""
    _store, components = _drain(_job())

    with pytest.raises(ValueError, match="heartbeat_seconds must be shorter"):
        build_ingest_consumer(
            components,
            lease_seconds=LEASE_SECONDS,
            job_timeout_seconds=JOB_TIMEOUT_SECONDS,
            heartbeat_seconds=LEASE_SECONDS,
        )


async def test_a_slow_job_holds_its_claim_while_it_works() -> None:
    """Without this the lease lapses mid-transcription and a second worker
    claims the job, so one recording is transcribed and billed twice."""
    parser = _SlowParser()
    store, components = _drain(_job(), parser=parser)  # type: ignore[arg-type]

    await _run(components, heartbeat_seconds=HEARTBEAT_SECONDS)

    assert store.renewals, "the lease was never pushed forward"
    assert store.done, "and the job still finished"


async def test_the_heartbeat_stops_when_the_job_does() -> None:
    """A beat left running would hold a finished job's row open for ever."""
    store, components = _drain(_job())

    await _run(components, heartbeat_seconds=HEARTBEAT_SECONDS)
    settled = len(store.renewals)
    await asyncio.sleep(HEARTBEAT_SECONDS * 5)

    assert len(store.renewals) == settled
