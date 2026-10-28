"""The admin membership routes, over the real handlers with a fake repository.

Uses the real GrantMembershipHandler/RevokeMembershipHandler so the route's
authorization and shaping are exercised end to end; only the database is faked.
"""

import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.membership_admin import (
    GrantMembershipHandler,
    RevokeMembershipHandler,
    UserRef,
)
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()
TARGET = uuid.uuid4()


class FakeMembershipLookup:
    def __init__(self, scopes: frozenset[str]) -> None:
        self._scopes = scopes

    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if tenant_id != TENANT or workspace_id != WORKSPACE:
            return None
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=PRINCIPAL,
            roles=frozenset({"org_admin"}),
            scopes=self._scopes,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


class FakeRepo:
    """Records writes; the reads answer as a small in-memory catalog."""

    def __init__(self) -> None:
        self.granted: dict[str, object] | None = None
        self.revoked: tuple[uuid.UUID, uuid.UUID] | None = None

    async def find_user_by_email(self, email: str) -> UserRef | None:
        if email == "newhire@fpt.com":
            return UserRef(user_id=TARGET, email=email, display_name="New Hire")
        return None

    async def known_roles(self, role_keys: frozenset[str]) -> frozenset[str]:
        return role_keys & {"sales", "am", "manager", "org_admin"}

    async def scopes_for_roles(self, role_keys: frozenset[str]) -> frozenset[str]:
        # "sales" carries only business scopes; "org_admin" carries a platform.* one.
        return frozenset({"platform.members.write"}) if "org_admin" in role_keys else frozenset()

    async def grant(self, context: AccessContext, *, audit: AuditEvent, **kw: object) -> None:
        self.granted = {**kw, "tenant": context.tenant_id}

    async def revoke(
        self,
        context: AccessContext,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        self.revoked = (user_id, workspace_id)
        return True


def make_container(repo: FakeRepo, scopes: frozenset[str]) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    authz = ScopeAuthorizationService()
    clock, ids = SystemClock(), Uuid4Generator()
    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup(scopes)),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=authz,
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
        grant_membership=GrantMembershipHandler(repo, authz, clock, ids),
        revoke_membership=RevokeMembershipHandler(repo, authz, clock, ids),
    )


def headers() -> dict[str, str]:
    token = DevTokenVerifier(SECRET).issue("dev|admin", email="admin@fpt.com")
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }


async def _post(container: ApiContainer, body: object) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/admin/members", json=body, headers=headers())


async def _delete(container: ApiContainer, user_id: uuid.UUID) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.delete(
                f"/api/v1/admin/members/{user_id}?workspace_id={WORKSPACE}", headers=headers()
            )


async def test_grant_creates_a_membership() -> None:
    repo = FakeRepo()
    body = {
        "email": "newhire@fpt.com",
        "workspace_id": str(WORKSPACE),
        "role_keys": ["sales"],
    }
    response = await _post(make_container(repo, frozenset({"platform.members.write"})), body)

    assert response.status_code == 201
    assert response.json()["display_name"] == "New Hire"
    assert repo.granted is not None
    assert repo.granted["user_id"] == TARGET
    assert repo.granted["role_keys"] == frozenset({"sales"})


async def test_grant_denied_without_the_scope() -> None:
    repo = FakeRepo()
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["sales"]}
    response = await _post(make_container(repo, frozenset()), body)

    assert response.status_code == 403
    assert repo.granted is None


async def test_grant_of_an_administrative_role_is_refused() -> None:
    repo = FakeRepo()
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["org_admin"]}
    response = await _post(make_container(repo, frozenset({"platform.members.write"})), body)

    assert response.status_code == 403  # only a platform admin may grant it
    assert repo.granted is None


async def test_revoke_removes_a_membership() -> None:
    repo = FakeRepo()
    response = await _delete(make_container(repo, frozenset({"platform.members.write"})), TARGET)

    assert response.status_code == 204
    assert repo.revoked == (TARGET, WORKSPACE)
