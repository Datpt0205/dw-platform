"""The one port every per-company rate limit asks (usage-and-limits R7, DO-49).

A limit that belongs to a company's data (60 events a minute into one Data Hub
source, 20 duplicate-check refusals per person per object in ten minutes) asks
`RateLimiterPort` and never keeps a counter of its own. W1 answers it with a
counter per process (`dw_platform.adapters.rate_limit.InProcessRateLimiter`);
W2's GCRA on Valkey answers the same Protocol, which is why both methods are
`async` although the W1 adapter does no I/O.

The key is typed and verified, never a free string (R7.2): a limit keyed by
the hash of an unverified bearer, as the API's door guard
(`dw_api.middleware.rate_limit`) is, hands a fresh bucket to every fresh token.
`SourceKey` and `PrincipalObjectKey` check their own field types when built,
and an adapter refuses anything that is not one of them, so a caller cannot
pass a string even past mypy.

A key names no purpose. Two callers building the same key type with different
limits would share one counter; in W1 each key type has exactly one caller
(Data Hub for `SourceKey`, custom-objects' duplicate check for
`PrincipalObjectKey`), and a second caller of a shape adds its own key type
rather than reusing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from dw_kernel.ids import TenantId


def _require(owner: object, name: str, kind: type) -> None:
    value = getattr(owner, name)
    if not isinstance(value, kind):
        raise TypeError(
            f"{type(owner).__name__}.{name} must be a {kind.__name__}, not {type(value).__name__}"
        )


@dataclass(frozen=True, slots=True)
class SourceKey:
    """One data source of one company: what a Data Hub event counts under."""

    tenant_id: TenantId
    source_id: UUID

    def __post_init__(self) -> None:
        _require(self, "tenant_id", TenantId)
        _require(self, "source_id", UUID)


@dataclass(frozen=True, slots=True)
class PrincipalObjectKey:
    """One person acting on one object of one company: what a duplicate
    check's refusals count under (custom-objects R7.6)."""

    tenant_id: TenantId
    principal_id: UUID
    object_id: UUID

    def __post_init__(self) -> None:
        _require(self, "tenant_id", TenantId)
        _require(self, "principal_id", UUID)
        _require(self, "object_id", UUID)


# The only keys a limiter accepts; an adapter checks `isinstance(key,
# RateLimitKey)`, so this union is the one list of them.
RateLimitKey = SourceKey | PrincipalObjectKey


@dataclass(frozen=True, slots=True)
class RateDecision:
    """Whether a call may go ahead, and when to try again if not.

    `retry_at` is None when the call is allowed, and also when it is refused
    with no wait that would help (a process share of zero, see the adapter).
    """

    allowed: bool
    retry_at: datetime | None


class RateLimiterPort(Protocol):
    """A sliding-window limit of `limit` calls per `window` for one key."""

    async def acquire(self, key: RateLimitKey, limit: int, window: timedelta) -> RateDecision:
        """Count one call if the key has room, and say whether it had."""
        ...

    async def peek(self, key: RateLimitKey, limit: int, window: timedelta) -> RateDecision:
        """Say whether a call would have room, counting nothing (R7.3)."""
        ...
