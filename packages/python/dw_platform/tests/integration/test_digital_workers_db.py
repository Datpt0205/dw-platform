"""Integration: Digital Workers on real PostgreSQL, as `dw_app` under RLS.

digital-worker ticket 01: R1.1 and R2.1 (one transaction writes the principal,
its membership, the DW and its classes), R1.5 (DWK3: another tenant or
workspace sees nothing, an unscoped connection reads nothing), R1.8 (the audit
event shares the transaction), R1.9 (DWK23), R1.11 (DWK25), R1.16 (DWK33),
R1.17 (DWK36) and R2.3 (the levels and the tenant's ceiling, read when asked).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import PageQuery, page_request
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDecisionLevels,
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.directory import SqlWorkspaceDirectory
from dw_platform.adapters.persistence.membership_admin import SqlMembershipAdminRepository
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.adapters.persistence.tenant_members import SqlTenantMembersRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.digital_workers import (
    ChangeState,
    CreateDigitalWorker,
    DecisionAutonomy,
    DigitalWorkerService,
)
from dw_platform.application.identity import context_from
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import DecisionClass, DwConfiguration, DwPeople
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import catalogue_test_keys

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
ISSUER = "dw-dev"
TOOLS = frozenset({"email.send"})


@dataclass(frozen=True)
class _Tools:
    def has_tool(self, name: str) -> bool:
        return name in TOOLS


@dataclass
class World:
    tag: str
    tenant_a: uuid.UUID
    ws1: uuid.UUID
    ws2: uuid.UUID
    tenant_b: uuid.UUID
    ws_b: uuid.UUID
    mailer_role: str
    users: dict[str, uuid.UUID] = field(default_factory=dict)


async def build_world(migrator: AsyncEngine) -> World:
    tag = uuid.uuid4().hex[:10]
    w = World(
        tag=tag,
        tenant_a=uuid.uuid4(),
        ws1=uuid.uuid4(),
        ws2=uuid.uuid4(),
        tenant_b=uuid.uuid4(),
        ws_b=uuid.uuid4(),
        mailer_role=f"dw_mailer_{tag}",
    )
    names = ("creator", "owner", "tech", "tech_narrow", "assigner", "validator", "b_member")
    w.users = {name: uuid.uuid4() for name in names}
    async with migrator.begin() as conn:
        await catalogue_test_keys(conn, ["email.send"])
        await conn.execute(
            sa.text(
                "INSERT INTO platform.roles (key, name, scopes)"
                " VALUES (:k, :k, '[\"email.send\"]'::jsonb)"
            ),
            {"k": w.mailer_role},
        )
        for tenant, workspaces in ((w.tenant_a, (w.ws1, w.ws2)), (w.tenant_b, (w.ws_b,))):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name, status)"
                    " VALUES (:id, :slug, :slug, 'active')"
                ),
                {"id": tenant, "slug": f"dw-{tenant.hex[:12]}"},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
                    " VALUES (:id, :t, 'professional')"
                ),
                {"id": uuid.uuid4(), "t": tenant},
            )
            for n, ws in enumerate(workspaces):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                        " VALUES (:id, :t, :slug, :slug)"
                    ),
                    {"id": ws, "t": tenant, "slug": f"ws{n}"},
                )
        for name, user in w.users.items():
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, email, display_name)"
                    " VALUES (:id, :sub, :email, :name)"
                ),
                {"id": user, "sub": f"dw-{user}", "email": f"{name}-{tag}@dw.test", "name": name},
            )
        for tenant, ws, name, roles in (
            (w.tenant_a, w.ws1, "creator", ["member", "org_admin", w.mailer_role]),
            (w.tenant_a, w.ws2, "creator", ["member", "org_admin", w.mailer_role]),
            (w.tenant_a, w.ws1, "owner", ["member"]),
            (w.tenant_a, w.ws1, "tech", ["member", w.mailer_role]),
            (w.tenant_a, w.ws1, "tech_narrow", ["member"]),
            (w.tenant_a, w.ws1, "assigner", ["member"]),
            (w.tenant_a, w.ws1, "validator", ["approver"]),
            (w.tenant_b, w.ws_b, "b_member", ["approver", "org_admin"]),
        ):
            await add_tenant_member(conn, tenant, w.users[name])
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships"
                    " (id, tenant_id, workspace_id, user_id, role_keys)"
                    " VALUES (:id, :t, :ws, :u, CAST(:r AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tenant,
                    "ws": ws,
                    "u": w.users[name],
                    "r": "[" + ", ".join(f'"{r}"' for r in roles) + "]",
                },
            )
    return w


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def world(migrator: AsyncEngine) -> World:
    return await build_world(migrator)


def service(app_engine: AsyncEngine) -> DigitalWorkerService:
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    return DigitalWorkerService(
        repo=SqlDigitalWorkerRepository(sessions),
        authz=ScopeAuthorizationService(),
        tools=_Tools(),
        members=SqlDwMembershipCheck(sessions),
        roles=SqlTenantMembersRepository(sessions),
        clock=FixedClock(NOW),
        id_generator=Uuid4Generator(),
    )


async def context_of(
    app_engine: AsyncEngine, w: World, name: str, tenant: uuid.UUID, ws: uuid.UUID
) -> AccessContext:
    """The access context sign-in would build: the real lookup."""
    lookup = SqlMembershipLookup(async_sessionmaker(app_engine, expire_on_commit=False))
    access = await lookup.find_access(f"dw-{w.users[name]}", ISSUER, tenant, ws)
    assert access is not None, name
    return context_from(access)


def command(w: World, key: str = "lead_care") -> CreateDigitalWorker:
    return CreateDigitalWorker(
        configuration=DwConfiguration(
            key=key,
            # A service account's name is unique in its company (org-and-principals 03).
            name="Chăm sóc lead" if key == "lead_care" else f"Chăm sóc lead ({key})",
            mandate="Gửi thư chào lead mới.",
            work_kinds=("lead.new",),
            allowed_tools=("email.send",),
            workflow_key="leadcare",
            workflow_version="1.0.0",
            parameters={"reply_wait_seconds": 60},
            role_keys=frozenset({"member", w.mailer_role}),
            decision_classes=(
                DecisionClass("email.first_touch", "external", True, "A3", "A3"),
                DecisionClass("lead.handoff", "internal", True, "A4", "A2"),
            ),
        ),
        people=DwPeople(
            business_owner_id=w.users["owner"],
            technical_owner_id=w.users["tech"],
            work_assigner_id=w.users["assigner"],
            validator_id=w.users["validator"],
        ),
    )


async def _count(migrator: AsyncEngine, sql: str, **params: object) -> int:
    async with migrator.connect() as conn:
        return int((await conn.execute(sa.text(sql), params)).scalar_one())


async def test_a_dw_and_its_principal_are_written_together(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R1.1, R2.1."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))

    async with migrator.connect() as conn:
        user = (
            await conn.execute(
                sa.text("SELECT kind, owner_tenant_id, email FROM platform.users WHERE id = :u"),
                {"u": worker.principal_user_id},
            )
        ).one()
        principal = (
            await conn.execute(
                sa.text(
                    "SELECT tenant_id, owning_workspace_id, owner_user_id"
                    " FROM platform.service_principals WHERE user_id = :u"
                ),
                {"u": worker.principal_user_id},
            )
        ).one()
        roles = (
            await conn.execute(
                sa.text(
                    "SELECT workspace_id, role_keys FROM platform.memberships WHERE user_id = :u"
                ),
                {"u": worker.principal_user_id},
            )
        ).all()
        dw = (
            await conn.execute(
                sa.text(
                    "SELECT state, tenant_id, workspace_id FROM platform.digital_workers"
                    " WHERE id = :id"
                ),
                {"id": worker.id},
            )
        ).one()
        classes = (
            await conn.execute(
                sa.text(
                    "SELECT key, effect_level, reversible, ceiling, earned_level"
                    " FROM platform.dw_decision_classes WHERE dw_id = :id ORDER BY key"
                ),
                {"id": worker.id},
            )
        ).all()
        audits = (
            await conn.execute(
                sa.text(
                    "SELECT action, actor_id FROM platform.audit_events WHERE resource_id = :id"
                ),
                {"id": str(worker.id)},
            )
        ).all()
        # org-and-principals R4.1, R6.1: the principal is an active company member.
        standing = (
            await conn.execute(
                sa.text("SELECT tenant_id, status FROM platform.tenant_members WHERE user_id = :u"),
                {"u": worker.principal_user_id},
            )
        ).all()

    assert [tuple(s) for s in standing] == [(world.tenant_a, "active")]
    assert (user.kind, user.owner_tenant_id, user.email) == ("service", world.tenant_a, None)
    assert tuple(principal) == (world.tenant_a, world.ws1, world.users["owner"])
    assert [(r.workspace_id, sorted(r.role_keys)) for r in roles] == [
        (world.ws1, sorted(["member", world.mailer_role]))
    ]
    assert tuple(dw) == ("draft", world.tenant_a, world.ws1)
    assert [tuple(c) for c in classes] == [
        ("email.first_touch", "external", True, "A3", "A3"),
        ("lead.handoff", "internal", True, "A4", "A2"),
    ]
    assert [(a.action, a.actor_id) for a in audits] == [("dw.created", world.users["creator"])]

    read = await service(app_engine).get(creator, worker.id)
    assert read.people == command(world).people
    assert read.configuration.role_keys == frozenset({"member", world.mailer_role})
    assert read.configuration.parameters == {"reply_wait_seconds": 60}


async def test_a_refused_create_leaves_no_row_behind(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """A second DW with the same key (another name, so its principal row
    passes): the database refuses the DW row after the service user, its
    principal and its membership were written."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    await service(app_engine).create(creator, command(world))
    count = "SELECT count(*) FROM platform.users WHERE kind = 'service' AND owner_tenant_id = :t"
    before = await _count(migrator, count, t=world.tenant_a)

    again = command(world)
    renamed = CreateDigitalWorker(
        configuration=replace(again.configuration, name="Chăm sóc lead (hai)"), people=again.people
    )
    with pytest.raises(ConflictError) as refused:
        await service(app_engine).create(creator, renamed)
    assert refused.value.details["reason_code"] == "dw_key_taken"
    # The same name under another key: the principal's name is taken
    # (org-and-principals 03 step 2), and nothing is left behind either.
    other = command(world, "another_key")
    same_name = CreateDigitalWorker(
        configuration=replace(other.configuration, name=again.configuration.name),
        people=other.people,
    )
    with pytest.raises(ConflictError) as named:
        await service(app_engine).create(creator, same_name)
    assert named.value.details["reason_code"] == "service_principal_name_taken"
    assert await _count(migrator, count, t=world.tenant_a) == before
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.service_principals WHERE tenant_id = :t",
            t=world.tenant_a,
        )
        == before
    )


