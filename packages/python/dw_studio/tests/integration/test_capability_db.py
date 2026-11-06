"""The capability analysis at a workflow's submit, on PostgreSQL (compliance-pdpl
ticket 05: R4.6, R4.7, R4.8, R5.5; CP21, CP26).

The real `LifecycleService` submit over `SqlArtifactStore` as `dw_app`, the
`workflow` kind over the fixture step types, with the check the composition
root registers (`workflow_capability_check`) given the test's label table
(`test_capability.py`'s): its facts read and its row written in the submit's
own transaction, under the submitting company's RLS.
"""

from __future__ import annotations

import dataclasses
import importlib
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from dw_agent_runtime.wflite.registry import registry_of
from dw_kernel.errors import DomainError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import WORKFLOW_KIND, workflow_kind
from dw_studio.lifecycle.adapters.store import SqlLifecycleStore
from dw_studio.lifecycle.application.service import LifecycleService
from dw_studio.submit_checks import workflow_capability_check
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS
from dw_studio.testing.lifecycle import StubBindings
from dw_studio.testing.workflows import (
    FakeTriggerActivation,
    NoTools,
    UncheckedExpressions,
    studio_step,
)
from dw_studio.workflows.adapters.capability import SqlVersionAssessments
from dw_studio.workflows.application.capability import (
    EXTERNAL,
    PRIVATE,
    UNTRUSTED,
    CapabilityFacts,
    LabelTable,
)
from dw_studio.workflows.application.capability_check import child_labels
from dw_studio.workflows.testing.fakes import RecordingBoundaries

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

_shared: Any = importlib.import_module("test_studio_runs")
World = Any
app_engine = _shared.app_engine
migrator = _shared.migrator
sessions = _shared.sessions
source = _shared.source
store = _shared.store
world = _shared.world
doc = _shared.doc
rows = _shared.rows


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(store: SqlArtifactStore) -> ArtifactService:
    return ArtifactService(store, kinds_with_test_types(), SystemClock(), store.ids)


_EFFECT = _shared.REGISTRY["fixture.effect@1"]
_CHILD_SCHEMA = {
    "type": "object",
    "required": ["version_id"],
    "properties": {"version_id": {"type": "string"}},
    "additionalProperties": False,
}
TYPES = (
    dataclasses.replace(_EFFECT, type="test.web@1", side_effect_level="none"),
    dataclasses.replace(_EFFECT, type="test.lead@1", side_effect_level="none"),
    dataclasses.replace(_EFFECT, type="test.send@1", side_effect_level="external"),
    dataclasses.replace(
        _EFFECT, type="test.child@1", side_effect_level="none", config_schema=_CHILD_SCHEMA
    ),
)
NODES = registry_of((*_shared.REGISTRY.values(), *TYPES))


def kinds_with_test_types() -> ArtifactKindRegistry:
    """The fixture kinds and a `workflow` kind over the fixture step types and
    the test's own, so a document using them seals."""
    return ArtifactKindRegistry(
        (
            *FIXTURE_KINDS,
            workflow_kind(
                nodes=NODES,
                tools=NoTools(),
                triggers=FakeTriggerActivation(),
                boundaries=RecordingBoundaries(),
                expressions=UncheckedExpressions(),
            ),
        )
    )


def _none(*_: Any) -> frozenset[Any]:
    return frozenset()


TABLE = LabelTable(
    rules={
        "test.web@1": lambda *_: frozenset({UNTRUSTED}),
        "test.lead@1": lambda *_: frozenset({PRIVATE}),
        "test.send@1": _none,
        "test.child@1": child_labels,
        "fixture.effect@1": _none,
        "fixture.trigger@1": _none,
    },
    internal_triggers=frozenset({"fixture.trigger@1"}),
    gates=frozenset({"human.approval@1"}),
    source_of=lambda step: None,
    child_types=frozenset({"test.child@1"}),
)


class Controls:
    async def admission_state(self, tenant_id: uuid.UUID, artifacts: Any = ()) -> str | None:
        return None


class FailingLookup:
    async def labels(self, tx: Any, version_ids: Any) -> Mapping[uuid.UUID, frozenset[Any]]:
        raise ConnectionError("the database went away")


def lifecycle_with(
    store: SqlArtifactStore, service: ArtifactService, check: Any
) -> LifecycleService:
    return LifecycleService(
        SqlLifecycleStore(store),
        service,
        Controls(),
        {WORKFLOW_KIND: (check,)},
        SystemClock(),
        bindings=StubBindings(),
    )


