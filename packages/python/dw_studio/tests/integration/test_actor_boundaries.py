"""The run's actor at every door, and the data boundaries of agents and
workflows (record-access ticket 04; revision 996c234cfde3).

Raw SQL on a migrated Postgres, each statement as the role the criterion names.
A company is planted as the migrator; boundaries are recorded as `dw_app`
through `SqlActorBoundaries`, as a publish hook or the run door will; runs are
rows of `platform.worker_runs` shaped as workflow-engine/02's door writes them
(planted as the migrator, with a manifest of their mode). An agent's call reads
through the runtime's `agent_record_session`; a workflow's through
`act_as_run`, the test helper that binds as the workflow runner will.

The versions are sealed drafts of the `workflow` kind planted directly: the
boundary code reads a version's id and hash, never its stage, except the gate
trial (R6.11, R6.12), whose candidate is moved to `evaluating` by the legal path.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_agent_runtime.adapters.record_session import agent_record_session
from dw_agent_runtime.contracts import RunContext
from dw_kernel.run_mode import RunMode
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.adapters.persistence.tenant_session import (
    ActorBindingRefusedError,
    TenantScope,
    bind_tenant,
)
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_platform.testing.record_objects import plant_object
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.testing.lifecycle import move_for_test
from dw_studio.testing.records import act_as_run, plant_record

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

BOUNDARIES = SqlActorBoundaries()
_TABLES = ("actor_boundaries", "actor_boundary_objects", "actor_boundary_fields")


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


def sqlstate(error: BaseException) -> str | None:
    return getattr(getattr(error, "orig", None), "sqlstate", None)


def constraint(error: BaseException) -> str | None:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


def sha256() -> str:
    return "sha256:" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def lead_only(*, read: bool = True, create: bool = False, update: bool = False) -> ObjectBoundary:
    return ObjectBoundary("mkt_lead", read, create, update, False, False)


def every_flag(api_name: str) -> ObjectBoundary:
    return ObjectBoundary(api_name, True, True, True, True, True)


# -- a company ------------------------------------------------------------------


async def _person(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    privileges: Sequence[tuple[uuid.UUID, str, str]],
    *,
    kind: str = "human",
) -> uuid.UUID:
    """A member of ``tenant`` holding, in its main workspace, a role of its
    own with those (object, action, depth) privileges."""
    t = tenant.tenant_id
    who = await plant_person(conn, t, kind=kind)
    membership = await plant_membership(conn, t, tenant.main, who)
    role = await plant_role(conn, t, f"r{uuid.uuid4().hex[:10]}", {})
    for obj, action, depth in privileges:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_object_privileges"
                " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, :d)"
            ),
            {"t": t, "r": role, "o": obj, "a": action, "d": depth},
        )
    await assign(conn, t, tenant.main, membership, role)
    return who


@dataclass(frozen=True)
class World:
    """Lead (with `phone`) and Campaign; `u` and `v` hold read, create, update
    and delete on Lead and read on Campaign, at own depth; records `u_lead`,
    `v_lead`, `u_campaign`; one sealed version and the manifests of each mode."""

    tenant: PlantedTenant
    lead: uuid.UUID
    phone: uuid.UUID
    campaign: uuid.UUID
    u: uuid.UUID
    v: uuid.UUID
    u_lead: uuid.UUID
    v_lead: uuid.UUID
    u_campaign: uuid.UUID
    artifact: uuid.UUID
    version: uuid.UUID
    hash: str
    manifests: dict[str, str]

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id


async def plant_version(
    conn: AsyncConnection, tenant: PlantedTenant, author: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A `workflow` artifact and a sealed draft of it: (artifact, version, hash)."""
    artifact, version, digest = uuid.uuid4(), uuid.uuid4(), sha256()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
            " row_version) VALUES (:a, :t, 'workflow', :n, :w, 1)"
        ),
        {"a": artifact, "t": tenant.tenant_id, "n": f"wf_{artifact.hex[:12]}", "w": tenant.main},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
            " version_no, document_schema, document, row_version, contributor_ids, content_hash,"
            " definition_hash) VALUES (:v, :t, :a, 'draft', 1, 'dw.workflow/v1', '{}', 1,"
            " ARRAY[:u]::uuid[], :c, :h)"
        ),
        {
            "v": version,
            "t": tenant.tenant_id,
            "a": artifact,
            "u": author,
            "c": sha256(),
            "h": digest,
        },
    )
    return artifact, version, digest


