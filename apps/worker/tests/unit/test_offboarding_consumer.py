"""TenantOffboardingLane orchestration, against fakes for every port.

The Postgres logic (catalog discovery, FK-ordered purge, RLS isolation, the
claim) is proven against a real database in dw_platform's own
test_offboarding.py, and the stores against real ones in their contract tests.
What is under test here is what this package owns: the order export, upload,
purge and delete happen in, the bundle written batch by batch (R11.9), the two
phases a failure can stop in (R11.10, R11.11), one bundle per request (R11.18),
the claim kept fresh while the pass runs (R11.17, R11.19), and that one
tenant's failure neither stops another nor is swallowed.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import tracemalloc
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, BinaryIO

import pytest

from dw_worker.consumers.offboarding import (
    ClaimLostError,
    TenantOffboardingLane,
    _json_default,
    build_offboarding_consumer,
    export_key_for,
    write_bundle,
)

pytestmark = pytest.mark.unit

TENANT = uuid.UUID(int=1)
OTHER_TENANT = uuid.UUID(int=2)
REQUEST = uuid.UUID(int=0xA1)
OTHER_REQUEST = uuid.UUID(int=0xA2)


@dataclass(frozen=True)
class _ExportedTable:
    schema: str
    table: str
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class _Claim:
    tenant_id: uuid.UUID
    request_id: uuid.UUID
    resume_export_key: str | None = None


@dataclass
class _FakeStore:
    claimed: list[_Claim]
    rows_by_tenant: dict[uuid.UUID, list[_ExportedTable]] = field(default_factory=dict)
    fail_export_for: set[uuid.UUID] = field(default_factory=set)
    export_delay: float = 0.0
    keep_claim_fails: bool = False
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    async def claim_requested(self) -> list[_Claim]:
        return self.claimed

    async def export_rows(self, tenant_id: uuid.UUID) -> AsyncIterator[_ExportedTable]:
        self.calls.append(("export_rows", tenant_id))
        if self.export_delay:
            await asyncio.sleep(self.export_delay)
        if tenant_id in self.fail_export_for:
            raise RuntimeError("export blew up")
        for batch in self.rows_by_tenant.get(tenant_id, []):
            yield batch

    async def purge_rows(self, tenant_id: uuid.UUID) -> None:
        self.calls.append(("purge_rows", tenant_id))

    async def keep_claim(self, tenant_id: uuid.UUID) -> None:
        self.calls.append(("keep_claim", tenant_id))
        if self.keep_claim_fails:
            raise ConnectionError("database unreachable")

    async def mark_status(
        self,
        tenant_id: uuid.UUID,
        status: str,
        *,
        export_key: str | None = None,
        error: str | None = None,
    ) -> None:
        self.calls.append(("mark_status", tenant_id, status, export_key, error))

    def statuses(self, tenant_id: uuid.UUID = TENANT) -> list[tuple[str, str | None, str | None]]:
        return [
            (c[2], c[3], c[4]) for c in self.calls if c[0] == "mark_status" and c[1] == tenant_id
        ]


@dataclass
class _FakeBucket:
    name: str
    objects: dict[str, bytes] = field(default_factory=dict)
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    async def get_object(self, key: str) -> bytes:
        self.calls.append((self.name, "get_object", key))
        return self.objects[key]

    async def list_objects(self, prefix: str) -> list[str]:
        self.calls.append((self.name, "list_objects", prefix))
        return [k for k in self.objects if k.startswith(prefix)]

    async def delete_object(self, key: str) -> None:
        self.calls.append((self.name, "delete_object", key))
        self.objects.pop(key, None)


@dataclass
class _FakeSink:
    """Honours `put_stream`'s contract: reads exactly `length` bytes."""

    objects: dict[str, bytes] = field(default_factory=dict)
    puts: list[str] = field(default_factory=list)

    async def put_stream(self, key: str, data: BinaryIO, length: int, content_type: str) -> str:
        body = data.read()
        assert len(body) == length, "the length handed over is the stream's"
        assert content_type == "application/zip"
        self.puts.append(key)
        self.objects[key] = body
        return f"s3://exports/{key}"

    async def has_object(self, key: str) -> bool:
        return key in self.objects


