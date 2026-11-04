"""The stage machine held by PostgreSQL (agent-lifecycle ticket 03; ADR-0120
decision 1): `studio.guard_version_stage()`, its indexes and keys, the
displayed-stage view, and who `contributor_ids` names.

The database is asked directly, as `dw_app` under one tenant (the role every
request runs as) and as the migrator where a test needs a role past RLS: a
move the machine does not have is refused whoever writes it (R1.1, AL1). A
legal move is set up through `dw_studio.testing.lifecycle`; a refused one is
written here in SQL, since it is the trigger under test.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
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

from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService, SealResult
from dw_studio.core.domain.artifacts import Stage
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import (
    decide_for_test,
    move_for_test,
    open_publish_request,
    publish_for_test,
    publish_on,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

TRANSITION = "ck_artifact_versions_stage_transition"
H1 = "sha256:" + "1" * 64
H2 = "sha256:" + "2" * 64


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


async def sealed_draft(
    service: ArtifactService, who: Person, *, kind: str, title: str = "Khách hàng"
) -> tuple[uuid.UUID, SealResult]:
    row, draft = await service.create(
        who.context(), kind=kind, api_name=name(), labels=[], document={"title": title}
    )
    async with service.store.transaction(who.context()) as tx:
        sealed = await service.seal(tx, row.id, draft.row_version)
    return row.id, sealed


async def next_sealed(
    service: ArtifactService, who: Person, artifact_id: uuid.UUID, title: str
) -> SealResult:
    draft = await service.create_draft(who.context(), artifact_id, ExpectedVersion(1))
    saved = await service.save_draft(
        who.context(), artifact_id, ExpectedVersion(draft.row_version), {"title": title}
    )
    async with service.store.transaction(who.context()) as tx:
        return await service.seal(tx, artifact_id, saved.row_version)


@asynccontextmanager
async def as_app(engine: AsyncEngine, tenant: uuid.UUID) -> AsyncIterator[AsyncConnection]:
    """One transaction as `dw_app` under `tenant`, as the store binds it."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        yield conn