async def plant_world(migrator: AsyncEngine) -> World:
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        t, mkt = tenant.tenant_id, tenant.main
        lead_def = await plant_object(conn, tenant, "mkt_lead", {"phone": "basic"})
        lead = lead_def.object_id
        campaign = (await plant_object(conn, tenant, "mkt_campaign", {})).object_id
        grants = [
            *((lead, a, "own") for a in ("read", "create", "update", "delete")),
            (campaign, "read", "own"),
        ]
        u = await _person(conn, tenant, grants)
        v = await _person(conn, tenant, grants)
        u_lead = await plant_record(conn, t, lead, mkt, u, name="Lead của U")
        v_lead = await plant_record(conn, t, lead, mkt, v, name="Lead của V")
        u_campaign = await plant_record(conn, t, campaign, mkt, u, name="Chiến dịch của U")
        artifact, version, digest = await plant_version(conn, tenant, u)
        manifests = {}
        for mode in ("live", "simulate"):
            manifests[mode] = sha256()
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
                    " VALUES (:t, :h, CAST(:b AS jsonb))"
                ),
                {"t": t, "h": manifests[mode], "b": json.dumps({"run_mode": mode})},
            )
    return World(
        tenant,
        lead,
        lead_def["phone"],
        campaign,
        u,
        v,
        u_lead,
        v_lead,
        u_campaign,
        artifact,
        version,
        digest,
        manifests,
    )


@dataclass(frozen=True)
class Parent:
    id: uuid.UUID
    root: uuid.UUID
    depth: int


async def plant_run(
    migrator: AsyncEngine,
    world: World,
    *,
    mode: str = "live",
    principal: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
    kind: str | None = "agent",
    artifact: uuid.UUID | None = None,
    version: uuid.UUID | None = None,
    definition_hash: str | None = None,
    parent: Parent | None = None,
) -> uuid.UUID:
    """A run row as the door writes it; ``kind=None`` is a pack worker's run,
    with no Studio root. ``definition_hash`` defaults to the world's for a
    Studio run (None for a draft's: pass `""`)."""
    run = uuid.uuid4()
    principal = principal or world.u
    studio = kind is not None
    if definition_hash is None:
        definition_hash = world.hash
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id, worker_version, graph_version, requested_by, run_as_principal_id,"
                " run_mode, run_manifest_hash, artifact_kind, artifact_id, artifact_version_id,"
                " definition_hash, trigger_kind, request_key, parent_run_id, root_run_id,"
                " chain_depth) VALUES (:r, :r, :t, :w, 'studio', '1', '1', :by, :as, :m, :h,"
                " :k, :a, :v, :d, :tk, :rk, :p, :root, :depth)"
            ),
            {
                "r": run,
                "t": world.t,
                "w": world.tenant.main,
                "by": requested_by or principal,
                "as": principal if studio else None,
                "m": mode,
                "h": world.manifests[mode] if studio else None,
                "k": kind,
                "a": (artifact or world.artifact) if studio else None,
                "v": (version or world.version) if studio else None,
                "d": (definition_hash or None) if studio else None,
                "tk": ("test" if mode == "simulate" else "manual") if studio else None,
                "rk": f"k:{run}" if studio else None,
                "p": parent.id if parent else None,
                "root": parent.root if parent else run,
                "depth": parent.depth + 1 if parent else 0,
            },
        )
    return run


async def record(
    app: AsyncEngine,
    tenant: uuid.UUID,
    objects: Sequence[ObjectBoundary],
    fields: Sequence[FieldBoundary] = (),
    *,
    version: uuid.UUID,
    digest: str,
    run: uuid.UUID | None = None,
    kind: str = "agent",
) -> uuid.UUID:
    """One boundary through the port, in a transaction of ``tenant`` as `dw_app`."""
    async with app.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=tenant))
        if run is None:
            return await BOUNDARIES.record(conn, kind, version, digest, objects, fields)  # type: ignore[arg-type]
        return await BOUNDARIES.record_provisional(
            conn,
            kind,  # type: ignore[arg-type]
            run,
            version,
            digest,
            objects,
            fields,
        )


def context(
    world: World,
    run: uuid.UUID,
    principal: uuid.UUID,
    *,
    run_mode: RunMode = "simulate",
) -> RunContext:
    """What the runtime carries for ``run``; `run_mode` is `RunContext`'s own
    default unless a test says otherwise, and `bind_actor` never reads it."""
    return RunContext(
        run_id=run,
        tenant_id=world.t,
        workspace_id=world.tenant.main,
        actor_id=principal,
        run_as_principal_id=principal,
        worker_id="studio:agent:probe",
        worker_version="1.0.0",
        channel="test",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="trace",
        run_mode=run_mode,
    )


def sessions(app: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app, class_=AsyncSession, expire_on_commit=False)


async def ids(
    conn: AsyncConnection | AsyncSession, sql: str = "SELECT id FROM studio.records"
) -> set[uuid.UUID]:
    return set((await conn.execute(sa.text(sql))).scalars())


async def as_agent(
    app: AsyncEngine, world: World, run: uuid.UUID, principal: uuid.UUID
) -> set[uuid.UUID]:
    async with agent_record_session(sessions(app), context(world, run, principal)) as session:
        return await ids(session)


async def as_workflow(
    app: AsyncEngine, world: World, run: uuid.UUID, principal: uuid.UUID
) -> set[uuid.UUID]:
    async with app.begin() as conn:
        await act_as_run(conn, world.t, principal, run, kind="workflow")
        return await ids(conn)