@dataclass
class _FakeVectorIndex:
    calls: list[uuid.UUID] = field(default_factory=list)

    async def delete_by_tenant(self, tenant_id: uuid.UUID) -> None:
        self.calls.append(tenant_id)


def _lane(
    store: _FakeStore,
    artifacts: _FakeBucket | None = None,
    exports: _FakeSink | None = None,
    attachments: _FakeBucket | None = None,
) -> TenantOffboardingLane:
    return TenantOffboardingLane(
        store=store,
        artifacts=artifacts or _FakeBucket("artifacts"),
        exports=exports or _FakeSink(),
        attachments=attachments or _FakeBucket("attachments"),
        vector_index=_FakeVectorIndex(),
        # A deployment without Qdrant has no memory points; the real-store case
        # is `tests/integration/test_offboarding_memory_vectors.py`.
        memory_vectors=None,
    )


async def test_run_exports_uploads_then_purges_in_order() -> None:
    store = _FakeStore(
        claimed=[_Claim(TENANT, REQUEST)],
        rows_by_tenant={
            TENANT: [_ExportedTable("platform", "workspaces", [{"tenant_id": str(TENANT)}])]
        },
    )
    artifacts = _FakeBucket("artifacts", objects={f"{TENANT}/ws/doc-1": b"pdf-bytes"})
    exports = _FakeSink()
    attachments = _FakeBucket(
        "attachments", objects={f"feedback/{TENANT}/ws/fb-1/att-1": b"png-bytes"}
    )

    await _lane(store, artifacts, exports, attachments).run(_Claim(TENANT, REQUEST))

    kinds = [c[0] for c in store.calls]
    assert kinds.index("export_rows") < kinds.index("purge_rows")
    assert len(exports.puts) == 1
    assert not artifacts.objects, "the artifact must be deleted after purge"
    assert not attachments.objects, "the attachment must be deleted after purge"
    assert [s for s, _, _ in store.statuses()] == ["exporting", "purging", "completed"]
    with zipfile.ZipFile(BytesIO(exports.objects[exports.puts[0]])) as zf:
        assert zf.read(f"blobs/artifacts/{TENANT}/ws/doc-1") == b"pdf-bytes"
        assert zf.read(f"blobs/attachments/feedback/{TENANT}/ws/fb-1/att-1") == b"png-bytes"


async def test_the_export_key_is_one_per_request_on_every_status() -> None:
    """R11.18 (FH44): the key names the request, so a pass run again after a
    dead worker overwrites its bundle instead of leaving a second one."""
    store = _FakeStore(claimed=[])
    exports = _FakeSink()
    lane = _lane(store, exports=exports)

    await lane.run(_Claim(TENANT, REQUEST))
    await lane.run(_Claim(TENANT, REQUEST))

    assert exports.puts == [f"{TENANT}/offboarding-{REQUEST}.zip"] * 2
    assert export_key_for(_Claim(TENANT, REQUEST)) == exports.puts[0]
    assert {key for _, key, _ in store.statuses()} == {exports.puts[0]}


async def test_a_failing_tenant_does_not_stop_another_claimed_on_the_same_tick() -> None:
    store = _FakeStore(
        claimed=[_Claim(TENANT, REQUEST), _Claim(OTHER_TENANT, OTHER_REQUEST)],
        fail_export_for={TENANT},
    )

    await build_offboarding_consumer(_lane(store))()  # must not raise

    failed = store.statuses(TENANT)
    assert failed[-1][0] == "failed", "a failure before purging is failed, as before"
    assert failed[-1][2] is not None, "the error message is recorded"
    assert store.statuses(OTHER_TENANT)[-1][0] == "completed"


async def test_a_purge_step_that_fails_keeps_the_request_purging_with_its_key() -> None:
    """R11.11 (FH38): once the bundle is up and the SQL purge may have run, the
    request is not handed back as failed; it waits in `purging` for the next
    claim, with the key of the bundle that was exported."""

    @dataclass
    class _DownMemoryVectors:
        async def delete_by_tenant(self, tenant_id: uuid.UUID) -> None:
            raise RuntimeError("qdrant xuống")

    store = _FakeStore(claimed=[_Claim(TENANT, REQUEST)])
    lane = replace(_lane(store), memory_vectors=_DownMemoryVectors())

    await build_offboarding_consumer(lane)()

    status, key, error = store.statuses()[-1]
    assert status == "purging"
    assert key == f"{TENANT}/offboarding-{REQUEST}.zip"
    assert error is not None and "qdrant xuống" in error
    assert all(s not in ("completed", "failed") for s, _, _ in store.statuses())


