"""Shared infrastructure for the knowledge integration tests.

Real Postgres, Qdrant and MinIO from `make infra-up`; fails loudly when they are
missing rather than skipping, because a silently skipped isolation test is worse
than none. Each test gets its own Qdrant collection so one test's documents can
never satisfy another's assertion.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
from minio import Minio
from qdrant_client import AsyncQdrantClient

# reuse the runtime harness (same infra, own database)
from runtime_harness import (
    TEST_DB,
    RuntimeUrls,
    recreate_database,
    run_migrations,
    runtime_urls,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_knowledge.adapters.hash_embedding import HashEmbeddingAdapter
from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter
from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter
from dw_knowledge.gateway import KnowledgeGateway
from dw_platform.application.access_context import AccessContext

ContextFactory = Callable[..., AccessContext]


@pytest.fixture(scope="session")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin, TEST_DB))
    except Exception as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up`. Error: {exc}")
    result = run_migrations(resolved.migrator)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stderr}")
    return resolved


@pytest.fixture
async def gateway(urls: RuntimeUrls) -> AsyncIterator[KnowledgeGateway]:
    engine = create_async_engine(urls.app, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    qdrant = AsyncQdrantClient(url=urls.qdrant_url, api_key=urls.qdrant_api_key)
    collection = f"dw_knowledge_test_{uuid.uuid4().hex[:8]}"
    minio_client = Minio(
        urls.minio_endpoint,
        access_key=urls.minio_access_key,
        secret_key=urls.minio_secret_key,
        secure=False,
    )
    built = KnowledgeGateway(
        session_factory=session_factory,
        vector_index=QdrantVectorIndexAdapter(client=qdrant, collection=collection),
        embeddings=HashEmbeddingAdapter(),
        object_storage=MinioObjectStorageAdapter(client=minio_client, bucket="dw-artifacts"),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )
    await built.ensure_ready()
    yield built
    await qdrant.delete_collection(collection)
    await qdrant.close()
    await engine.dispose()


@pytest.fixture
def make_context() -> ContextFactory:
    """A verified caller. Clearance is a parameter because retrieval reads it."""

    def build(
        tenant: uuid.UUID, workspace: uuid.UUID, *, clearance: str = "internal"
    ) -> AccessContext:
        return AccessContext(
            tenant_id=tenant,
            workspace_id=workspace,
            principal_id=uuid.uuid4(),
            roles=frozenset({"member"}),
            scopes=frozenset({"knowledge.read"}),
            plan_id="professional",
            clearance=clearance,
        )

    return build
