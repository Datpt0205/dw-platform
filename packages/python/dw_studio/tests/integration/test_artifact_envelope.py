"""The artifact envelope against PostgreSQL (tenant-config ticket 02).

Two halves. The database's own rules, asked as `dw_app` and as the migrator:
sealed content (R2.9, TC1), the API name (R2.10, TC4), the gate flag (R2.14),
composite keys (R2.18, TC29), the owning workspace (R2.19, TC30), one
unreleased version (R2.20), deletes only while offboarding (R3.8, TC31), the
artifact target (R3.3). Then `ArtifactService.seal` and the lock rule over
the real store: numbering and hashes (R2.6-R2.8, R2.13, R2.16, R2.17), where-used
in the seal's transaction (R3.1, TC6), resolution of `artifact` references and
the soft delete that waits on it (R3.3, TC5), and one lock for the three version
writes (R2.7, R2.23).

A version outside `draft` is placed by `dw_studio.testing.lifecycle`, the
legal path `studio.guard_version_stage()` allows (agent-lifecycle 03); a live
version is of `fixture_gateless`, since the gated `fixture` reaches `live` only
through ticket 06's gate.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Any

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

from dw_kernel.canonical import content_hash
from dw_kernel.errors import ConflictError, PreconditionFailedError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.core.adapters.artifact_store import SqlArtifactStore, SqlArtifactTx
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService, SealResult
from dw_studio.core.domain.artifacts import (
    ClosureItem,
    DocumentInvalidError,
    definition_body,
)
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import move_for_test, publish_for_test, submit_on
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

HASH = "sha256:" + "c" * 64


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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(migrator: AsyncEngine) -> AsyncIterator[StudioWorld]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            planted = await plant_world(conn)
        yield planted


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(app_engine: AsyncEngine, world: StudioWorld) -> ArtifactService:
    ids = Uuid7Generator()
    sessions = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    return ArtifactService(
        SqlArtifactStore(sessions, ids), ArtifactKindRegistry(FIXTURE_KINDS), SystemClock(), ids
    )


def name() -> str:
    return f"a_{uuid.uuid4().hex[:12]}"


def doc(*uses: uuid.UUID, title: str = "Khách hàng") -> dict[str, Any]:
    return {"title": title, "uses": [str(u) for u in uses]}


async def make(
    service: ArtifactService, who: Person, *, kind: str = "fixture", document: Any = None
) -> tuple[uuid.UUID, int]:
    row, draft = await service.create(
        who.context(), kind=kind, api_name=name(), labels=[], document=document or doc()
    )
    return row.id, draft.row_version


async def seal(
    service: ArtifactService, who: Person, artifact_id: uuid.UUID, expected: int
) -> SealResult:
    async with service.store.transaction(who.context()) as tx:
        return await service.seal(tx, artifact_id, expected)


async def run(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def as_app(
    engine: AsyncEngine, tenant: uuid.UUID, statement: str, **values: Any
) -> list[Any]:
    """`dw_app` under one tenant, as the store binds it."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def stage(migrator: AsyncEngine, version_id: uuid.UUID, to: str) -> None:
    await move_for_test(migrator, version_id, to)


async def published(
    service: ArtifactService, migrator: AsyncEngine, who: Person, **kw: Any
) -> tuple[uuid.UUID, SealResult]:
    """An artifact (`fixture_gateless` unless `kind=`) with a `live` version 1."""
    artifact_id, row_version = await make(service, who, **{"kind": "fixture_gateless", **kw})
    sealed = await seal(service, who, artifact_id, row_version)
    await publish_for_test(migrator, sealed.version_id)
    return artifact_id, sealed


async def versions(migrator: AsyncEngine, artifact_id: uuid.UUID) -> list[Any]:
    return await run(
        migrator,
        "SELECT * FROM studio.artifact_versions WHERE artifact_id = :a"
        " ORDER BY version_no NULLS LAST",
        a=artifact_id,
    )


async def dependencies_of(migrator: AsyncEngine, version_id: uuid.UUID) -> list[Any]:
    return await run(
        migrator,
        "SELECT * FROM studio.dependencies WHERE from_version_id = :v ORDER BY path",
        v=version_id,
    )


def refused_by(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None) or getattr(cause, "sqlstate", None)


