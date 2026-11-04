"""The admin membership routes, over the real services with a fake repository.

Uses the real RoleAssignmentService/RevokeMembershipHandler so the route's
authorization and shaping are exercised end to end; only the database is faked
(`fake_role_assignments.FakeRoleAssignments`, which refuses where the SQL
adapter does). Placing a person writes the membership at once and proposes each
role for a second person to confirm (tenant-rbac R7.1): 202 with `proposals`.
"""

import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fake_role_assignments import FakeRole, FakeRoleAssignments

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.membership_admin import RevokeMembershipHandler
from dw_platform.application.role_assignments import RoleAssignmentService
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()
TARGET = uuid.uuid4()
WRITE_AND_BIND = frozenset({"platform.members.write", "platform.roles.bind"})


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


def company() -> FakeRoleAssignments:
    """`sales` carries business keys only; `org_admin` is critical and carries
    `platform.roles.write`, which the caller here never holds."""
    repo = FakeRoleAssignments(
        TENANT,
        {WORKSPACE: "Chính"},
        [
            FakeRole("sales", frozenset({"crm.read"})),
            FakeRole(
                "org_admin",
                frozenset({"platform.members.write", "platform.roles.write"}),
                critical=True,
            ),
        ],
    )
    repo.add_person(TARGET, "newhire@fpt.com", "New Hire")
    return repo


class RevokeRepo:
    """Records the one revoke `RevokeMembershipHandler` asks for."""

    def __init__(self) -> None:
        self.revoked: tuple[uuid.UUID, uuid.UUID] | None = None

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


def make_container(
    repo: FakeRoleAssignments, scopes: frozenset[str], revokes: RevokeRepo | None = None
) -> ApiContainer:
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
        role_assignments=RoleAssignmentService(repo, authz, clock, ids),
        revoke_membership=RevokeMembershipHandler(revokes or RevokeRepo(), authz, clock, ids),
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


def _nothing_written(repo: FakeRoleAssignments) -> None:
    assert repo.memberships == {}
    assert repo.assignments == {}
    assert repo.proposals == []
    assert repo.audits == []


async def test_grant_creates_a_membership_and_proposes_its_role() -> None:
    repo = company()
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["sales"]}
    response = await _post(make_container(repo, WRITE_AND_BIND), body)

    assert response.status_code == 202, response.text
    view = response.json()
    assert view["display_name"] == "New Hire"
    assert view["user_id"] == str(TARGET)
    [proposal] = repo.proposals
    assert view["proposals"] == [str(proposal.id)]
    assert proposal.kind == "assignment_grant"
    assert proposal.role_id == repo.roles["sales"].id
    assert proposal.payload["user_id"] == str(TARGET)
    # The membership is there and grants nothing until a second person confirms.
    assert (TARGET, WORKSPACE) in repo.memberships
    assert repo.held(TARGET, WORKSPACE) == frozenset()
    assert [a.action for a in repo.audits] == ["platform.role_change.proposed"]


async def test_grant_denied_without_the_scope() -> None:
    repo = company()
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["sales"]}
    response = await _post(make_container(repo, frozenset()), body)

    assert response.status_code == 403
    _nothing_written(repo)


async def test_grant_needs_the_bind_key_besides_the_members_key() -> None:
    """R8.2: `platform.members.write` alone places nobody in a role."""
    repo = company()
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["sales"]}
    response = await _post(make_container(repo, frozenset({"platform.members.write"})), body)

    assert response.status_code == 403
    _nothing_written(repo)


async def test_grant_of_a_role_the_caller_does_not_hold_is_refused() -> None:
    """R6.1, R6.3: `platform.roles.bind` covers only a role that is not
    critical; any other role needs every key it carries."""
    repo = company()
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["org_admin"]}
    response = await _post(make_container(repo, WRITE_AND_BIND), body)

    assert response.status_code == 403
    details = response.json()["details"]
    assert details["reason_code"] == "rbac_escalation"
    assert details["keys"] == ["platform.roles.write:workspace"]
    _nothing_written(repo)


async def test_grant_with_nobody_to_confirm_writes_nothing() -> None:
    """ADR-0104 decision 10: one refusal refuses the whole request."""
    repo = company()
    repo.checker = False
    body = {"email": "newhire@fpt.com", "workspace_id": str(WORKSPACE), "role_keys": ["sales"]}
    response = await _post(make_container(repo, WRITE_AND_BIND), body)

    assert response.status_code == 409
    assert response.json()["details"]["reason_code"] == "no_checker_available"
    _nothing_written(repo)


async def test_revoke_removes_a_membership() -> None:
    revokes = RevokeRepo()
    response = await _delete(make_container(company(), WRITE_AND_BIND, revokes), TARGET)

    assert response.status_code == 204
    assert revokes.revoked == (TARGET, WORKSPACE)
