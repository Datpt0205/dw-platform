"""Cache adapters: Valkey/Redis-backed, and a null fallback.

``ValkeyCache`` wraps an async redis client (Valkey speaks the Redis protocol,
so the same client serves both). Every call is wrapped so a connection problem
degrades to "miss / no-op" rather than raising — the platform must keep serving
from the database when the cache is down.

``NullCache`` is the no-cache path: always a miss. It is what a deployment with
no ``REDIS_URL`` gets, and what tests use unless they assert on caching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import redis.asyncio as aioredis
from redis.exceptions import RedisError


@dataclass(frozen=True)
class ValkeyCache:
    """Implements ``CachePort`` over an async Redis/Valkey client."""

    client: aioredis.Redis

    @classmethod
    def from_url(cls, url: str) -> ValkeyCache:
        # redis-py's from_url is not annotated, so the call reads as untyped.
        client: aioredis.Redis = aioredis.from_url(url, decode_responses=True)  # type: ignore[no-untyped-call]
        return cls(client)

    async def get(self, key: str) -> str | None:
        try:
            return cast("str | None", await self.client.get(key))
        except RedisError:
            return None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        try:
            await self.client.set(key, value, ex=ttl_seconds)
        except RedisError:
            return


@dataclass(frozen=True)
class NullCache:
    """Implements ``CachePort`` with no storage — every get misses."""

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        return