async def test_another_tenant_or_workspace_does_not_find_a_dw(
    world: World, app_engine: AsyncEngine
) -> None:
    """DWK3."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))

    in_b = await context_of(app_engine, world, "b_member", world.tenant_b, world.ws_b)
    in_ws2 = await context_of(app_engine, world, "creator", world.tenant_a, world.ws2)
    for caller in (in_b, in_ws2):
        with pytest.raises(NotFoundError):
            await service(app_engine).get(caller, worker.id)
        query = PageQuery(key="digital_workers")
        listed = await service(app_engine).list(
            caller, page_request(limit=50, cursor=None, query=query)
        )
        assert worker.id not in {item.id for item in listed.items}

    async with app_engine.connect() as conn:
        for table in ("digital_workers", "dw_decision_classes", "service_principals"):
            found = (await conn.execute(sa.text(f"SELECT count(*) FROM platform.{table}"))).scalar()
            assert found == 0, f"an unscoped connection reads platform.{table}"


async def test_a_state_change_and_its_audit_event_share_one_transaction(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R1.8: an audit event the database refuses (another tenant's, which RLS
    will not let in) takes the state change with it."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))
    repo = SqlDigitalWorkerRepository(async_sessionmaker(app_engine, expire_on_commit=False))
    foreign = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(world.tenant_b),
        workspace_id=WorkspaceId(world.ws_b),
        actor_id=UserId(world.users["owner"]),
        action="dw.state_changed",
        resource_type="digital_worker",
        resource_id=str(worker.id),
        occurred_at=NOW,
    )
    with pytest.raises(DBAPIError):
        await repo.change_state(
            creator, worker.id, current="draft", target="retired", audit=foreign
        )

    assert (await service(app_engine).get(creator, worker.id)).state == "draft"
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.audit_events"
            " WHERE resource_id = :id AND action = 'dw.state_changed'",
            id=str(worker.id),
        )
        == 0
    )


async def test_a_second_person_who_covers_the_principal_puts_it_into_operation(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK23 with the real membership scopes: the narrow Technical Owner lacks
    the mailer role's `email.send`; the other one holds it."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    narrow = command(world)
    narrow_people = DwPeople(
        business_owner_id=world.users["owner"],
        technical_owner_id=world.users["tech_narrow"],
        work_assigner_id=world.users["assigner"],
        validator_id=world.users["validator"],
    )
    worker = await service(app_engine).create(
        creator, CreateDigitalWorker(configuration=narrow.configuration, people=narrow_people)
    )
    tech_narrow = await context_of(app_engine, world, "tech_narrow", world.tenant_a, world.ws1)
    with pytest.raises(PermissionDeniedError) as refused:
        await service(app_engine).change_state(tech_narrow, worker.id, ChangeState("operating"))
    assert refused.value.details["reason_code"] == "grants_not_covered"

    owners = await service(app_engine).replace_people(
        await context_of(app_engine, world, "owner", world.tenant_a, world.ws1),
        worker.id,
        command(world).people,
    )
    assert owners.people.technical_owner_id == world.users["tech"]
    tech = await context_of(app_engine, world, "tech", world.tenant_a, world.ws1)
    moved = await service(app_engine).change_state(tech, worker.id, ChangeState("operating"))
    assert moved.state == "operating"
    actions = "SELECT count(*) FROM platform.audit_events WHERE resource_id = :id AND action = :a"
    assert await _count(migrator, actions, id=str(worker.id), a="dw.state_changed") == 1
    assert await _count(migrator, actions, id=str(worker.id), a="dw.people_changed") == 1


async def test_a_principal_never_signs_in_and_is_never_listed_as_a_person(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK25."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))

    with pytest.raises(DBAPIError, match="a service user has no login"):
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.external_identities (id, user_id, issuer, subject)"
                    " VALUES (:id, :u, 'https://idp.test', :s)"
                ),
                {"id": uuid.uuid4(), "u": worker.principal_user_id, "s": f"svc-{world.tag}"},
            )

    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    directory = SqlWorkspaceDirectory(sessions)
    assert worker.principal_user_id not in {
        m.user_id for m in await directory.list_members(creator)
    }
    in_ws2 = await context_of(app_engine, world, "creator", world.tenant_a, world.ws2)
    assert worker.principal_user_id not in {
        c.user_id for c in await directory.list_candidates(in_ws2)
    }
    members = await SqlTenantMembersRepository(sessions).list_members(creator)
    assert worker.principal_user_id not in {m.user_id for m in members}
    assert world.users["owner"] in {m.user_id for m in members}


async def _as_app(app_engine: AsyncEngine, w: World, sql: str, **params: object) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.workspace_id', :ws, true)"
            ),
            {"t": str(w.tenant_a), "ws": str(w.ws1)},
        )
        await conn.execute(sa.text(sql), params)


async def test_the_accountable_owner_is_a_human_member_of_the_tenant(
    world: World, app_engine: AsyncEngine
) -> None:
    """DWK33 (R1.16): a user of tenant B, and a service user."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    first = await service(app_engine).create(creator, command(world, "first_dw"))
    second = await service(app_engine).create(creator, command(world, "second_dw"))
    update = "UPDATE platform.service_principals SET owner_user_id = :owner WHERE user_id = :p"
    for owner in (world.users["b_member"], second.principal_user_id):
        with pytest.raises(DBAPIError, match="accountable owner"):
            await _as_app(app_engine, world, update, owner=owner, p=first.principal_user_id)
    await _as_app(app_engine, world, update, owner=world.users["tech"], p=first.principal_user_id)


