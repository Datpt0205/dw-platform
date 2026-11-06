"""The run manifest against PostgreSQL (tenant-config ticket 04).

Tried at the ticket's own seams: `RunManifestBuilder.build` in the caller's
transaction, a run row the test writes the way the door of workflow-engine/02
will, and `PinnedResolver.load` through `SqlRunManifestStore`, once in a fresh
process (R6.4). The door, the runner's durability and the resume checks are
workflow-engine/02, 03 and 05's.
"""

from __future__ import annotations

import asyncio
import json
import subprocess  # nosec B404 - runs this interpreter on a module of this repo
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.studio_resume import WorkflowEngineFacts
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_kernel.canonical import CanonicalError, content_hash
from dw_kernel.errors import ConfigError, ConflictError, NotFoundError, PayloadTooLargeError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.application import run_manifests as builder_module
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.service import ArtifactService
from dw_studio.core.domain.artifacts import DocumentInvalidError, definition_body
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import move_for_test, publish_for_test
from dw_studio.testing.run_manifests import (
    TEST_PLAN,
    draft_of,
    fixture_document,
    insert_run,
    published,
    sealed,
    shipped_models,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

# The engine facts a manifest pins (workflow-engine R6.7), of the fixture types.
ENGINE_FACTS = WorkflowEngineFacts(fixture_node_registry())


REF = "sha256:" + "e" * 64


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


def store_of(service: ArtifactService) -> SqlArtifactStore:
    """The concrete store, whose transaction is also a `RunManifestTx`."""
    assert isinstance(service.store, SqlArtifactStore)
    return service.store


@pytest.fixture
def builder() -> RunManifestBuilder:
    return RunManifestBuilder(
        ArtifactKindRegistry(FIXTURE_KINDS), REF, shipped_models(), ENGINE_FACTS
    )


async def build(
    service: ArtifactService,
    builder: RunManifestBuilder,
    who: Person,
    version_id: uuid.UUID,
    mode: Any,
) -> str:
    async with store_of(service).transaction(who.context()) as tx:
        return await builder.build(tx, version_id, mode, tenant_id=who.tenant_id, plan_id=TEST_PLAN)


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def as_app(engine: AsyncEngine, tenant: uuid.UUID, statement: str, **values: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        await conn.execute(sa.text(statement), values)


async def manifest_body(migrator: AsyncEngine, manifest_hash: str) -> dict[str, Any]:
    found = await rows(
        migrator, "SELECT body FROM platform.run_manifests WHERE hash = :h", h=manifest_hash
    )
    assert len(found) == 1
    return dict(found[0].body)


async def keys_of(migrator: AsyncEngine, manifest_hash: str) -> list[uuid.UUID]:
    found = await rows(
        migrator,
        "SELECT artifact_version_id FROM platform.run_manifest_keys WHERE manifest_hash = :h",
        h=manifest_hash,
    )
    return [row.artifact_version_id for row in found]


async def counts(migrator: AsyncEngine, *tenants: uuid.UUID) -> tuple[int, int]:
    found = await rows(
        migrator,
        "SELECT (SELECT count(*) FROM platform.run_manifests WHERE tenant_id = ANY(:t)) AS m,"
        " (SELECT count(*) FROM platform.run_manifest_keys WHERE tenant_id = ANY(:t)) AS k",
        t=list(tenants),
    )
    return found[0].m, found[0].k


async def waits_on_a_lock(migrator: AsyncEngine, task: asyncio.Task[Any]) -> None:
    """Until another session of this database waits on a lock: a sleep alone
    passes for a statement that is merely slow (failure-modes #3)."""
    for _ in range(200):
        assert not task.done(), "it did not wait"
        waiting = await rows(
            migrator,
            "SELECT count(*) AS n FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
            " WHERE NOT l.granted AND a.datname = current_database()",
        )
        if waiting[0].n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("nothing waited on a lock")


def refused_by(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None) or getattr(cause, "sqlstate", None)


async def refusal(call: Any) -> str | None:
    with pytest.raises(DBAPIError) as caught:
        await call
    return refused_by(caught.value)


async def a_live_root(
    service: ArtifactService, migrator: AsyncEngine, who: Person, *, stage: str = "live"
) -> tuple[uuid.UUID, Any, list[tuple[uuid.UUID, Any]]]:
    """A root at `stage` whose `uses` are two artifacts with a `live` v1."""
    targets = [
        await published(service, migrator, who, fixture_document(title=f"đích {n}"))
        for n in range(2)
    ]
    root_id, root = await published(
        service, migrator, who, fixture_document(*(t for t, _ in targets)), stage=stage
    )
    return root_id, root, targets


async def load_as(
    sessions: async_sessionmaker[AsyncSession], tenant: uuid.UUID, manifest_hash: str
) -> PinnedResolver:
    async with tenant_session(sessions, TenantScope(tenant_id=tenant)) as session:
        return await PinnedResolver.load(SqlRunManifestStore(session), manifest_hash)


@pytest.fixture
def app_sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)


async def in_a_fresh_process(
    studio_db: DatabaseUrls, who: Person, run_id: uuid.UUID, kind: str, key: str
) -> dict[str, Any]:
    """R6.4: another interpreter, another connection, the run's row only."""
    done = await asyncio.to_thread(
        subprocess.run,  # nosec B603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "dw_studio.testing.pinned_probe",
            studio_db.app,
            str(who.tenant_id),
            str(run_id),
            kind,
            key,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    answer: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return answer


# ================================================================ R6.1 ===


async def test_a_sealed_root_pins_its_definition_closure_and_three_keys(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    root_id, root, targets = await a_live_root(service, migrator, writer)

    manifest_hash = await build(service, builder, writer, root.version_id, "live")

    body = await manifest_body(migrator, manifest_hash)
    definition = await rows(
        migrator,
        "SELECT body FROM studio.definition_manifests WHERE hash = :h",
        h=root.definition_hash,
    )
    assert manifest_hash == content_hash(body)
    assert body == {
        "schema": "dw.run_manifest/v1",
        "release_manifest_ref": REF,
        "run_mode": "live",
        "root": {
            "kind": "fixture_gateless",
            "artifact_id": str(root_id),
            "version_id": str(root.version_id),
            "version_no": 1,
            "definition_hash": root.definition_hash,
        },
        "closure": definition[0].body["closure"],
        # The deployment's profile, by value (model-connections R1.4).
        "engine": {
            "durability": "sync",
            **await shipped_models().pin(writer.tenant_id, TEST_PLAN, frozenset()),
        },
    }
    assert len(body["closure"]) == 2
    assert sorted(await keys_of(migrator, manifest_hash)) == sorted(
        [root.version_id, *(t.version_id for _, t in targets)]
    )
    # The door of workflow-engine/02, played here: the run row names it.
    run_id = await insert_run(app_engine, writer, run_mode="live", run_manifest_hash=manifest_hash)
    assert await rows(
        migrator,
        "SELECT 1 FROM platform.worker_runs WHERE id = :r AND run_manifest_hash = :h",
        r=run_id,
        h=manifest_hash,
    )


async def test_a_simulated_draft_pins_the_hash_its_seal_gives_and_writes_nothing_else(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """R6.1 (TC28)."""
    writer = world["writer"]
    target, _ = await published(service, migrator, writer, fixture_document())
    draft_id, version_id, row_version = await draft_of(
        service, writer, fixture_document(target, title="nháp")
    )
    before = await rows(
        migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=version_id
    )
    manifests_before = await rows(migrator, "SELECT count(*) AS n FROM studio.definition_manifests")

    manifest_hash = await build(service, builder, writer, version_id, "simulate")

    root = (await manifest_body(migrator, manifest_hash))["root"]
    assert root["stage"] == "draft" and root["version_id"] == str(version_id)
    assert root["version_no"] is None
    assert len(await keys_of(migrator, manifest_hash)) == 2
    assert (
        await rows(migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=version_id)
        == before
    )
    assert not await rows(
        migrator, "SELECT 1 FROM studio.dependencies WHERE from_version_id = :v", v=version_id
    )
    assert (
        await rows(migrator, "SELECT count(*) AS n FROM studio.definition_manifests")
        == manifests_before
    )

    seal = await sealed(service, writer, draft_id, row_version)
    assert seal.definition_hash == root["definition_hash"]


async def test_a_draft_that_cannot_be_pinned_writes_no_manifest(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """R6.1: `closure_of`'s refusal verbatim, and `CanonicalError` with its
    pointer; neither writes a manifest or a key."""
    writer = world["writer"]
    unreleased, _, _ = await draft_of(service, writer, fixture_document())
    _, broken, _ = await draft_of(service, writer, fixture_document(unreleased))
    _, floating, _ = await draft_of(service, writer, fixture_document())
    await rows(
        migrator,
        'UPDATE studio.artifact_versions SET document = \'{"title": "x", "size": 1.5}\''
        " WHERE id = :v",
        v=floating,
    )
    before = await counts(migrator, writer.tenant_id)

    with pytest.raises(DocumentInvalidError) as unresolved:
        await build(service, builder, writer, broken, "simulate")
    with pytest.raises(CanonicalError) as unhashable:
        await build(service, builder, writer, floating, "simulate")

    assert [(p.pointer, p.code) for p in unresolved.value.problems] == [
        ("/uses/0", "dependency_unresolved")
    ]
    assert unhashable.value.details == {"reason": "float_forbidden", "pointer": "/size"}
    assert await counts(migrator, writer.tenant_id) == before


async def test_a_body_past_one_mebibyte_is_too_large_and_written_nowhere(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R6.1: the table's CHECK is the one measure, read back by its name."""
    writer = world["writer"]
    _, root, _ = await a_live_root(service, migrator, writer)
    huge = RunManifestBuilder(
        ArtifactKindRegistry(FIXTURE_KINDS), "r" * (1 << 20), shipped_models(), ENGINE_FACTS
    )
    before = await counts(migrator, writer.tenant_id)

    with pytest.raises(PayloadTooLargeError):
        await build(service, huge, writer, root.version_id, "live")

    assert await counts(migrator, writer.tenant_id) == before


# ================================================================ R6.2 ===


async def test_the_same_content_is_one_manifest_and_another_mode_another(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    _, root, _ = await a_live_root(service, migrator, writer)

    first = await build(service, builder, writer, root.version_id, "live")
    again = await build(service, builder, writer, root.version_id, "live")
    tested = await build(service, builder, writer, root.version_id, "test")

    assert first == again != tested
    assert (
        len(await rows(migrator, "SELECT 1 FROM platform.run_manifests WHERE hash = :h", h=first))
        == 1
    )
    assert len(await keys_of(migrator, first)) == 3
    assert (await manifest_body(migrator, tested))["run_mode"] == "test"


async def test_two_concurrent_builds_of_one_content_both_commit(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """R6.2: the second waits on the first's insert, then finds it there."""
    writer = world["writer"]
    _, root, _ = await a_live_root(service, migrator, writer)
    built, release = asyncio.Event(), asyncio.Event()

    async def first() -> str:
        async with store_of(service).transaction(writer.context()) as tx:
            manifest_hash = await builder.build(
                tx, root.version_id, "live", tenant_id=writer.tenant_id, plan_id=TEST_PLAN
            )
            built.set()
            await release.wait()
            return manifest_hash

    async def second() -> str:
        await built.wait()
        return await build(service, builder, writer, root.version_id, "live")

    one, two = asyncio.create_task(first()), asyncio.create_task(second())
    await built.wait()
    await waits_on_a_lock(migrator, two)
    release.set()
    hashes = await asyncio.gather(one, two)

    assert hashes[0] == hashes[1]
    assert len(await keys_of(migrator, hashes[0])) == 3


# ============================================================ R6.3 TC15 ===


async def test_another_tenant_neither_builds_on_nor_loads_this_tenants_rows(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_sessions: async_sessionmaker[AsyncSession],
    world: StudioWorld,
) -> None:
    """CLAUDE.md, Tenancy and authorization: the version and the manifest of
    tenant A, from a transaction bound to tenant B."""
    writer, outsider = world["writer"], world["outsider"]
    _, root, _ = await a_live_root(service, migrator, writer)
    mine = await build(service, builder, writer, root.version_id, "live")
    before = await counts(migrator, writer.tenant_id, outsider.tenant_id)

    with pytest.raises(NotFoundError):
        await build(service, builder, outsider, root.version_id, "live")
    with pytest.raises(ConfigError) as caught:
        await load_as(app_sessions, outsider.tenant_id, mine)

    assert caught.value.details["reason"] == "manifest_not_found"
    assert await counts(migrator, writer.tenant_id, outsider.tenant_id) == before
    assert (await load_as(app_sessions, writer.tenant_id, mine)).hash == mine


async def test_a_soft_deleted_root_is_not_found(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    artifact_id, root = await published(service, migrator, writer, fixture_document())
    await rows(
        migrator, "UPDATE studio.artifacts SET deleted_at = now() WHERE id = :a", a=artifact_id
    )
    with pytest.raises(NotFoundError):
        await build(service, builder, writer, root.version_id, "live")
    with pytest.raises(NotFoundError):
        await build(service, builder, writer, uuid.uuid4(), "live")


# ================================================================ R6.7 ===


@pytest.mark.parametrize("mode", ["live", "test"])
async def test_a_draft_root_outside_simulate_is_refused_before_any_write(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
    mode: str,
) -> None:
    """R6.7 (TC28): called straight, no route in between."""
    writer = world["writer"]
    _, version_id, _ = await draft_of(service, writer, fixture_document())
    before = await counts(migrator, writer.tenant_id)

    with pytest.raises(ConflictError) as caught:
        await build(service, builder, writer, version_id, mode)

    assert caught.value.details["reason_code"] == "draft_root_not_simulate"
    assert await counts(migrator, writer.tenant_id) == before


# ================================================================ R6.8 ===


async def test_the_manifest_pins_sync_and_an_engine_the_model_refuses_writes_nothing(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R6.8 (TC32): the model checks the body before the first write."""
    writer = world["writer"]
    _, root, _ = await a_live_root(service, migrator, writer)
    manifest_hash = await build(service, builder, writer, root.version_id, "live")
    engine = (await manifest_body(migrator, manifest_hash))["engine"]
    assert engine["durability"] == "sync"
    assert (set(engine["model_routes"]), engine["default_model_profile"]) == (
        {"balanced"},
        "balanced",
    )

    _, other, _ = await a_live_root(service, migrator, writer)
    before = await counts(migrator, writer.tenant_id)
    for wrong in ({"durability": "async"}, {}, {"durability": "sync", "format": "x"}):
        monkeypatch.setattr(builder_module, "ENGINE", wrong)
        with pytest.raises(ValueError, match="validation error"):
            await build(service, builder, writer, other.version_id, "live")
    assert await counts(migrator, writer.tenant_id) == before


# ================================================================ R6.9 ===


async def test_a_run_row_holds_its_manifests_mode_and_keeps_its_manifest(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: StudioWorld,
) -> None:
    """R6.9 (TC28): from `dw_app`, past every service."""
    writer = world["writer"]
    _, version_id, _ = await draft_of(service, writer, fixture_document())
    simulated = await build(service, builder, writer, version_id, "simulate")
    _, root, _ = await a_live_root(service, migrator, writer)
    live = await build(service, builder, writer, root.version_id, "live")

    assert (
        await refusal(insert_run(app_engine, writer, run_mode="live", run_manifest_hash=simulated))
        == "ck_worker_runs_manifest_run_mode"
    )
    run_id = await insert_run(app_engine, writer, run_mode="simulate", run_manifest_hash=simulated)
    await insert_run(app_engine, writer, run_mode="live", run_manifest_hash=None)
    for statement, refused in (
        ("SET run_manifest_hash = :h", "ck_worker_runs_manifest_pinned"),
        ("SET run_manifest_hash = NULL", "ck_worker_runs_manifest_pinned"),
        ("SET run_mode = 'live'", "ck_worker_runs_manifest_run_mode"),
    ):
        assert (
            await refusal(
                as_app(
                    app_engine,
                    writer.tenant_id,
                    f"UPDATE platform.worker_runs {statement} WHERE id = :r",
                    h=live,
                    r=run_id,
                )
            )
            == refused
        ), statement
    held = await rows(
        migrator,
        "SELECT run_mode, run_manifest_hash FROM platform.worker_runs WHERE id = :r",
        r=run_id,
    )
    assert [tuple(row) for row in held] == [("simulate", simulated)]


# ===================================================== R6.4 TC15, resumes ===


async def test_a_resume_elsewhere_resolves_the_version_it_pinned(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    studio_db: DatabaseUrls,
    world: StudioWorld,
) -> None:
    """R6.4: v2 of a target sealed, `live`, v1 `retired` while the run waits."""
    writer = world["writer"]
    _, root, targets = await a_live_root(service, migrator, writer)
    run_id = await insert_run(
        app_engine,
        writer,
        run_mode="live",
        run_manifest_hash=await build(service, builder, writer, root.version_id, "live"),
    )
    target_id, v1 = targets[0]
    draft = await service.create_draft(writer.context(), target_id, ExpectedVersion(1))
    saved = (
        await service.save_draft(
            writer.context(),
            target_id,
            ExpectedVersion(draft.row_version),
            fixture_document(title="phiên bản 2"),
        )
    ).version
    v2 = await sealed(service, writer, target_id, saved.row_version)
    await publish_for_test(migrator, v2.version_id)  # v1 retired, superseded

    answer = await in_a_fresh_process(studio_db, writer, run_id, "artifact", str(target_id))

    assert answer["version_id"] == str(v1.version_id)
    assert answer["version"] == 1
    assert answer["document"]["title"] == "đích 0"


async def test_a_simulated_draft_saved_again_refuses_its_resume(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    studio_db: DatabaseUrls,
    world: StudioWorld,
) -> None:
    """R6.4: the draft's new content is not run; a target published anew is."""
    writer = world["writer"]
    target, _ = await published(service, migrator, writer, fixture_document())
    edited_id, edited, _ = await draft_of(service, writer, fixture_document(target))
    kept_id, kept, _ = await draft_of(service, writer, fixture_document(target, title="giữ"))
    edited_run = await insert_run(
        app_engine,
        writer,
        run_mode="simulate",
        run_manifest_hash=await build(service, builder, writer, edited, "simulate"),
    )
    kept_run = await insert_run(
        app_engine,
        writer,
        run_mode="simulate",
        run_manifest_hash=await build(service, builder, writer, kept, "simulate"),
    )
    current = await service.get_draft(writer.context(), edited_id)
    await service.save_draft(
        writer.context(),
        edited_id,
        ExpectedVersion(current.row_version),
        fixture_document(target, title="đã sửa"),
    )
    # The target publishes v2 while the kept draft's run waits.
    draft = await service.create_draft(writer.context(), target, ExpectedVersion(1))
    v2 = await sealed(service, writer, target, draft.row_version)
    await publish_for_test(migrator, v2.version_id)

    refused = await in_a_fresh_process(studio_db, writer, edited_run, "artifact", str(target))
    resumed = await in_a_fresh_process(studio_db, writer, kept_run, "artifact", str(target))

    assert refused == {"refused": "pinned_version_changed"}
    assert resumed["version"] == 1 and resumed["version_id"] != str(v2.version_id)
    assert kept_id != edited_id


async def test_a_candidate_sent_back_and_edited_refuses_its_test_run(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_sessions: async_sessionmaker[AsyncSession],
    world: StudioWorld,
) -> None:
    """R6.4: pinned at `evaluating`, then back to `draft` as agent-lifecycle's
    withdrawal does; unchanged it loads, edited it is refused."""
    writer = world["writer"]
    _, root, _ = await a_live_root(service, migrator, writer, stage="evaluating")
    manifest_hash = await build(service, builder, writer, root.version_id, "test")
    assert "stage" not in (await manifest_body(migrator, manifest_hash))["root"]

    await move_for_test(migrator, root.version_id, "draft")
    resolver = await load_as(app_sessions, writer.tenant_id, manifest_hash)
    assert resolver.root.artifact is not None and resolver.root.artifact.stage == "draft"

    await rows(
        migrator,
        "UPDATE studio.artifact_versions"
        " SET document = jsonb_set(document, '{title}', '\"khác\"') WHERE id = :v",
        v=root.version_id,
    )
    with pytest.raises(ConfigError) as caught:
        await load_as(app_sessions, writer.tenant_id, manifest_hash)
    assert caught.value.details["reason"] == "pinned_version_changed"


async def test_the_receipt_holds_off_a_save_of_the_draft_it_hashes(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """R6.1: the artifact row `FOR SHARE` from the first read of the receipt
    to its end, so the content hashed is the content received. Held right
    after that read: once the key row is written, its foreign key alone would
    hold off the save, and a test from there could not see the lock."""
    writer = world["writer"]
    original = fixture_document(title="trước")
    artifact_id, version_id, row_version = await draft_of(service, writer, original)
    read, release = asyncio.Event(), asyncio.Event()

    async def receipt() -> tuple[Any, str]:
        async with store_of(service).transaction(writer.context()) as tx:
            found = await tx.root_version(version_id)
            read.set()
            await release.wait()
            return found, await builder.build(
                tx, version_id, "simulate", tenant_id=writer.tenant_id, plan_id=TEST_PLAN
            )

    holder = asyncio.create_task(receipt())
    await read.wait()
    save = asyncio.create_task(
        service.save_draft(
            writer.context(),
            artifact_id,
            ExpectedVersion(row_version),
            fixture_document(title="sau"),
        )
    )
    await waits_on_a_lock(migrator, save)
    release.set()
    found, manifest_hash = await holder
    assert (await save).version.row_version == row_version + 1
    assert found is not None and found.version.document["title"] == "trước"
    root = (await manifest_body(migrator, manifest_hash))["root"]
    received = definition_body("fixture", artifact_id, content_hash(found.version.document), [])
    assert root["definition_hash"] == content_hash(received)


# ============================================ R2.18, R3.8, R6.5: the keys ===


async def leaving_world(migrator: AsyncEngine) -> StudioWorld:
    """A company of its own, for a case that moves it to `offboarding`."""
    async with migrator.begin() as conn:
        return await plant_world(conn)


async def offboard(migrator: AsyncEngine, tenant: uuid.UUID) -> None:
    await rows(
        migrator, "UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t", t=tenant
    )


async def test_a_key_never_points_into_another_tenant(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """R2.18 (TC29): as the migrator, past RLS, the composite key refuses."""
    writer, outsider = world["writer"], world["outsider"]
    _, root, _ = await a_live_root(service, migrator, writer)
    manifest_hash = await build(service, builder, writer, root.version_id, "live")
    _, theirs, _ = await draft_of(service, outsider, fixture_document())

    refused = await refusal(
        rows(
            migrator,
            "INSERT INTO platform.run_manifest_keys"
            " (id, tenant_id, manifest_hash, artifact_version_id) VALUES (:id, :t, :h, :v)",
            id=uuid.uuid4(),
            t=writer.tenant_id,
            h=manifest_hash,
            v=theirs,
        )
    )
    assert refused == "fk_run_manifest_keys_artifact_version_id_artifact_versions"


async def test_what_a_run_still_points_to_is_never_deleted(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
) -> None:
    """R6.5 (TC15): in an offboarding company (outside it R3.8 refuses the
    delete first), each RESTRICT key holds."""
    local = await leaving_world(migrator)
    writer = local["writer"]
    _, root = await published(service, migrator, writer, fixture_document())
    manifest_hash = await build(service, builder, writer, root.version_id, "live")
    await insert_run(app_engine, writer, run_mode="live", run_manifest_hash=manifest_hash)
    await offboard(migrator, writer.tenant_id)

    held_by_key = await refusal(
        as_app(
            app_engine,
            writer.tenant_id,
            "DELETE FROM studio.artifact_versions WHERE id = :v",
            v=root.version_id,
        )
    )
    held_by_run = await refusal(
        as_app(
            app_engine,
            writer.tenant_id,
            "DELETE FROM platform.run_manifests WHERE hash = :h",
            h=manifest_hash,
        )
    )

    assert held_by_key == "fk_run_manifest_keys_artifact_version_id_artifact_versions"
    assert held_by_run == "fk_worker_runs_run_manifest_hash_run_manifests"


@pytest.mark.parametrize("table", ["run_manifest_keys", "run_manifests"])
async def test_only_an_offboarding_company_loses_its_run_manifests(
    service: ArtifactService,
    builder: RunManifestBuilder,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    table: str,
) -> None:
    """R3.8 (TC31). The manifest case deletes a manifest with no keys, so the
    keys' own trigger, reached by CASCADE, cannot stand in for the manifest's."""
    local = await leaving_world(migrator)
    writer = local["writer"]
    _, root = await published(service, migrator, writer, fixture_document())
    if table == "run_manifest_keys":
        await build(service, builder, writer, root.version_id, "live")
    else:
        await as_app(
            app_engine,
            writer.tenant_id,
            "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
            ' VALUES (:t, :h, \'{"run_mode": "live"}\')',
            t=writer.tenant_id,
            h="sha256:" + uuid.uuid4().hex * 2,
        )
    delete = f"DELETE FROM platform.{table} WHERE tenant_id = :t"
    count = f"SELECT count(*) AS n FROM platform.{table} WHERE tenant_id = :t"

    refused = await refusal(as_app(app_engine, writer.tenant_id, delete, t=writer.tenant_id))
    assert refused == "ck_delete_outside_offboarding"
    assert (await rows(migrator, count, t=writer.tenant_id))[0].n >= 1

    await offboard(migrator, writer.tenant_id)
    await as_app(app_engine, writer.tenant_id, delete, t=writer.tenant_id)
    assert (await rows(migrator, count, t=writer.tenant_id))[0].n == 0
