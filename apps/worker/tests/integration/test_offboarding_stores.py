"""The offboarding lane against real stores: what discovery 09 measured failing.

Two passes, each against the stores compose runs:

- a company that never uploaded an attachment (the `feedback` bucket does not
  exist yet) and whose knowledge collection was never created: the lane used to
  fail at the attachments list, and at the knowledge index's `delete_by_tenant`
  after the SQL purge had committed (foundations-hardening R11.12);
- a bundle streamed from the real `SqlTenantOffboarding.export_rows` of one
  company while another has rows in the same tables, uploaded through
  `put_stream` and read back from the real export bucket (R11.9): every row of
  the one, none of the other, under the request's own key (R11.18). The upload
  in parts itself is the store's contract test's.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from minio import Minio
from pg_test_db import DatabaseUrls, load_env
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter
from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_worker.consumers.offboarding import (
    TenantOffboardingLane,
    build_offboarding_consumer,
    export_key_for,
)
from dw_worker.main import build_tenant_wide_scopes

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def minio() -> Minio:
    env = load_env()
    return Minio(
        f"127.0.0.1:{env.get('DW_MINIO_HOST_PORT', '9000')}",
        access_key=env["MINIO_ROOT_USER"],
        secret_key=env["MINIO_ROOT_PASSWORD"],
        secure=False,
    )


def _remove_bucket(client: Minio, bucket: str) -> None:
    if client.bucket_exists(bucket):
        for obj in client.list_objects(bucket, recursive=True):
            client.remove_object(bucket, obj.object_name)
        client.remove_bucket(bucket)


@pytest.fixture
def buckets(minio: Minio) -> Iterator[dict[str, MinioObjectStorageAdapter]]:
    """Three bucket names nobody has created; the export one is made by the
    lane's own upload. All removed afterwards."""
    names = {role: f"dw-off-{role}-{uuid.uuid4().hex[:8]}" for role in ("art", "fb", "exp")}
    yield {
        role: MinioObjectStorageAdapter(client=minio, bucket=name) for role, name in names.items()
    }
    for name in names.values():
        _remove_bucket(minio, name)


@pytest.fixture
async def absent_collection() -> AsyncIterator[QdrantVectorIndexAdapter]:
    env = load_env()
    client = AsyncQdrantClient(
        url=env.get("QDRANT_URL", "http://127.0.0.1:6333"),
        api_key=env.get("QDRANT_API_KEY") or None,
    )
    adapter = QdrantVectorIndexAdapter(
        client=client, collection=f"dw_knowledge_absent_{uuid.uuid4().hex[:8]}"
    )
    try:
        exists = await client.collection_exists(adapter.collection)
    except Exception as exc:  # pragma: no cover - environment, not logic
        await client.close()
        pytest.fail(f"Qdrant unreachable — run `make infra-up`. Error: {exc}")
    assert not exists
    yield adapter
    await client.close()


@dataclass(frozen=True)
class _Claim:
    tenant_id: uuid.UUID
    request_id: uuid.UUID
    resume_export_key: str | None = None


@dataclass
class _Store:
    """The Postgres half, faked: what is under test is the stores."""

    claims: list[_Claim]
    statuses: list[tuple[str, str | None, str | None]] = field(default_factory=list)

    async def claim_requested(self) -> list[_Claim]:
        return self.claims

    async def export_rows(self, tenant_id: uuid.UUID) -> AsyncIterator[Any]:
        for batch in ():
            yield batch

    async def purge_rows(self, tenant_id: uuid.UUID) -> None:
        return None

    async def keep_claim(self, tenant_id: uuid.UUID) -> None:
        return None

    async def mark_status(
        self,
        tenant_id: uuid.UUID,
        status: str,
        *,
        export_key: str | None = None,
        error: str | None = None,
    ) -> None:
        self.statuses.append((status, export_key, error))


