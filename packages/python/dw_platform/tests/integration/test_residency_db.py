"""Integration: the data route class on PostgreSQL (compliance-pdpl R2.1, R2.2,
R2.4, R2.7, R2.8; CP2, CP4, CP5).

- The three CHECKs hold the kernel's classes, strictest first.
- The gate's reader reads a tenant's and a workspace's class under RLS, never
  another tenant's, and the gate refuses what it cannot read or recognise.
- The admin service tightens with one person and audits it in the same
  transaction, refuses a loosening (409 `second_person_required`), a workspace
  looser than its tenant (422), a caller without `platform.tenant.settings.write`
  (403) and another tenant's workspace (404), and changes no row when it refuses.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_kernel.residency import (
    ROUTE_CLASSES,
    Destination,
    ResidencyGate,
    ResidencyRefusedError,
    TenantRouteScope,
)
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.admin_console_repo import SqlAdminConsoleRepository
from dw_platform.adapters.persistence.residency import SqlRouteClasses
from dw_platform.application.access_context import AccessContext
from dw_platform.application.admin_console import (
    ACTION_RESIDENCY_CHANGED,
    AdminConsoleService,
    UpdateTenantSettings,
    UpdateWorkspace,
)
from dw_platform.application.authorization import ScopeAuthorizationService

pytestmark = pytest.mark.integration

ADMIN_SCOPES = frozenset(
    {"platform.members.read", "platform.workspaces.write", "platform.tenant.settings.write"}
)
VN = Destination("rerank", "vn", "viettel_ai")
FOREIGN = Destination("rerank", "foreign", "openai")


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _tenant(
    migrator: AsyncEngine, tenant_class: str = "vn_only", workspace_class: str | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """A company of its own, planted as the migrator, so no test shares a row."""
    tenant_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    slug = f"res-{tenant_id.hex[:12]}"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(
                id=tenant_id, slug=slug, name=slug, data_route_class=tenant_class
            )
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=workspace_id,
                tenant_id=tenant_id,
                slug="main",
                name="Main",
                data_route_class=workspace_class,
            )
        )
    return tenant_id, workspace_id


def _admin(
    tenant_id: uuid.UUID, workspace_id: uuid.UUID, scopes: frozenset[str] = ADMIN_SCOPES
) -> AccessContext:
    return AccessContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        scopes=scopes,
        plan_id="professional",
    )


def _service(engine: AsyncEngine) -> AdminConsoleService:
    repo = SqlAdminConsoleRepository(async_sessionmaker(engine, expire_on_commit=False))
    return AdminConsoleService(repo, ScopeAuthorizationService(), SystemClock(), Uuid4Generator())


async def _classes(
    migrator: AsyncEngine, tenant_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[str, str | None]:
    async with migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT t.data_route_class, w.data_route_class FROM platform.tenants t"
                    " JOIN platform.workspaces w ON w.tenant_id = t.id"
                    " WHERE t.id = :t AND w.id = :w"
                ),
                {"t": tenant_id, "w": workspace_id},
            )
        ).one()
    return row[0], row[1]


async def _residency_audits(migrator: AsyncEngine, tenant_id: uuid.UUID) -> list[dict[str, object]]:
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT details FROM platform.audit_events"
                " WHERE tenant_id = :t AND action = :a ORDER BY occurred_at"
            ),
            {"t": tenant_id, "a": ACTION_RESIDENCY_CHANGED},
        )
        return [dict(r[0]) for r in rows]


# ---- the catalog --------------------------------------------------------------


async def test_every_check_holds_the_kernel_s_classes(migrator: AsyncEngine) -> None:
    """One owner of the three values: a CHECK written apart from the kernel's
    list fails here, not at the first refused write."""
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                    " WHERE conname IN ('ck_tenants_data_route_class',"
                    " 'ck_workspaces_data_route_class', 'ck_worker_runs_data_route_class')"
                )
            )
        ).all()
    assert len(rows) == 3
    for name, definition in rows:
        positions = [definition.find(f"'{c}'") for c in ROUTE_CLASSES]
        assert all(p >= 0 for p in positions) and positions == sorted(positions), name
        assert definition.count("'::text") == len(ROUTE_CLASSES), name


async def test_a_new_tenant_starts_vn_only_and_a_new_workspace_inherits(
    migrator: AsyncEngine,
) -> None:
    tenant_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(id=tenant_id, slug=f"d-{tenant_id.hex}", name="d")
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=workspace_id, tenant_id=tenant_id, slug="main", name="Main"
            )
        )
    assert await _classes(migrator, tenant_id, workspace_id) == ("vn_only", None)


# ---- the gate's reader ---------------------------------------------------------


async def test_the_reader_reads_both_classes_under_the_tenant_s_rls(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    tenant_id, workspace_id = await _tenant(migrator, "cross_border_full", "vn_only")
    reader = SqlRouteClasses(async_sessionmaker(app_engine))

    assert await reader.route_classes(tenant_id, workspace_id) == ("cross_border_full", "vn_only")
    assert await reader.route_classes(tenant_id, None) == ("cross_border_full", None)


async def test_another_tenant_s_workspace_is_never_read_and_the_gate_refuses(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP2: a scope naming tenant B with tenant A's workspace reads nothing of
    A, and an unknown class sends nothing."""
    _, a_workspace = await _tenant(migrator, "cross_border_full")
    b_tenant, _ = await _tenant(migrator, "cross_border_full")
    reader = SqlRouteClasses(async_sessionmaker(app_engine))

    with pytest.raises(NotFoundError):
        await reader.route_classes(b_tenant, a_workspace)
    with pytest.raises(ResidencyRefusedError):
        await ResidencyGate(classes=reader).check(
            TenantRouteScope(tenant_id=b_tenant, workspace_id=a_workspace), VN
        )


