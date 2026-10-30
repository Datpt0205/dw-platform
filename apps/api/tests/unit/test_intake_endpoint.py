"""The intake door's profile rules (leadcare R2.5, R2.7, R2.12; LCP7, LCP17):
closed in any deployed profile, 503 without a signing secret, and a deployed
API without 32 bytes of it does not start. The signature rules against a real
database are `dw_platform`'s `test_intake_db.py`."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from test_dev_endpoints import deployed_settings

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"


class Intake:
    def __init__(self) -> None:
        self.calls = 0

    async def receive(self, **_: object) -> object:
        self.calls += 1
        raise AssertionError("a closed door must not reach the intake")


def make(settings: ApiSettings, intake: Intake | None) -> ApiContainer:
    async def ok() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=settings,
        engine=None,
        health_service=HealthService(probes={"database": ok}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=None,
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
        intake=intake,  # type: ignore[arg-type]
    )


async def post(container: ApiContainer) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/intake/leads", content=b"{}")


async def test_a_deployed_profile_keeps_the_door_closed() -> None:
    """R2.12 (LCP17)."""
    intake = Intake()
    settings = deployed_settings("uat").model_copy(update={"rate_limit_per_minute": 0})
    response = await post(make(settings, intake))
    assert response.status_code == 503
    assert response.json()["details"]["reason_code"] == "intake_disabled"
    assert intake.calls == 0


async def test_without_a_secret_the_door_answers_503() -> None:
    """R2.7 (LCP7)."""
    response = await post(make(ApiSettings(profile="test", dev_secret=SECRET), None))
    assert response.status_code == 503
    assert response.json()["details"]["reason_code"] == "intake_unconfigured"


def test_a_deployed_api_needs_32_bytes_of_intake_secret() -> None:
    """R2.5 (LCP7)."""
    short = deployed_settings("uat").model_copy(
        update={"intake_signing_secret": SecretStr("x" * 16)}
    )
    with pytest.raises(RuntimeError, match="INTAKE_SIGNING_SECRET"):
        short.validate_for_profile()
    deployed_settings("uat").model_copy(
        update={"intake_signing_secret": SecretStr("x" * 32)}
    ).validate_for_profile()