async def refusal(call: Awaitable[Any]) -> str | None:
    with pytest.raises(DBAPIError) as caught:
        await call
    return refused_by(caught.value)


# ===================================================== the database's rules ==


@pytest.mark.parametrize("to", ["evaluating", "live"])
async def test_a_sealed_versions_content_is_fixed(
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: StudioWorld,
    to: str,
) -> None:
    """R2.9 (TC1): from `dw_app`, by SQL, past the service."""
    kind = "fixture" if to == "evaluating" else "fixture_gateless"
    artifact_id, row_version = await make(service, world["writer"], kind=kind)
    sealed = await seal(service, world["writer"], artifact_id, row_version)
    await stage(migrator, sealed.version_id, to)

    refused = await refusal(
        as_app(
            app_engine,
            world.tenant.tenant_id,
            'UPDATE studio.artifact_versions SET document = \'{"title": "khác"}\' WHERE id = :v',
            v=sealed.version_id,
        )
    )
    assert refused == "ck_artifact_versions_sealed_content"


async def test_the_api_name_is_fixed_by_the_database_once_live(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R2.10 (TC4): a direct UPDATE as `dw_app`."""
    artifact_id, _ = await published(service, migrator, world["writer"])
    refused = await refusal(
        as_app(
            app_engine,
            world.tenant.tenant_id,
            "UPDATE studio.artifacts SET api_name = :n WHERE id = :a",
            n=name(),
            a=artifact_id,
        )
    )
    assert refused == "ck_artifacts_api_name_immutable"


async def test_a_kind_registered_without_its_gate_flag_is_refused(
    migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.14 (TC27): NOT NULL, and no DEFAULT that would fill it."""
    refused = await refusal(
        run(migrator, "INSERT INTO studio.artifact_kinds (kind) VALUES ('probe_kind')")
    )
    assert refused == "23502"
    default = await run(
        migrator,
        "SELECT column_default FROM information_schema.columns WHERE table_schema = 'studio'"
        " AND table_name = 'artifact_kinds' AND column_name = 'has_quality_gate'",
    )
    assert default == [(None,)]


async def _other_tenant_version(
    service: ArtifactService, world: StudioWorld
) -> tuple[uuid.UUID, uuid.UUID]:
    """An artifact and its version in the other company."""
    artifact_id, _ = await make(service, world["outsider"])
    rows = await service.versions(world["outsider"].context(), artifact_id)
    draft = await service.get_draft(world["outsider"].context(), artifact_id)
    assert rows == []
    return artifact_id, draft.id


@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("to_version_id", "fk_dependencies_to_version_id_artifact_versions"),
        ("from_version_id", "fk_dependencies_from_version_id_artifact_versions"),
        ("to_artifact_id", "fk_dependencies_to_artifact_id_artifacts"),
        ("from_artifact_id", "fk_dependencies_from_artifact_id_artifacts"),
    ],
)
async def test_a_dependency_never_points_into_another_tenant(
    service: ArtifactService,
    migrator: AsyncEngine,
    world: StudioWorld,
    column: str,
    constraint: str,
) -> None:
    """R2.18 (TC29): as the migrator, which bypasses RLS; a one-column key
    would accept every row here."""
    mine, _ = await make(service, world["writer"])
    my_draft = await service.get_draft(world["writer"].context(), mine)
    theirs, their_version = await _other_tenant_version(service, world)
    values = {
        "from_artifact_id": mine,
        "from_version_id": my_draft.id,
        "to_artifact_id": None,
        "to_version_id": None,
    }
    foreign = {"to_version_id": their_version, "from_version_id": their_version}.get(column, theirs)
    values[column] = foreign
    to_kind = "artifact" if column.startswith("to_") else "connector"
    if column == "to_version_id":
        values["to_artifact_id"] = mine
    if column == "to_artifact_id":
        values["to_version_id"] = my_draft.id
    to_key = str(values["to_artifact_id"]) if to_kind == "artifact" else "c1"
    refused = await refusal(
        run(
            migrator,
            "INSERT INTO studio.dependencies (id, tenant_id, from_artifact_id, from_version_id,"
            " to_kind, to_key, to_artifact_id, to_version_id, usage, path)"
            " VALUES (:id, :t, :fa, :fv, :k, :key, :ta, :tv, 'read', '/x')",
            id=uuid.uuid4(),
            t=world.tenant.tenant_id,
            fa=values["from_artifact_id"],
            fv=values["from_version_id"],
            k=to_kind,
            key=to_key,
            ta=values["to_artifact_id"],
            tv=values["to_version_id"],
        )
    )
    assert refused == constraint


