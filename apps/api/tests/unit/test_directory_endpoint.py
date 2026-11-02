import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.directory import WorkspaceMember
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()
COLLEAGUE = uuid.uuid4()


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
            roles=frozenset({"member"}),
            scopes=self._scopes,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


class FakeDirectory:
    """Records the context it was asked with, so the test can assert scoping."""

    def __init__(self) -> None:
        self.seen: AccessContext | None = None

    async def list_members(self, context: AccessContext) -> list[WorkspaceMember]:
        self.seen = context
        return [
            WorkspaceMember(
                user_id=PRINCIPAL,
                display_name="An Nguyễn",
                email="an@alpha.local",
                role_keys=("member",),
                permission_set_keys=(),
                department="sales",
            ),
            WorkspaceMember(
                user_id=COLLEAGUE,
                display_name="Bình Trần",
                email=None,
                role_keys=("approver", "member"),
                permission_set_keys=(),
                department="sales",
            ),
        ]


def make_container(
    directory: FakeDirectory | None,
    scopes: frozenset[str] = frozenset({"directory.read"}),
) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup(scopes)),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        workspace_directory=directory,
    )


async def call_members(container: ApiContainer) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/directory/members", headers=auth_headers())


def auth_headers() -> dict[str, str]:
    token = DevTokenVerifier(SECRET).issue("dev|an.nguyen", email="an@alpha.local")
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }


async def test_members_are_listed_for_the_callers_workspace() -> None:
    directory = FakeDirectory()
    response = await call_members(make_container(directory))

    assert response.status_code == 200
    body = response.json()
    assert [member["display_name"] for member in body] == ["An Nguyễn", "Bình Trần"]
    assert body[1]["role_keys"] == ["approver", "member"]
    assert body[1]["email"] is None
    # The workspace comes from the verified context, never from the request.
    assert directory.seen is not None
    assert directory.seen.workspace_id == WORKSPACE
    assert directory.seen.tenant_id == TENANT


async def test_members_denied_without_the_scope() -> None:
    response = await call_members(make_container(FakeDirectory(), scopes=frozenset()))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_members_without_a_database_report_infrastructure() -> None:
    response = await call_members(make_container(None))
    assert response.status_code == 503
    assert response.json()["code"] == "upstream_unavailable"