async def test_a_company_with_no_attachment_bucket_and_no_knowledge_collection_completes(
    buckets: dict[str, MinioObjectStorageAdapter],
    absent_collection: QdrantVectorIndexAdapter,
) -> None:
    """R11.12 (FH39): the two failures discovery 09 measured, end to end."""
    claim = _Claim(tenant_id=uuid.uuid4(), request_id=uuid.uuid4())
    store = _Store(claims=[claim])
    lane = TenantOffboardingLane(
        store=store,
        artifacts=buckets["art"],
        exports=buckets["exp"],
        attachments=buckets["fb"],
        vector_index=absent_collection,
        memory_vectors=None,
    )

    await build_offboarding_consumer(lane)()

    assert [s for s, _, _ in store.statuses] == ["exporting", "purging", "completed"], (
        store.statuses
    )
    assert await buckets["exp"].has_object(export_key_for(claim))


# -- a bundle of one company, from the real export --------------------------------

_WORKSPACES = 1_200  # more than one keyset batch of `platform.workspaces`


async def _seed_company(migrator: Any, tenant: uuid.UUID) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status)"
                " VALUES (:t, :s, :s, 'offboarding')"
            ),
            {"t": tenant, "s": f"off-{tenant.hex[:12]}"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " SELECT gen_random_uuid(), :t, 'ws-' || n, 'Phòng ' || n"
                " FROM generate_series(1, :n) AS n"
            ),
            {"t": tenant, "n": _WORKSPACES},
        )


async def _file_request(migrator: Any, tenant: uuid.UUID) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_offboarding_requests (id, tenant_id, requested_by)"
                " VALUES (gen_random_uuid(), :t, gen_random_uuid())"
            ),
            {"t": tenant},
        )


async def test_a_streamed_bundle_of_one_company_holds_none_of_another(
    worker_db: DatabaseUrls,
    buckets: dict[str, MinioObjectStorageAdapter],
    absent_collection: QdrantVectorIndexAdapter,
    minio: Minio,
) -> None:
    """R11.9 (FH37): rows read by the real export, written batch by batch, uploaded
    and read back: the leaving company's rows once each, the other's none."""
    leaving, staying = uuid.uuid4(), uuid.uuid4()
    migrator = create_async_engine(worker_db.migrator, poolclass=NullPool)
    app = create_async_engine(worker_db.app, poolclass=NullPool)
    try:
        await _seed_company(migrator, leaving)
        await _seed_company(migrator, staying)
        await _file_request(migrator, leaving)
        store = SqlTenantOffboarding(
            session_factory=async_sessionmaker(app, class_=AsyncSession, expire_on_commit=False),
            scopes=build_tenant_wide_scopes(),
        )
        lane = TenantOffboardingLane(
            store=store,
            artifacts=buckets["art"],
            exports=buckets["exp"],
            attachments=buckets["fb"],
            vector_index=absent_collection,
            memory_vectors=None,
        )

        claims = [c for c in await store.claim_requested() if c.tenant_id == leaving]
        assert len(claims) == 1 and claims[0].resume_export_key is None
        await lane.run(claims[0])

        key = export_key_for(claims[0])
        response = minio.get_object(buckets["exp"].bucket, key)
        try:
            body = response.read()
        finally:
            response.close()
            response.release_conn()
        async with migrator.connect() as conn:
            left = dict(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT tenant_id, count(*) FROM platform.workspaces"
                            " WHERE tenant_id IN (:a, :b) GROUP BY tenant_id"
                        ),
                        {"a": leaving, "b": staying},
                    )
                )
                .tuples()
                .all()
            )
    finally:
        await app.dispose()
        await migrator.dispose()

    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        workspaces = [
            json.loads(line) for line in zf.read("tables/platform.workspaces.ndjson").splitlines()
        ]
        tenants_seen = {
            row.get("tenant_id")
            for name in zf.namelist()
            if name.startswith("tables/")
            for row in map(json.loads, zf.read(name).splitlines())
            if "tenant_id" in row
        }
    assert len(workspaces) == _WORKSPACES
    assert len({row["id"] for row in workspaces}) == _WORKSPACES
    assert tenants_seen == {str(leaving)}, "no row of another company is in the bundle"
    assert left == {staying: _WORKSPACES}, "the purge took the one company and left the other"
