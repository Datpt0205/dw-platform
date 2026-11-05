"""Field security's column and its live inputs on PostgreSQL (field-security
ticket 01; revision 2f177d264a27).

The catalog half first: one `access_mode` per field held to two values
(R1.1), a personal-data field created secured whatever the statement says
(R1.2, FS1), a sensitive field never opened by any writer (R1.3, FS11), and
the trigger function nobody calls. Then `FieldAccessService` over
`SqlFieldSecurityInputs` in transactions bound the way the API door
(`act_as_user`) and the runtime's tool session (`agent_record_session`) bind
them: grants at every anchor (R2.4), the boundary chain of a run (R2.5, R2.8),
nothing kept between two transactions (R2.9), another company's grants never
counted (R2.10, FS13), a person other than the caller, and a service account
kept from a sensitive field.

The publish path (R1.6, R1.8) is in `test_object_definitions.py`, beside the
hook's other tests; the revision over existing rows (R1.7) in
`test_access_mode_backfill.py`, on a database of its own.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.record_session import agent_record_session
from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import NotFoundError
from dw_platform.adapters.persistence.tenant_session import TenantScope, bind_tenant
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_platform.testing.record_objects import Lead, plant_object
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.core.application.field_access import ActorUnboundError, FieldAccessService
from dw_studio.core.domain.field_access import FieldAccess, FieldAction
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.testing.records import act_as_run, act_as_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SERVICE = FieldAccessService(SqlFieldSecurityInputs())
BOUNDARIES = SqlActorBoundaries()
LEAD_FIELDS = {"phone": "basic", "email": "basic", "status": "none", "cccd": "sensitive"}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_engine(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


def constraint(error: BaseException) -> str | None:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


def sqlstate(error: BaseException) -> str | None:
    return getattr(getattr(error, "orig", None), "sqlstate", None)


def sha256() -> str:
    return "sha256:" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()


async def member(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    lead: Lead,
    actions: Mapping[str, str],
    fields: Mapping[str, str] | None = None,
    *,
    user: uuid.UUID | None = None,
    workspace: uuid.UUID | None = None,
    kind: str = "human",
) -> uuid.UUID:
    """A member of ``tenant`` (a new person unless ``user`` is given) holding,
    in ``workspace``, a role with ``actions`` (action -> depth) on the lead
    and ``fields`` (api_name -> read or edit)."""
    t = tenant.tenant_id
    workspace = workspace or tenant.main
    if user is None:
        user = await plant_person(conn, t, kind=kind)
    membership = await conn.scalar(
        sa.text(
            "SELECT id FROM platform.memberships"
            " WHERE tenant_id = :t AND workspace_id = :w AND user_id = :u"
        ),
        {"t": t, "w": workspace, "u": user},
    )
    if membership is None:
        joined = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"
            ),
            {"t": t, "u": user},
        )
        if not joined:
            await add_tenant_member(conn, t, user)
        membership = await plant_membership(conn, t, workspace, user)
    role = await plant_role(conn, t, f"r{uuid.uuid4().hex[:10]}", {})
    for action, depth in actions.items():
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_object_privileges"
                " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, :d)"
            ),
            {"t": t, "r": role, "o": lead.object_id, "a": action, "d": depth},
        )
    for api_name, access in (fields or {}).items():
        await conn.execute(
            sa.text(
                "INSERT INTO studio.field_permissions (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :r, :f, :a)"
            ),
            {"t": t, "r": role, "f": lead[api_name], "a": access},
        )
    await assign(conn, t, workspace, membership, role)
    return user


@dataclass(frozen=True)
class Company:
    tenant: PlantedTenant
    lead: Lead

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id


async def plant_company(conn: AsyncConnection, *, workspaces: int = 1) -> Company:
    tenant = await plant_tenant(conn, workspaces=workspaces)
    return Company(tenant, await plant_object(conn, tenant, "lead", dict(LEAD_FIELDS)))


def by_name(access: FieldAccess) -> dict[str, str]:
    return {name: access.levels[f] for f, name in access.api_names.items()}


async def as_user(
    app: AsyncEngine,
    company: Company,
    user: uuid.UUID,
    action: FieldAction = "update",
    *,
    workspace: uuid.UUID | None = None,
) -> dict[str, str]:
    """`for_object` in a transaction bound as ``user``'s Studio request."""
    async with app.begin() as conn:
        await act_as_user(conn, company.t, user)
        if workspace is not None:
            await conn.execute(
                sa.text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(workspace)}
            )
        return by_name(await SERVICE.for_object(conn, company.lead.object_id, action))


