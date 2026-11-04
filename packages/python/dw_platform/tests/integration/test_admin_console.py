"""Integration: the Org Admin console — workspaces, roles, tenant settings.

Same rails as membership admin: an entry point needs a ``platform.*`` scope a
plain member lacks, and every write is bounded to the caller's tenant by RLS. The
cross-tenant test is the one that matters: an admin of one company must never see
or touch another's workspaces.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from rbac_world import role_admin_service, tenant_role
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.admin_console_repo import SqlAdminConsoleRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.admin_console import (
    AdminConsoleService,
    ArchiveWorkspace,
    CreateWorkspace,
    RenameWorkspace,
    UpdateTenantSettings,
)
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.testing.seed_env import seed_test_env

pytestmark = pytest.mark.integration

ALPHA = uuid.UUID("d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d")
ALPHA_WS = uuid.UUID("64764894-718d-5558-ba17-9a2949214063")
ADMIN_SCOPES = frozenset(
    {
        "platform.members.read",
        "platform.workspaces.write",
        "platform.roles.read",
        "platform.tenant.settings.write",
    }
)


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    await seed_test_env(db_urls.migrator)
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


def _admin(tenant: uuid.UUID = ALPHA, workspace: uuid.UUID = ALPHA_WS) -> AccessContext:
    return AccessContext(
        tenant_id=tenant,
        workspace_id=workspace,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        scopes=ADMIN_SCOPES,
        plan_id="professional",
    )


def _service(engine: AsyncEngine) -> AdminConsoleService:
    repo = SqlAdminConsoleRepository(async_sessionmaker(engine, expire_on_commit=False))
    return AdminConsoleService(repo, ScopeAuthorizationService(), SystemClock(), Uuid4Generator())


async def _new_tenant(migrator: AsyncEngine, slug: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(id=tenant_id, slug=slug, name=slug.upper())
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=workspace_id, tenant_id=tenant_id, slug="main", name="Main"
            )
        )
    return tenant_id, workspace_id


async def test_workspace_create_list_rename_archive(app_engine: AsyncEngine) -> None:
    svc = _service(app_engine)

    created = await svc.create_workspace(
        _admin(), CreateWorkspace(name="Miền Bắc", slug="mien-bac")
    )
    assert created.slug == "mien-bac"

    listed = await svc.list_workspaces(_admin())
    mine = next(w for w in listed if w.workspace_id == created.workspace_id)
    assert mine.name == "Miền Bắc"
    assert mine.member_count == 0  # brand new, nobody in it yet
    assert mine.archived is False

    renamed = await svc.rename_workspace(
        _admin(), RenameWorkspace(workspace_id=created.workspace_id, name="Miền Bắc 2")
    )
    assert renamed.name == "Miền Bắc 2"

    await svc.archive_workspace(_admin(), ArchiveWorkspace(workspace_id=created.workspace_id))
    after = next(
        w for w in await svc.list_workspaces(_admin()) if w.workspace_id == created.workspace_id
    )
    assert after.archived is True  # archived, not deleted — the row survives


async def test_a_slug_is_unique_within_the_tenant(app_engine: AsyncEngine) -> None:
    svc = _service(app_engine)
    await svc.create_workspace(_admin(), CreateWorkspace(name="Team A", slug="dup-team"))
    with pytest.raises(ConflictError):
        await svc.create_workspace(_admin(), CreateWorkspace(name="Team B", slug="dup-team"))


async def test_workspaces_never_cross_tenants(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The rail that matters: an admin of one tenant neither sees nor renames a
    workspace in another, even given its id."""
    beta, beta_ws = await _new_tenant(migrator_engine, f"beta-{uuid.uuid4().hex[:8]}")
    svc = _service(app_engine)

    alpha_ws = await svc.create_workspace(
        _admin(), CreateWorkspace(name="Alpha team", slug="a-team")
    )
    beta_admin = _admin(tenant=beta, workspace=beta_ws)
    beta_ws2 = await svc.create_workspace(
        beta_admin, CreateWorkspace(name="Beta team", slug="b-team")
    )

    alpha_ids = {w.workspace_id for w in await svc.list_workspaces(_admin())}
    beta_ids = {w.workspace_id for w in await svc.list_workspaces(beta_admin)}
    assert alpha_ws.workspace_id in alpha_ids and beta_ws2.workspace_id not in alpha_ids
    assert beta_ws2.workspace_id in beta_ids and alpha_ws.workspace_id not in beta_ids

    # Beta's admin cannot rename Alpha's workspace even by id — it reads as absent.
    with pytest.raises(NotFoundError):
        await svc.rename_workspace(
            beta_admin, RenameWorkspace(workspace_id=alpha_ws.workspace_id, name="hijacked")
        )


async def test_a_plain_member_cannot_manage_workspaces(app_engine: AsyncEngine) -> None:
    svc = _service(app_engine)
    member = AccessContext(
        tenant_id=ALPHA,
        workspace_id=ALPHA_WS,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"crm.account.read"}),
        plan_id="professional",
    )
    with pytest.raises(PermissionDeniedError):
        await svc.create_workspace(member, CreateWorkspace(name="Nope", slug="nope"))


