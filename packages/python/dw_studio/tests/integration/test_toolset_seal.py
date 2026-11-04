"""A toolset through the envelope's seal and back out of a run manifest
(tools-and-skills ticket 02: R4.2, R4.5; TS1).

The `fixture` kind embeds a `toolset` the way an agent version will, and
reaches the service only through its registry (tenant-config R2.15). Its
objects stand in as `fixture_gateless` artifacts with a `live` v1: the seal
pins any artifact a reference names, and which kind an object tool needs is
ticket 03's to check when it compiles one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
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

from dw_agent_runtime.adapters.studio_tools import CompiledTool, studio_tools
from dw_agent_runtime.contracts import ToolDefinition
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.model.profiles import ModelCapabilities
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import PinnedEntry
from dw_agent_runtime.tool_kinds import ToolAssembler, ToolBinding, ToolContract
from dw_agent_runtime.tool_schema import json_schema_behaviour
from dw_agent_runtime.tools import ToolBehaviour, ToolRegistry
from dw_kernel.errors import ErrorCode
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.service import ArtifactService
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.core.domain.toolset import parse_toolset
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.run_manifests import (
    TEST_PLAN,
    draft_of,
    fixture_document,
    live_closure,
    published,
    sealed,
    shipped_models,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REF = "sha256:" + "e" * 64
COPY = load_runtime_copy(
    Path(__file__).resolve().parents[5] / "configs" / "copy" / "runtime@1.3.0.yaml"
)
SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


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


def with_toolset(tools: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {**fixture_document(title="Trợ lý"), "toolset": {"tools": list(tools)}}


def objects(ids: Sequence[uuid.UUID]) -> list[dict[str, Any]]:
    return [{"kind": "object_crud", "object": str(i), "operations": ["search", "get"]} for i in ids]


ACTION: dict[str, Any] = {
    "kind": "connector_action",
    "connector": "smtp@1.0.0",
    "action": "email.send",
    "binding": "hop_thu",
}


async def stage_of(migrator: AsyncEngine, version_id: uuid.UUID) -> tuple[str, int | None]:
    async with migrator.begin() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT stage, version_no FROM studio.artifact_versions WHERE id = :v"),
                {"v": version_id},
            )
        ).one()
    return row.stage, row.version_no


async def dependencies(migrator: AsyncEngine, version_id: uuid.UUID) -> list[Any]:
    async with migrator.begin() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT to_kind, to_key, usage, path, to_version_id, to_hash"
                        " FROM studio.dependencies WHERE from_version_id = :v"
                        " ORDER BY path, to_kind"
                    ),
                    {"v": version_id},
                )
            ).all()
        )


async def refused_seal(
    service: ArtifactService, who: Person, document: dict[str, Any]
) -> tuple[DocumentInvalidError, uuid.UUID]:
    artifact_id, version_id, row_version = await draft_of(service, who, document)
    with pytest.raises(DocumentInvalidError) as caught:
        await sealed(service, who, artifact_id, row_version)
    return caught.value, version_id


# ------------------------------------------------------------------- R4.5 --


async def test_forty_one_tools_are_refused_at_seal_and_forty_are_sealed(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """R4.5: twenty object entries of two operations and one action are 41
    tools → 422 `validation_failed`, `too_many_tools`, the version still a
    draft; the twenty alone are 40 and seal, each object pinned at its live
    version and hash."""
    writer = world["writer"]
    targets = await live_closure(service, migrator, writer, 20)

    refused, draft_id = await refused_seal(
        service, writer, with_toolset([*objects(targets), ACTION])
    )

    assert refused.code is ErrorCode.VALIDATION_FAILED
    assert [(p.pointer, p.code) for p in refused.problems] == [("/toolset/tools", "too_many_tools")]
    assert await stage_of(migrator, draft_id) == ("draft", None)

    artifact_id, _, row_version = await draft_of(service, writer, with_toolset(objects(targets)))
    result = await sealed(service, writer, artifact_id, row_version)

    pinned = await dependencies(migrator, result.version_id)
    assert len(pinned) == 20
    assert {row.to_kind for row in pinned} == {"artifact"}
    assert all(row.to_version_id is not None and row.to_hash for row in pinned)


async def test_an_object_and_an_action_pin_the_object_and_name_the_connector_and_binding(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    writer = world["writer"]
    lead_id, lead = await published(service, migrator, writer, fixture_document(title="Lead"))
    artifact_id, _, row_version = await draft_of(
        service, writer, with_toolset([*objects([lead_id]), ACTION])
    )

    result = await sealed(service, writer, artifact_id, row_version)

    rows = [
        (r.to_kind, r.to_key, r.usage, r.path, r.to_version_id, r.to_hash)
        for r in await dependencies(migrator, result.version_id)
    ]
    assert rows == [
        ("artifact", str(lead_id), "read", "/toolset/tools/0", lead.version_id, lead.content_hash),
        ("binding", "hop_thu", "bind", "/toolset/tools/1", None, None),
        ("connector", "smtp@1.0.0", "invoke", "/toolset/tools/1", None, None),
    ]


async def test_an_object_with_no_live_version_is_unresolved_at_its_entry(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    writer = world["writer"]
    drafted, draft_version, _ = await draft_of(service, writer, fixture_document())

    refused, version_id = await refused_seal(
        service, writer, with_toolset([ACTION, *objects([drafted])])
    )

    assert [(p.pointer, p.code) for p in refused.problems] == [
        ("/toolset/tools/1", "dependency_unresolved")
    ]
    assert await stage_of(migrator, version_id) == ("draft", None)
    assert await stage_of(migrator, draft_version) == ("draft", None)


async def test_another_tenants_live_object_is_unresolved_like_one_that_never_existed(
    service: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """CLAUDE.md, Tenancy: tenant B's live object named in tenant A's toolset
    answers as an id nobody has, and nothing is pinned."""
    writer, outsider = world["writer"], world["outsider"]
    theirs, _ = await published(service, migrator, outsider, fixture_document(title="Của B"))

    foreign, foreign_version = await refused_seal(service, writer, with_toolset(objects([theirs])))
    missing, _ = await refused_seal(service, writer, with_toolset(objects([uuid.uuid4()])))

    assert [(p.pointer, p.code) for p in foreign.problems] == [
        (p.pointer, p.code) for p in missing.problems
    ]
    assert foreign.problems[0].code == "dependency_unresolved"
    assert await dependencies(migrator, foreign_version) == []


async def test_a_kind_outside_w1_is_refused_at_seal(
    service: ArtifactService, world: StudioWorld
) -> None:
    refused, _ = await refused_seal(
        service, world["writer"], with_toolset([{"kind": "http", "url": "https://a.vn"}])
    )

    assert [(p.pointer, p.code) for p in refused.problems] == [
        ("/toolset/tools/0/kind", "toolset.kind_unsupported")
    ]


# ------------------------------------------------- R4.2 through a manifest --


class Factory:
    def build(self, binding: ToolBinding, contract: ToolContract) -> ToolBehaviour:
        async def handler(payload: Any, run_context: Any) -> Any:
            return {}

        return json_schema_behaviour(contract.input_schema, contract.output_schema, handler)


def tool_definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0.0",
        description=name,
        input_schema_ref=f"pinned/{name}/input.json",
        output_schema_ref=f"pinned/{name}/output.json",
        required_scopes=frozenset(),
        side_effect_level="none",
        approval_policy="never",
        timeout_seconds=5,
        max_retries=0,
        idempotent=True,
        data_classification=frozenset({"internal"}),
    )


class ObjectSource:
    def compile(self, entry: Any, pinned: PinnedEntry) -> Sequence[CompiledTool]:
        assert pinned.artifact is not None
        return [
            CompiledTool(
                ToolBinding("object_crud", operation="read"),
                ToolContract(tool_definition(f"obj_lead.{op}"), SCHEMA, SCHEMA),
            )
            for op in entry.operations
        ]


class ActionSource:
    def compile(self, entry: Any, pinned: PinnedEntry) -> Sequence[CompiledTool]:
        return [
            CompiledTool(
                ToolBinding("connector_action", operation="read"),
                ToolContract(tool_definition(entry.action), SCHEMA, SCHEMA),
            )
        ]


async def test_a_sealed_toolset_builds_from_the_run_manifest_with_its_pins(
    service: ArtifactService, migrator: AsyncEngine, app_engine: AsyncEngine, world: StudioWorld
) -> None:
    """R4.2: the run's manifest, read back in a session of the run's tenant,
    gives every entry's tool its pinned version id and hash; nothing is read
    from the registry, nothing written to it."""
    writer = world["writer"]
    lead_id, lead = await published(service, migrator, writer, fixture_document(title="Lead"))
    _, root = await published(
        service, migrator, writer, with_toolset([*objects([lead_id]), ACTION])
    )
    store = service.store
    assert isinstance(store, SqlArtifactStore)  # its transaction is a `RunManifestTx` too
    builder = RunManifestBuilder(ArtifactKindRegistry(FIXTURE_KINDS), REF, shipped_models())
    async with store.transaction(writer.context()) as tx:
        manifest_hash = await builder.build(
            tx, root.version_id, "live", tenant_id=writer.tenant_id, plan_id=TEST_PLAN
        )
    sessions = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    async with tenant_session(sessions, TenantScope(tenant_id=writer.tenant_id)) as session:
        resolver = await PinnedResolver.load(SqlRunManifestStore(session), manifest_hash)
    assert resolver.root.artifact is not None
    registry = ToolRegistry()

    built = studio_tools(
        parse_toolset(resolver.root.artifact.document["toolset"]).tools,
        resolver,
        ToolAssembler(
            registry=registry, kinds={"object_crud": Factory(), "connector_action": Factory()}
        ),
        {"object_crud": ObjectSource(), "connector_action": ActionSource()},
        executor=None,  # type: ignore[arg-type]  # nothing is called here
        capabilities=ModelCapabilities(),
        approval_type_prefix="studio.agent.tool.",
        copy=COPY,
    )

    assert [(t.name, t.metadata) for t in built.tools] == [
        (
            "obj_lead__search",
            {
                "tool_version_id": str(lead.version_id),
                "content_hash": lead.content_hash,
                "kind": "object_crud",
            },
        ),
        (
            "obj_lead__get",
            {
                "tool_version_id": str(lead.version_id),
                "content_hash": lead.content_hash,
                "kind": "object_crud",
            },
        ),
        (
            "email__send",
            {"tool_version_id": "smtp@1.0.0", "content_hash": None, "kind": "connector_action"},
        ),
    ]
    assert registry.all_definitions() == []