# ---- R1.1-R1.3: the column -----------------------------------------------------


async def test_r1_1_r1_2_fs1_one_mode_per_field_and_personal_data_starts_secured(
    migrator: AsyncEngine,
) -> None:
    """Every row has a mode; a personal-data field is created `secured` even
    when the statement says `open`; a field without personal data takes what
    it is given; a third value is refused by name."""
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        for api_name, category, asked in (
            ("hand_basic", "basic", "open"),
            ("hand_sensitive", "sensitive", "open"),
            ("hand_none", "none", "secured"),
        ):
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels,"
                    " type, required, is_unique, indexed, pd_category, sensitive_type,"
                    " storage_kind, field_no, max_length, created_by, updated_by, access_mode)"
                    " VALUES (gen_random_uuid(), :t, :o, :n, '{\"vi\": \"Trường\"}', 'text',"
                    " false, false, false, :c,"
                    " CASE WHEN :c = 'sensitive' THEN 'health' END, 'data',"
                    " (SELECT coalesce(max(field_no), 0) + 1 FROM studio.field_defs"
                    "  WHERE object_id = :o), 255, :u, :u, :m)"
                ),
                {
                    "t": company.t,
                    "o": company.lead.object_id,
                    "n": api_name,
                    "c": category,
                    "u": uuid.uuid4(),
                    "m": asked,
                },
            )
        rows = (
            await conn.execute(
                sa.text("SELECT api_name, access_mode FROM studio.field_defs WHERE object_id = :o"),
                {"o": company.lead.object_id},
            )
        ).all()
        modes: dict[str, str] = {row[0]: row[1] for row in rows}
    assert modes == {
        "phone": "secured",
        "email": "secured",
        "status": "open",
        "cccd": "secured",
        "hand_basic": "secured",
        "hand_sensitive": "secured",
        "hand_none": "secured",
    }
    with pytest.raises(DBAPIError) as refused:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE studio.field_defs SET access_mode = 'public' WHERE id = :f"),
                {"f": company.lead["status"]},
            )
    assert constraint(refused.value) == "ck_field_defs_access_mode"


@pytest.mark.parametrize("role", ["dw_app", "dw_migrator"])
async def test_r1_3_fs11_a_sensitive_field_is_never_opened(
    migrator: AsyncEngine, app_engine: AsyncEngine, role: str
) -> None:
    async with migrator.begin() as conn:
        company = await plant_company(conn)
    engine = app_engine if role == "dw_app" else migrator
    with pytest.raises(DBAPIError) as refused:
        async with engine.begin() as conn:
            await bind_tenant(conn, TenantScope(tenant_id=company.t))
            await conn.execute(
                sa.text("UPDATE studio.field_defs SET access_mode = 'open' WHERE id = :f"),
                {"f": company.lead["cccd"]},
            )
    assert sqlstate(refused.value) == "23514"
    assert constraint(refused.value) == "ck_field_defs_sensitive_is_secured"
    async with migrator.connect() as conn:
        mode = await conn.scalar(
            sa.text("SELECT access_mode FROM studio.field_defs WHERE id = :f"),
            {"f": company.lead["cccd"]},
        )
    assert mode == "secured"


