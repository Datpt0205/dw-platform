"""The columns, keys and CHECKs of a Studio run on `platform.worker_runs`, as
`dw_app` writes them in SQL, past any service (workflow-engine ticket 02:
R3.1, R3.2, R3.3, R3.7, R3.8, R3.12, R3.19; WE18, WE21, WE50).

Each refusal is read back by the constraint that made it, so a test cannot be
satisfied by a different error. The set the CHECK of `trigger_kind` takes and
the set `uq_worker_runs_active_thread` treats as finished are read from the
catalog and compared with the code's (failure-modes #2).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
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

from dw_agent_runtime.adapters.run_store import TERMINAL_STATUSES, RunStatus
from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import W1_TRIGGER_KINDS
from dw_studio.core.application.service import ArtifactService
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.run_manifests import draft_of, fixture_document
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REF = "sha256:" + "a" * 64
SHA = "sha256:" + "c" * 64
HEX = "c" * 64


@dataclass(frozen=True)
class Root:
    """A tenant's draft and a `simulate` manifest of it, for rows to name."""

    who: Person
    artifact_id: uuid.UUID
    version_id: uuid.UUID
    manifest: str


@dataclass(frozen=True)
class Roots:
    mine: Root
    theirs: Root


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
async def roots(app_engine: AsyncEngine, world: StudioWorld) -> Roots:
    ids = Uuid7Generator()
    registry = ArtifactKindRegistry(FIXTURE_KINDS)
    store = SqlArtifactStore(
        async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False), ids
    )
    service = ArtifactService(store, registry, SystemClock(), ids)
    builder = RunManifestBuilder(registry, REF)

    async def root(who: Person) -> Root:
        artifact_id, version_id, _ = await draft_of(service, who, fixture_document())
        async with store.transaction(who.context()) as tx:
            manifest = await builder.build(tx, version_id, "simulate")
        return Root(who, artifact_id, version_id, manifest)

    return Roots(await root(world["writer"]), await root(world["outsider"]))


def studio_row(root: Root, **values: Any) -> dict[str, Any]:
    run_id = uuid.uuid4()
    return {
        "id": run_id,
        "thread_id": run_id,
        "tenant_id": root.who.tenant_id,
        "workspace_id": root.who.workspace_id,
        "worker_id": f"studio:fixture:{root.artifact_id}",
        "worker_version": "draft",
        "graph_version": root.manifest,
        "status": "queued",
        "requested_by": root.who.id,
        "run_as_principal_id": root.who.id,
        "run_mode": "simulate",
        "run_manifest_hash": root.manifest,
        "artifact_kind": "fixture",
        "artifact_id": root.artifact_id,
        "artifact_version_id": root.version_id,
        "trigger_kind": "test",
        "request_key": f"test:{root.who.id}:{run_id}",
        **values,
    }


def code_row(who: Person, **values: Any) -> dict[str, Any]:
    """A code-defined worker's run: no Studio column."""
    run_id = uuid.uuid4()
    return {
        "id": run_id,
        "thread_id": run_id,
        "tenant_id": who.tenant_id,
        "workspace_id": who.workspace_id,
        "worker_id": "code_worker",
        "worker_version": "1.0.0",
        "graph_version": "1.0.0",
        "status": "running",
        "requested_by": who.id,
        "run_mode": "live",
        **values,
    }


async def insert(app: AsyncEngine, row: dict[str, Any]) -> None:
    """One INSERT as `dw_app`, bound to the row's tenant."""
    columns = ", ".join(row)
    params = ", ".join(f":{name}" for name in row)
    async with app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(row["tenant_id"])}
        )
        await conn.execute(
            sa.text(f"INSERT INTO platform.worker_runs ({columns}) VALUES ({params})"),  # nosec B608
            row,
        )


