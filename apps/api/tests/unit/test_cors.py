import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService

pytestmark = pytest.mark.unit

WEB_ORIGIN = "http://localhost:3000"
# CORSMiddleware answers the preflight before routing, so any path exercises
# the method allow-list; this one is a real PUT route (sales intel).
PREFLIGHT_PATH = "/api/v1/intel/accounts/00000000-0000-5000-8000-000000000001/tenders/pref"


def make_container() -> ApiContainer:
    return ApiContainer(
        settings=ApiSettings(profile="test"),
        engine=None,
        health_service=HealthService(probes={}),
        token_verifier=None,
        access_context_factory=None,
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
    )


async def preflight(method: str) -> httpx.Response:
    app = create_app(make_container())
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.options(
                PREFLIGHT_PATH,
                headers={
                    "Origin": WEB_ORIGIN,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type,authorization",
                },
            )


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_preflight_allows_every_method_the_routes_use(method: str) -> None:
    response = await preflight(method)
    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]


async def test_preflight_still_rejects_a_method_no_route_uses() -> None:
    response = await preflight("TRACE")
    assert response.status_code == 400


async def test_a_browser_may_send_conditions_and_read_etag_and_location() -> None:
    # app-standards R3.6: without these the web client could neither send the
    # version it read nor see the one a write returned.
    app = create_app(make_container())
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            preflight_response = await client.options(
                PREFLIGHT_PATH,
                headers={
                    "Origin": WEB_ORIGIN,
                    "Access-Control-Request-Method": "PATCH",
                    "Access-Control-Request-Headers": "if-match,if-none-match",
                },
            )
            simple = await client.get("/api/v1/health", headers={"Origin": WEB_ORIGIN})
    assert preflight_response.status_code == 200
    allowed = preflight_response.headers["access-control-allow-headers"].lower()
    assert "if-match" in allowed and "if-none-match" in allowed
    exposed = {
        h.strip().lower() for h in simple.headers["access-control-expose-headers"].split(",")
    }
    assert {"etag", "location"} <= exposed