async def test_a_dw_principals_roles_do_not_grow(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK36 (R1.17): no role, no permission set and no workspace added, through
    SQL and through the members repository; narrowing and removing pass."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))
    p = worker.principal_user_id
    before = await _count(
        migrator,
        "SELECT count(*) FROM platform.memberships WHERE user_id = :u AND role_keys ? 'approver'",
        u=p,
    )
    for sql in (
        "UPDATE platform.memberships SET role_keys = role_keys || '[\"approver\"]'::jsonb"
        " WHERE user_id = :p",
        "UPDATE platform.memberships"
        " SET permission_set_keys = '[\"approver_boost\"]'::jsonb WHERE user_id = :p",
    ):
        with pytest.raises(DBAPIError, match="roles of a digital worker principal are fixed"):
            await _as_app(app_engine, world, sql, p=p)

    repo = SqlMembershipAdminRepository(async_sessionmaker(app_engine, expire_on_commit=False))
    audit = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(world.tenant_a),
        workspace_id=WorkspaceId(world.ws2),
        actor_id=UserId(world.users["creator"]),
        action="platform.membership.grant",
        resource_type="membership",
        resource_id=str(p),
        occurred_at=NOW,
    )
    with pytest.raises(ConflictError) as refused:
        await repo.grant(
            creator,
            user_id=p,
            workspace_id=world.ws2,
            role_keys=frozenset({"member"}),
            department="general",
            audit=audit,
        )
    assert refused.value.details["reason_code"] == "dw_principal_roles_fixed"
    assert (
        await _count(migrator, "SELECT count(*) FROM platform.memberships WHERE user_id = :u", u=p)
        == 1
    )
    assert before == 0

    await _as_app(
        app_engine,
        world,
        "UPDATE platform.memberships SET role_keys = '[\"member\"]'::jsonb WHERE user_id = :p",
        p=p,
    )
    await _as_app(app_engine, world, "DELETE FROM platform.memberships WHERE user_id = :p", p=p)
    assert (
        await _count(migrator, "SELECT count(*) FROM platform.memberships WHERE user_id = :u", u=p)
        == 0
    )


