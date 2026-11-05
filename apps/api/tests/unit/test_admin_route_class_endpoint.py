"""The two routes that take a data route class, over HTTP with the real service
and a fake repository (compliance-pdpl R2.4, R2.7, R2.8; CP4, CP5).

What reaches the problem envelope: 409 `second_person_required` for a
loosening, 422 for a workspace looser than its tenant or a value outside the
three, 403 without `platform.tenant.settings.write`, 404 for a workspace the
tenant does not hold; and `data_route_class: null` sent on purpose is a value
(back to inheriting, a loosening), never "leave as is". What the database
does with a write (RLS, the audit in the same transaction) is
`dw_platform`'s `test_residency_db.py`.
"""

import uuid
from typing import Any

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
from dw_platform.application.admin_console import (
    AdminConsoleService,
    RouteClassWrite,
    TenantSettings,
    UpdateTenantSettings,
    WorkspaceRef,
)
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
SETTINGS = frozenset({"platform.tenant.settings.write", "platform.workspaces.write"})


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
            principal_id=uuid.uuid4(),
            roles=frozenset({"member"}),
            scopes=self._scopes,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


class FakeRepo:
    """Answers like `SqlAdminConsoleRepository` for one tenant and its one
    workspace: a write only while the row still holds `expected`, each audit
    with its write, None for a workspace the tenant does not hold."""

    def __init__(self, tenant_class: str = "vn_only", workspace_class: str | None = None) -> None:
        self.tenant_class = tenant_class
        self.workspace_class = workspace_class
        self.name = "Main"
        self.audits: list[AuditEvent] = []

    def _settings(self) -> TenantSettings:
        return TenantSettings(
            tenant_id=TENANT,
            slug="acme",
            name="Acme",
            status="active",
            record_visibility="open",
            timezone=None,
            locale=None,
            max_autonomy_level="A4",
            data_route_class=self.tenant_class,
        )

    async def get_tenant_settings(self, context: AccessContext) -> TenantSettings | None:
        return self._settings()

    async def update_tenant_settings(
        self,
        context: AccessContext,
        *,
        command: UpdateTenantSettings,
        audit: AuditEvent,
        route_class: RouteClassWrite | None = None,
    ) -> TenantSettings | None:
        if route_class is not None:
            assert route_class.expected == self.tenant_class
            assert route_class.new is not None
            self.tenant_class = route_class.new
            self.audits.append(route_class.audit)
        return self._settings()

    async def route_classes(
        self, context: AccessContext, workspace_id: uuid.UUID
    ) -> tuple[str, str | None] | None:
        if workspace_id != WORKSPACE:
            return None
        return self.tenant_class, self.workspace_class

    async def update_workspace(
        self,
        context: AccessContext,
        *,
        workspace_id: uuid.UUID,
        name: str | None,
        route_class: RouteClassWrite | None,
        audit: AuditEvent | None,
    ) -> WorkspaceRef | None:
        if workspace_id != WORKSPACE:
            return None
        if name is not None:
            self.name = name
        if route_class is not None:
            assert route_class.expected == self.workspace_class
            self.workspace_class = route_class.new
            self.audits.append(route_class.audit)
        if audit is not None:
            self.audits.append(audit)
        return WorkspaceRef(WORKSPACE, "main", self.name, self.workspace_class)

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(f"{name} is not exercised by the route class tests")


def make_container(repo: FakeRepo, scopes: frozenset[str] = SETTINGS) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    authz = ScopeAuthorizationService()
    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup(scopes)),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=authz,
        admin_console=AdminConsoleService(repo, authz, SystemClock(), Uuid4Generator()),
    )


async def _patch(container: ApiContainer, path: str, body: object) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue("dev|admin", email="admin@fpt.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.patch(f"/api/v1/admin{path}", json=body, headers=headers)


async def test_loosening_the_tenant_is_409_and_keeps_the_class() -> None:
    repo = FakeRepo("vn_only")
    response = await _patch(
        make_container(repo), "/tenant", {"data_route_class": "cross_border_full"}
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason_code"] == "second_person_required"
    assert (repo.tenant_class, repo.audits) == ("vn_only", [])


async def test_tightening_the_tenant_is_applied_and_audited() -> None:
    repo = FakeRepo("cross_border_full")
    response = await _patch(make_container(repo), "/tenant", {"data_route_class": "vn_only"})
    assert response.status_code == 200
    assert response.json()["data_route_class"] == "vn_only"
    assert [a.action for a in repo.audits] == ["residency.class_changed"]


async def test_a_value_outside_the_three_is_422() -> None:
    repo = FakeRepo("cross_border_full")
    response = await _patch(make_container(repo), "/tenant", {"data_route_class": "anywhere"})
    assert response.status_code == 422
    assert repo.tenant_class == "cross_border_full"


async def test_null_sent_on_purpose_is_a_loosening_of_the_workspace() -> None:
    """CP5: back to inheriting is 409, the row kept, nothing audited."""
    repo = FakeRepo("vn_only", "vn_only")
    response = await _patch(
        make_container(repo), f"/workspaces/{WORKSPACE}", {"data_route_class": None}
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason_code"] == "second_person_required"
    assert (repo.workspace_class, repo.audits) == ("vn_only", [])


async def test_a_rename_alone_leaves_the_class_alone() -> None:
    """Absent is not null: a name change does not touch the route."""
    repo = FakeRepo("vn_only", "vn_only")
    response = await _patch(make_container(repo), f"/workspaces/{WORKSPACE}", {"name": "Bắc"})
    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": str(WORKSPACE),
        "slug": "main",
        "name": "Bắc",
        "data_route_class": "vn_only",
    }
    assert [a.action for a in repo.audits] == ["platform.workspace.rename"]


async def test_a_workspace_looser_than_its_tenant_is_422() -> None:
    repo = FakeRepo("vn_only")
    response = await _patch(
        make_container(repo), f"/workspaces/{WORKSPACE}", {"data_route_class": "cross_border_full"}
    )
    assert response.status_code == 422
    assert response.json()["details"]["reason_code"] == "route_class_looser_than_tenant"
    assert repo.workspace_class is None


async def test_tightening_a_workspace_is_applied_and_audited() -> None:
    repo = FakeRepo("vn_only")
    response = await _patch(
        make_container(repo), f"/workspaces/{WORKSPACE}", {"data_route_class": "vn_only"}
    )
    assert response.status_code == 200
    assert response.json()["data_route_class"] == "vn_only"
    assert [a.action for a in repo.audits] == ["residency.class_changed"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/tenant", {"data_route_class": "vn_only"}),
        (f"/workspaces/{WORKSPACE}", {"data_route_class": "vn_only"}),
    ],
    ids=["tenant", "workspace"],
)
async def test_without_the_settings_key_it_is_403(path: str, body: object) -> None:
    """CP4: `platform.workspaces.write` renames; it does not set the route."""
    repo = FakeRepo("cross_border_full")
    response = await _patch(
        make_container(repo, frozenset({"platform.workspaces.write"})), path, body
    )
    assert response.status_code == 403
    assert (repo.tenant_class, repo.workspace_class, repo.audits) == ("cross_border_full", None, [])


async def test_a_workspace_the_tenant_does_not_hold_is_404() -> None:
    """CP4: as if it did not exist; nothing written."""
    repo = FakeRepo("vn_only")
    response = await _patch(
        make_container(repo), f"/workspaces/{uuid.uuid4()}", {"data_route_class": "vn_only"}
    )
    assert response.status_code == 404
    assert (repo.workspace_class, repo.audits) == (None, [])