async def test_a_resumed_request_purges_with_its_bundle_and_exports_nothing() -> None:
    """R11.10 (FH38): claimed back in `purging`, the pass reads no row, uploads
    no bundle and completes under the key it already had."""
    key = f"{TENANT}/offboarding-{REQUEST}.zip"
    store = _FakeStore(claimed=[_Claim(TENANT, REQUEST, resume_export_key=key)])
    exports = _FakeSink(objects={key: b"the bundle"})
    artifacts = _FakeBucket("artifacts", objects={f"{TENANT}/ws/doc-1": b"x"})

    await build_offboarding_consumer(_lane(store, artifacts, exports))()

    kinds = [c[0] for c in store.calls]
    assert "export_rows" not in kinds
    assert "purge_rows" in kinds
    assert exports.puts == []
    assert exports.objects == {key: b"the bundle"}
    assert not artifacts.objects
    assert store.statuses() == [("completed", key, None)]


async def test_a_resumed_request_whose_bundle_is_gone_deletes_nothing() -> None:
    """R11.10 (FH38): deleting cannot be undone, so a resumed pass looks for its
    bundle first and stops in `purging` when it is not there."""
    key = f"{TENANT}/offboarding-{REQUEST}.zip"
    store = _FakeStore(claimed=[_Claim(TENANT, REQUEST, resume_export_key=key)])
    artifacts = _FakeBucket("artifacts", objects={f"{TENANT}/ws/doc-1": b"x"})
    lane = _lane(store, artifacts, _FakeSink())

    await build_offboarding_consumer(lane)()

    assert "purge_rows" not in [c[0] for c in store.calls]
    assert artifacts.objects, "no blob is deleted without the bundle"
    assert isinstance(lane.vector_index, _FakeVectorIndex) and lane.vector_index.calls == []
    status, kept, error = store.statuses()[-1]
    assert (status, kept) == ("purging", key)
    assert error is not None and "not in the export bucket" in error


async def test_a_live_pass_keeps_its_claim_and_stops_when_done() -> None:
    """R11.17 (FH44): a pass longer than the refresh period refreshes the claim
    while it runs, and the refreshing ends with the pass."""
    store = _FakeStore(claimed=[], export_delay=0.3)
    lane = replace(_lane(store), heartbeat_seconds=0.05)

    await lane.run(_Claim(TENANT, REQUEST))
    refreshed = [c for c in store.calls if c[0] == "keep_claim"]
    await asyncio.sleep(0.2)

    assert len(refreshed) >= 2
    assert refreshed == [("keep_claim", TENANT)] * len(refreshed)
    assert [c for c in store.calls if c[0] == "keep_claim"] == refreshed, "stops with the pass"


async def test_a_pass_that_cannot_keep_its_claim_stops_before_uploading() -> None:
    """R11.19 (FH44): two refreshes in a row fail, so another worker may own the
    request: the pass stops before it uploads, and writes no status."""
    store = _FakeStore(claimed=[_Claim(TENANT, REQUEST)], export_delay=1.0, keep_claim_fails=True)
    exports = _FakeSink()
    lane = replace(_lane(store, exports=exports), heartbeat_seconds=0.05)

    with pytest.raises(ClaimLostError):
        await lane.run(_Claim(TENANT, REQUEST))
    await build_offboarding_consumer(lane)()

    assert exports.puts == []
    assert "purge_rows" not in [c[0] for c in store.calls]
    assert store.statuses() == [], "a pass that lost its claim writes nothing"