async def test_a_human_members_roles_still_grow(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """The trigger touches only a DW's principal."""
    await _as_app(
        app_engine,
        world,
        "UPDATE platform.memberships SET role_keys = role_keys || '[\"approver\"]'::jsonb"
        " WHERE user_id = :u",
        u=world.users["assigner"],
    )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.memberships WHERE user_id = :u"
            " AND role_keys ? 'approver'",
            u=world.users["assigner"],
        )
        == 1
    )


async def test_the_effective_level_reads_the_tenants_ceiling_when_asked(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.3 (DWK6) on the real tables: earned A3 under a class ceiling of A3,
    then the tenant's ceiling lowered to A1 between two questions."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))
    autonomy = DecisionAutonomy(SqlDecisionLevels(async_sessionmaker(app_engine)))
    where = {"tenant_id": world.tenant_a, "workspace_id": world.ws1, "dw_id": worker.id}

    assert await autonomy.effective_level(**where, key="email.first_touch") == "A3"
    assert await autonomy.requires_person(**where, key="email.first_touch") is False

    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET max_autonomy_level = 'A1' WHERE id = :t"),
            {"t": world.tenant_a},
        )
    assert await autonomy.effective_level(**where, key="email.first_touch") == "A1"
    assert await autonomy.requires_person(**where, key="email.first_touch") is True
    assert await autonomy.effective_level(**where, key="no.such_class") == "A0"
    # Another workspace's scope cannot read the class, so it is A0 there.
    elsewhere = {**where, "workspace_id": world.ws2}
    assert await autonomy.effective_level(**elsewhere, key="email.first_touch") == "A0"