async def as_app(app: AsyncEngine, tenant: uuid.UUID, statement: str, **values: Any) -> list[Any]:
    async with app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def refused(call: Any) -> str | None:
    with pytest.raises(DBAPIError) as caught:
        await call
    cause = getattr(getattr(caught.value, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


async def row_of(migrator: AsyncEngine, run_id: uuid.UUID) -> Any:
    async with migrator.connect() as conn:
        return (
            await conn.execute(
                sa.text("SELECT * FROM platform.worker_runs WHERE id = :r"), {"r": run_id}
            )
        ).one_or_none()


# ---- R3.1: the columns ----------------------------------------------------------

# (type, nullable, default) as `information_schema.columns` reads them.
_COLUMNS: dict[str, tuple[str, str, str | None]] = {
    "root_run_id": ("uuid", "NO", None),
    "parent_run_id": ("uuid", "YES", None),
    "chain_depth": ("smallint", "NO", "0"),
    "artifact_kind": ("text", "YES", None),
    "artifact_id": ("uuid", "YES", None),
    "artifact_version_id": ("uuid", "YES", None),
    "definition_hash": ("text", "YES", None),
    "trigger_kind": ("text", "YES", None),
    "inbound_event_id": ("uuid", "YES", None),
    "run_as_principal_id": ("uuid", "YES", None),
    "request_key": ("text", "YES", None),
    "priority": ("smallint", "NO", "0"),
    "available_at": ("timestamp with time zone", "NO", "now()"),
    "lease_owner": ("text", "YES", None),
    "lease_until": ("timestamp with time zone", "YES", None),
    "attempt": ("smallint", "NO", "0"),
    "deadline_at": ("timestamp with time zone", "YES", None),
}
_NOT_W1 = ("lease_expires_at", "attempts", "dead_at", "cancel_requested_at", "trigger_ref")


async def test_r3_1_the_seventeen_columns_as_the_data_section_names_them(
    migrator: AsyncEngine,
) -> None:
    async with migrator.connect() as conn:
        found = {
            row.column_name: (row.data_type, row.is_nullable, row.column_default)
            for row in await conn.execute(
                sa.text(
                    "SELECT column_name, data_type, is_nullable, column_default"
                    " FROM information_schema.columns"
                    " WHERE table_schema = 'platform' AND table_name = 'worker_runs'"
                )
            )
        }
    assert {name: found.get(name) for name in _COLUMNS} == _COLUMNS
    assert [name for name in _NOT_W1 if name in found] == []
    # The table description the runtime and the door write through.
    assert set(found) == {column.name for column in worker_runs.columns}
    assert {c.name for c in worker_runs.columns if not c.nullable} == {
        name for name, (_, nullable, _) in found.items() if nullable == "NO"
    }


async def test_r3_1_priority_is_one_of_three(
    app_engine: AsyncEngine, roots: Roots, world: StudioWorld
) -> None:
    assert await refused(insert(app_engine, studio_row(roots.mine, priority=3))) == (
        "ck_worker_runs_priority"
    )
    await insert(app_engine, studio_row(roots.mine, priority=2))


async def test_r3_1_a_row_naming_no_root_is_its_own_and_the_tree_holds_its_shape(
    app_engine: AsyncEngine, migrator: AsyncEngine, roots: Roots, world: StudioWorld
) -> None:
    run = code_row(world["writer"])
    await insert(app_engine, run)
    stored = await row_of(migrator, run["id"])
    assert (stored.root_run_id, stored.chain_depth, stored.parent_run_id) == (run["id"], 0, None)
    # A root names itself, nothing else.
    assert await refused(
        insert(app_engine, code_row(world["writer"], root_run_id=uuid.uuid4()))
    ) == ("ck_worker_runs_root_run")
    # A child names its parent and sits deeper.
    assert await refused(
        insert(app_engine, code_row(world["writer"], parent_run_id=run["id"], chain_depth=0))
    ) == ("ck_worker_runs_root_run")


async def test_r3_1_a_parent_with_a_child_is_not_deleted(
    app_engine: AsyncEngine, migrator: AsyncEngine, roots: Roots
) -> None:
    parent = studio_row(roots.mine)
    child = studio_row(
        roots.mine, parent_run_id=parent["id"], root_run_id=parent["id"], chain_depth=1
    )
    await insert(app_engine, parent)
    await insert(app_engine, child)
    assert await refused(
        as_app(
            app_engine,
            roots.mine.who.tenant_id,
            "DELETE FROM platform.worker_runs WHERE id = :r",
            r=parent["id"],
        )
    ) == ("fk_worker_runs_parent_run_id_worker_runs")
    assert await row_of(migrator, parent["id"]) is not None
    assert await row_of(migrator, child["id"]) is not None


async def test_r3_1_the_definition_hash_is_read_by_its_owner(
    app_engine: AsyncEngine, roots: Roots, world: StudioWorld
) -> None:
    # A wf-lite run keeps its bare hex; a Studio run carries `sha256:`.
    await insert(app_engine, code_row(world["writer"], definition_hash=HEX))
    await insert(app_engine, studio_row(roots.mine, definition_hash=SHA))
    assert await refused(insert(app_engine, studio_row(roots.mine, definition_hash=HEX))) == (
        "ck_worker_runs_definition_hash"
    )
    assert await refused(insert(app_engine, code_row(world["writer"], definition_hash=SHA))) == (
        "ck_worker_runs_definition_hash"
    )


async def test_r3_1_a_dead_letter_holds_no_thread(
    app_engine: AsyncEngine, world: StudioWorld
) -> None:
    thread = uuid.uuid4()
    await insert(app_engine, code_row(world["writer"], thread_id=thread, status="dead_lettered"))
    await insert(app_engine, code_row(world["writer"], thread_id=thread, status="running"))
    assert await refused(
        insert(app_engine, code_row(world["writer"], thread_id=thread, status="queued"))
    ) == ("uq_worker_runs_active_thread")


async def test_r3_1_the_finished_statuses_are_one_set_in_code_and_index(
    app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """Each status: a run in it either holds its thread (the index) or it is
    in `TERMINAL_STATUSES`, never both, never neither."""
    holds: set[RunStatus] = set()
    for status in RunStatus:
        thread = uuid.uuid4()
        await insert(app_engine, code_row(world["writer"], thread_id=thread, status=status.value))
        try:
            await insert(app_engine, code_row(world["writer"], thread_id=thread))
        except DBAPIError:
            holds.add(status)
    assert set(RunStatus) - holds == set(TERMINAL_STATUSES)


# ---- R3.2, R3.3, R3.19: what a Studio row must carry -------------------------------


async def test_r3_2_a_status_outside_the_set_is_refused(
    app_engine: AsyncEngine, roots: Roots
) -> None:
    assert await refused(insert(app_engine, studio_row(roots.mine, status="bogus"))) == (
        "ck_worker_runs_status"
    )


@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("run_manifest_hash", "ck_worker_runs_studio_manifest"),
        ("run_as_principal_id", "ck_worker_runs_studio_run_as"),
        ("request_key", "ck_worker_runs_studio_request_key"),
        ("artifact_version_id", "ck_worker_runs_studio_artifact"),
        ("artifact_id", "ck_worker_runs_studio_artifact"),
        ("trigger_kind", "ck_worker_runs_studio_trigger_kind"),
    ],
)
async def test_r3_3_r3_19_a_studio_row_without_what_it_must_carry_is_refused(
    app_engine: AsyncEngine, roots: Roots, column: str, constraint: str
) -> None:
    assert await refused(insert(app_engine, studio_row(roots.mine, **{column: None}))) == (
        constraint
    )


async def test_a_code_run_carrying_studio_columns_is_refused(
    app_engine: AsyncEngine, roots: Roots, world: StudioWorld
) -> None:
    assert await refused(
        insert(app_engine, code_row(world["writer"], artifact_version_id=roots.mine.version_id))
    ) == ("ck_worker_runs_studio_artifact")


# ---- R3.8 (WE18): the trigger kind -------------------------------------------------


async def test_r3_8_the_trigger_kind_is_one_of_w1_and_required_of_a_studio_run(
    app_engine: AsyncEngine, roots: Roots, world: StudioWorld
) -> None:
    assert await refused(insert(app_engine, studio_row(roots.mine, trigger_kind="bogus"))) == (
        "ck_worker_runs_trigger_kind"
    )
    assert await refused(insert(app_engine, studio_row(roots.mine, trigger_kind=None))) == (
        "ck_worker_runs_studio_trigger_kind"
    )
    await insert(app_engine, code_row(world["writer"]))  # no kind, no Studio column


async def test_r3_8_the_checks_set_is_the_doors(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        definition = await conn.scalar(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_worker_runs_trigger_kind'"
            )
        )
    assert set(re.findall(r"'(\w+)'::text", definition)) == W1_TRIGGER_KINDS


# ---- R3.7, R3.12 (WE21): another company -------------------------------------------


async def test_r3_7_another_companys_run_reads_as_nothing(
    app_engine: AsyncEngine, roots: Roots
) -> None:
    theirs = studio_row(roots.theirs)
    await insert(app_engine, theirs)
    seen = await as_app(
        app_engine,
        roots.mine.who.tenant_id,
        "SELECT id FROM platform.worker_runs WHERE id = :r",
        r=theirs["id"],
    )
    assert seen == []


async def test_r3_12_a_run_cannot_name_another_companys_version_or_parent(
    app_engine: AsyncEngine, migrator: AsyncEngine, roots: Roots
) -> None:
    across = studio_row(roots.mine, artifact_version_id=roots.theirs.version_id)
    assert await refused(insert(app_engine, across)) == (
        "fk_worker_runs_artifact_version_id_artifact_versions"
    )
    assert await row_of(migrator, across["id"]) is None

    their_parent = studio_row(roots.theirs)
    await insert(app_engine, their_parent)
    child = studio_row(
        roots.mine,
        parent_run_id=their_parent["id"],
        root_run_id=their_parent["id"],
        chain_depth=1,
    )
    assert await refused(insert(app_engine, child)) == ("fk_worker_runs_parent_run_id_worker_runs")
    assert await row_of(migrator, child["id"]) is None