def test_json_default_handles_every_type_a_row_can_hold() -> None:
    assert _json_default(uuid.UUID(int=1)) == str(uuid.UUID(int=1))
    assert _json_default(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00+00:00"
    assert _json_default(date(2026, 1, 1)) == "2026-01-01"
    assert _json_default(Decimal("1.50")) == "1.50"
    assert _json_default(b"hi") == "hi"
    with pytest.raises(TypeError):
        _json_default(object())


async def _batches(tables: list[_ExportedTable]) -> AsyncIterator[_ExportedTable]:
    for table in tables:
        yield table


async def _blobs(items: dict[str, bytes]) -> AsyncIterator[tuple[str, bytes]]:
    for name, data in items.items():
        yield name, data


async def _bundle(tables: list[_ExportedTable], blobs: dict[str, bytes]) -> bytes:
    out = BytesIO()
    await write_bundle(out, _batches(tables), _blobs(blobs))
    return out.getvalue()


async def test_the_bundle_holds_table_ndjson_and_both_blob_kinds() -> None:
    tables = [_ExportedTable("platform", "workspaces", [{"id": str(uuid.uuid4())}])]
    bundle = await _bundle(
        tables,
        {"blobs/artifacts/art-1": b"artifact-bytes", "blobs/attachments/att-1": b"attachment"},
    )

    with zipfile.ZipFile(BytesIO(bundle)) as zf:
        names = set(zf.namelist())
        assert "tables/platform.workspaces.ndjson" in names
        assert zf.read("blobs/artifacts/art-1") == b"artifact-bytes"
        assert zf.read("blobs/attachments/att-1") == b"attachment"
        row = json.loads(zf.read("tables/platform.workspaces.ndjson").decode().splitlines()[0])
        assert "id" in row


async def test_two_batches_of_one_table_become_one_ndjson_entry() -> None:
    """foundations-hardening R11.2: a table arrives in batches of at most a
    thousand rows; the bundle still holds one entry per table, every row once."""
    first = _ExportedTable("platform", "workspaces", [{"n": i} for i in range(1000)])
    second = _ExportedTable("platform", "workspaces", [{"n": 1000}])
    other = _ExportedTable("studio", "records", [{"n": "khác"}])
    bundle = await _bundle([first, second, other], {})

    with zipfile.ZipFile(BytesIO(bundle)) as zf:
        assert zf.namelist().count("tables/platform.workspaces.ndjson") == 1
        lines = zf.read("tables/platform.workspaces.ndjson").decode().splitlines()
        assert zf.read("tables/studio.records.ndjson").decode() == '{"n": "khác"}'
    assert [json.loads(line)["n"] for line in lines] == list(range(1001))


async def test_a_table_arriving_in_two_runs_is_refused() -> None:
    """R11.9: a second entry of one name would be a bundle a reader merges or
    misses; the writer refuses rather than write it."""
    a = _ExportedTable("platform", "workspaces", [{"n": 1}])
    b = _ExportedTable("studio", "records", [{"n": 2}])

    with pytest.raises(ValueError, match="two runs"):
        await _bundle([a, b, a], {})


async def _vietnamese_batches(count: int, rows: int) -> AsyncIterator[_ExportedTable]:
    """Made one batch at a time, as `export_rows` reads them: about 2 KB of
    non-Latin-1 text a row, which CPython stores two bytes a character."""
    note = "Khách quan tâm gói dịch vụ doanh nghiệp, hẹn gọi lại tuần sau để báo giá. " * 24
    for b in range(count):
        yield _ExportedTable(
            "studio",
            "records",
            [
                {"id": str(uuid.uuid4()), "n": b * rows + i, "ghi_chu": f"{i} {note}"}
                for i in range(rows)
            ],
        )


async def test_the_bundle_writer_holds_one_batch_not_the_table() -> None:
    """R11.9 (FH37): ten batches of a thousand ~2 KB rows (about 20 MB of
    ndjson) are written with a traced peak under 32 MB. Gathering the table's
    lines before writing, as the lane did at `b0113f4`, held every line, their
    join and its UTF-8 copy at once: well over 100 MB here, 9,143 B a record
    in discovery 09's worker."""
    with tempfile.TemporaryFile() as spool:
        tracemalloc.start()
        try:
            await write_bundle(spool, _vietnamese_batches(10, 1000), _blobs({}))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        spool.seek(0)
        with zipfile.ZipFile(spool) as zf, zf.open("tables/studio.records.ndjson") as raw:
            numbers = [json.loads(line)["n"] for line in raw]

    assert numbers == list(range(10_000))
    assert peak < 32 * 1024 * 1024, f"traced peak {peak:,} B"