async def test_offboarding_exports_and_purges_a_tenant_holding_a_dw(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """The DW tables hold their workspace and principal by RESTRICT: the purge
    order the catalog derives must still clear them, and only this tenant's."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    worker = await service(app_engine).create(creator, command(world))
    in_b = await context_of(app_engine, world, "b_member", world.tenant_b, world.ws_b)
    theirs_command = CreateDigitalWorker(
        configuration=replace(
            command(world, "theirs").configuration, role_keys=frozenset({"member"})
        ),
        people=DwPeople(
            business_owner_id=world.users["b_member"],
            technical_owner_id=world.users["b_member"],
            work_assigner_id=world.users["b_member"],
            validator_id=world.users["b_member"],
        ),
    )
    theirs = await service(app_engine).create(in_b, theirs_command)

    offboarding = SqlTenantOffboarding(
        session_factory=async_sessionmaker(app_engine, expire_on_commit=False)
    )
    exported = {
        f"{batch.schema}.{batch.table}": len(batch.rows)
        async for batch in offboarding.export_rows(world.tenant_a)
    }
    assert exported["platform.digital_workers"] == 1
    assert exported["platform.dw_decision_classes"] == 2
    assert exported["platform.service_principals"] == 1

    # As the lane finds it: offboarding has begun (compliance-pdpl R5.6).
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": world.tenant_a},
        )
    await offboarding.purge_rows(world.tenant_a)

    for table, column in (
        ("digital_workers", "id"),
        ("dw_decision_classes", "dw_id"),
    ):
        assert (
            await _count(
                migrator,
                f"SELECT count(*) FROM platform.{table} WHERE {column} = :id",
                id=worker.id,
            )
            == 0
        ), table
        assert (
            await _count(
                migrator,
                f"SELECT count(*) FROM platform.{table} WHERE {column} = :id",
                id=theirs.id,
            )
            > 0
        ), table
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.service_principals WHERE tenant_id = :t",
            t=world.tenant_a,
        )
        == 0
    )


# ---- org-and-principals 03 (R6.4, R6.19) --------------------------------------


@pytest.fixture
async def admin_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this database: only to watch `pg_stat_activity`."""
    url = db_urls.admin.rsplit("/", 1)[0] + "/" + db_urls.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _set_status(migrator: AsyncEngine, w: World, user: uuid.UUID, status: str) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_members SET status = :s"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"s": status, "t": w.tenant_a, "u": user},
        )


