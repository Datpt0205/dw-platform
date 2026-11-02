"""A tiny cache port the platform reads through.

Deliberately small: get a string, set a string with a TTL. Nothing invalidates
by pattern any more: an AccessContext is keyed by the tenant's access version
(`platform.tenant_access_versions`, bumped by the database on every write that
feeds authorization, tenant-rbac R4), so a change made by an API route, a lane,
an import or raw SQL is a new key at the next request, and the old entry simply
expires.

Every implementation is **fail-open**: if the cache is unreachable, a get is a
miss and a set is a no-op, so the caller falls back to the source of truth. A
cache outage must never deny a request.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


def membership_cache_key(
    tenant_id: UUID, version: int, workspace_id: UUID, issuer: str, subject: str
) -> str:
    """Key for one signed-in identity's resolved AccessContext in one workspace,
    at one access version of its tenant."""
    return f"ml:{tenant_id}:{version}:{workspace_id}:{issuer}:{subject}"


class CachePort(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...
