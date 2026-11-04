"""The `workflow` kind against Postgres (workflow-engine ticket 01: R1.3-R1.6).

The kind reaches the envelope only through its registry entry, built over
the fixture step types and a `FakeTriggerActivation`. The artifacts a
workflow uses stand in as `fixture_gateless` artifacts with a `live` v1, since
the seal pins any artifact a reference names (tools-and-skills 02 does the
same for a toolset's objects).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.run_manifests import draft_of, fixture_document, published, sealed
from dw_studio.testing.workflows import (
    FakeTriggerActivation,
    plant_holder,
    studio_document,
    studio_step,
    workflow_entry,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

TRIGGERS = FakeTriggerActivation()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(migrator: AsyncEngine) -> AsyncIterator[tuple[StudioWorld, Person]]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            planted = await plant_world(conn)
            author = await plant_holder(conn, planted.tenant, workspace=planted.ws1)
        yield planted, author


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(
    studio_db: DatabaseUrls, world: tuple[StudioWorld, Person]
) -> AsyncIterator[ArtifactService]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    ids = Uuid7Generator()
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    registry = ArtifactKindRegistry((*FIXTURE_KINDS, workflow_entry(TRIGGERS)))
    yield ArtifactService(SqlArtifactStore(sessions, ids), registry, SystemClock(), ids)
    await engine.dispose()


async def rows(migrator: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with migrator.connect() as conn:
        return list((await conn.execute(sa.text(statement), values)).all())


def nested(source: uuid.UUID, obj: uuid.UUID) -> dict[str, Any]:
    """A trigger using `source`, and a step reading `obj` in the error lane of
    a step in the approved lane of an approval."""
    reader = studio_step("doc_lead", "fixture.object@1", object=str(obj))
    risky = {**studio_step("thu_gui"), "on_error": "route", "error_lane": [reader]}
    gate = studio_step(
        "duyet",
        "human.approval@1",
        decision_class="lead.reply",
        proposal="x",
        approved=[risky],
        rejected=[],
    )
    return {
        **studio_document(gate, source=str(source)),
        "decision_classes": [
            {"key": "lead.reply", "effect_level": "internal", "reversible": True, "ceiling": "A2"}
        ],
    }


async def test_r1_3_a_seal_indexes_every_use_at_every_depth(
    service: ArtifactService, migrator: AsyncEngine, world: tuple[StudioWorld, Person]
) -> None:
    planted, author = world
    source, _ = await published(service, migrator, planted["writer"], fixture_document())
    obj, _ = await published(service, migrator, planted["writer"], fixture_document())
    artifact_id, _, row_version = await draft_of(
        service, author, nested(source, obj), kind="workflow"
    )
    result = await sealed(service, author, artifact_id, row_version)

    found = await rows(
        migrator,
        "SELECT to_kind, to_key, usage, path, to_version_id IS NOT NULL AS pinned"
        " FROM studio.dependencies WHERE from_version_id = :v ORDER BY path",
        v=result.version_id,
    )
    assert sorted((r.to_kind, r.to_key, r.path, r.pinned) for r in found) == sorted(
        [
            ("node_type", "fixture.trigger@1", "/triggers/0/type", False),
            ("artifact", str(source), "/triggers/0/config/source", True),
            ("node_type", "human.approval@1", "/steps/0/type", False),
            ("node_type", "fixture.effect@1", "/steps/0/config/approved/0/type", False),
            (
                "node_type",
                "fixture.object@1",
                "/steps/0/config/approved/0/error_lane/0/type",
                False,
            ),
            (
                "artifact",
                str(obj),
                "/steps/0/config/approved/0/error_lane/0/config/object",
                True,
            ),
        ]
    )
    # The closure the definition hash pins holds both artifacts.
    assert {item.key for item in result.closure if item.kind == "artifact"} == {
        str(source),
        str(obj),
    }


async def test_r1_4_a_seal_runs_the_kind_s_check(
    service: ArtifactService, world: tuple[StudioWorld, Person]
) -> None:
    _, author = world
    bad = studio_document(studio_step("x", "foo.bar@1"))
    artifact_id, _, row_version = await draft_of(service, author, bad, kind="workflow")
    with pytest.raises(DocumentInvalidError) as refused:
        await sealed(service, author, artifact_id, row_version)
    assert [(p.code, p.pointer) for p in refused.value.problems] == [
        ("wf.unknown_type", "/steps/0/type")
    ]


async def _one_step(
    service: ArtifactService, migrator: AsyncEngine, world: tuple[StudioWorld, Person]
) -> tuple[uuid.UUID, int]:
    """A workflow draft of one step whose trigger uses a live source."""
    planted, author = world
    source, _ = await published(service, migrator, planted["writer"], fixture_document())
    document = studio_document(studio_step("x"), source=str(source))
    artifact_id, _, row_version = await draft_of(service, author, document, kind="workflow")
    return artifact_id, row_version


async def test_r1_6_the_hook_runs_on_the_publish_transaction_and_changes_no_stage(
    service: ArtifactService, migrator: AsyncEngine, world: tuple[StudioWorld, Person]
) -> None:
    _, author = world
    artifact_id, row_version = await _one_step(service, migrator, world)
    result = await sealed(service, author, artifact_id, row_version)
    TRIGGERS.versions[result.version_id] = artifact_id
    hook = service.registry.get("workflow").publish_hook  # type: ignore[union-attr]

    async with service.store.transaction(author.context()) as tx:
        await hook(tx, result.version_id)
    TRIGGERS.settle(tx, committed=True)

    assert TRIGGERS.calls[-1] == (tx, result.version_id)
    assert TRIGGERS.active[artifact_id] == result.version_id
    version = await rows(
        migrator,
        "SELECT stage FROM studio.artifact_versions WHERE id = :v",
        v=result.version_id,
    )
    assert [r.stage for r in version] == ["draft"]
    published_events = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.audit_events"
        " WHERE resource_id = :a AND action = 'studio.version.published'",
        a=str(artifact_id),
    )
    assert published_events[0].n == 0


async def test_r1_6_a_failing_port_rolls_the_publish_transaction_back(
    service: ArtifactService, migrator: AsyncEngine, world: tuple[StudioWorld, Person]
) -> None:
    """The seal written in the same transaction is undone with it."""
    _, author = world
    artifact_id, row_version = await _one_step(service, migrator, world)
    failing = FakeTriggerActivation(fail=True)
    hook = workflow_entry(failing).publish_hook
    with pytest.raises(ConflictError):
        async with service.store.transaction(author.context()) as tx:
            result = await service.seal(tx, artifact_id, row_version)
            await hook(tx, result.version_id)
    version = await rows(
        migrator,
        "SELECT stage, version_no FROM studio.artifact_versions WHERE artifact_id = :a",
        a=artifact_id,
    )
    assert [(r.stage, r.version_no) for r in version] == [("draft", None)]
    assert failing.active == {}


async def test_r1_5_the_kind_row_and_its_keys_are_in_the_catalogue(
    migrator: AsyncEngine,
) -> None:
    kind = await rows(
        migrator, "SELECT has_quality_gate FROM studio.artifact_kinds WHERE kind = 'workflow'"
    )
    assert [r.has_quality_gate for r in kind] == [True]
    keys = await rows(
        migrator,
        "SELECT key, area, scope_kind, risk, status, owner_package, tenant_grantable"
        " FROM platform.permissions WHERE key LIKE 'studio.workflows.%' ORDER BY key",
    )
    assert [tuple(r) for r in keys] == [
        (key, "studio", "workspace", "standard", "active", "dw_studio", True)
        for key in ("studio.workflows.edit", "studio.workflows.read", "studio.workflows.test")
    ]