async def _until(check: Callable[[], Awaitable[bool]], *, seconds: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if await check():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_a_suspended_person_of_the_dw_makes_no_dw(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """org-and-principals R6.19 (OP18): a Validator who is a member but not
    `active` reads as no membership: 422 `owner_not_member`, nothing written."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    await _set_status(migrator, world, world.users["validator"], "suspended")
    count = "SELECT count(*) FROM platform.users WHERE kind = 'service' AND owner_tenant_id = :t"
    before = await _count(migrator, count, t=world.tenant_a)
    with pytest.raises(DomainError) as refused:
        await service(app_engine).create(creator, command(world))
    assert refused.value.details["reason_code"] == "owner_not_member"
    assert refused.value.details["users"] == [str(world.users["validator"])]
    assert await _count(migrator, count, t=world.tenant_a) == before


async def test_a_principal_that_is_not_active_is_never_put_into_operation(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """org-and-principals R6.19 (OP18), digital-worker R1.9: a suspended
    principal's empty grants would be covered by anyone. The second person
    (who lacks the mailer role's key) is refused 409 `principal_inactive` and
    the DW stays `draft`; once the principal is `active` again the comparison
    runs and refuses 403 `grants_not_covered`."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    narrow = command(world)
    worker = await service(app_engine).create(
        creator,
        CreateDigitalWorker(
            configuration=narrow.configuration,
            people=replace(narrow.people, technical_owner_id=world.users["tech_narrow"]),
        ),
    )
    second = await context_of(app_engine, world, "tech_narrow", world.tenant_a, world.ws1)

    await _set_status(migrator, world, worker.principal_user_id, "suspended")
    with pytest.raises(ConflictError) as inactive:
        await service(app_engine).change_state(second, worker.id, ChangeState("operating"))
    assert inactive.value.details["reason_code"] == "principal_inactive"
    assert (await service(app_engine).get(creator, worker.id)).state == "draft"

    await _set_status(migrator, world, worker.principal_user_id, "active")
    with pytest.raises(PermissionDeniedError) as uncovered:
        await service(app_engine).change_state(second, worker.id, ChangeState("operating"))
    assert uncovered.value.details["reason_code"] == "grants_not_covered"
    assert (await service(app_engine).get(creator, worker.id)).state == "draft"


async def test_a_standing_is_read_in_one_statement(world: World, app_engine: AsyncEngine) -> None:
    """org-and-principals R6.19: kind, company status and scopes in one
    snapshot, so a suspension between two reads cannot pair `active` with the
    empty scopes it leaves."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    statements: list[str] = []

    def seen(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        if "set_config" not in statement:
            statements.append(statement)

    event.listen(app_engine.sync_engine, "before_cursor_execute", seen)
    try:
        standing = await SqlDwMembershipCheck(async_sessionmaker(app_engine)).standing(
            creator, world.users["tech"]
        )
    finally:
        event.remove(app_engine.sync_engine, "before_cursor_execute", seen)
    assert standing is not None and "email.send" in standing.scopes
    assert len(statements) == 1, statements


async def test_dw_creation_takes_its_role_rows_before_the_access_version_row(
    world: World, app_engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    """org-and-principals R6.4 (step 4, one lock order): B holds the mailer
    role's row as the confirm of tenant-rbac/03 does; DW creation with that
    role waits for it before it writes anything that bumps the tenant's access
    version; B then writes a key into the role (which bumps the version) and
    commits. Neither side is chosen as a deadlock victim (40P01)."""
    creator = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    async with app_engine.connect() as b:
        await b.begin()
        await b.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(world.tenant_a)}
        )
        role = (
            await b.execute(
                sa.text(
                    "SELECT id FROM platform.tenant_roles WHERE tenant_id = :t AND key = :k"
                    " FOR NO KEY UPDATE"
                ),
                {"t": world.tenant_a, "k": world.mailer_role},
            )
        ).scalar_one()
        b_pid = int((await b.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one())

        creating = asyncio.create_task(service(app_engine).create(creator, command(world)))

        async def a_waits() -> bool:
            async with admin_engine.connect() as watch:
                waiting = await watch.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                        "   AND pid <> :b"
                    ),
                    {"b": b_pid},
                )
            return bool(waiting)

        assert await _until(a_waits), "DW creation never waited on the role row"
        await b.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth)"
                " VALUES (:t, :r, 'dw.read', 'workspace')"
            ),
            {"t": world.tenant_a, "r": role},
        )
        await b.commit()
        worker = await creating
    assert worker.configuration.role_keys == frozenset({"member", world.mailer_role})