async def test_a_strange_value_in_the_tenant_row_refuses(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP2: with the CHECK dropped on a scratch copy of the rule, a value
    outside the three is never read as a loose class."""
    tenant_id, workspace_id = await _tenant(migrator, "cross_border_full")
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("ALTER TABLE platform.tenants DROP CONSTRAINT ck_tenants_data_route_class")
        )
        await conn.execute(
            sa.text("UPDATE platform.tenants SET data_route_class = 'anywhere' WHERE id = :t"),
            {"t": tenant_id},
        )
    try:
        gate = ResidencyGate(classes=SqlRouteClasses(async_sessionmaker(app_engine)))
        with pytest.raises(ResidencyRefusedError):
            await gate.check(TenantRouteScope(tenant_id=tenant_id, workspace_id=workspace_id), VN)
    finally:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.tenants SET data_route_class = 'vn_only'"
                    " WHERE data_route_class NOT IN"
                    " ('vn_only', 'cross_border_minimised', 'cross_border_full')"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE platform.tenants ADD CONSTRAINT ck_tenants_data_route_class"
                    " CHECK (data_route_class IN"
                    " ('vn_only', 'cross_border_minimised', 'cross_border_full'))"
                )
            )


async def test_a_vn_only_workspace_tightens_its_tenant_for_a_call_outside_a_run(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    tenant_id, workspace_id = await _tenant(migrator, "cross_border_full", "vn_only")
    gate = ResidencyGate(classes=SqlRouteClasses(async_sessionmaker(app_engine)))

    await gate.check(TenantRouteScope(tenant_id=tenant_id, workspace_id=None), FOREIGN)
    with pytest.raises(ResidencyRefusedError):
        await gate.check(TenantRouteScope(tenant_id=tenant_id, workspace_id=workspace_id), FOREIGN)


# ---- the tenant's class (R2.7, R2.8) ---------------------------------------------


@pytest.mark.parametrize("requested", ["cross_border_minimised", "cross_border_full"])
async def test_one_person_cannot_loosen_the_tenant(
    app_engine: AsyncEngine, migrator: AsyncEngine, requested: str
) -> None:
    """CP5: 409 `second_person_required`, the class kept, nothing audited, and
    a name sent with it is not applied either."""
    tenant_id, workspace_id = await _tenant(migrator)

    with pytest.raises(ConflictError) as refused:
        await _service(app_engine).update_tenant_settings(
            _admin(tenant_id, workspace_id),
            UpdateTenantSettings(name="Đổi tên", data_route_class=requested),
        )

    assert refused.value.details["reason_code"] == "second_person_required"
    assert await _classes(migrator, tenant_id, workspace_id) == ("vn_only", None)
    assert await _residency_audits(migrator, tenant_id) == []
    settings = await _service(app_engine).get_tenant_settings(_admin(tenant_id, workspace_id))
    assert settings.name != "Đổi tên"


async def test_one_person_tightens_the_tenant_and_it_is_audited_once(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.8: applied at once, `residency.class_changed` in the same
    transaction; sending the class it holds changes and audits nothing."""
    tenant_id, workspace_id = await _tenant(migrator, "cross_border_full")
    admin = _admin(tenant_id, workspace_id)
    svc = _service(app_engine)

    updated = await svc.update_tenant_settings(
        admin, UpdateTenantSettings(data_route_class="vn_only")
    )
    again = await svc.update_tenant_settings(
        admin, UpdateTenantSettings(data_route_class="vn_only")
    )

    assert updated.data_route_class == again.data_route_class == "vn_only"
    assert await _residency_audits(migrator, tenant_id) == [
        {"scope": "tenant", "from": "cross_border_full", "to": "vn_only"}
    ]


async def test_a_caller_without_the_settings_key_cannot_set_the_tenant_s_class(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP4: 403, the row kept."""
    tenant_id, workspace_id = await _tenant(migrator, "cross_border_full")
    member = _admin(tenant_id, workspace_id, frozenset({"platform.workspaces.write"}))
    member = member.model_copy(update={"roles": frozenset({"member"})})

    with pytest.raises(PermissionDeniedError):
        await _service(app_engine).update_tenant_settings(
            member, UpdateTenantSettings(data_route_class="vn_only")
        )
    assert await _classes(migrator, tenant_id, workspace_id) == ("cross_border_full", None)


# ---- a workspace's class (R2.4, R2.7, R2.8) --------------------------------------


async def test_one_person_tightens_a_workspace_from_inheriting(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    tenant_id, workspace_id = await _tenant(migrator)
    admin = _admin(tenant_id, workspace_id)
    svc = _service(app_engine)
    tighten = UpdateWorkspace(
        workspace_id=workspace_id, data_route_class="vn_only", sets_route_class=True
    )

    ref = await svc.update_workspace(admin, tighten)
    again = await svc.update_workspace(admin, tighten)

    assert ref.data_route_class == again.data_route_class == "vn_only"
    assert await _residency_audits(migrator, tenant_id) == [
        {"scope": "workspace", "from": None, "to": "vn_only"}
    ]


async def test_a_workspace_going_back_to_inheriting_needs_a_second_person(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP5: from `vn_only` back to NULL is a loosening: 409, the row kept."""
    tenant_id, workspace_id = await _tenant(migrator, "vn_only", "vn_only")

    with pytest.raises(ConflictError) as refused:
        await _service(app_engine).update_workspace(
            _admin(tenant_id, workspace_id),
            UpdateWorkspace(
                workspace_id=workspace_id, data_route_class=None, sets_route_class=True
            ),
        )

    assert refused.value.details["reason_code"] == "second_person_required"
    assert await _classes(migrator, tenant_id, workspace_id) == ("vn_only", "vn_only")
    assert await _residency_audits(migrator, tenant_id) == []


async def test_a_workspace_looser_than_its_tenant_is_invalid(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP4: `cross_border_full` under a `vn_only` tenant is 422, before the
    loosening check, and no row changes."""
    tenant_id, workspace_id = await _tenant(migrator)

    with pytest.raises(DomainError) as refused:
        await _service(app_engine).update_workspace(
            _admin(tenant_id, workspace_id),
            UpdateWorkspace(
                workspace_id=workspace_id,
                data_route_class="cross_border_full",
                sets_route_class=True,
            ),
        )

    assert not isinstance(refused.value, ConflictError)
    assert refused.value.details["reason_code"] == "route_class_looser_than_tenant"
    assert await _classes(migrator, tenant_id, workspace_id) == ("vn_only", None)


async def test_a_caller_without_the_settings_key_cannot_set_a_workspace_s_class(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP4: holding `platform.workspaces.write` renames; it does not decide
    where the company's data goes."""
    tenant_id, workspace_id = await _tenant(migrator)
    renamer = _admin(tenant_id, workspace_id, frozenset({"platform.workspaces.write"}))
    renamer = renamer.model_copy(update={"roles": frozenset({"member"})})

    with pytest.raises(PermissionDeniedError):
        await _service(app_engine).update_workspace(
            renamer,
            UpdateWorkspace(
                workspace_id=workspace_id, data_route_class="vn_only", sets_route_class=True
            ),
        )
    assert await _classes(migrator, tenant_id, workspace_id) == ("vn_only", None)


async def test_another_tenant_s_workspace_is_not_found_and_kept(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """CP4: tenant B's admin naming tenant A's workspace gets 404, A's row kept."""
    a_tenant, a_workspace = await _tenant(migrator)
    b_tenant, b_workspace = await _tenant(migrator)

    with pytest.raises(NotFoundError):
        await _service(app_engine).update_workspace(
            _admin(b_tenant, b_workspace),
            UpdateWorkspace(
                workspace_id=a_workspace, data_route_class="vn_only", sets_route_class=True
            ),
        )
    assert await _classes(migrator, a_tenant, a_workspace) == ("vn_only", None)
    assert await _residency_audits(migrator, a_tenant) == []
    assert await _residency_audits(migrator, b_tenant) == []


async def test_an_audit_that_cannot_be_written_leaves_the_class_as_it_was(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.8: the change and its event are one transaction."""
    tenant_id, workspace_id = await _tenant(migrator)
    function = f"refuse_residency_audit_{tenant_id.hex[:8]}"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"CREATE FUNCTION platform.{function}() RETURNS trigger LANGUAGE plpgsql AS $$"
                " BEGIN IF NEW.action = 'residency.class_changed' THEN"
                " RAISE EXCEPTION 'audit refused'; END IF; RETURN NEW; END $$"
            )
        )
        await conn.execute(
            sa.text(
                f"CREATE TRIGGER {function} BEFORE INSERT ON platform.audit_events"
                f" FOR EACH ROW EXECUTE FUNCTION platform.{function}()"
            )
        )
    try:
        with pytest.raises(Exception, match="audit refused"):
            await _service(app_engine).update_workspace(
                _admin(tenant_id, workspace_id),
                UpdateWorkspace(
                    workspace_id=workspace_id, data_route_class="vn_only", sets_route_class=True
                ),
            )
    finally:
        async with migrator.begin() as conn:
            await conn.execute(sa.text(f"DROP TRIGGER {function} ON platform.audit_events"))
            await conn.execute(sa.text(f"DROP FUNCTION platform.{function}()"))
    assert await _classes(migrator, tenant_id, workspace_id) == ("vn_only", None)
