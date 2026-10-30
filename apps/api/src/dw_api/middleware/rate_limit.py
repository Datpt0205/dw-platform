"""Per-caller rate limiting (fixed 60s window, in-process; runtime-hardening R7.1).

Every request but the health probes counts against its client address. One
that carries `Authorization` counts in the address's bucket at `10 * L`, then in
its bearer's at `L`; one without counts in the address's anonymous bucket at
`L`, as before. The address bucket is what a client cannot step around: a
bearer is not verified at this layer, so a fresh random one per request would
otherwise be a fresh bucket per request.

The address is `request.client.host` as uvicorn builds it: `X-Forwarded-For`
is trusted only from `FORWARDED_ALLOW_IPS` (the proxy, in a deployed profile),
so a client that sends a different one each time is still one address. IPv6
counts by its `/64`, the block one subscriber is handed.

The counters live in this process: the guard at the API's door. A limit per
tenant shared between replicas is `usage-and-limits`'s `RateLimiterPort`
(DO-49), not this; losing these counters only relaxes the limit briefly.
"""

from __future__ import annotations

import hashlib
import ipaddress
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from dw_api.errors import problem_response
from dw_kernel.errors import ErrorCode

_WINDOW_SECONDS = 60.0
_EXEMPT_PATHS = ("/api/v1/health", "/api/v1/ready")
# An address carries this many bearers' worth of requests (si-platform's
# `10 * L`): enough for a few people behind one NAT, not for a key per request.
_ADDRESS_FACTOR = 10
_MAX_KEYS = 10_000


def client_address(request: Request) -> str:
    """The address a request is counted under: the client's, an IPv6 one by
    its `/64`."""
    host = request.client.host if request.client else "unknown"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable,  # type: ignore[type-arg]
        *,
        requests_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._clock = clock
        self._counters: dict[str, tuple[float, int]] = {}

    def _count(self, key: str, now: float) -> tuple[int, float]:
        """One more request in `key`'s window: its count and when it began."""
        window_start, count = self._counters.get(key, (now, 0))
        if now - window_start >= _WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        self._counters[key] = (window_start, count)
        return count, window_start

    def _over(self, now: float, request: Request) -> float | None:
        """The window start of the bucket this request overflows, or None."""
        address = client_address(request)
        token = request.headers.get("Authorization")
        if not token:
            count, start = self._count(f"anon:{address}", now)
            return start if count > self._limit else None
        count, start = self._count(f"ip:{address}", now)
        if count > _ADDRESS_FACTOR * self._limit:
            # Refused by its address: its bearer gets no key of its own.
            return start
        digest = hashlib.sha256(token.encode()).hexdigest()[:32]
        count, start = self._count(f"tok:{digest}", now)
        return start if count > self._limit else None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._limit <= 0 or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        now = self._clock()
        window_start = self._over(now, request)

        if len(self._counters) > _MAX_KEYS:
            # Bound memory under key churn: only windows already over go.
            cutoff = now - _WINDOW_SECONDS
            self._counters = {k: v for k, v in self._counters.items() if v[0] >= cutoff}

        if window_start is not None:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - window_start)))
            # Answered here, before any route or handler, so it is built by
            # the same function every handler uses.
            return problem_response(
                request,
                ErrorCode.RATE_LIMITED,
                "too many requests, slow down",
                details={"limit_per_minute": self._limit},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
