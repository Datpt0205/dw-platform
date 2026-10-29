"""Soft-delete (tombstone) semantics in the vector index."""

from __future__ import annotations

import uuid

import pytest

from dw_knowledge.adapters.memory_index import InMemoryVectorIndexAdapter
from dw_knowledge.ports import IndexableChunk, TrustedSearchFilter

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WS = uuid.uuid4()
DOC = uuid.uuid4()


def _chunk() -> IndexableChunk:
    return IndexableChunk(
        chunk_id=uuid.uuid4(),
        document_id=DOC,
        tenant_id=TENANT,
        workspace_id=WS,
        domain="legal",
        content="Điều 1. Phạm vi điều chỉnh",
        classification="internal",
        source_version="1",
        index_version="v1",
        provenance_hash="0" * 64,
        acl_principals=("tenant:*",),
        vector=(1.0, 0.0, 0.0),
    )


def _filter() -> TrustedSearchFilter:
    return TrustedSearchFilter(
        tenant_id=TENANT,
        workspace_id=WS,
        domain="legal",
        allowed_classifications=("internal",),
        acl_principals=("tenant:*",),
    )


async def test_tombstone_excludes_then_reindex_restores() -> None:
    index = InMemoryVectorIndexAdapter()
    await index.upsert([_chunk()])
    assert await index.search((1.0, 0.0, 0.0), _filter(), 5)  # found

    await index.tombstone_document(DOC, TENANT)  # soft delete
    assert not await index.search((1.0, 0.0, 0.0), _filter(), 5)  # excluded

    await index.upsert([_chunk()])  # re-ingest reactivates
    assert await index.search((1.0, 0.0, 0.0), _filter(), 5)  # found again


async def test_hard_delete_removes_permanently() -> None:
    index = InMemoryVectorIndexAdapter()
    await index.upsert([_chunk()])
    await index.delete_document(DOC, TENANT)
    assert not await index.search((1.0, 0.0, 0.0), _filter(), 5)


async def test_another_tenant_cannot_tombstone_or_delete_the_document() -> None:
    """A document id names no tenant, so the tenant is part of the match (R2.1)."""
    index = InMemoryVectorIndexAdapter()
    await index.upsert([_chunk()])
    other = uuid.uuid4()

    await index.tombstone_document(DOC, other)
    await index.delete_document(DOC, other)

    assert await index.search((1.0, 0.0, 0.0), _filter(), 5)
