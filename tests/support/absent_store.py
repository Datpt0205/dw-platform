"""`dw_knowledge.ports.ABSENT_STORE_RULE`, checked the same way for every adapter.

A bucket or collection nobody has created yet holds nothing of any tenant, so a
tenant-wide list of it is empty and a tenant-wide delete from it is done
(foundations-hardening R11.12). The offboarding lane lists and deletes through
three adapters, and discovery 09 measured two of them failing the pass on a store
that did not exist yet while the third answered this way. Each adapter's
integration test hands its own adapter, pointed at a name that was never
created, to the functions here, so the three answer one question one way.
"""

from __future__ import annotations

import uuid
from typing import Protocol


class _Lists(Protocol):
    async def list_objects(self, prefix: str) -> list[str]: ...


class _PurgesTenants(Protocol):
    async def delete_by_tenant(self, tenant_id: uuid.UUID) -> None: ...


async def a_missing_bucket_lists_nothing(store: _Lists) -> None:
    """Listing a tenant's prefix in a bucket that does not exist is `[]`."""
    tenant = uuid.uuid4()
    assert await store.list_objects(f"{tenant}/") == []
    assert await store.list_objects(f"feedback/{tenant}/") == []


async def a_missing_collection_purge_is_done(store: _PurgesTenants) -> None:
    """Deleting a tenant from a collection that does not exist returns, twice."""
    tenant = uuid.uuid4()
    await store.delete_by_tenant(tenant)
    await store.delete_by_tenant(tenant)
