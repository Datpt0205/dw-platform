"""`RateLimiterPort` answered by a counter in this process (usage-and-limits R7.1, DO-49).

Each process allows `floor(limit / replicas)` calls per window for a key, where
`replicas` is how many processes serve the same callers. A replica that dies
lowers the total rather than raising it, and no Valkey is needed: the cost is
that a caller whose calls all land on one process gets only that process's
share. W2's GCRA on Valkey is the second adapter of the same port.

Behaviour a caller relies on:

* The table is keyed by the `RateLimitKey` itself, its type and every field,
  `tenant_id` included: two companies naming the same source, person or object
  never share a counter (R7.2).
* A refused `acquire` counts nothing, so a key holds at most its share of
  timestamps and a caller who keeps trying is let in again the moment its
  oldest counted call leaves the window, which is the `retry_at` it was given.
* A share of zero (`limit < replicas`) refuses every call, with `retry_at`
  None: the limit fails closed rather than being rounded up to one.
* Time is the injected `UtcClock`. A wall clock stepping backwards lengthens
  the windows it already holds, which errs towards refusing.
* A key not used for its window plus one minute is dropped, swept at most once
  a minute from `acquire`, so the table holds only keys used recently
  (failure-modes #6). There is no cap on how many: each key is a verified
  company id plus a source, person or object the caller already resolved.

No `await` sits between reading and writing a key's entry, so the tasks of one
event loop cannot interleave inside a decision; the instance is not shared
between threads.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dw_kernel.ports import UtcClock
from dw_platform.application.rate_limit import RateDecision, RateLimitKey

_IDLE_GRACE = timedelta(minutes=1)
_SWEEP_EVERY = timedelta(minutes=1)


@dataclass
class _Entry:
    window: timedelta
    last_used: datetime
    stamps: deque[datetime] = field(default_factory=deque)


class InProcessRateLimiter:
    """Implements `RateLimiterPort` with a sliding window per key in memory."""

    def __init__(self, replicas: int, clock: UtcClock) -> None:
        if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 1:
            raise ValueError(f"replicas must be a positive int, got {replicas!r}")
        self._replicas = replicas
        self._clock = clock
        self._entries: dict[RateLimitKey, _Entry] = {}
        self._next_sweep: datetime | None = None

    @property
    def replicas(self) -> int:
        return self._replicas

    def __len__(self) -> int:
        """How many keys the table holds."""
        return len(self._entries)

    async def acquire(self, key: RateLimitKey, limit: int, window: timedelta) -> RateDecision:
        return self._decide(key, limit, window, count=True)

    async def peek(self, key: RateLimitKey, limit: int, window: timedelta) -> RateDecision:
        return self._decide(key, limit, window, count=False)

    def _decide(
        self, key: RateLimitKey, limit: int, window: timedelta, *, count: bool
    ) -> RateDecision:
        if not isinstance(key, RateLimitKey):
            raise TypeError(f"a rate limit key must be a RateLimitKey, not {type(key).__name__}")
        if limit < 0:
            raise ValueError(f"limit must not be negative, got {limit}")
        if window <= timedelta(0):
            raise ValueError(f"window must be positive, got {window}")
        now = self._clock.now()
        if count:
            self._sweep(now)
        share = limit // self._replicas
        if share == 0:
            return RateDecision(allowed=False, retry_at=None)
        entry = self._entries.get(key)
        if entry is not None:
            entry.window = window
            entry.last_used = now
            while entry.stamps and entry.stamps[0] + window <= now:
                entry.stamps.popleft()
        if entry is not None and len(entry.stamps) >= share:
            return RateDecision(allowed=False, retry_at=entry.stamps[0] + window)
        if count:
            if entry is None:
                entry = self._entries[key] = _Entry(window=window, last_used=now)
            entry.stamps.append(now)
        return RateDecision(allowed=True, retry_at=None)

    def _sweep(self, now: datetime) -> None:
        if self._next_sweep is not None and now < self._next_sweep:
            return
        self._next_sweep = now + _SWEEP_EVERY
        idle = [
            key
            for key, entry in self._entries.items()
            if entry.last_used + entry.window + _IDLE_GRACE < now
        ]
        for key in idle:
            del self._entries[key]