async def test_roles_read_lists_the_catalog(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """Since tenant-rbac ticket 03 the catalogue is the role templates a tenant
    clones from (`GET /admin/role-templates`) and the tenant's own roles
    (`GET /admin/roles/{id}`), each with the privileges it carries."""
    svc = role_admin_service(app_engine)
    templates = {t.key: t for t in await svc.list_templates(_admin())}
    assert "member" in templates
    assert ("knowledge.write", "workspace") in {
        (p.key, p.depth) for p in templates["member"].privileges
    }
    org_admin = await svc.get_role(_admin(), await tenant_role(migrator_engine, ALPHA, "org_admin"))
    assert ("platform.members.write", "tenant") in {(p.key, p.depth) for p in org_admin.privileges}
    with pytest.raises(PermissionDeniedError):
        await svc.list_templates(
            AccessContext(
                tenant_id=ALPHA,
                workspace_id=ALPHA_WS,
                principal_id=uuid.uuid4(),
                roles=frozenset({"member"}),
                scopes=frozenset({"approvals.read"}),
                plan_id="professional",
            )
        )


async def test_the_permission_catalogue_lists_every_row_by_area_then_key(
    app_engine: AsyncEngine,
) -> None:
    """tenant-rbac R1.4: six fields on every row, ordered by area then key;
    a caller without `platform.roles.read` is refused."""
    svc = _service(app_engine)
    rows = await svc.list_permissions(_admin())
    assert rows == sorted(rows, key=lambda r: (r.area, r.key))
    by_key = {r.key: r for r in rows}
    assert by_key["platform.sod_waivers.write"].risk == "critical"
    assert by_key["approvals.pending"].status == "retired"
    assert all(r.label_vi.strip() and r.scope_kind and r.risk and r.status for r in rows)
    member = AccessContext(
        tenant_id=ALPHA,
        workspace_id=ALPHA_WS,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"approvals.read"}),
        plan_id="professional",
    )
    with pytest.raises(PermissionDeniedError):
        await svc.list_permissions(member)


async def test_tenant_settings_get_and_update(app_engine: AsyncEngine) -> None:
    svc = _service(app_engine)
    before = await svc.get_tenant_settings(_admin())
    assert before.slug == "tenant-alpha"

    updated = await svc.update_tenant_settings(
        _admin(),
        UpdateTenantSettings(name="FDX Corp", timezone="Asia/Ho_Chi_Minh", locale="vi-VN"),
    )
    assert updated.name == "FDX Corp"
    assert updated.timezone == "Asia/Ho_Chi_Minh"
    assert updated.locale == "vi-VN"

    again = await svc.get_tenant_settings(_admin())
    assert again.name == "FDX Corp" and again.locale == "vi-VN"


@pytest.fixture
async def ceiling_reset(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    """Put tenant ALPHA's ceiling back to its default around a test.

    The test database lives for the whole session and ALPHA is shared by every
    module. A test that set the ceiling and left it leaked into the next module
    that read the default — measured: `test_permission_sets` saw A1 because
    `test_admin_console` ran first and set it, green alone and red together.
    """

    async def _reset() -> None:
        async with migrator_engine.begin() as conn:
            await conn.execute(
                sa.update(tables.tenants)
                .where(tables.tenants.c.id == ALPHA)
                .values(max_autonomy_level="A4")
            )

    await _reset()
    yield
    await _reset()


# ---------------------------------------------------------- autonomy ceiling --
#
# The one control a tenant has over how much its workers do unasked. It can only
# lower a worker's declared level (the runtime takes the more restrictive of the
# two); what is checked here is that an admin can set it, that nobody else can,
# that a value nobody can read never gets in, and that setting it is on the record.


async def test_a_tenant_admin_can_lower_the_autonomy_ceiling(
    app_engine: AsyncEngine, ceiling_reset: None
) -> None:
    svc = _service(app_engine)
    assert (await svc.get_tenant_settings(_admin())).max_autonomy_level == "A4"

    updated = await svc.update_tenant_settings(
        _admin(), UpdateTenantSettings(max_autonomy_level="A1")
    )

    assert updated.max_autonomy_level == "A1"
    assert (await svc.get_tenant_settings(_admin())).max_autonomy_level == "A1"


async def test_changing_the_ceiling_is_on_the_audit_trail(
    app_engine: AsyncEngine, ceiling_reset: None
) -> None:
    """How much a tenant lets its workers do without asking is exactly what an audit
    trail is for. The setting this is modelled on, `record_visibility`, is left out
    of its own audit event; this one is not."""
    await _service(app_engine).update_tenant_settings(
        _admin(), UpdateTenantSettings(max_autonomy_level="A1")
    )

    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(ALPHA)}
        )
        details = (
            await conn.execute(
                sa.text(
                    "SELECT details FROM platform.audit_events"
                    " WHERE action = 'platform.tenant.settings.update'"
                    " ORDER BY occurred_at DESC LIMIT 1"
                )
            )
        ).scalar_one()
    assert details["max_autonomy_level"] == "A1"


async def test_an_unknown_level_is_refused_before_it_reaches_the_database(
    app_engine: AsyncEngine, ceiling_reset: None
) -> None:
    with pytest.raises(DomainError, match="max_autonomy_level"):
        await _service(app_engine).update_tenant_settings(
            _admin(), UpdateTenantSettings(max_autonomy_level="A9")
        )


async def test_a_plain_member_cannot_change_the_ceiling(
    app_engine: AsyncEngine, ceiling_reset: None
) -> None:
    """Otherwise the control is worthless: whoever the ceiling holds back could lift it."""
    member = AccessContext(
        tenant_id=ALPHA,
        workspace_id=ALPHA_WS,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"crm.account.read"}),
        plan_id="professional",
    )

    with pytest.raises(PermissionDeniedError):
        await _service(app_engine).update_tenant_settings(
            member, UpdateTenantSettings(max_autonomy_level="A4")
        )