_SETTINGS = sa.text(
    "SELECT current_setting('app.actor_kind', true) AS kind,"
    " current_setting('app.user_id', true) AS user_id,"
    " current_setting('app.boundary_id', true) AS boundary,"
    " current_setting('app.run_mode', true) AS mode"
)


async def counts(migrator: AsyncEngine, tenant: uuid.UUID) -> dict[str, int]:
    async with migrator.connect() as conn:
        return {
            table: int(
                await conn.scalar(
                    sa.text(f"SELECT count(*) FROM studio.{table} WHERE tenant_id = :t"),  # nosec B608
                    {"t": tenant},
                )
                or 0
            )
            for table in _TABLES
        }


# -- R6.3 (RA18): the tool session binds the run's actor from its row -------------


async def test_r6_3_the_tool_session_binds_agent_the_run_s_principal_and_boundary(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """`app.user_id` is `coalesce(run_as_principal_id, requested_by)`: the run
    acts as U though a lane asked for it; `app.boundary_id` is the version's."""
    world = await plant_world(migrator)
    boundary = await record(
        app_engine, world.t, [lead_only()], version=world.version, digest=world.hash
    )
    lane = uuid.uuid4()
    run = await plant_run(migrator, world, principal=world.u, requested_by=lane)
    async with agent_record_session(sessions(app_engine), context(world, run, world.u)) as session:
        bound = (await session.execute(_SETTINGS)).one()
    assert (bound.kind, bound.user_id, bound.boundary) == ("agent", str(world.u), str(boundary))
    # A pack worker's run acts as whoever asked (`run_as_principal_id` NULL)
    # and, with no Studio root, has no boundary: it binds and reads nothing.
    pack = await plant_run(migrator, world, kind=None, principal=world.v)
    pack_context = context(world, pack, world.v).model_copy(update={"run_as_principal_id": None})
    async with agent_record_session(sessions(app_engine), pack_context) as session:
        bound = (await session.execute(_SETTINGS)).one()
        seen = await ids(session)
    assert (bound.kind, bound.user_id, bound.boundary) == ("agent", str(world.v), "")
    assert seen == set()


async def test_r6_3_the_mode_is_the_run_row_s_never_the_context_s(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    run = await plant_run(migrator, world, mode="live")
    held = context(world, run, world.u, run_mode="simulate")
    async with agent_record_session(sessions(app_engine), held) as session:
        bound = (await session.execute(_SETTINGS)).one()
    assert held.run_mode == "simulate"
    assert bound.mode == "live"


async def test_r6_3_a_context_naming_another_principal_or_run_binds_nothing(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Gate (m): the principal the context names must be the row's; a run of
    no row under the tenant is refused, and nothing is bound either way."""
    world = await plant_world(migrator)
    run = await plant_run(migrator, world, principal=world.u)
    for wrong in (context(world, run, world.v), context(world, uuid.uuid4(), world.u)):
        with pytest.raises(ActorBindingRefusedError):
            async with agent_record_session(sessions(app_engine), wrong):
                pass  # pragma: no cover - never entered


# -- R6.4 (RA19): the boundary, intersected with the principal's reach ------------


async def test_r6_4_a_lead_boundary_reads_no_campaign_and_never_deletes_a_lead(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Lead with read, create and update, no delete: U's campaign record is
    out though U reaches it; V's lead out by U's reach; a plain update of U's
    lead goes through, its soft delete is refused by WITH CHECK, its DELETE
    touches nothing; a campaign record cannot be created."""
    world = await plant_world(migrator)
    await record(
        app_engine,
        world.t,
        [lead_only(create=True, update=True)],
        version=world.version,
        digest=world.hash,
    )
    run = await plant_run(migrator, world)
    run_context = context(world, run, world.u)
    async with agent_record_session(sessions(app_engine), run_context) as session:
        seen = await ids(session)
        renamed = cast(
            "CursorResult[Any]",
            await session.execute(
                sa.text("UPDATE studio.records SET name = 'Đổi tên' WHERE id = :r"),
                {"r": world.u_lead},
            ),
        ).rowcount
        deleted = cast(
            "CursorResult[Any]",
            await session.execute(
                sa.text("DELETE FROM studio.records WHERE id = :r"), {"r": world.u_lead}
            ),
        ).rowcount
        made = cast(
            "CursorResult[Any]",
            await session.execute(
                sa.text(
                    "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id,"
                    " owner_kind, owner_id, name, created_by, updated_by) VALUES"
                    " (gen_random_uuid(), :t, :o, :w, 'user', :u, 'Lead mới', :u, :u)"
                ),
                {"t": world.t, "o": world.lead, "w": world.tenant.main, "u": world.u},
            ),
        ).rowcount
    assert seen == {world.u_lead}
    assert (renamed, deleted, made) == (1, 0, 1)
    for statement, values in (
        ("UPDATE studio.records SET deleted_at = now() WHERE id = :r", {"r": world.u_lead}),
        (
            "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
            " owner_id, name, created_by, updated_by) VALUES (gen_random_uuid(), :t, :o, :w,"
            " 'user', :u, 'Chiến dịch mới', :u, :u)",
            {"t": world.t, "o": world.campaign, "w": world.tenant.main, "u": world.u},
        ),
    ):
        with pytest.raises(DBAPIError) as caught:
            async with agent_record_session(sessions(app_engine), run_context) as session:
                await session.execute(sa.text(statement), values)
        assert sqlstate(caught.value) == "42501", statement
    async with migrator.connect() as conn:
        still = await conn.scalar(
            sa.text("SELECT deleted_at IS NULL FROM studio.records WHERE id = :r"),
            {"r": world.u_lead},
        )
    assert still is True


async def read_lead_tool(
    factory: async_sessionmaker[AsyncSession], run: RunContext, record_id: str
) -> dict[str, Any]:
    """A fixture Studio object tool: one record by id, through the tool session,
    as `agent-builder/03`'s object tools will read."""
    async with agent_record_session(factory, run) as session:
        row = (
            await session.execute(
                sa.text("SELECT id, name FROM studio.records WHERE id = CAST(:r AS uuid)"),
                {"r": record_id},
            )
        ).one_or_none()
    if row is None:
        return {"error": "not_found"}
    return {"id": str(row.id), "name": row.name}


async def test_r6_4_an_injected_request_for_another_person_s_lead_finds_nothing(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The model, told by injected text to fetch V's lead by its id, calls the
    tool with it: the policy, not the prompt, answers not found."""
    world = await plant_world(migrator)
    await record(app_engine, world.t, [lead_only()], version=world.version, digest=world.hash)
    run = context(world, await plant_run(migrator, world), world.u)
    injected = await read_lead_tool(sessions(app_engine), run, str(world.v_lead))
    own = await read_lead_tool(sessions(app_engine), run, str(world.u_lead))
    assert injected == {"error": "not_found"}
    assert own == {"id": str(world.u_lead), "name": "Lead của U"}


async def test_r6_4_a_child_run_reads_the_intersection_of_its_chain(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Gate (f): the parent's boundary holds Lead read only, the child's Lead
    and Campaign with every flag; the child reads no campaign and edits no lead."""
    world = await plant_world(migrator)
    async with migrator.begin() as conn:
        child_artifact, child_version, child_hash = await plant_version(conn, world.tenant, world.u)
    parent_boundary = await record(
        app_engine,
        world.t,
        [lead_only()],
        version=world.version,
        digest=world.hash,
        kind="workflow",
    )
    child_boundary = await record(
        app_engine,
        world.t,
        [every_flag("mkt_lead"), every_flag("mkt_campaign")],
        version=child_version,
        digest=child_hash,
        kind="workflow",
    )
    parent = await plant_run(migrator, world, kind="workflow")
    child = await plant_run(
        migrator,
        world,
        kind="workflow",
        artifact=child_artifact,
        version=child_version,
        definition_hash=child_hash,
        parent=Parent(parent, parent, 0),
    )
    async with app_engine.begin() as conn:
        await act_as_run(conn, world.t, world.u, child, kind="workflow")
        bound = (await conn.execute(_SETTINGS)).one()
        seen = await ids(conn)
        edited = (
            await conn.execute(
                sa.text("UPDATE studio.records SET name = 'Đổi' WHERE id = :r"),
                {"r": world.u_lead},
            )
        ).rowcount
    assert (bound.kind, bound.boundary) == ("workflow", f"{parent_boundary},{child_boundary}")
    assert seen == {world.u_lead}
    assert edited == 0


# -- R6.5 (RA19): no boundary, another company's, a link of another company's --------


async def test_r6_5_no_boundary_or_another_company_s_reads_nothing(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    other = await plant_world(migrator)
    theirs = await record(
        app_engine, other.t, [every_flag("mkt_lead")], version=other.version, digest=other.hash
    )
    # The version has no boundary recorded: the chain is empty.
    run = await plant_run(migrator, world)
    async with agent_record_session(sessions(app_engine), context(world, run, world.u)) as session:
        bound = (await session.execute(_SETTINGS)).one()
        unbounded = await ids(session)
    assert (bound.kind, bound.boundary) == ("agent", "")
    assert unbounded == set()
    ours = await record(
        app_engine, world.t, [every_flag("mkt_lead")], version=world.version, digest=world.hash
    )
    # A child whose own version has no boundary, under a parent that has one:
    # one missing link empties the whole chain.
    async with migrator.begin() as conn:
        child_artifact, child_version, child_hash = await plant_version(conn, world.tenant, world.u)
    child = await plant_run(
        migrator,
        world,
        artifact=child_artifact,
        version=child_version,
        definition_hash=child_hash,
        parent=Parent(run, run, 0),
    )
    async with agent_record_session(
        sessions(app_engine), context(world, child, world.u)
    ) as session:
        child_bound = (await session.execute(_SETTINGS)).one().boundary
        child_seen = await ids(session)
    assert (child_bound, child_seen) == ("", set())
    seen: dict[str, set[uuid.UUID]] = {}
    for name, value in (
        ("ours", str(ours)),
        ("theirs", str(theirs)),
        ("a link of theirs", f"{ours},{theirs}"),
        ("malformed", f"{ours};drop"),
    ):
        async with agent_record_session(
            sessions(app_engine), context(world, run, world.u)
        ) as session:
            await session.execute(
                sa.text("SELECT set_config('app.boundary_id', :b, true)"), {"b": value}
            )
            seen[name] = await ids(session)
    assert seen == {
        "ours": {world.u_lead},
        "theirs": set(),
        "a link of theirs": set(),
        "malformed": set(),
    }


# -- R6.6 (RA19): live reach on resume; no residue on the connection ----------------


async def test_r6_6_a_resumed_run_reads_with_the_principal_s_reach_now(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The run pauses for an approval after reading U's lead; U loses the role
    assignment; the first transaction after the resume reads nothing."""
    world = await plant_world(migrator)
    await record(app_engine, world.t, [lead_only()], version=world.version, digest=world.hash)
    run = await plant_run(migrator, world)
    before = await as_agent(app_engine, world, run, world.u)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "DELETE FROM platform.role_assignments a USING platform.memberships m"
                " WHERE a.tenant_id = :t AND m.tenant_id = :t AND a.membership_id = m.id"
                "   AND m.user_id = :u"
            ),
            {"t": world.t, "u": world.u},
        )
    after = await as_agent(app_engine, world, run, world.u)
    assert before == {world.u_lead}
    assert after == set()


async def test_r6_6_the_next_transaction_on_the_connection_carries_no_actor(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    await record(app_engine, world.t, [lead_only()], version=world.version, digest=world.hash)
    run = await plant_run(migrator, world)
    async with app_engine.connect() as conn:
        async with conn.begin():
            await act_as_run(conn, world.t, world.u, run)
            first = await ids(conn)
        async with conn.begin():
            await bind_tenant(conn, TenantScope(tenant_id=world.t, principal_id=world.u))
            bound = (await conn.execute(_SETTINGS)).one()
            second = await ids(conn)
    assert first == {world.u_lead}
    assert (bound.kind or "", bound.boundary or "", bound.mode or "") == ("", "", "")
    assert second == set()


# -- R6.7: one boundary per published version, by api_name, written by the definer --


async def test_r6_7_record_writes_one_boundary_by_api_name(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    boundary = await record(
        app_engine,
        world.t,
        [lead_only(update=True)],
        [FieldBoundary("mkt_lead", "phone", "read")],
        version=world.version,
        digest=world.hash,
    )
    async with migrator.connect() as conn:
        head = (
            await conn.execute(
                sa.text(
                    "SELECT id, kind, source_id, source_version, run_id"
                    " FROM studio.actor_boundaries WHERE tenant_id = :t"
                ),
                {"t": world.t},
            )
        ).one()
        objects = (
            await conn.execute(
                sa.text(
                    "SELECT object_id, can_read, can_create, can_update, can_delete, can_assign"
                    " FROM studio.actor_boundary_objects WHERE boundary_id = :b"
                ),
                {"b": boundary},
            )
        ).all()
        fields = (
            await conn.execute(
                sa.text(
                    "SELECT field_id, access FROM studio.actor_boundary_fields"
                    " WHERE boundary_id = :b"
                ),
                {"b": boundary},
            )
        ).all()
    assert tuple(head) == (boundary, "agent", world.version, world.hash, None)
    assert [tuple(o) for o in objects] == [(world.lead, True, False, True, False, False)]
    assert [tuple(f) for f in fields] == [(world.phone, "read")]

    with pytest.raises(DBAPIError) as twice:
        await record(app_engine, world.t, [lead_only()], version=world.version, digest=world.hash)
    assert sqlstate(twice.value) == "23505"
    assert (await counts(migrator, world.t))["actor_boundaries"] == 1

    async with migrator.begin() as conn:
        _, other_version, other_hash = await plant_version(conn, world.tenant, world.u)
    refusals = {}
    for name, objects_, fields_, digest in (
        ("object", [ObjectBoundary("mkt_nope", True, False, False, False, False)], [], other_hash),
        ("field", [lead_only()], [FieldBoundary("mkt_lead", "nope", "read")], other_hash),
        ("hash", [lead_only()], [], sha256()),
    ):
        with pytest.raises(DBAPIError) as caught:
            await record(
                app_engine, world.t, objects_, fields_, version=other_version, digest=digest
            )
        refusals[name] = (sqlstate(caught.value), constraint(caught.value))
    assert refusals == {
        "object": ("23503", "fk_actor_boundary_objects_object_id_object_defs"),
        "field": ("23503", "fk_actor_boundary_fields_field_id_field_defs"),
        "hash": ("23514", "ck_actor_boundaries_source"),
    }
    assert await counts(migrator, world.t) == {
        "actor_boundaries": 1,
        "actor_boundary_objects": 1,
        "actor_boundary_fields": 1,
    }


async def test_r6_7_dw_app_inserts_no_boundary_row(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Gate (i): a live version's boundary cannot gain a row after its publish."""
    world = await plant_world(migrator)
    boundary = await record(
        app_engine, world.t, [lead_only()], version=world.version, digest=world.hash
    )
    for statement in (
        "INSERT INTO studio.actor_boundary_objects (tenant_id, boundary_id, object_id, can_read,"
        " can_create, can_update, can_delete, can_assign)"
        " VALUES (:t, :b, :o, true, true, true, true, true)",
        "INSERT INTO studio.actor_boundaries (tenant_id, id, kind, source_id, source_version)"
        " VALUES (:t, gen_random_uuid(), 'agent', :b, 'x')",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_engine.begin() as conn:
                await bind_tenant(conn, TenantScope(tenant_id=world.t))
                await conn.execute(
                    sa.text(statement), {"t": world.t, "b": boundary, "o": world.campaign}
                )


# -- R6.8 (RA20): frozen; deleted only while offboarding, or when provisional ---------


async def test_r6_8_a_boundary_never_changes_and_a_published_one_stays_while_active(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    published = await record(
        app_engine,
        world.t,
        [lead_only()],
        [FieldBoundary("mkt_lead", "phone", "read")],
        version=world.version,
        digest=world.hash,
    )
    run = await plant_run(migrator, world, mode="simulate", definition_hash="")
    provisional = await record(
        app_engine, world.t, [lead_only()], version=world.version, digest=sha256(), run=run
    )
    updates = (
        "UPDATE studio.actor_boundary_objects SET can_delete = true WHERE boundary_id = :b",
        "UPDATE studio.actor_boundary_fields SET access = 'edit' WHERE boundary_id = :b",
        "UPDATE studio.actor_boundaries SET source_version = 'x' WHERE id = :b",
    )
    for boundary in (published, provisional):
        for statement in updates:
            if "fields" in statement and boundary == provisional:
                continue
            with pytest.raises(DBAPIError) as owner:
                async with migrator.begin() as conn:
                    await conn.execute(sa.text(statement), {"b": boundary})
            assert (sqlstate(owner.value), constraint(owner.value)) == (
                "23514",
                "ck_actor_boundaries_frozen",
            ), statement
            with pytest.raises(DBAPIError, match="permission denied"):
                async with app_engine.begin() as conn:
                    await bind_tenant(conn, TenantScope(tenant_id=world.t))
                    await conn.execute(sa.text(statement), {"b": boundary})
    deletes = (
        "DELETE FROM studio.actor_boundary_objects WHERE boundary_id = :b",
        "DELETE FROM studio.actor_boundary_fields WHERE boundary_id = :b",
        "DELETE FROM studio.actor_boundaries WHERE id = :b",
    )
    for statement in deletes:
        with pytest.raises(DBAPIError) as active:
            async with app_engine.begin() as conn:
                await bind_tenant(conn, TenantScope(tenant_id=world.t))
                await conn.execute(sa.text(statement), {"b": published})
        assert (sqlstate(active.value), constraint(active.value)) == (
            "23514",
            "ck_actor_boundaries_frozen",
        ), statement
    assert await counts(migrator, world.t) == {
        "actor_boundaries": 2,
        "actor_boundary_objects": 2,
        "actor_boundary_fields": 1,
    }
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": world.t},
        )
    deleted = []
    async with app_engine.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=world.t))
        for statement in deletes:
            deleted.append((await conn.execute(sa.text(statement), {"b": published})).rowcount)
    assert deleted == [1, 1, 1]


# -- R6.9 (RA21): an unattended run reads with its service account's reach ----------


async def test_r6_9_an_unattended_workflow_reads_with_its_service_account(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The service account holds read on Lead at own depth; the publisher at
    tenant depth. The run asked by a lane acting as itself sees the account's
    lead and none of the publisher's."""
    world = await plant_world(migrator)
    async with migrator.begin() as conn:
        account = await _person(conn, world.tenant, [(world.lead, "read", "own")], kind="service")
        publisher = await _person(conn, world.tenant, [(world.lead, "read", "tenant")])
        accounts = await plant_record(conn, world.t, world.lead, world.tenant.main, account)
        publishers = await plant_record(conn, world.t, world.lead, world.tenant.main, publisher)
    await record(
        app_engine,
        world.t,
        [lead_only()],
        version=world.version,
        digest=world.hash,
        kind="workflow",
    )
    lane = uuid.uuid4()
    run = await plant_run(migrator, world, kind="workflow", principal=account, requested_by=lane)
    seen = await as_workflow(app_engine, world, run, account)
    assert accounts in seen
    assert publishers not in seen and world.u_lead not in seen
    with pytest.raises(ActorBindingRefusedError):
        await as_workflow(app_engine, world, run, publisher)


# -- R6.10: offboarding exports then deletes every boundary row -----------------------


async def test_r6_10_offboarding_exports_and_purges_the_boundaries(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    leaving = await plant_world(migrator)
    staying = await plant_world(migrator)
    for world in (leaving, staying):
        await record(
            app_engine,
            world.t,
            [lead_only()],
            [FieldBoundary("mkt_lead", "phone", "read")],
            version=world.version,
            digest=world.hash,
        )
    run = await plant_run(migrator, leaving, mode="simulate", definition_hash="")
    await record(
        app_engine,
        leaving.t,
        [every_flag("mkt_campaign")],
        version=leaving.version,
        digest=sha256(),
        run=run,
    )
    planted = await counts(migrator, leaving.t)
    kept = await counts(migrator, staying.t)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": leaving.t},
        )
    lane = SqlTenantOffboarding(session_factory=sessions(app_engine), scopes=OFFBOARDING_SCOPES)
    exported: dict[str, list[tuple[Any, ...]]] = {table: [] for table in _TABLES}
    async for batch in lane.export_rows(leaving.t):
        if batch.schema == "studio" and batch.table in exported:
            exported[batch.table].extend(
                tuple(sorted((k, str(v)) for k, v in row.items())) for row in batch.rows
            )
            assert {row["tenant_id"] for row in batch.rows} == {leaving.t}
    await lane.purge_rows(leaving.t)
    assert planted == {
        "actor_boundaries": 2,
        "actor_boundary_objects": 2,
        "actor_boundary_fields": 1,
    }
    assert {t: len(rows) for t, rows in exported.items()} == planted
    assert all(len(set(rows)) == len(rows) for rows in exported.values())
    assert await counts(migrator, leaving.t) == dict.fromkeys(_TABLES, 0)
    async with migrator.connect() as conn:
        definitions = await conn.scalar(
            sa.text(
                "SELECT (SELECT count(*) FROM studio.object_defs WHERE tenant_id = :t)"
                " + (SELECT count(*) FROM studio.field_defs WHERE tenant_id = :t)"
            ),
            {"t": leaving.t},
        )
    assert definitions == 0
    assert await counts(migrator, staying.t) == kept


# -- R6.11 (RA27): a provisional boundary for one simulate run ------------------------


async def test_r6_11_a_simulate_run_gets_one_provisional_boundary(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    pinned = sha256()
    first = await plant_run(migrator, world, mode="simulate", definition_hash="")
    second = await plant_run(migrator, world, mode="simulate", definition_hash="")
    boundary = await record(
        app_engine,
        world.t,
        [lead_only()],
        [FieldBoundary("mkt_lead", "phone", "read")],
        version=world.version,
        digest=pinned,
        run=first,
    )
    async with migrator.connect() as conn:
        head = (
            await conn.execute(
                sa.text(
                    "SELECT run_id, source_id, source_version FROM studio.actor_boundaries"
                    " WHERE id = :b"
                ),
                {"b": boundary},
            )
        ).one()
    assert tuple(head) == (first, world.version, pinned)
    assert await counts(migrator, world.t) == {
        "actor_boundaries": 1,
        "actor_boundary_objects": 1,
        "actor_boundary_fields": 1,
    }
    with pytest.raises(DBAPIError) as twice:
        await record(
            app_engine, world.t, [lead_only()], version=world.version, digest=pinned, run=first
        )
    assert sqlstate(twice.value) == "23505"
    # The same draft and hash for another run, and the published boundary of
    # the same version beside them: no unique index is shared.
    await record(
        app_engine, world.t, [lead_only()], version=world.version, digest=pinned, run=second
    )
    await record(app_engine, world.t, [lead_only()], version=world.version, digest=world.hash)
    assert (await counts(migrator, world.t))["actor_boundaries"] == 3

    # A gate trial of a candidate in `evaluating`, under its definition hash.
    async with migrator.begin() as conn:
        artifact, candidate, digest = await plant_version(conn, world.tenant, world.u)
    await move_for_test(migrator, candidate, "evaluating")
    trial = await plant_run(
        migrator,
        world,
        mode="simulate",
        artifact=artifact,
        version=candidate,
        definition_hash=digest,
    )
    gate = await record(
        app_engine, world.t, [lead_only()], version=candidate, digest=digest, run=trial
    )
    async with migrator.connect() as conn:
        stage = await conn.scalar(
            sa.text("SELECT stage FROM studio.artifact_versions WHERE id = :v"), {"v": candidate}
        )
        gate_row = (
            await conn.execute(
                sa.text(
                    "SELECT run_id, source_id, source_version FROM studio.actor_boundaries"
                    " WHERE id = :b"
                ),
                {"b": gate},
            )
        ).one()
    assert stage == "evaluating"
    assert tuple(gate_row) == (trial, candidate, digest)


# -- R6.12 (RA27): read within the provisional boundary and the tester's reach --------


async def test_r6_12_a_simulate_run_reads_within_its_provisional_boundary(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    # A draft's trial by its tester, U.
    draft = await plant_run(migrator, world, mode="simulate", definition_hash="")
    await record(
        app_engine, world.t, [lead_only()], version=world.version, digest=sha256(), run=draft
    )
    # A gate trial of V's candidate, in V's name.
    async with migrator.begin() as conn:
        artifact, candidate, digest = await plant_version(conn, world.tenant, world.v)
    await move_for_test(migrator, candidate, "evaluating")
    trial = await plant_run(
        migrator,
        world,
        mode="simulate",
        principal=world.v,
        artifact=artifact,
        version=candidate,
        definition_hash=digest,
    )
    await record(app_engine, world.t, [lead_only()], version=candidate, digest=digest, run=trial)
    async with agent_record_session(sessions(app_engine), context(world, draft, world.u)) as s:
        mode = (await s.execute(_SETTINGS)).one().mode
        tester = await ids(s)
    submitter = await as_agent(app_engine, world, trial, world.v)
    assert mode == "simulate"
    assert tester == {world.u_lead}
    assert submitter == {world.v_lead}


# -- R6.13 (RA27): a provisional boundary only in simulate ----------------------------


async def test_r6_13_a_provisional_boundary_outside_simulate_reads_and_writes_nothing(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    run = await plant_run(migrator, world, mode="simulate", definition_hash="")
    await record(
        app_engine,
        world.t,
        [lead_only(create=True)],
        version=world.version,
        digest=sha256(),
        run=run,
    )
    insert = (
        "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
        " owner_id, name, created_by, updated_by) VALUES (gen_random_uuid(), :t, :o, :w,"
        " 'user', :u, 'Lead mới', :u, :u)"
    )
    values = {"t": world.t, "o": world.lead, "w": world.tenant.main, "u": world.u}
    seen = {}
    for mode in ("simulate", "live", ""):
        async with agent_record_session(sessions(app_engine), context(world, run, world.u)) as s:
            await s.execute(sa.text("SELECT set_config('app.run_mode', :m, true)"), {"m": mode})
            seen[mode] = await ids(s)
            if mode == "simulate":
                await s.execute(sa.text(insert), values)
                continue
        with pytest.raises(DBAPIError) as refused:
            async with agent_record_session(
                sessions(app_engine), context(world, run, world.u)
            ) as s:
                await s.execute(sa.text("SELECT set_config('app.run_mode', :m, true)"), {"m": mode})
                await s.execute(sa.text(insert), values)
        assert sqlstate(refused.value) == "42501", mode
    assert seen == {"simulate": {world.u_lead}, "live": set(), "": set()}


# -- R6.14 (RA27): a provisional boundary names a simulate run of its company ---------


async def test_r6_14_a_provisional_boundary_for_a_live_or_another_company_s_run_is_refused(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    other = await plant_world(migrator)
    live = await plant_run(migrator, world, mode="live")
    theirs = await plant_run(migrator, other, mode="simulate", definition_hash="")
    for run in (live, theirs, uuid.uuid4()):
        with pytest.raises(DBAPIError) as caught:
            await record(
                app_engine,
                world.t,
                [lead_only()],
                [FieldBoundary("mkt_lead", "phone", "read")],
                version=world.version,
                digest=sha256(),
                run=run,
            )
        assert (sqlstate(caught.value), constraint(caught.value)) == (
            "23514",
            "ck_actor_boundaries_provisional_run",
        )
    assert await counts(migrator, world.t) == dict.fromkeys(_TABLES, 0)


# -- R6.15 (RA27): deleting one provisional boundary --------------------------------


async def test_r6_15_deleting_a_provisional_boundary_cascades_and_spares_the_rest(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await plant_world(migrator)
    published = await record(
        app_engine,
        world.t,
        [lead_only()],
        [FieldBoundary("mkt_lead", "phone", "read")],
        version=world.version,
        digest=world.hash,
    )
    x_run = await plant_run(migrator, world, mode="simulate", definition_hash="")
    y_run = await plant_run(migrator, world, mode="simulate", definition_hash="")
    provisional = {}
    for name, run in (("x", x_run), ("y", y_run)):
        provisional[name] = await record(
            app_engine,
            world.t,
            [lead_only()],
            [FieldBoundary("mkt_lead", "phone", "read")],
            version=world.version,
            digest=sha256(),
            run=run,
        )
    async with app_engine.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=world.t))
        deleted = (
            await conn.execute(
                sa.text("DELETE FROM studio.actor_boundaries WHERE id = :b"),
                {"b": provisional["x"]},
            )
        ).rowcount
    assert deleted == 1
    async with migrator.connect() as conn:
        left = {
            table: set(
                (
                    await conn.execute(
                        sa.text(
                            f"SELECT {'id' if table == 'actor_boundaries' else 'boundary_id'}"
                            f" FROM studio.{table} WHERE tenant_id = :t"  # nosec B608
                        ),
                        {"t": world.t},
                    )
                ).scalars()
            )
            for table in _TABLES
        }
    assert left == {table: {published, provisional["y"]} for table in _TABLES}
    async with agent_record_session(sessions(app_engine), context(world, x_run, world.u)) as s:
        chain = (await s.execute(_SETTINGS)).one().boundary
        await s.execute(
            sa.text("SELECT set_config('app.boundary_id', :b, true)"),
            {"b": str(provisional["x"])},
        )
        seen = await ids(s)
    assert chain == ""
    assert seen == set()
