"""The public unsubscribe door (compliance-pdpl R3.4, R3.6; CP9, CP10, CP27).

The token is the whole authority: a forged or altered one is the same 404,
with the same body, on GET and POST, and writes nothing; GET only checks, so a
link scanner opts nobody out; POST writes one suppression under the token's own
tenant, and a second POST writes no second row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ports import FixedClock, SystemClock
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.marketing_send import (
    UnsubscribeLinks,
    UnsubscribeService,
    address_hash,
)

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
SIGNING = b"unsubscribe-signing-secret-0123456789"
TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()


@dataclass
class Suppressions:
    rows: set[tuple[uuid.UUID, str, str]] = field(default_factory=set)

    async def suppress(
        self, tenant_id: uuid.UUID, channel: str, hashed: str, *, source: str
    ) -> bool:
        before = len(self.rows)
        self.rows.add((tenant_id, channel, hashed))
        return len(self.rows) > before


def links(clock: object = None) -> UnsubscribeLinks:
    return UnsubscribeLinks(
        secret=SIGNING,
        base_url="https://app.example.com",
        clock=clock or SystemClock(),  # type: ignore[arg-type]
    )


def make(store: Suppressions | None) -> ApiContainer:
    async def ok() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=None,
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
        unsubscribe=None if store is None else UnsubscribeService(links=links(), store=store),
    )


async def call(container: ApiContainer, method: str, token: str) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, f"/api/v1/public/unsubscribe/{token}")


def token_for(tenant: uuid.UUID, address: str = "An@Khach.vn ") -> str:
    url = links().link(tenant, "email", address)
    return url.rsplit("/", 1)[1]


async def test_get_only_checks_and_post_writes_once_under_the_tokens_tenant() -> None:
    """CP9, CP10, CP27."""
    store = Suppressions()
    container = make(store)
    token = token_for(TENANT_A)

    seen = await call(container, "GET", token)
    assert seen.status_code == 200
    assert seen.json() == {"channel": "email", "unsubscribed": False}
    assert store.rows == set()

    done = await call(container, "POST", token)
    assert done.status_code == 200 and done.json()["unsubscribed"] is True
    expected = (TENANT_A, "email", address_hash(TENANT_A, "email", "an@khach.vn"))
    assert store.rows == {expected}
    assert (await call(container, "POST", token)).status_code == 200
    assert store.rows == {expected}


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),  # signature altered
        lambda t: "x" + t,  # body altered
        lambda t: "not-a-token",
    ],
)
async def test_a_token_that_does_not_verify_is_the_same_404_on_both_and_writes_nothing(
    mangle: object,
) -> None:
    """CP10."""
    store = Suppressions()
    container = make(store)
    bad = mangle(token_for(TENANT_A))  # type: ignore[operator]
    seen = await call(container, "GET", bad)
    done = await call(container, "POST", bad)
    assert (seen.status_code, done.status_code) == (404, 404)
    # The same body but for the request's own id.
    per_request = {"request_id", "instance"}
    assert {k: v for k, v in seen.json().items() if k not in per_request} == {
        k: v for k, v in done.json().items() if k not in per_request
    }
    assert store.rows == set()


async def test_a_token_signed_with_another_secret_or_too_old_is_refused() -> None:
    other = UnsubscribeLinks(
        secret=b"another-secret-of-thirty-two-bytes!!", base_url="x", clock=SystemClock()
    )
    forged = other.link(TENANT_A, "email", "an@khach.vn").rsplit("/", 1)[1]
    assert links().verify(forged) is None
    issued = links(FixedClock(SystemClock().now() - timedelta(days=401)))
    old = issued.link(TENANT_A, "email", "an@khach.vn").rsplit("/", 1)[1]
    assert links().verify(old) is None
    fresh = issued.link(TENANT_B, "email", "an@khach.vn")
    assert links().verify(fresh.rsplit("/", 1)[1]) is None


async def test_without_a_signing_secret_the_door_answers_503() -> None:
    response = await call(make(None), "GET", token_for(TENANT_A))
    assert response.status_code == 503