async def test_the_trigger_function_is_no_role_s_to_call(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        calls = {
            role: await conn.scalar(
                sa.text(
                    "SELECT has_function_privilege(:r, 'studio.secure_personal_field()', 'EXECUTE')"
                ),
                {"r": role},
            )
            for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
        }
    assert not any(calls.values()), calls


# ---- R2.2-R2.4: a person's request ----------------------------------------------


async def test_r2_2_r2_3_r2_4_a_request_reads_the_person_s_live_grants(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Sales reads the lead and not its phone or email (FS1); a second role
    giving `edit` adds up with the first's `read`; edit needs `update`."""
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        sales = await member(conn, company.tenant, company.lead, {"read": "tenant"})
        marketing = await member(
            conn, company.tenant, company.lead, {"read": "tenant"}, {"phone": "read"}
        )
        await member(
            conn,
            company.tenant,
            company.lead,
            {"update": "tenant"},
            {"phone": "edit"},
            user=marketing,
        )
    assert await as_user(app_engine, company, sales) == {
        "phone": "hidden",
        "email": "hidden",
        "status": "read",
        "cccd": "hidden",
    }
    found = await as_user(app_engine, company, marketing)
    assert (found["phone"], found["email"], found["status"]) == ("edit", "hidden", "edit")
    assert (await as_user(app_engine, company, marketing, "read"))["phone"] == "read"


async def test_r2_4_grants_anchored_in_another_workspace_still_count(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """`obj.lead.read` at own depth anchored in workspace A, the request made
    from workspace B: the field keys are the person's in the company, whatever
    workspace the request acts in; which records it reaches is RLS's."""
    async with migrator.begin() as conn:
        company = await plant_company(conn, workspaces=2)
        a, b = company.tenant.workspaces
        person = await member(
            conn, company.tenant, company.lead, {"read": "own"}, {"phone": "read"}, workspace=a
        )
    assert (await as_user(app_engine, company, person, workspace=b))["phone"] == "read"


# ---- R2.10 (FS13): another company ------------------------------------------------


async def test_r2_10_fs13_a_grant_in_one_company_is_not_one_in_another(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """One person, a member of A and B, both with an object `lead`; read on
    `phone` only in A. Bound to B, B's `phone` is hidden; A's object is not
    B's to decide (NotFoundError under B's policies)."""
    async with migrator.begin() as conn:
        a = await plant_company(conn)
        b = await plant_company(conn)
        person = await member(conn, a.tenant, a.lead, {"read": "tenant"}, {"phone": "read"})
        await member(conn, b.tenant, b.lead, {"read": "tenant"}, user=person)
    assert (await as_user(app_engine, a, person))["phone"] == "read"
    assert (await as_user(app_engine, b, person))["phone"] == "hidden"
    async with app_engine.begin() as conn:
        await act_as_user(conn, b.t, person)
        with pytest.raises(NotFoundError):
            await SERVICE.for_object(conn, a.lead.object_id)


# ---- for_person, and a service account ---------------------------------------------


async def test_for_person_reads_that_person_s_grants_in_the_bound_company(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        other = await plant_company(conn)
        caller = await member(conn, company.tenant, company.lead, {"read": "tenant"})
        approver = await member(
            conn, company.tenant, company.lead, {"read": "tenant"}, {"phone": "read"}
        )
        stranger = await member(
            conn, other.tenant, other.lead, {"read": "tenant"}, {"phone": "read"}
        )
    async with app_engine.begin() as conn:
        await act_as_user(conn, company.t, caller)
        seen = by_name(await SERVICE.for_person(conn, approver, company.lead.object_id))
        foreign = by_name(await SERVICE.for_person(conn, stranger, company.lead.object_id))
    assert (seen["phone"], seen["email"], seen["status"]) == ("read", "hidden", "read")
    assert set(foreign.values()) == {"hidden"}


async def test_a_service_account_never_reads_a_sensitive_field(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """tenant-rbac R9.9 on this side: a role that creates leads reads a unique
    field (R2.6), a person holding it reads a unique sensitive one too
    (ADR-0106 decision 4), a service account holding it never does."""
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        await conn.execute(
            sa.text(
                "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels, type,"
                " required, is_unique, indexed, pd_category, sensitive_type, storage_kind, slot,"
                " max_length, created_by, updated_by) VALUES (gen_random_uuid(), :t, :o, 'so_cccd',"
                " '{\"vi\": \"Số CCCD\"}', 'text', false, true, false, 'sensitive',"
                " 'identity_credentials', 'slot', 'u01', 255, :u, :u)"
            ),
            {"t": company.t, "o": company.lead.object_id, "u": uuid.uuid4()},
        )
        writes = {"read": "tenant", "create": "tenant"}
        person = await member(conn, company.tenant, company.lead, writes)
        bot = await member(conn, company.tenant, company.lead, writes, kind="service")
    found = await as_user(app_engine, company, person)
    assert found["so_cccd"] == "read"
    writing: tuple[FieldAction, ...] = ("update", "create")
    for action in writing:
        assert (await as_user(app_engine, company, bot, action))["so_cccd"] == "hidden"
    async with app_engine.begin() as conn:
        await act_as_user(conn, company.t, person)
        assert (await SERVICE.for_person(conn, bot, company.lead.object_id)).level_of(
            "so_cccd"
        ) == "hidden"
        assert (await SERVICE.for_person(conn, person, company.lead.object_id)).level_of(
            "so_cccd"
        ) == "read"


# ---- R2.5, R2.8, R2.9: a run ------------------------------------------------------


@dataclass(frozen=True)
class Flow:
    """A `workflow` artifact's sealed version and the company's manifests."""

    version: uuid.UUID
    hash: str
    manifest: str


async def plant_flow(conn: AsyncConnection, company: Company, author: uuid.UUID) -> Flow:
    artifact, version, digest, manifest = uuid.uuid4(), uuid.uuid4(), sha256(), sha256()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
            " row_version) VALUES (:a, :t, 'workflow', :n, :w, 1)"
        ),
        {"a": artifact, "t": company.t, "n": f"wf_{artifact.hex[:12]}", "w": company.tenant.main},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage, version_no,"
            " document_schema, document, row_version, contributor_ids, content_hash,"
            " definition_hash) VALUES (:v, :t, :a, 'draft', 1, 'dw.workflow/v1', '{}', 1,"
            " ARRAY[:u]::uuid[], :c, :h)"
        ),
        {"v": version, "t": company.t, "a": artifact, "u": author, "c": sha256(), "h": digest},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
            " VALUES (:t, :h, CAST(:b AS jsonb))"
        ),
        {"t": company.t, "h": manifest, "b": json.dumps({"run_mode": "live"})},
    )
    return Flow(version, digest, manifest)


async def plant_run(
    migrator: AsyncEngine,
    company: Company,
    principal: uuid.UUID,
    flow: Flow | None,
    kind: str = "agent",
) -> uuid.UUID:
    """A live run row acting as ``principal``; ``flow=None`` is a pack worker's
    run with no Studio root, whose chain is empty."""
    run = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id, worker_version, graph_version, requested_by, run_as_principal_id,"
                " run_mode, run_manifest_hash, artifact_kind, artifact_id, artifact_version_id,"
                " definition_hash, trigger_kind, request_key, root_run_id, chain_depth)"
                " VALUES (:r, :r, :t, :w, 'studio', '1', '1', :p, :as, 'live', :h, :k,"
                " (SELECT artifact_id FROM studio.artifact_versions WHERE id = :v), :v, :d,"
                " :tk, :rk, :r, 0)"
            ),
            {
                "r": run,
                "t": company.t,
                "w": company.tenant.main,
                "p": principal,
                "as": principal if flow else None,
                "h": flow.manifest if flow else None,
                "k": kind if flow else None,
                "v": flow.version if flow else None,
                "d": flow.hash if flow else None,
                "tk": "manual" if flow else None,
                "rk": f"k:{run}" if flow else None,
            },
        )
    return run