async def run(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


def refused_by(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None) or getattr(cause, "sqlstate", None)


async def refusal(call: Awaitable[Any]) -> str | None:
    with pytest.raises(DBAPIError) as caught:
        await call
    return refused_by(caught.value)


async def version(migrator: AsyncEngine, version_id: uuid.UUID) -> Any:
    return (
        await run(migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=version_id)
    )[0]


async def app_update(
    app_engine: AsyncEngine, tenant: uuid.UUID, version_id: uuid.UUID, assignments: str, **kw: Any
) -> None:
    async with as_app(app_engine, tenant) as conn:
        await conn.execute(
            sa.text(f"UPDATE studio.artifact_versions SET {assignments} WHERE id = :v"),
            {"v": version_id, **kw},
        )


# =============================================================== the catalog ==


async def test_the_catalog_has_the_trigger_the_checks_the_indexes_and_the_view(
    migrator: AsyncEngine,
) -> None:
    """Ticket step 9: asked of `pg_catalog`, not of the migration's text."""
    trigger = await run(
        migrator,
        "SELECT t.tgenabled::text, p.proname, p.prosecdef FROM pg_trigger t"
        " JOIN pg_proc p ON p.oid = t.tgfoid"
        " WHERE t.tgrelid = 'studio.artifact_versions'::regclass"
        " AND t.tgname = 'guard_version_stage' AND NOT t.tgisinternal",
    )
    assert trigger == [("O", "guard_version_stage", False)]  # invoker's rights
    checks = {
        row.conname
        for row in await run(
            migrator,
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid = 'studio.artifact_versions'::regclass AND contype = 'c'",
        )
    }
    assert {
        "ck_artifact_versions_stage",
        "ck_artifact_versions_contributor_ids",
        "ck_artifact_versions_tighten_only_compared",
        "ck_artifact_versions_retire_reason_code",
    } <= checks
    indexes = {
        row.indexname: row.indexdef
        for row in await run(
            migrator,
            "SELECT indexname, indexdef FROM pg_indexes"
            " WHERE schemaname = 'studio' AND tablename = 'artifact_versions'",
        )
    }
    assert "UNIQUE" in indexes["uq_artifact_versions_live"]
    assert "WHERE (stage = 'live'::text)" in indexes["uq_artifact_versions_live"]
    assert "UNIQUE" in indexes["uq_artifact_versions_unreleased"]
    view = await run(
        migrator,
        "SELECT c.relkind::text, c.reloptions FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'studio' AND c.relname = 'artifact_display_stage'",
    )
    assert view == [("v", ["security_invoker=true"])]
    # R1.5: nothing stores the displayed stage.
    assert not await run(
        migrator,
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_schema = 'studio' AND column_name = 'display_stage'"
        " AND table_name <> 'artifact_display_stage'",
    )


async def test_the_stage_check_holds_exactly_the_stage_enum(migrator: AsyncEngine) -> None:
    definition = (
        await run(
            migrator,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'ck_artifact_versions_stage'",
        )
    )[0][0]
    assert set(re.findall(r"'([a-z_]+)'::text", definition)) == {s.value for s in Stage}


# ================================================ R1.1: every illegal move ==

# Moves the machine has (ADR-0120 decision 1); a bare stage write of one of
# them is refused as well, for the columns it lacks, so they are not listed.
_LEGAL = {
    ("draft", "evaluating"),
    ("evaluating", "draft"),
    ("evaluating", "awaiting_approval"),
    ("draft", "awaiting_approval"),
    ("awaiting_approval", "draft"),
    ("awaiting_approval", "live"),
    ("draft", "live"),
    ("live", "retired"),
}
_ILLEGAL = [
    (kind, source, target)
    for kind, sources in (
        ("fixture", ("draft", "evaluating")),
        ("fixture_gateless", ("draft", "awaiting_approval", "live", "retired")),
    )
    for source in sources
    for target in (s.value for s in Stage)
    if target != source and (source, target) not in _LEGAL
]


@pytest.mark.parametrize(("kind", "source", "target"), _ILLEGAL)
async def test_r1_1_an_illegal_move_written_by_dw_app_is_refused(
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: StudioWorld,
    kind: str,
    source: str,
    target: str,
) -> None:
    """AL1: every pair outside the machine, by `dw_app` SQL past the service."""
    _, sealed = await sealed_draft(service, world["writer"], kind=kind)
    await move_for_test(migrator, sealed.version_id, source)
    before = await version(migrator, sealed.version_id)

    refused = await refusal(
        app_update(app_engine, world.tenant.tenant_id, sealed.version_id, "stage = :s", s=target)
    )

    assert refused == TRANSITION
    assert await version(migrator, sealed.version_id) == before


async def test_r1_1_a_version_is_inserted_as_a_draft_only(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    artifact_id, sealed = await sealed_draft(service, world["writer"], kind="fixture_gateless")
    await publish_for_test(migrator, sealed.version_id)
    for stage in ("live", "evaluating"):
        assert (
            await refusal(
                run(
                    migrator,
                    "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
                    " version_no, document_schema, document, content_hash, definition_hash,"
                    " row_version, contributor_ids) VALUES (:id, :t, :a, :s, 9, 'dw.fixture/v1',"
                    " '{}', :h, :h, 1, ARRAY[:u]::uuid[])",
                    id=uuid.uuid4(),
                    t=world.tenant.tenant_id,
                    a=artifact_id,
                    s=stage,
                    h=H1,
                    u=world["writer"].id,
                )
            )
            == TRANSITION
        )


# ======================================================= R1.2: one live ==


async def test_r1_2_a_second_live_version_is_refused_by_the_index(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """AL2: v2 submitted without a comparison (NULL, so the trigger's rule
    holds) and approved, taken live beside v1: the one-live index refuses."""
    writer = world["writer"]
    artifact_id, v1 = await sealed_draft(service, writer, kind="fixture_gateless")
    await publish_for_test(migrator, v1.version_id)
    v2 = await next_sealed(service, writer, artifact_id, "v2")
    async with migrator.begin() as conn:
        approval = await open_publish_request(conn, v2.version_id, requested_by=writer.id)
        await conn.execute(
            sa.text(
                "UPDATE studio.artifact_versions SET stage = 'awaiting_approval',"
                " submitted_by = :s, submitted_at = now(), publish_approval_id = :a"
                " WHERE id = :v"
            ),
            {"s": writer.id, "a": approval, "v": v2.version_id},
        )
        await decide_for_test(conn, approval, decided_by=uuid.uuid4())

    refused = await refusal(
        run(
            migrator,
            "UPDATE studio.artifact_versions SET stage = 'live', published_by = :p,"
            " published_at = now() WHERE id = :v",
            p=uuid.uuid4(),
            v=v2.version_id,
        )
    )
    assert refused == "uq_artifact_versions_live"


# ================================================ R1.6: the rule per kind ==


async def _awaiting(
    conn: AsyncConnection,
    version_id: uuid.UUID,
    *,
    submitter: uuid.UUID,
    approval: uuid.UUID,
    compared: str | None = None,
) -> None:
    await conn.execute(
        sa.text(
            "UPDATE studio.artifact_versions SET stage = 'awaiting_approval', submitted_by = :s,"
            " submitted_at = now(), publish_approval_id = :a, compared_live_hash = :h"
            " WHERE id = :v"
        ),
        {"s": submitter, "a": approval, "h": compared, "v": version_id},
    )


_GO_LIVE = (
    "UPDATE studio.artifact_versions SET stage = 'live', published_by = :p, published_at = now()"
    " WHERE id = :v"
)


async def test_r1_6_a_gateless_version_goes_live_through_its_approval_as_dw_app(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """No `gate_run_id` anywhere, every step written by `dw_app`."""
    _, sealed = await sealed_draft(service, world["writer"], kind="fixture_gateless")
    async with as_app(app_engine, world.tenant.tenant_id) as conn:
        await publish_on(conn, sealed.version_id)
    row = await version(migrator, sealed.version_id)
    assert (row.stage, row.gate_run_id) == ("live", None)
    assert row.publish_approval_id is not None and row.published_by is not None


async def test_r1_6_a_gated_kind_never_takes_the_gateless_path(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """`fixture` straight to `awaiting_approval`, and on from `evaluating`
    (until ticket 06's gate): both refused."""
    writer = world["writer"]
    _, sealed = await sealed_draft(service, writer, kind="fixture")
    async with migrator.begin() as conn:
        approval = await open_publish_request(conn, sealed.version_id, requested_by=writer.id)

    async def straight() -> None:
        async with as_app(app_engine, world.tenant.tenant_id) as conn:
            await _awaiting(conn, sealed.version_id, submitter=writer.id, approval=approval)

    assert await refusal(straight()) == TRANSITION
    await move_for_test(migrator, sealed.version_id, "evaluating")

    async def on() -> None:
        async with as_app(app_engine, world.tenant.tenant_id) as conn:
            await conn.execute(
                sa.text(
                    "UPDATE studio.artifact_versions SET stage = 'awaiting_approval',"
                    " publish_approval_id = :a WHERE id = :v"
                ),
                {"a": approval, "v": sealed.version_id},
            )

    assert await refusal(on()) == TRANSITION


@pytest.mark.parametrize(
    "case",
    ["pending", "decider_contributor", "decider_submitter", "other_kind", "other_version"],
)
async def test_r1_6_live_needs_this_versions_approved_request_from_a_second_person(
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: StudioWorld,
    case: str,
) -> None:
    writer, co_writer = world["writer"], world["co_writer"]
    _, sealed = await sealed_draft(service, writer, kind="fixture_gateless")
    # A submitter who is not an author, so each rule is asked on its own.
    submitter = uuid.uuid4()
    other = (await sealed_draft(service, writer, kind="fixture_gateless"))[1]
    async with migrator.begin() as conn:
        approval = await open_publish_request(
            conn,
            sealed.version_id,
            requested_by=submitter,
            kind="fixture" if case == "other_kind" else None,
            payload_version_id=other.version_id if case == "other_version" else None,
        )
        await _awaiting(conn, sealed.version_id, submitter=submitter, approval=approval)
        if case != "pending":
            decider = {
                "decider_contributor": writer.id,
                "decider_submitter": submitter,
            }.get(case, co_writer.id)
            await decide_for_test(conn, approval, decided_by=decider)

    refused = await refusal(
        app_update(
            app_engine,
            world.tenant.tenant_id,
            sealed.version_id,
            "stage = 'live', published_by = :p, published_at = now()",
            p=co_writer.id,
        )
    )
    assert refused == TRANSITION
    assert (await version(migrator, sealed.version_id)).stage == "awaiting_approval"


@pytest.mark.parametrize(
    ("assignment", "value"),
    [
        ("contributor_ids = ARRAY[:x]::uuid[]", "person"),
        ("compared_live_hash = :x", H2),
        ("submitted_by = :x", "person"),
        ("tighten_only = true, compared_live_hash = :x", H2),
        ("published_by = :x, published_at = now()", "person"),
        ("retired_by = :x, retired_at = now(), retire_reason_code = 'explicit'", "person"),
    ],
)
async def test_r1_6_a_lifecycle_column_changes_only_at_its_own_step(
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: StudioWorld,
    assignment: str,
    value: str,
) -> None:
    """A candidate's columns, written by `dw_app` without a move: refused."""
    _, sealed = await sealed_draft(service, world["writer"], kind="fixture_gateless")
    await move_for_test(migrator, sealed.version_id, "awaiting_approval")
    before = await version(migrator, sealed.version_id)
    x = uuid.uuid4() if value == "person" else value

    refused = await refusal(
        app_update(app_engine, world.tenant.tenant_id, sealed.version_id, assignment, x=x)
    )
    assert refused == TRANSITION
    assert await version(migrator, sealed.version_id) == before


async def test_r1_6_the_flag_is_read_by_the_trigger_itself(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """`fixture_gateless` flagged gated when the move is written: its `draft ->
    awaiting_approval`, written by hand, is refused (the flag is read then)."""
    writer = world["writer"]
    _, sealed = await sealed_draft(service, writer, kind="fixture_gateless")
    async with migrator.begin() as conn:
        approval = await open_publish_request(conn, sealed.version_id, requested_by=writer.id)
    flag = "UPDATE studio.artifact_kinds SET has_quality_gate = :g WHERE kind = 'fixture_gateless'"
    await run(migrator, flag, g=True)
    try:

        async def straight() -> None:
            async with as_app(app_engine, world.tenant.tenant_id) as conn:
                await _awaiting(conn, sealed.version_id, submitter=writer.id, approval=approval)

        refused = await refusal(straight())
    finally:
        await run(migrator, flag, g=False)
    assert refused == TRANSITION


# ============================================ R1.7: the tighten-only branch ==


async def _object(migrator: AsyncEngine, world: StudioWorld, kind: str) -> dict[str, Any]:
    """An artifact of `kind` with v1 live and a sealed v2 draft, in raw rows
    (the trigger reads no document)."""
    ids = {"a": uuid.uuid4(), "v1": uuid.uuid4(), "v2": uuid.uuid4()}
    writer = world["writer"]
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
                " row_version, last_version_no) VALUES (:a, :t, :k, :n, :w, 1, 2)"
            ),
            {"a": ids["a"], "t": world.tenant.tenant_id, "k": kind, "n": name(), "w": world.ws1},
        )
        for key, number, digest in (("v1", 1, H1), ("v2", 2, H2)):
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
                    " version_no, document_schema, document, content_hash, definition_hash,"
                    " row_version, contributor_ids) VALUES (:v, :t, :a, 'draft', :n,"
                    " 'dw.object/v1', '{}', :h, :h, 1, ARRAY[:u]::uuid[])"
                ),
                {
                    "v": ids[key],
                    "t": world.tenant.tenant_id,
                    "a": ids["a"],
                    "n": number,
                    "h": digest,
                    "u": writer.id,
                },
            )
            if key == "v1":
                await publish_on(conn, ids["v1"])
    return ids


async def _tighten(
    app_engine: AsyncEngine, world: StudioWorld, ids: dict[str, Any], *, compared: str
) -> None:
    async with as_app(app_engine, world.tenant.tenant_id) as conn:
        await conn.execute(
            sa.text(
                "UPDATE studio.artifact_versions SET stage = 'retired', retired_by = :u,"
                " retired_at = now(), retire_reason_code = 'superseded' WHERE id = :v"
            ),
            {"u": world["writer"].id, "v": ids["v1"]},
        )
        await conn.execute(
            sa.text(
                "UPDATE studio.artifact_versions SET stage = 'live', tighten_only = true,"
                " compared_live_hash = :h, submitted_by = :u, submitted_at = now(),"
                " published_by = :u, published_at = now() WHERE id = :v"
            ),
            {"h": compared, "u": world["writer"].id, "v": ids["v2"]},
        )


async def test_r1_7_an_object_that_only_tightens_goes_live_without_approval(
    migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    ids = await _object(migrator, world, "object")
    await _tighten(app_engine, world, ids, compared=H1)
    stages = await run(
        migrator,
        "SELECT id, stage, publish_approval_id FROM studio.artifact_versions"
        " WHERE artifact_id = :a",
        a=ids["a"],
    )
    by_id = {row.id: (row.stage, row.publish_approval_id) for row in stages}
    assert by_id[ids["v2"]] == ("live", None)
    assert by_id[ids["v1"]][0] == "retired"


@pytest.mark.parametrize(("kind", "compared"), [("fixture_gateless", H1), ("object", H2)])
async def test_r1_7_the_branch_is_the_objects_alone_and_on_its_comparison(
    migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld, kind: str, compared: str
) -> None:
    """AL4: another kind without a gate, or a comparison not with the version
    this publish replaces: refused, nothing changed."""
    ids = await _object(migrator, world, kind)
    assert await refusal(_tighten(app_engine, world, ids, compared=compared)) == TRANSITION
    assert (await version(migrator, ids["v1"])).stage == "live"


# =========================================== R1.8: the base it was compared with ==


async def _candidate_compared_with_v1(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> tuple[SealResult, SealResult]:
    writer = world["writer"]
    artifact_id, v1 = await sealed_draft(service, writer, kind="fixture_gateless")
    await publish_for_test(migrator, v1.version_id)
    v2 = await next_sealed(service, writer, artifact_id, "v2")
    async with migrator.begin() as conn:
        approval = await open_publish_request(conn, v2.version_id, requested_by=writer.id)
        await _awaiting(
            conn,
            v2.version_id,
            submitter=writer.id,
            approval=approval,
            compared=v1.definition_hash,
        )
        await decide_for_test(conn, approval, decided_by=world["co_writer"].id)
    return v1, v2


async def test_r1_8_a_candidate_whose_base_moved_is_refused(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """AL19: v1 retired (explicit) after v2 was compared with it."""
    v1, v2 = await _candidate_compared_with_v1(service, migrator, world)
    await move_for_test(migrator, v1.version_id, "retired")
    refused = await refusal(
        app_update(
            app_engine,
            world.tenant.tenant_id,
            v2.version_id,
            "stage = 'live', published_by = :p, published_at = now()",
            p=world["co_writer"].id,
        )
    )
    assert refused == TRANSITION


async def test_r1_8_the_base_retired_superseded_in_the_same_transaction_is_taken(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    v1, v2 = await _candidate_compared_with_v1(service, migrator, world)
    async with as_app(app_engine, world.tenant.tenant_id) as conn:
        await conn.execute(
            sa.text(
                "UPDATE studio.artifact_versions SET stage = 'retired', retired_by = :p,"
                " retired_at = now(), retire_reason_code = 'superseded' WHERE id = :v"
            ),
            {"p": world["co_writer"].id, "v": v1.version_id},
        )
        await conn.execute(sa.text(_GO_LIVE), {"p": world["co_writer"].id, "v": v2.version_id})
    assert (await version(migrator, v2.version_id)).stage == "live"


async def test_r1_8_a_base_superseded_in_an_earlier_transaction_is_not_this_publishs(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """The replaced version is the one retired in this transaction only."""
    v1, v2 = await _candidate_compared_with_v1(service, migrator, world)
    await app_update(
        app_engine,
        world.tenant.tenant_id,
        v1.version_id,
        "stage = 'retired', retired_by = :p, retired_at = now(), retire_reason_code = 'superseded'",
        p=world["co_writer"].id,
    )
    refused = await refusal(
        app_update(
            app_engine,
            world.tenant.tenant_id,
            v2.version_id,
            "stage = 'live', published_by = :p, published_at = now()",
            p=world["co_writer"].id,
        )
    )
    assert refused == TRANSITION


async def test_r1_8_no_live_version_at_submit_or_at_publish_is_taken(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """Both NULL: the first version of an artifact."""
    _, sealed = await sealed_draft(service, world["writer"], kind="fixture_gateless")
    await publish_for_test(migrator, sealed.version_id)
    row = await version(migrator, sealed.version_id)
    assert (row.stage, row.compared_live_hash) == ("live", None)


# ===================================== R1.9: no key into another company ==


async def test_r1_9_a_publish_request_of_another_company_is_refused_by_the_key(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """AL21: as the migrator, past RLS; the composite key alone refuses."""
    writer, outsider = world["writer"], world["outsider"]
    _, theirs = await sealed_draft(service, outsider, kind="fixture_gateless")
    _, mine = await sealed_draft(service, writer, kind="fixture_gateless")
    async with migrator.begin() as conn:
        their_request = await open_publish_request(
            conn, theirs.version_id, requested_by=outsider.id
        )
        my_request = await open_publish_request(conn, mine.version_id, requested_by=writer.id)

    async def point(request: uuid.UUID) -> None:
        async with migrator.begin() as conn:
            await _awaiting(conn, mine.version_id, submitter=writer.id, approval=request)

    assert await refusal(point(their_request)) == (
        "fk_artifact_versions_publish_approval_id_approval_requests"
    )
    assert (await version(migrator, mine.version_id)).publish_approval_id is None
    await point(my_request)
    assert (await version(migrator, mine.version_id)).publish_approval_id == my_request


# ======================================================== R1.5: the view ==


async def _display(app_engine: AsyncEngine, tenant: uuid.UUID, artifact_id: uuid.UUID) -> Any:
    async with as_app(app_engine, tenant) as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT display_stage FROM studio.artifact_display_stage WHERE artifact_id = :a"
                ),
                {"a": artifact_id},
            )
        ).scalar_one_or_none()


async def test_r1_5_the_view_orders_killed_live_awaiting_evaluating_draft_retired(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    writer = world["writer"]
    tenant = world.tenant.tenant_id
    gated, sealed_gated = await sealed_draft(service, writer, kind="fixture")
    assert await _display(app_engine, tenant, gated) == "draft"
    await move_for_test(migrator, sealed_gated.version_id, "evaluating")
    assert await _display(app_engine, tenant, gated) == "evaluating"

    artifact_id, v1 = await sealed_draft(service, writer, kind="fixture_gateless")
    await move_for_test(migrator, v1.version_id, "awaiting_approval")
    assert await _display(app_engine, tenant, artifact_id) == "awaiting_approval"
    await move_for_test(migrator, v1.version_id, "draft")
    await publish_for_test(migrator, v1.version_id)
    v2 = await next_sealed(service, writer, artifact_id, "v2")
    # A draft beside the live version: live first.
    assert await _display(app_engine, tenant, artifact_id) == "live"
    async with as_app(app_engine, tenant) as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type,"
                " owning_workspace_id, target_id, action, origin, reason_code, reason, set_by)"
                " VALUES (:id, :t, 'agent', :w, :a, 'kill', 'tenant', 'test', 'thử', :u)"
            ),
            {"id": uuid.uuid4(), "t": tenant, "w": world.ws1, "a": artifact_id, "u": writer.id},
        )
    assert await _display(app_engine, tenant, artifact_id) == "killed"

    retired, r1 = await sealed_draft(service, writer, kind="fixture_gateless")
    await move_for_test(migrator, r1.version_id, "retired")
    assert await _display(app_engine, tenant, retired) == "retired"
    assert v2.version_no == 2


async def test_r1_5_the_view_reads_under_the_readers_own_tenant(
    service: ArtifactService, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """`security_invoker`: tenant A's `dw_app` sees no row of tenant B."""
    theirs, _ = await sealed_draft(service, world["outsider"], kind="fixture")
    assert await _display(app_engine, world.tenant.tenant_id, theirs) is None
    async with as_app(app_engine, world.tenant.tenant_id) as conn:
        foreign = (
            await conn.execute(
                sa.text("SELECT count(*) FROM studio.artifact_display_stage WHERE tenant_id <> :t"),
                {"t": world.tenant.tenant_id},
            )
        ).scalar_one()
    assert foreign == 0
    assert await _display(app_engine, world.other.tenant_id, theirs) == "draft"


# ============================================ R5.1 via AL1: contributor_ids ==


async def test_contributors_are_everyone_who_created_or_saved_the_draft(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """A creates, B saves, A saves: `[A, B]`; a new draft names its creator."""
    a, b = world["writer"], world["co_writer"]
    row, draft = await service.create(
        a.context(), kind="fixture_gateless", api_name=name(), labels=[], document={"title": "1"}
    )
    assert draft.contributor_ids == (a.id,)
    saved = await service.save_draft(
        b.context(), row.id, ExpectedVersion(draft.row_version), {"title": "2"}
    )
    saved = await service.save_draft(
        a.context(), row.id, ExpectedVersion(saved.row_version), {"title": "3"}
    )
    assert (await version(migrator, saved.id)).contributor_ids == [a.id, b.id]

    async with service.store.transaction(a.context()) as tx:
        sealed = await service.seal(tx, row.id, saved.row_version)
    await publish_for_test(migrator, sealed.version_id)
    next_draft = await service.create_draft(b.context(), row.id, ExpectedVersion(1))
    assert (await version(migrator, next_draft.id)).contributor_ids == [b.id]


async def test_an_empty_or_null_holding_contributor_list_is_refused(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    _, sealed = await sealed_draft(service, world["writer"], kind="fixture")
    for value in ("ARRAY[]::uuid[]", "ARRAY[NULL]::uuid[]"):
        assert (
            await refusal(
                run(
                    migrator,
                    f"UPDATE studio.artifact_versions SET contributor_ids = {value} WHERE id = :v",
                    v=sealed.version_id,
                )
            )
            == "ck_artifact_versions_contributor_ids"
        )