async def test_a_version_never_belongs_to_or_builds_on_another_tenant(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.18 (TC29): `artifact_id` on insert, `based_on_version_id` on update."""
    _, their_version = await _other_tenant_version(service, world)
    # Their artifact with no unreleased version, so no index refuses a draft
    # before the key does (a version is inserted as a draft, agent-lifecycle R1.1).
    released, _ = await published(service, migrator, world["outsider"])
    refused = await refusal(
        run(
            migrator,
            "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
            " document_schema, document, row_version, contributor_ids)"
            " VALUES (:id, :t, :a, 'draft', 'dw.fixture/v1', '{}', 1, ARRAY[:u]::uuid[])",
            id=uuid.uuid4(),
            t=world.tenant.tenant_id,
            a=released,
            u=world["writer"].id,
        )
    )
    assert refused == "fk_artifact_versions_artifact_id_artifacts"

    mine, _ = await make(service, world["writer"])
    my_draft = await service.get_draft(world["writer"].context(), mine)
    refused = await refusal(
        run(
            migrator,
            "UPDATE studio.artifact_versions SET based_on_version_id = :b WHERE id = :v",
            b=their_version,
            v=my_draft.id,
        )
    )
    assert refused == "fk_artifact_versions_based_on_version_id_artifact_versions"


async def test_an_artifact_is_never_owned_by_another_tenants_workspace(
    migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.18 (TC29): the composite key to `uq_workspaces_tenant_id_id`."""
    refused = await refusal(
        run(
            migrator,
            "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
            " row_version) VALUES (:id, :t, 'fixture', :n, :w, 1)",
            id=uuid.uuid4(),
            t=world.tenant.tenant_id,
            n=name(),
            w=world.other.main,
        )
    )
    assert refused == "fk_artifacts_owning_workspace_id_workspaces"


async def leaving_world(migrator: AsyncEngine) -> StudioWorld:
    """A world of its own, for a case that ends with its company offboarding,
    a status no company leaves again."""
    async with migrator.begin() as conn:
        return await plant_world(conn)


async def offboard(migrator: AsyncEngine, tenant: uuid.UUID) -> None:
    await run(
        migrator, "UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t", t=tenant
    )


async def test_deleting_a_base_version_nulls_only_the_reference(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R2.18: `ON DELETE SET NULL (based_on_version_id)`, in an offboarding
    company (outside it R3.8 refuses the delete first)."""
    local = await leaving_world(migrator)
    artifact_id, v1 = await published(service, migrator, local["writer"])
    draft = await service.create_draft(local["writer"].context(), artifact_id, ExpectedVersion(1))
    assert draft.based_on_version_id == v1.version_id
    await stage(migrator, v1.version_id, "retired")
    tenant = local.tenant.tenant_id
    await offboard(migrator, tenant)
    await as_app(
        app_engine, tenant, "DELETE FROM studio.artifact_versions WHERE id = :v", v=v1.version_id
    )
    row = await run(
        migrator,
        "SELECT based_on_version_id, tenant_id FROM studio.artifact_versions WHERE id = :v",
        v=draft.id,
    )
    assert row == [(None, tenant)]


async def test_the_owning_workspace_never_changes(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R2.19 (TC30): no column grant for `dw_app`, a trigger for the migrator."""
    artifact_id, _ = await make(service, world["writer"])
    tenant = world.tenant.tenant_id
    refused = await refusal(
        as_app(
            app_engine,
            tenant,
            "UPDATE studio.artifacts SET owning_workspace_id = :w WHERE id = :a",
            w=world.ws2,
            a=artifact_id,
        )
    )
    assert refused == "42501"
    refused = await refusal(
        run(
            migrator,
            "UPDATE studio.artifacts SET owning_workspace_id = :w WHERE id = :a",
            w=world.ws2,
            a=artifact_id,
        )
    )
    assert refused == "ck_artifacts_owning_workspace_fixed"
    await as_app(
        app_engine,
        tenant,
        "UPDATE studio.artifacts SET labels = ARRAY['hot'] WHERE id = :a",
        a=artifact_id,
    )
    after = await run(
        migrator,
        "SELECT owning_workspace_id, labels FROM studio.artifacts WHERE id = :a",
        a=artifact_id,
    )
    assert after == [(world.ws1, ["hot"])]


async def test_one_unreleased_version_per_artifact(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R2.20 (TC27): a second draft, a draft beside a candidate: refused; beside
    `live` and `retired` versions: taken."""
    tenant = world.tenant.tenant_id
    insert = (
        "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
        " document_schema, document, row_version, contributor_ids)"
        " VALUES (:id, :t, :a, 'draft', 'dw.fixture/v1', '{\"title\": \"x\"}', 1,"
        " ARRAY[gen_random_uuid()])"
    )
    with_draft, _ = await make(service, world["writer"])
    assert (
        await refusal(as_app(app_engine, tenant, insert, id=uuid.uuid4(), t=tenant, a=with_draft))
        == "uq_artifact_versions_unreleased"
    )

    with_candidate, row_version = await make(service, world["writer"], kind="fixture_gateless")
    sealed = await seal(service, world["writer"], with_candidate, row_version)
    await stage(migrator, sealed.version_id, "awaiting_approval")
    assert (
        await refusal(
            as_app(app_engine, tenant, insert, id=uuid.uuid4(), t=tenant, a=with_candidate)
        )
        == "uq_artifact_versions_unreleased"
    )

    released, _ = await published(service, migrator, world["writer"])
    v2 = await service.create_draft(world["writer"].context(), released, ExpectedVersion(1))
    v2_sealed = await seal(service, world["writer"], released, v2.row_version)
    await publish_for_test(migrator, v2_sealed.version_id)  # v1 retired, superseded
    await as_app(app_engine, tenant, insert, id=uuid.uuid4(), t=tenant, a=released)


async def _offboarding_rows(
    migrator: AsyncEngine, status: str
) -> tuple[PlantedTenant, dict[str, Any]]:
    """A company in `status` with one artifact, its sealed version and a manifest."""
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, status=status)
    artifact_id, version_id = uuid.uuid4(), uuid.uuid4()
    await run(
        migrator,
        "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
        " row_version, last_version_no) VALUES (:a, :t, 'fixture', :n, :w, 1, 1)",
        a=artifact_id,
        t=tenant.tenant_id,
        n=name(),
        w=tenant.main,
    )
    await run(
        migrator,
        "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage, version_no,"
        " document_schema, document, content_hash, definition_hash, row_version,"
        " contributor_ids)"
        " VALUES (:v, :t, :a, 'draft', 1, 'dw.fixture/v1', '{}', :h, :h, 1, ARRAY[:u]::uuid[])",
        v=version_id,
        t=tenant.tenant_id,
        a=artifact_id,
        h=HASH,
        u=uuid.uuid4(),
    )
    await run(
        migrator,
        "INSERT INTO studio.definition_manifests (tenant_id, hash, body) VALUES (:t, :h, '{}')",
        t=tenant.tenant_id,
        h=HASH,
    )
    return tenant, {"artifacts": artifact_id, "artifact_versions": version_id}


@pytest.mark.parametrize("table", ["artifact_versions", "artifacts", "definition_manifests"])
async def test_only_an_offboarding_company_loses_these_rows(
    migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld, table: str
) -> None:
    """R3.8 (TC31): `dw_app` holds DELETE for the offboarding lane alone."""
    active, _ = await _offboarding_rows(migrator, "active")
    leaving, _ = await _offboarding_rows(migrator, "offboarding")
    order = ["artifact_versions", "artifacts"] if table == "artifacts" else [table]
    statement = "DELETE FROM studio.{} WHERE tenant_id = :t"

    for each in order:
        refused = await refusal(
            as_app(app_engine, active.tenant_id, statement.format(each), t=active.tenant_id)
        )
        assert refused == "ck_delete_outside_offboarding", each
    left = await run(
        migrator, f"SELECT count(*) FROM studio.{table} WHERE tenant_id = :t", t=active.tenant_id
    )
    assert left == [(1,)]

    for each in order:
        await as_app(app_engine, leaving.tenant_id, statement.format(each), t=leaving.tenant_id)
    gone = await run(
        migrator, f"SELECT count(*) FROM studio.{table} WHERE tenant_id = :t", t=leaving.tenant_id
    )
    assert gone == [(0,)]


async def test_an_artifact_dependency_names_its_target_by_id(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R3.3: `ck_dependencies_artifact_target`, so the soft-delete trigger
    finds every dependent by `to_artifact_id` (failure-modes #7)."""
    target, live = await published(service, migrator, world["writer"])
    source, _ = await make(service, world["writer"])
    draft = await service.get_draft(world["writer"].context(), source)
    tenant = world.tenant.tenant_id
    insert = (
        "INSERT INTO studio.dependencies (id, tenant_id, from_artifact_id, from_version_id,"
        " to_kind, to_key, to_artifact_id, to_version_id, usage, path)"
        " VALUES (:id, :t, :fa, :fv, 'artifact', :key, :ta, :tv, 'read', '/uses/0')"
    )
    common = {"t": tenant, "fa": source, "fv": draft.id}
    for key, ta, tv in (
        (str(target), None, live.version_id),
        (str(uuid.uuid4()), target, live.version_id),
    ):
        refused = await refusal(
            as_app(app_engine, tenant, insert, id=uuid.uuid4(), key=key, ta=ta, tv=tv, **common)
        )
        assert refused == "ck_dependencies_artifact_target"


async def test_a_hard_delete_under_a_dependent_fails_on_the_key(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R3.3 (TC5): in an offboarding company, the RESTRICT key holds."""
    local = await leaving_world(migrator)
    target, _ = await published(service, migrator, local["writer"])
    user, row_version = await make(service, local["writer"], document=doc(target))
    await seal(service, local["writer"], user, row_version)
    tenant = local.tenant.tenant_id
    await offboard(migrator, tenant)
    refused = await refusal(
        as_app(
            app_engine,
            tenant,
            "DELETE FROM studio.artifact_versions WHERE artifact_id = :a",
            a=target,
        )
    )
    assert refused == "fk_dependencies_to_version_id_artifact_versions"


# ============================================================ the seal ======


async def test_a_seal_numbers_hashes_and_leaves_the_stage(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.7 (TC2), R2.13 (TC27): both kinds sealed alike, both left in `draft`,
    no approval opened; the definition hash recomputed here."""
    target, live = await published(service, migrator, world["writer"])
    approvals = await run(migrator, "SELECT count(*) FROM platform.approval_requests")
    for kind in ("fixture", "fixture_gateless"):
        artifact_id, row_version = await make(
            service, world["writer"], kind=kind, document=doc(target)
        )
        sealed = await seal(service, world["writer"], artifact_id, row_version)

        row = (await versions(migrator, artifact_id))[0]
        assert (row.stage, row.version_no) == ("draft", 1)
        assert row.content_hash == sealed.content_hash == content_hash(row.document)
        closure = [ClosureItem("artifact", str(target), 1, live.content_hash)]
        body = definition_body(kind, artifact_id, sealed.content_hash, closure)
        assert row.definition_hash == sealed.definition_hash == content_hash(body)
        assert sealed.definition_hash.startswith("sha256:") and len(sealed.definition_hash) == 71
        manifest = await run(
            migrator,
            "SELECT body FROM studio.definition_manifests WHERE hash = :h",
            h=row.definition_hash,
        )
        assert manifest == [(body,)]
    assert await run(migrator, "SELECT count(*) FROM platform.approval_requests") == approvals


async def test_two_drafts_with_one_closure_have_two_definition_hashes(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    target, _ = await published(service, migrator, world["writer"])
    hashes = set()
    for title in ("một", "hai"):
        artifact_id, row_version = await make(
            service, world["writer"], document=doc(target, title=title)
        )
        hashes.add((await seal(service, world["writer"], artifact_id, row_version)).definition_hash)
    assert len(hashes) == 2


async def test_a_document_with_three_faults_is_refused_with_three_pointers(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.6: every fault, no number given."""
    artifact_id, row_version = await make(service, world["writer"], document={"uses": [1, 2]})
    with pytest.raises(DocumentInvalidError) as refused:
        await seal(service, world["writer"], artifact_id, row_version)
    assert [p.pointer for p in refused.value.problems] == ["/title", "/uses/0", "/uses/1"]
    assert (await versions(migrator, artifact_id))[0].version_no is None


async def test_a_seal_with_a_stale_row_version_seals_nothing(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.17 (TC3): the submit's `If-Match` from before a save."""
    target, _ = await published(service, migrator, world["writer"])
    artifact_id, row_version = await make(service, world["writer"], document=doc(target))
    await service.save_draft(
        world["writer"].context(),
        artifact_id,
        ExpectedVersion(row_version),
        doc(target, title="mới"),
    )
    with pytest.raises(PreconditionFailedError) as refused:
        await seal(service, world["writer"], artifact_id, row_version)
    assert refused.value.details["reason_code"] == "stale_version"
    row = (await versions(migrator, artifact_id))[0]
    assert row.version_no is None
    assert await dependencies_of(migrator, row.id) == []
    assert await run(
        migrator, "SELECT last_version_no FROM studio.artifacts WHERE id = :a", a=artifact_id
    ) == [(0,)]


async def test_a_version_back_in_draft_is_resealed_under_a_new_number(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.8 (TC2), R3.1: a new number, and only the new where-used rows."""
    first, _ = await published(service, migrator, world["writer"])
    second, _ = await published(service, migrator, world["writer"])
    artifact_id, row_version = await make(service, world["writer"], document=doc(first))
    sealed = await seal(service, world["writer"], artifact_id, row_version)
    await stage(migrator, sealed.version_id, "evaluating")
    await stage(migrator, sealed.version_id, "draft")
    saved = (
        await service.save_draft(
            world["writer"].context(), artifact_id, ExpectedVersion(row_version + 1), doc(second)
        )
    ).version
    assert (saved.version_no, saved.content_hash, saved.definition_hash) == (None, None, None)

    again = await seal(service, world["writer"], artifact_id, saved.row_version)

    assert again.version_no == 2
    assert [r.version_no for r in await versions(migrator, artifact_id)] == [2]
    assert [r.to_artifact_id for r in await dependencies_of(migrator, again.version_id)] == [second]


async def test_a_failure_inside_the_seal_leaves_nothing(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R3.1 (TC6): the number, the manifest and the where-used rows go together."""
    target, _ = await published(service, migrator, world["writer"])
    artifact_id, row_version = await make(service, world["writer"], document=doc(target))

    class BrokenError(Exception):
        pass

    with pytest.raises(BrokenError):
        async with service.store.transaction(world["writer"].context()) as tx:
            assert isinstance(tx, SqlArtifactTx)

            async def fail(*_a: Any, **_k: Any) -> None:
                raise BrokenError

            tx.replace_dependencies = fail  # type: ignore[method-assign]
            await service.seal(tx, artifact_id, row_version)

    row = (await versions(migrator, artifact_id))[0]
    assert (row.version_no, row.definition_hash) == (None, None)
    assert await dependencies_of(migrator, row.id) == []
    assert await run(
        migrator, "SELECT last_version_no FROM studio.artifacts WHERE id = :a", a=artifact_id
    ) == [(0,)]


async def test_the_fixture_kinds_where_used_rows_are_exactly_its_uses(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R3.1, R3.3 (TC6): one `artifact` row per use, pinned to the live version."""
    target, live = await published(service, migrator, world["writer"])
    artifact_id, row_version = await make(service, world["writer"], document=doc(target))
    sealed = await seal(service, world["writer"], artifact_id, row_version)

    rows = await dependencies_of(migrator, sealed.version_id)
    assert [
        (
            r.to_kind,
            r.to_key,
            r.to_artifact_id,
            r.to_version_id,
            r.to_version,
            r.to_hash,
            r.usage,
            r.path,
        )
        for r in rows
    ] == [
        ("artifact", str(target), target, live.version_id, 1, live.content_hash, "read", "/uses/0")
    ]


async def test_every_unresolved_reference_is_named_at_its_pointer(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R3.3 (TC5): no such id, a soft-deleted target, a target never live."""
    gone, _ = await make(service, world["writer"])
    await service.soft_delete(world["writer"].context(), gone, ExpectedVersion(1))
    never_live, _ = await make(service, world["writer"])
    artifact_id, row_version = await make(
        service, world["writer"], document=doc(uuid.uuid4(), gone, never_live)
    )
    with pytest.raises(DocumentInvalidError) as refused:
        await seal(service, world["writer"], artifact_id, row_version)
    assert [(p.pointer, p.code) for p in refused.value.problems] == [
        ("/uses/0", "dependency_unresolved"),
        ("/uses/1", "dependency_unresolved"),
        ("/uses/2", "dependency_unresolved"),
    ]
    assert (await versions(migrator, artifact_id))[0].version_no is None


async def test_a_seal_in_flight_holds_off_the_soft_delete_of_its_target(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R3.3 (TC5): the seal reads the target `FOR SHARE`; a soft delete
    started right after that read, before the dependency row exists (whose
    key would lock the target too), waits, then meets the dependency of a
    version that went `evaluating` in the same transaction."""
    target, _ = await published(service, migrator, world["writer"])
    artifact_id, row_version = await make(service, world["writer"], document=doc(target))
    writer = world["writer"].context()
    seen: dict[str, Any] = {}

    async with service.store.transaction(writer) as tx:
        read_target = tx.live_target

        async def then_delete(target_id: uuid.UUID) -> Any:
            found = await read_target(target_id)
            seen["delete"] = asyncio.create_task(
                service.soft_delete(writer, target, ExpectedVersion(1))
            )
            await asyncio.sleep(0.5)
            seen["waited"] = not seen["delete"].done()
            return found

        tx.live_target = then_delete  # type: ignore[method-assign,assignment]
        sealed = await service.seal(tx, artifact_id, row_version)
        await tx.update_version(
            sealed.version_id,
            stage="evaluating",
            submitted_by=world["writer"].id,
            submitted_at=sa.func.now(),
        )
    assert seen["waited"], "the soft delete did not wait for the seal's read"
    with pytest.raises(ConflictError) as refused:
        await seen["delete"]
    assert refused.value.details["reason_code"] == "artifact_in_use"
    assert refused.value.details["in_use"] == {"evaluating": 1}


async def test_two_seals_of_one_draft_give_one_number(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.7 (TC2): same `expected_row_version` twice at once."""
    artifact_id, row_version = await make(service, world["writer"])
    outcomes = await asyncio.gather(
        seal(service, world["writer"], artifact_id, row_version),
        seal(service, world["writer"], artifact_id, row_version),
        return_exceptions=True,
    )
    numbers = [o.version_no for o in outcomes if isinstance(o, SealResult)]
    stale = [o for o in outcomes if isinstance(o, PreconditionFailedError)]
    assert numbers == [1]
    assert len(stale) == 1 and stale[0].details["reason_code"] == "stale_version"


async def test_a_new_seal_never_touches_the_live_version(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.16 (TC27): `fixture_gateless` with v1 live; v2 sealed beside it."""
    artifact_id, v1 = await published(service, migrator, world["writer"], kind="fixture_gateless")
    before = await run(
        migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=v1.version_id
    )
    draft = await service.create_draft(world["writer"].context(), artifact_id, ExpectedVersion(1))
    v2 = await seal(service, world["writer"], artifact_id, draft.row_version)

    assert v2.version_no == 2
    assert (
        await run(migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=v1.version_id)
        == before
    )
    new = await run(
        migrator, "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=v2.version_id
    )
    assert new == [("draft",)]


Write = Callable[[ArtifactService, Person, uuid.UUID, int], Coroutine[Any, Any, Any]]


async def _save(service: ArtifactService, who: Person, artifact_id: uuid.UUID, rv: int) -> Any:
    return (
        await service.save_draft(who.context(), artifact_id, ExpectedVersion(rv), doc())
    ).version


async def _create_draft(
    service: ArtifactService, who: Person, artifact_id: uuid.UUID, rv: int
) -> Any:
    return await service.create_draft(who.context(), artifact_id, ExpectedVersion(1))


async def _seal(service: ArtifactService, who: Person, artifact_id: uuid.UUID, rv: int) -> Any:
    return await seal(service, who, artifact_id, rv)


# What the lock holder changes before it commits, and what the write must then
# answer: only a write that read the versions after taking the lock sees it.
Change = Callable[[AsyncConnection, uuid.UUID, uuid.UUID], Coroutine[Any, Any, None]]


async def _bump(conn: AsyncConnection, artifact_id: uuid.UUID, tenant: uuid.UUID) -> None:
    await conn.execute(
        sa.text(
            "UPDATE studio.artifact_versions SET row_version = row_version + 1"
            " WHERE artifact_id = :a AND stage = 'draft'"
        ),
        {"a": artifact_id},
    )


async def _candidate(conn: AsyncConnection, artifact_id: uuid.UUID, tenant: uuid.UUID) -> None:
    """A sealed v2 inserted as a draft and submitted, as the legal path goes."""
    version_id = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage, version_no,"
            " document_schema, document, content_hash, definition_hash, row_version,"
            " contributor_ids) VALUES (:v, :t, :a, 'draft', 2, 'dw.fixture/v1', '{}', :h, :h, 1,"
            " ARRAY[gen_random_uuid()])"
        ),
        {"v": version_id, "t": tenant, "a": artifact_id, "h": HASH},
    )
    await submit_on(conn, version_id)


@pytest.mark.parametrize(
    ("write", "change", "answer"),
    [
        (_save, _bump, "stale_version"),
        (_create_draft, _candidate, "candidate_pending"),
        (_seal, _bump, "stale_version"),
    ],
    ids=["save_draft", "create_draft", "seal"],
)
async def test_each_version_write_reads_only_after_the_artifact_lock(
    service: ArtifactService,
    migrator: AsyncEngine,
    world: StudioWorld,
    write: Write,
    change: Change,
    answer: str,
) -> None:
    """R2.7 (TC2), R2.23: another transaction holds the artifact row `FOR
    UPDATE` and changes its versions; the write waits until it commits and
    answers from what it then finds. A write that read before the lock would
    answer from the old state (failure-modes #3: "it waited" alone cannot
    tell, the dependency key and the version row lock it too)."""
    if write is _create_draft:
        artifact_id, _ = await published(service, migrator, world["writer"])
        rv = 1
    else:
        artifact_id, rv = await make(service, world["writer"])
    async with migrator.connect() as conn, conn.begin():
        await conn.execute(
            sa.text("SELECT 1 FROM studio.artifacts WHERE id = :a FOR UPDATE"), {"a": artifact_id}
        )
        pending = asyncio.create_task(write(service, world["writer"], artifact_id, rv))
        await asyncio.sleep(0.5)
        waited = not pending.done()
        await change(conn, artifact_id, world.tenant.tenant_id)
    assert waited, "the write did not wait for the artifact row lock"
    with pytest.raises((ConflictError, PreconditionFailedError)) as refused:
        await pending
    assert refused.value.details["reason_code"] == answer


async def test_two_draft_creations_at_once_make_one_draft(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R2.23 (TC27): one 201, one `draft_exists`."""
    artifact_id, _ = await published(service, migrator, world["writer"])
    context = world["writer"].context()
    outcomes = await asyncio.gather(
        service.create_draft(context, artifact_id, ExpectedVersion(1)),
        service.create_draft(context, artifact_id, ExpectedVersion(1)),
        return_exceptions=True,
    )
    conflicts = [o for o in outcomes if isinstance(o, ConflictError)]
    assert len(conflicts) == 1 and conflicts[0].details["reason_code"] == "draft_exists"
    drafts = [r for r in await versions(migrator, artifact_id) if r.stage == "draft"]
    assert len(drafts) == 1


async def test_a_second_draft_written_round_the_service_is_a_conflict(
    service: ArtifactService, world: StudioWorld
) -> None:
    """R2.23: the store's insert, past the service's own check, maps the index."""
    artifact_id, _ = await make(service, world["writer"])
    async with service.store.transaction(world["writer"].context()) as tx:
        with pytest.raises(ConflictError) as refused:
            await tx.insert_draft(
                version_id=uuid.uuid4(),
                artifact_id=artifact_id,
                document_schema="dw.fixture/v1",
                document=json.loads('{"title": "x"}'),
                based_on_version_id=None,
                contributor_ids=[world["writer"].id],
            )
    assert refused.value.details["reason_code"] == "draft_exists"