async def boundary(
    app: AsyncEngine,
    company: Company,
    flow: Flow,
    fields: Sequence[tuple[str, str]],
    kind: Literal["agent", "workflow"] = "agent",
) -> uuid.UUID:
    async with app.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=company.t))
        return await BOUNDARIES.record(
            conn,
            kind,
            flow.version,
            flow.hash,
            [ObjectBoundary("lead", True, True, True, False, False)],
            [FieldBoundary("lead", name, access) for name, access in fields],  # type: ignore[arg-type]
        )


def run_context(company: Company, run: uuid.UUID, principal: uuid.UUID) -> RunContext:
    return RunContext(
        run_id=run,
        tenant_id=company.t,
        workspace_id=company.tenant.main,
        actor_id=principal,
        run_as_principal_id=principal,
        worker_id="studio:agent:probe",
        worker_version="1.0.0",
        channel="test",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="trace",
        run_mode="live",
    )


async def as_agent(
    app: AsyncEngine, company: Company, run: uuid.UUID, principal: uuid.UUID
) -> dict[str, str]:
    """`for_object` inside the runtime's own tool session for ``run``."""
    sessions = async_sessionmaker(app, class_=AsyncSession, expire_on_commit=False)
    async with agent_record_session(sessions, run_context(company, run, principal)) as session:
        return by_name(await SERVICE.for_object(session, company.lead.object_id))


