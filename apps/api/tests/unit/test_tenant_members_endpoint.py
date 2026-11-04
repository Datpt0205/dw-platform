"""The tenant member routes over the real services, the database faked honestly.

What the route owns: shaping `PUT .../memberships` (200 when it only removes,
202 with `proposals` when it adds a role, tenant-rbac R7.1, R7.6), and
replaying an `Idempotency-Key` without a second write or audit. Every
membership write bumps the tenant's access version, so the route evicts no
cached AccessContext (tenant-rbac R4.1). The rules themselves are
integration-tested against PostgreSQL.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fake_role_assignments import FakeRole, FakeRoleAssignments
from test_idempotency_dependency import MemoryStore

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.idempotency import HttpIdempotency
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.role_assignments import RoleAssignmentService
from dw_platform.application.tenant_members import TenantMembersService

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT, WS1, WS2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
PRINCIPAL, PERSON = uuid.uuid4(), uuid.uuid4()
SCOPES = frozenset(
    {"platform.members.read", "platform.members.write", "platform.roles.bind", "crm.read"}
)


class Lookup:
    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=PRINCIPAL,
            roles=frozenset({"org_admin"}),
            scopes=SCOPES,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


def company() -> FakeRoleAssignments:
    """One person in this tenant, holding `sales` in ws1 and ws2."""
    repo = FakeRoleAssignments(
        TENANT,
        {WS1: "Một", WS2: "Hai"},
        [FakeRole("sales", frozenset({"crm.read"})), FakeRole("am", frozenset({"crm.read"}))],
    )
    repo.add_person(PERSON, "p@example.test", "Person", status="active")
    repo.place(PERSON, WS1, "sales")
    repo.place(PERSON, WS2, "sales")
    return repo


class Cache:
    """A cache that holds nothing: the route evicts nothing either, since every
    membership write bumps the tenant's access version (tenant-rbac R4.1)."""

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        return None


def _container(repo: FakeRoleAssignments, cache: Cache, store: MemoryStore) -> ApiContainer:
    async def ok() -> CheckState:
        return "ok"

    authz = ScopeAuthorizationService()
    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(Lookup()),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=authz,
        cache=cache,
        idempotency=HttpIdempotency(store, SystemClock()),
        tenant_members=TenantMembersService(repo, authz),
        role_assignments=RoleAssignmentService(repo, authz, SystemClock(), Uuid4Generator()),
    )


async def _put(container: ApiContainer, body: object, key: str | None = None) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue("dev|admin", email="admin@example.test")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WS1),
    }
    if key:
        headers["Idempotency-Key"] = key
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.put(
                f"/api/v1/admin/members/{PERSON}/memberships", json=body, headers=headers
            )


BODY = {"memberships": [{"workspace_id": str(WS1), "role_keys": ["sales"]}]}
DROP_WS2 = ["platform.role_assignment.revoke", "platform.membership.revoke"]


async def test_dropping_a_workspace_revokes_its_membership() -> None:
    repo, cache = company(), Cache()
    response = await _put(_container(repo, cache, MemoryStore()), BODY)
    assert response.status_code == 200, response.text
    view = response.json()
    assert [m["workspace_id"] for m in view["memberships"]] == [str(WS1)]
    assert view["applied"] == [{"workspace_id": str(WS2), "role_key": "sales"}]
    assert view["proposals"] == []
    # Only narrows, so applied at once with an audit each (R7.6).
    assert [a.action for a in repo.audits] == DROP_WS2
    assert (PERSON, WS2) not in repo.memberships
    assert repo.proposals == []


async def test_a_role_added_is_a_proposal_and_a_role_dropped_is_gone() -> None:
    """R7.1 (RB32): removing `sales` and adding `am` answers 202, `sales`
    removed, `am` waiting for a second person."""
    repo = company()
    body = {
        "memberships": [
            {"workspace_id": str(WS1), "role_keys": ["am"]},
            {"workspace_id": str(WS2), "role_keys": ["sales"]},
        ]
    }
    response = await _put(_container(repo, Cache(), MemoryStore()), body)
    assert response.status_code == 202, response.text
    view = response.json()
    [proposal] = repo.proposals
    assert view["proposals"] == [str(proposal.id)]
    assert view["applied"] == [{"workspace_id": str(WS1), "role_key": "sales"}]
    assert proposal.payload["workspace_id"] == str(WS1)
    assert proposal.role_id == repo.roles["am"].id
    assert repo.held(PERSON, WS1) == frozenset()
    assert repo.held(PERSON, WS2) == {"sales"}


async def test_a_replayed_key_answers_the_same_and_audits_once() -> None:
    repo, cache, store = company(), Cache(), MemoryStore()
    container = _container(repo, cache, store)
    first = await _put(container, BODY, key="put-1")
    again = await _put(container, BODY, key="put-1")
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert [a.action for a in repo.audits] == DROP_WS2


async def test_an_unknown_body_field_is_refused() -> None:
    response = await _put(
        _container(company(), Cache(), MemoryStore()), {**BODY, "user_id": str(uuid.uuid4())}
    )
    assert response.status_code == 422
