"""Consumer registry.

The registry is typed and fail-fast: duplicate names are rejected.

A consumer may name its own cadence. Most do not and get the worker's poll
interval, because a queue consumer that sleeps is a queue that waits. The ones
that do are the periodic jobs - reaping and retention - where the poll interval
would mean thousands of connections a day spent discovering that nothing is
broken. Declaring it here rather than sleeping inside the consumer keeps the
shutdown event the single thing that wakes every loop.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

ConsumerFn = Callable[[], Awaitable[None]]
CloseFn = Callable[[], Awaitable[None]]


@dataclass
class ConsumerRegistry:
    _consumers: dict[str, ConsumerFn] = field(default_factory=dict)
    _intervals: dict[str, float] = field(default_factory=dict)
    _closers: dict[str, CloseFn] = field(default_factory=dict)

    def register(
        self,
        name: str,
        consumer: ConsumerFn,
        *,
        interval_seconds: float | None = None,
        close: CloseFn | None = None,
    ) -> None:
        """`close`, when given, runs once at an orderly shutdown, after every
        loop has stopped: a lane that holds work across ticks (the
        `studio_runs` lane's claims) hands it back there."""
        if not name.strip():
            raise ValueError("consumer name must not be blank")
        if name in self._consumers:
            raise ValueError(f"consumer {name!r} is already registered")
        if interval_seconds is not None and interval_seconds <= 0:
            raise ValueError(f"consumer {name!r} interval must be positive")
        self._consumers[name] = consumer
        if interval_seconds is not None:
            self._intervals[name] = interval_seconds
        if close is not None:
            self._closers[name] = close

    def all(self) -> dict[str, ConsumerFn]:
        return dict(self._consumers)

    def closers(self) -> dict[str, CloseFn]:
        return dict(self._closers)

    def interval_for(self, name: str, default: float) -> float:
        """This consumer's own cadence, or the worker's poll interval."""
        return self._intervals.get(name, default)
