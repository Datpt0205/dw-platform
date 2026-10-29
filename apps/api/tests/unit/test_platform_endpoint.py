"""The /platform provisioning routes, over the real ProvisioningService.

The repository is faked; the service's validation/audit and the route's operator
gate run for real. The gate is the point: a non-operator can never reach these.
"""

import fnmatch
import re
import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi.routing import iter_route_contexts

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.caching_lookup import CachingMembershipLookup
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.identity_bootstrap import BootstrapView
from dw_platform.application.provisioning import (
    OffboardingStatus,
    OperatorRef,
    ProvisioningService,
    TenantSummary,
    UserRef,
)

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
PRINCIPAL = uuid.uuid4()
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
TARGET = uuid.uuid4()


class FakeBootstrap:
    """Stands in for identity resolution: flips the operator bit under test."""

    def __init__(self, is_operator: bool) -> None:
        self._is_operator = is_operator

    async def bootstrap(self, identity: object) -> BootstrapView:
        return BootstrapView(
            principal_id=PRINCIPAL,
            subject="dev|op",
            email="op@fpt.com",
            display_name="Operator",
            memberships=(),
            is_platform_operator=self._is_operator,
        )


class FakeRepo:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.audits: list[dict[str, object]] = []
        self.granted: list[dict[str, object]] = []
        self.removed: list[uuid.UUID] = []
        self.statuses: dict[uuid.UUID, str] = {TENANT: "active"}

    async def list_tenants(self) -> list[TenantSummary]:
        return []

    async def list_users(self) -> list[UserRef]:
        return [UserRef(user_id=TARGET, email="newhire@fpt.com", display_name="New Hire")]

    async def slug_exists(self, slug: str) -> bool:
        return slug == "taken"

    async def plan_exists(self, plan_id: str) -> bool:
        return plan_id == "professional"

    async def create_tenant(self, **kw: object) -> None:
        self.created.append(kw)

    async def set_tenant_status(
        self, tenant_id: uuid.UUID, status: str, *, only_from: frozenset[str] | None = None
    ) -> str | None:
        # The SQL repository's contract: the status the tenant had, None for no
        # tenant, and no change when it is outside `only_from`.
        previous = self.statuses.get(tenant_id)
        if previous is not None and (only_from is None or previous in only_from):
            self.statuses[tenant_id] = status
        return previous

    async def main_workspace_id(self, tenant_id: uuid.UUID) -> uuid.UUID | None:
        return WORKSPACE if tenant_id == TENANT else None

    async def find_user_by_email(self, email: str) -> UserRef | None:
        if email.strip().lower() == "newhire@fpt.com":
            return UserRef(user_id=TARGET, email=email, display_name="New Hire")
        return None

    async def grant_role(self, **kw: object) -> None:
        self.granted.append(kw)

    async def list_operators(self) -> list[OperatorRef]:
        return []

    async def is_operator(self, user_id: uuid.UUID) -> bool:
        return False

    async def add_operator(self, **kw: object) -> None:
        pass

    async def remove_operator(self, user_id: uuid.UUID) -> bool:
        self.removed.append(user_id)
        return True

    async def record_audit(self, **kw: object) -> None:
        self.audits.append(kw)

    async def create_offboarding_request(self, **kw: object) -> None:
        self.created.append(kw)

    async def get_offboarding_status(self, tenant_id: uuid.UUID) -> OffboardingStatus | None:
        return None


def make_container(repo: FakeRepo, is_operator: bool) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=None,
        identity_bootstrap=FakeBootstrap(is_operator),
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
        provisioning=ProvisioningService(repo=repo, clock=SystemClock(), ids=Uuid4Generator()),
    )


def headers() -> dict[str, str]:
    token = DevTokenVerifier(SECRET).issue("dev|op", email="op@fpt.com")
    return {"Authorization": f"Bearer {token}"}


async def _request(container: ApiContainer, method: str, path: str, **kw: object) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers(), **kw)


async def test_non_operator_is_forbidden() -> None:
    response = await _request(make_container(FakeRepo(), False), "GET", "/api/v1/platform/tenants")
    assert response.status_code == 403


async def test_non_operator_cannot_initiate_offboarding() -> None:
    """The same gate, on the newest routes — refused at the dependency, never
    reaching `FakeRepo` (which does not even implement the offboarding methods
    yet in this fixture, and does not need to: 403 happens before any of
    them would be called)."""
    response = await _request(
        make_container(FakeRepo(), False),
        "POST",
        f"/api/v1/platform/tenants/{TARGET}/offboard",
    )
    assert response.status_code == 403


async def test_non_operator_cannot_read_offboarding_status() -> None:
    response = await _request(
        make_container(FakeRepo(), False), "GET", f"/api/v1/platform/tenants/{TARGET}/offboard"
    )
    assert response.status_code == 403


async def test_non_operator_cannot_finalize_offboarding() -> None:
    response = await _request(
        make_container(FakeRepo(), False),
        "POST",
        f"/api/v1/platform/tenants/{TARGET}/offboard/finalize",
    )
    assert response.status_code == 403


async def test_operator_lists_users_for_the_picker() -> None:
    response = await _request(make_container(FakeRepo(), True), "GET", "/api/v1/platform/users")
    assert response.status_code == 200
    assert response.json()[0]["email"] == "newhire@fpt.com"


