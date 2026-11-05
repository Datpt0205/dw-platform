"""The knowledge index's tenant purge against a real Qdrant (foundations-hardening R11.12).

Offboarding deletes a company's points with one filtered delete. Discovery 09
measured it failing on a collection nobody had created, after the SQL purge had
committed, so the company was gone from Postgres while its request read
`failed`. A collection that does not exist holds nothing of anyone
(`dw_knowledge.ports.ABSENT_STORE_RULE`), as the memory ranker already answered;
a Qdrant that cannot be reached is still an error.
"""

from __future__ import annotations

import uuid

import pytest
from absent_store import a_missing_collection_purge_is_done
from qdrant_client import AsyncQdrantClient
from runtime_harness import RuntimeUrls

from dw_kernel.errors import InfrastructureError
from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter

pytestmark = pytest.mark.integration


async def test_purging_a_tenant_from_a_collection_nobody_made_is_done(urls: RuntimeUrls) -> None:
    client = AsyncQdrantClient(url=urls.qdrant_url, api_key=urls.qdrant_api_key)
    collection = f"dw_knowledge_absent_{uuid.uuid4().hex[:8]}"
    try:
        await a_missing_collection_purge_is_done(
            QdrantVectorIndexAdapter(client=client, collection=collection)
        )
        assert not await client.collection_exists(collection), "the purge creates nothing"
    finally:
        await client.close()


async def test_purging_from_a_qdrant_that_cannot_be_reached_raises() -> None:
    client = AsyncQdrantClient(url="http://127.0.0.1:1", timeout=2)
    try:
        with pytest.raises(InfrastructureError):
            await QdrantVectorIndexAdapter(client=client, collection="never").delete_by_tenant(
                uuid.uuid4()
            )
    finally:
        await client.close()