def capability(**over: Any) -> Any:
    check = workflow_capability_check(
        registry=NODES,
        tools=NoTools(),
        ids=Uuid7Generator(),
        profile_locations=lambda profile: None,
        default_profile=None,
        table=TABLE,
    )
    if over:
        inner = check.check
        current: Any = inner.facts
        facts = dataclasses.replace(current, **over)
        check = dataclasses.replace(check, check=dataclasses.replace(inner, facts=facts))
    return check


async def submit_new(
    store: SqlArtifactStore,
    service: ArtifactService,
    world: World,
    document: dict[str, Any],
    check: Any = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    from dw_studio.testing.run_manifests import draft_of

    artifact, version, row_version = await draft_of(
        service, world.tester, document, kind="workflow"
    )
    lifecycle = lifecycle_with(store, service, check or capability())
    await lifecycle.submit(
        world.tester.context(), "workflow", artifact, version, ExpectedVersion(row_version)
    )
    return artifact, version


def w(*steps: dict[str, Any], source: uuid.UUID) -> dict[str, Any]:
    document: dict[str, Any] = doc(source, *steps)
    return document


async def assessments_of(migrator: AsyncEngine, version: uuid.UUID) -> list[Any]:
    found: list[Any] = await rows(
        migrator,
        "SELECT tenant_id, signals, labels, analyser_version, definition_hash"
        " FROM studio.version_assessments WHERE version_id = :v",
        v=version,
    )
    return found


WEB = studio_step("web", "test.web@1")
LEAD = studio_step("lead", "test.lead@1")
SEND = studio_step("gui", "test.send@1")


# ---- R4.6: one row, in the submit's transaction ------------------------------------


async def test_r4_6_a_valid_submit_writes_one_row_and_a_second_adds_none(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version = await submit_new(store, service, world, w(WEB, SEND, source=source))
    (row,) = await assessments_of(migrator, version)
    assert sorted(row.signals) == sorted({UNTRUSTED, EXTERNAL})
    assert row.analyser_version == "1" and row.labels["gui"] == [EXTERNAL]
    (version_row,) = await rows(
        migrator, "SELECT definition_hash FROM studio.artifact_versions WHERE id = :v", v=version
    )
    assert row.definition_hash == version_row.definition_hash
    # Written again for the same content and analyser: nothing added, no error.
    async with store.transaction(world.tester.context()) as tx:
        found = await tx.versions(await _artifact_of(migrator, version))
        (sealed,) = [v for v in found if v.id == version]
        await SqlVersionAssessments(Uuid7Generator()).write(
            tx, sealed, _analysis({"gui": frozenset({EXTERNAL})})
        )
    assert len(await assessments_of(migrator, version)) == 1


async def test_r4_2_a_refused_submit_leaves_no_row_and_the_draft(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    from dw_studio.testing.run_manifests import draft_of

    artifact, version, row_version = await draft_of(
        service, world.tester, w(WEB, LEAD, SEND, source=source), kind="workflow"
    )
    with pytest.raises(DomainError) as refused:
        await lifecycle_with(store, service, capability()).submit(
            world.tester.context(), "workflow", artifact, version, ExpectedVersion(row_version)
        )
    assert refused.value.details["reason_code"] == "trifecta_path_unapproved"
    assert refused.value.details["paths"] == [["web", "lead", "gui"]]
    assert await assessments_of(migrator, version) == []
    (row,) = await rows(
        migrator, "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=version
    )
    assert row.stage == "draft"


async def test_r4_6_dw_app_cannot_update_an_assessment(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version = await submit_new(store, service, world, w(SEND, source=source))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(world.tenant)}
            )
            await conn.execute(
                sa.text(
                    "UPDATE studio.version_assessments SET verdict = 'pass' WHERE version_id = :v"
                ),
                {"v": version},
            )


# ---- R4.7: a row never names another company's version --------------------------------


async def test_r4_7_a_row_of_company_a_never_names_a_version_of_company_b(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version = await submit_new(store, service, world, w(SEND, source=source))
    other = world.studio.other.tenant_id
    with pytest.raises(DBAPIError) as refused:
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(other)}
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.version_assessments (tenant_id, id, version_id,"
                    " definition_hash, analyser_version, signals, labels, verdict)"
                    " VALUES (:t, gen_random_uuid(), :v, :h, '1', '{}', '{}', 'pass')"
                ),
                {"t": other, "v": version, "h": "sha256:" + "0" * 64},
            )
    assert getattr(getattr(refused.value, "orig", None), "sqlstate", None) == "23503"


# ---- R5.5: offboarding takes the rows with the versions ------------------------------


async def test_r5_5_deleting_a_version_takes_its_assessment_and_spares_the_rest(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    gone_artifact, gone = await submit_new(store, service, world, w(SEND, source=source))
    _, kept = await submit_new(store, service, world, w(SEND, source=source))
    # As the offboarding lane's purge deletes a company's versions; outside
    # it the guard refuses, so the test stands it aside in its transaction.
    async with migrator.begin() as conn:
        for statement in (
            "ALTER TABLE studio.artifact_versions DISABLE TRIGGER USER",
            "DELETE FROM studio.dependencies WHERE from_version_id = :v",
            "DELETE FROM studio.artifact_versions WHERE id = :v",
            "ALTER TABLE studio.artifact_versions ENABLE TRIGGER USER",
        ):
            await conn.execute(sa.text(statement), {"v": gone} if ":v" in statement else {})
    assert await assessments_of(migrator, gone) == []
    assert len(await assessments_of(migrator, kept)) == 1
    _ = gone_artifact


# ---- R4.8: a child's row, under the submitting company's RLS ------------------------


async def test_r4_8_a_childs_row_carries_its_labels_into_the_parent(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, child_version = await submit_new(store, service, world, w(SEND, source=source))
    parent = w(
        WEB, LEAD, studio_step("con", "test.child@1", version_id=str(child_version)), source=source
    )
    from dw_studio.testing.run_manifests import draft_of

    artifact, version, row_version = await draft_of(service, world.tester, parent, kind="workflow")
    with pytest.raises(DomainError) as refused:
        await lifecycle_with(store, service, capability()).submit(
            world.tester.context(), "workflow", artifact, version, ExpectedVersion(row_version)
        )
    assert refused.value.details["paths"] == [["web", "lead", "con"]]


async def test_r4_8_another_companys_child_row_is_not_read_so_the_step_carries_every_label(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    """The child is of this company but its row is planted under another
    company's id: RLS does not return it, so the step carries all three, and a
    step carrying all three needs an approval of its own."""
    _, child_version = await submit_new(
        store, service, world, w(studio_step("noop", "fixture.effect@1"), source=source)
    )
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE studio.version_assessments SET signals = '{}' WHERE version_id = :v"),
            {"v": child_version},
        )
    parent = w(studio_step("con", "test.child@1", version_id=str(child_version)), source=source)
    _, version = await submit_new(store, service, world, parent)
    (row,) = await assessments_of(migrator, version)
    assert row.labels["con"] == []
    # The same lookup in another company's transaction finds nothing.
    other = world.studio["outsider"]
    async with store.transaction(other.context()) as tx:
        found = await SqlVersionAssessments(Uuid7Generator()).labels(tx, [child_version])
    assert found == {}


async def test_r4_8_a_lookup_that_fails_fails_the_submit_and_writes_nothing(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    from dw_studio.testing.run_manifests import draft_of

    _, child_version = await submit_new(store, service, world, w(SEND, source=source))
    parent = w(studio_step("con", "test.child@1", version_id=str(child_version)), source=source)
    artifact, version, row_version = await draft_of(service, world.tester, parent, kind="workflow")
    with pytest.raises(ConnectionError):
        await lifecycle_with(store, service, capability(assessments=FailingLookup())).submit(
            world.tester.context(), "workflow", artifact, version, ExpectedVersion(row_version)
        )
    assert await assessments_of(migrator, version) == []


# ---- helpers ------------------------------------------------------------------------


async def _artifact_of(migrator: AsyncEngine, version: uuid.UUID) -> uuid.UUID:
    (row,) = await rows(
        migrator, "SELECT artifact_id FROM studio.artifact_versions WHERE id = :v", v=version
    )
    artifact: uuid.UUID = row.artifact_id
    return artifact


def _analysis(labels: Mapping[str, frozenset[Any]]) -> Any:
    from dw_studio.workflows.application.capability import CapabilityAnalysis

    return CapabilityAnalysis(labels, ())


_ = CapabilityFacts