async def test_operator_creates_a_tenant() -> None:
    repo = FakeRepo()
    response = await _request(
        make_container(repo, True),
        "POST",
        "/api/v1/platform/tenants",
        json={"slug": "fis", "name": "FPT IS", "plan_id": "professional"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "fis"
    assert len(repo.created) == 1
    assert repo.created[0]["plan_id"] == "professional"
    # The write left a provisioning-audit row.
    assert any(a["action"] == "platform.tenant.create" for a in repo.audits)


async def test_create_rejects_an_unknown_plan() -> None:
    repo = FakeRepo()
    response = await _request(
        make_container(repo, True),
        "POST",
        "/api/v1/platform/tenants",
        json={"slug": "fis", "name": "FPT IS", "plan_id": "nope"},
    )
    assert response.status_code == 404
    assert repo.created == []


async def test_create_rejects_a_bad_slug() -> None:
    repo = FakeRepo()
    response = await _request(
        make_container(repo, True),
        "POST",
        "/api/v1/platform/tenants",
        json={"slug": "Not A Slug", "name": "X", "plan_id": "professional"},
    )
    assert response.status_code == 422
    assert repo.created == []


async def test_assign_org_admin_needs_a_signed_in_user() -> None:
    repo = FakeRepo()
    response = await _request(
        make_container(repo, True),
        "POST",
        f"/api/v1/platform/tenants/{TENANT}/org-admins",
        json={"email": "ghost@fpt.com"},
    )
    assert response.status_code == 404
    assert repo.granted == []


async def test_assign_org_admin_grants_the_role() -> None:
    repo = FakeRepo()
    response = await _request(
        make_container(repo, True),
        "POST",
        f"/api/v1/platform/tenants/{TENANT}/org-admins",
        json={"email": "newhire@fpt.com"},
    )
    assert response.status_code == 201
    assert repo.granted and repo.granted[0]["role"] == "org_admin"
    assert repo.granted[0]["workspace_id"] == WORKSPACE


async def test_operator_cannot_remove_themselves() -> None:
    repo = FakeRepo()
    response = await _request(
        make_container(repo, True), "DELETE", f"/api/v1/platform/operators/{PRINCIPAL}"
    )
    assert response.status_code == 422
    assert repo.removed == []


async def test_every_platform_route_refuses_a_non_operator() -> None:
    """Read from the app's own routes, so a route added later (the support
    staff and support request routes of ADR 0024 included) is covered the day
    it exists. A non-operator gets 403 before any repository is reached."""
    container = make_container(FakeRepo(), False)
    app = create_app(container)
    routes = [
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        if route.path and route.path.startswith("/api/v1/platform/")
        for method in route.methods or ()
    ]
    assert ("POST", "/api/v1/platform/support-requests/{grant_id}/assign") in routes
    assert ("DELETE", "/api/v1/platform/support-staff/{user_id}") in routes
    for method, path in routes:
        concrete = re.sub(r"\{[^}]+\}", str(TARGET), path)
        response = await _request(container, method, concrete, json={})
        assert response.status_code == 403, (method, path)


# ---- tenant lifecycle (foundations-hardening R3.1, R3.3; FH7, FH8) -------------


class _HonestCache:
    """Deletes what a pattern matches, as Redis's SCAN + DEL does."""

    def __init__(self) -> None:
        self.entries: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.entries.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self.entries[key] = value

    async def delete_pattern(self, pattern: str) -> None:
        for key in [k for k in self.entries if fnmatch.fnmatchcase(k, pattern)]:
            del self.entries[key]


class _StatusAwareLookup:
    """The uncached lookup's rule: a tenant that is not `active` resolves nothing."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if self.repo.statuses.get(tenant_id) != "active":
            return None
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=TARGET,
            roles=frozenset({"member"}),
            scopes=frozenset(),
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


def _lifecycle_container(repo: FakeRepo, cache: _HonestCache) -> ApiContainer:
    container = make_container(repo, True)
    container.cache = cache
    container.access_context_factory = DbAccessContextFactory(
        CachingMembershipLookup(inner=_StatusAwareLookup(repo), cache=cache)
    )
    return container


async def _as_member(container: ApiContainer) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue("dev|member", email="member@fpt.com")
    member = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/me", headers=member)


async def test_a_lock_stops_the_next_request_of_a_member_whose_context_is_cached() -> None:
    """R3.3 (FH8): the member's context is in the cache when the operator locks."""
    repo, cache = FakeRepo(), _HonestCache()
    container = _lifecycle_container(repo, cache)
    assert (await _as_member(container)).status_code == 200
    assert cache.entries, "the premise: the member's context is cached"

    locked = await _request(container, "POST", f"/api/v1/platform/tenants/{TENANT}/lock")
    assert locked.status_code == 204, locked.text

    assert (await _as_member(container)).status_code == 403


@pytest.mark.parametrize("route", ["lock", "unlock"])
async def test_lock_and_unlock_refuse_an_offboarding_tenant(route: str) -> None:
    """R3.1 (FH7): 409 `tenant_offboarding`, and the status stays."""
    repo = FakeRepo()
    repo.statuses[TENANT] = "offboarding"

    response = await _request(
        make_container(repo, True), "POST", f"/api/v1/platform/tenants/{TENANT}/{route}"
    )

    assert response.status_code == 409, response.text
    assert response.json()["details"]["reason_code"] == "tenant_offboarding"
    assert repo.statuses[TENANT] == "offboarding"
