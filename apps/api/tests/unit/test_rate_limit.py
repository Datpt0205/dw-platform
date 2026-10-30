"""Rate limit middleware: per-caller fixed window, 429 with Retry-After."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from dw_api.middleware.rate_limit import RateLimitMiddleware

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def build_app(limit: int, clock: FakeClock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=limit, clock=clock)

    @app.get("/api/v1/things")
    async def things() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


async def _get(app: FastAPI, path: str, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def test_limits_per_caller_and_recovers_after_window() -> None:
    clock = FakeClock()
    app = build_app(limit=3, clock=clock)

    for _ in range(3):
        assert (await _get(app, "/api/v1/things", token="alice")).status_code == 200
    blocked = await _get(app, "/api/v1/things", token="alice")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["code"] == "rate_limited"

    # a different caller is unaffected
    assert (await _get(app, "/api/v1/things", token="bob")).status_code == 200

    clock.value += 61
    assert (await _get(app, "/api/v1/things", token="alice")).status_code == 200


async def test_health_is_exempt_and_zero_disables() -> None:
    clock = FakeClock()
    app = build_app(limit=1, clock=clock)
    for _ in range(5):
        assert (await _get(app, "/api/v1/health")).status_code == 200

    unlimited = build_app(limit=0, clock=clock)
    for _ in range(5):
        assert (await _get(unlimited, "/api/v1/things", token="x")).status_code == 200


async def _get_from(
    app: object, path: str, *, headers: dict[str, str], client: tuple[str, int]
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, client=client)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path, headers=headers)


async def test_a_fresh_bearer_per_request_does_not_step_around_the_address() -> None:
    """runtime-hardening R7.1 (RH20): `10 * L + 1` requests from one address,
    each with its own random bearer: the last is refused."""
    clock = FakeClock()
    limit = 3
    app = build_app(limit=limit, clock=clock)
    answers = [
        (await _get(app, "/api/v1/things", token=f"random-{n}")).status_code
        for n in range(10 * limit + 1)
    ]
    assert answers[:-1] == [200] * (10 * limit)
    assert answers[-1] == 429


async def test_an_anonymous_address_keeps_its_limit_of_l() -> None:
    """R7.1: a request without `Authorization` is counted at `L`, as before;
    the address's bearer allowance is not handed to anonymous traffic."""
    clock = FakeClock()
    app = build_app(limit=3, clock=clock)
    answers = [(await _get(app, "/api/v1/things")).status_code for _ in range(4)]
    assert answers == [200, 200, 200, 429]


async def test_a_forged_forwarded_for_from_an_untrusted_peer_is_one_address() -> None:
    """R7.1 (RH20): uvicorn trusts `X-Forwarded-For` only from
    `FORWARDED_ALLOW_IPS`; a client sending a new one each time is still its
    own address. The control: from the trusted proxy, each is its own."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    clock = FakeClock()
    limit = 2
    forged = ProxyHeadersMiddleware(build_app(limit=limit, clock=clock), trusted_hosts="10.9.9.9")
    answers = [
        (
            await _get_from(
                forged,
                "/api/v1/things",
                headers={"X-Forwarded-For": f"203.0.113.{n}"},
                client=("198.51.100.7", 4000),
            )
        ).status_code
        for n in range(limit + 1)
    ]
    assert answers[-1] == 429

    proxied = ProxyHeadersMiddleware(build_app(limit=limit, clock=clock), trusted_hosts="10.9.9.9")
    answers = [
        (
            await _get_from(
                proxied,
                "/api/v1/things",
                headers={"X-Forwarded-For": f"203.0.113.{n}"},
                client=("10.9.9.9", 4000),
            )
        ).status_code
        for n in range(limit + 1)
    ]
    assert answers == [200] * (limit + 1)


async def test_ipv6_addresses_count_by_their_64() -> None:
    """R7.1: a client rotating addresses inside its `/64` is one address."""
    clock = FakeClock()
    app = build_app(limit=2, clock=clock)
    answers = [
        (
            await _get_from(
                app, "/api/v1/things", headers={}, client=(f"2001:db8:1:2::{n:x}", 4000)
            )
        ).status_code
        for n in range(1, 4)
    ]
    assert answers == [200, 200, 429]
    other = await _get_from(app, "/api/v1/things", headers={}, client=("2001:db8:1:3::1", 4000))
    assert other.status_code == 200