async def test_r2_5_a_run_reads_within_its_boundary_and_a_wider_one_widens_it(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        principal = await member(
            conn,
            company.tenant,
            company.lead,
            {"read": "tenant", "update": "tenant"},
            {"phone": "edit", "email": "read"},
        )
        narrow = await plant_flow(conn, company, principal)
        wide = await plant_flow(conn, company, principal)
    await boundary(app_engine, company, narrow, [("status", "read")])
    await boundary(app_engine, company, wide, [("status", "edit"), ("phone", "read")])
    first = await as_agent(
        app_engine, company, await plant_run(migrator, company, principal, narrow), principal
    )
    assert first == {"phone": "hidden", "email": "hidden", "status": "read", "cccd": "hidden"}
    second = await as_agent(
        app_engine, company, await plant_run(migrator, company, principal, wide), principal
    )
    assert second == {"phone": "read", "email": "hidden", "status": "edit", "cccd": "hidden"}
    # The same principal as a person: no boundary.
    alone = await as_user(app_engine, company, principal)
    assert (alone["phone"], alone["email"]) == ("edit", "read")


async def test_r2_8_an_empty_chain_hides_all_and_no_actor_is_refused(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A run with no Studio root binds `agent` with an empty chain: every
    field hidden, the open one included, never read as a `user`. A
    transaction that bound no actor gets no `FieldAccess` at all."""
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        principal = await member(
            conn, company.tenant, company.lead, {"read": "tenant"}, {"phone": "read"}
        )
    run = await plant_run(migrator, company, principal, None)
    found = await as_agent(app_engine, company, run, principal)
    assert set(found.values()) == {"hidden"}
    async with app_engine.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=company.t, principal_id=principal))
        with pytest.raises(ActorUnboundError):
            await SERVICE.for_object(conn, company.lead.object_id)


async def test_r2_8_a_workflow_run_is_bound_from_its_row_too(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        principal = await member(
            conn, company.tenant, company.lead, {"read": "tenant"}, {"phone": "read"}
        )
        flow = await plant_flow(conn, company, principal)
    await boundary(app_engine, company, flow, [("phone", "read")], "workflow")
    run = await plant_run(migrator, company, principal, flow, kind="workflow")
    async with app_engine.begin() as conn:
        await act_as_run(conn, company.t, principal, run, kind="workflow")
        found = by_name(await SERVICE.for_object(conn, company.lead.object_id))
    assert found == {"phone": "read", "email": "hidden", "status": "hidden", "cccd": "hidden"}


async def test_r2_9_fs12_a_grant_revoked_between_two_calls_of_one_run(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        company = await plant_company(conn)
        principal = await member(
            conn, company.tenant, company.lead, {"read": "tenant"}, {"phone": "read"}
        )
        flow = await plant_flow(conn, company, principal)
    await boundary(app_engine, company, flow, [("phone", "read"), ("status", "read")])
    run = await plant_run(migrator, company, principal, flow)
    assert (await as_agent(app_engine, company, run, principal))["phone"] == "read"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM studio.field_permissions WHERE tenant_id = :t AND field_id = :f"),
            {"t": company.t, "f": company.lead["phone"]},
        )
    assert (await as_agent(app_engine, company, run, principal))["phone"] == "hidden"
