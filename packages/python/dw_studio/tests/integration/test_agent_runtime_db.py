"""A Studio agent's run on PostgreSQL (agent-builder ticket 03: R3.1-R3.8;
AB5, AB6, AB7, AB9, AB14, AB17).

Runs go in through the real `RunRequestService` over `SqlArtifactStore` as
`dw_app`, the `agent` and `object` kinds of the running app, and are run by
`LangGraphWorkflowRunner.run_studio` over the real `SqlStudioRunStore` and
checkpoint saver, with the real `StudioGraphSource` and `StudioAgentCompiler`.
Only the chat model is scripted (`Routes`), keyed by the route a call reaches,
and the turn and reply ports are in memory. A tool call is driven on the
compiled graph itself at autonomy A1, since a Studio agent's run has no
autonomy level at its door until compliance-pdpl/07 sets one (an A0 read waits
for a person, which ends the run `approval_wait_unavailable` here).
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from studio_run_stack import build_runner, claimed, run_claimed

from dw_agent_runtime.adapters.agent_threads import SqlAgentThreads
from dw_agent_runtime.adapters.chat_model import MockChatModel, require_permit
from dw_agent_runtime.adapters.langgraph_runner import (
    LangGraphWorkflowRunner,
    _studio_run_context,
    agent_run_context,
)
from dw_agent_runtime.adapters.record_session import agent_record_session
from dw_agent_runtime.adapters.run_names import SqlRunNames
from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.studio_agents import StudioAgentCompiler
from dw_agent_runtime.adapters.studio_resume import WorkflowEngineFacts
from dw_agent_runtime.adapters.tool_claims import SqlToolClaims
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.ports import StudioRun
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.studio_agent import AgentMessage, StudioAgentPorts
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.models import any_plan
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.tenant_session import (
    ActorBindingRefusedError,
    TenantScope,
    bind_tenant,
)
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.adapters.rate_limit import InProcessRateLimiter
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_platform.testing.residency import run_gate
from dw_studio.agents.adapters.graph_source import StudioGraphSource
from dw_studio.agents.application.settings import AGENTS_AUTHOR_SCOPE
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestEngines
from dw_studio.core.adapters.studio_runs import SqlStudioRunStore
from dw_studio.core.application.boundaries import (
    BoundaryDeriver,
    DerivedBoundary,
    FieldBoundary,
    ObjectBoundary,
)
from dw_studio.core.application.field_access import FieldAccessService
from dw_studio.core.application.registry import ArtifactKindRegistry, no_model_profiles
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import (
    PersonRequester,
    RunLaneRegistry,
    RunRequest,
    RunRequestService,
)
from dw_studio.core.application.service import ArtifactService
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.records.adapters.definition_store import SqlObjectDefinitionReader
from dw_studio.records.adapters.record_store import SqlRecordStore
from dw_studio.records.application.object_tools import ObjectToolKinds
from dw_studio.records.application.record_service import RecordDoor, RecordService
from dw_studio.records.application.schema_projector import ObjectSchemaProjector
from dw_studio.records.presentation.object_data import RecordObjectData
from dw_studio.testing.agents import AUTHOR_KEYS, agent_document
from dw_studio.testing.bindings import unasked_pins
from dw_studio.testing.lifecycle import move_for_test
from dw_studio.testing.object_tools import object_tool_copy
from dw_studio.testing.objects import object_document, object_field, plant_manager, running_kinds
from dw_studio.testing.record_world import holder, person_door, publish_object, sessions_of
from dw_studio.testing.run_manifests import sealed
from dw_studio.testing.workflows import plant_holder
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REPO = Path(__file__).resolve().parents[5]
REF = "sha256:" + "f" * 64
PROFILE = "agent_test_chat"
LEAD = "mkt_lead"
CAMPAIGN = "mkt_campaign"
LANES = {"studio_gate": ("eval",)}
ENGINE_FACTS = WorkflowEngineFacts(fixture_node_registry())
ANSWER = "Bạn có một lead."


def chat_profile(model: str = "agent-chat-1", location: str = "vn") -> ModelProfile:
    route = {
        "provider": "mock",
        "model": model,
        "data_location": location,
        "processor": "mock" if location == "vn" else "abroad",
        "retention_days": 0,
        "no_training": True,
    }
    return ModelProfile.model_validate(
        {
            "schema_version": "2.0",
            "profile_id": PROFILE,
            "routing_policy_version": "1.0.0",
            "structured_extraction": route,
            "reasoning": route,
            "chat": route,
        }
    )


def resolver_of(profile: ModelProfile, sessions: Any = None) -> ModelResolver:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO / "configs" / "models")
    profiles.register(profile)
    return ModelResolver(
        profiles,
        any_plan({PROFILE, "balanced"}),
        "balanced",
        None if sessions is None else SqlRunManifestEngines(sessions),
    )


class LoggedModel(MockChatModel):
    label: str
    log: Any

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        self.log.append(self.label)
        return super()._generate(messages, stop, run_manager, **kw)


@dataclass
class Routes:
    """`RouteChatModelFactory`: a scripted model per route's model name, each
    call logged; the script is the next turns of the run's conversation."""

    script: list[AIMessage] = field(default_factory=lambda: [AIMessage(ANSWER)])
    log: list[str] = field(default_factory=list)
    models: list[LoggedModel] = field(default_factory=list)

    def for_route(self, route: ModelRoute) -> BaseChatModel:
        model = LoggedModel(
            responses=list(self.script), mock_reply="", label=route.model, log=self.log
        )
        self.models.append(model)
        return require_permit(model)

    def systems(self) -> list[str]:
        return [s for m in self.models for s in m.system_prompts]


@dataclass
class Conversation:
    """`AgentTurnPort` and `AgentReplyPort` in memory."""

    replies: dict[uuid.UUID, str] = field(default_factory=dict)

    async def turn(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> Sequence[AgentMessage]:
        return [AgentMessage("user", "Tôi có bao nhiêu lead?")]

    async def reply(self, tenant_id: uuid.UUID, run_id: uuid.UUID, text: str) -> None:
        self.replies[run_id] = text


class NoThreads:
    async def forget(self, tenant_id: uuid.UUID, thread_id: uuid.UUID) -> None:
        return None


def lead_document() -> dict[str, Any]:
    return object_document(
        object_field("phone", "phone", pd_category="basic", is_unique=True),
        object_field("status", "picklist", indexed=True),
    )


# ---- the world ----------------------------------------------------------------


@dataclass
class World:
    migrator: AsyncEngine
    app: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    tenant: PlantedTenant
    manager: Person
    # Builds agents, and reads the leads it owns.
    tester: Person
    # Reads every lead of the workspace; owns `theirs`.
    colleague: Person
    lead: uuid.UUID
    campaign: uuid.UUID
    mine: uuid.UUID
    theirs: uuid.UUID
    records: RecordService
    conversation: Conversation = field(default_factory=Conversation)

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id

    def registry(self, *, profiles: bool = True) -> ArtifactKindRegistry:
        kinds = running_kinds()
        if not profiles:
            kinds = tuple(
                dataclasses.replace(k, model_profiles=no_model_profiles) if k.kind == "agent" else k
                for k in kinds
            )
        return ArtifactKindRegistry(kinds)

    def service(self) -> ArtifactService:
        ids = Uuid7Generator()
        return ArtifactService(
            SqlArtifactStore(self.sessions, ids), self.registry(), SystemClock(), ids
        )

    def door(
        self, *, profiles: bool = True, profile: ModelProfile | None = None
    ) -> RunRequestService:
        registry = self.registry(profiles=profiles)
        return RunRequestService(
            SqlArtifactStore(self.sessions, Uuid7Generator()),
            registry,
            RunManifestBuilder(registry, REF, resolver_of(profile or chat_profile()), ENGINE_FACTS),
            {("agent", "test"): AGENTS_AUTHOR_SCOPE, ("agent", "chat"): AGENTS_AUTHOR_SCOPE},
            RunLaneRegistry(LANES),
            SystemClock(),
            Uuid7Generator(),
            bindings=unasked_pins(),
            boundaries=SqlActorBoundaries(),
            # A stand-in for agent-builder/05's derivation: the boundary of a
            # version that pins `mkt_lead`'s read tools.
            boundary_derivers={"agent": BoundaryDeriver("agent", lead_boundary)},
            pinnable={},
        )

    async def rows(self, statement: str, **values: Any) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list((await conn.execute(sa.text(statement), values)).all())

    async def run_row(self, run_id: uuid.UUID) -> Any:
        [row] = await self.rows(
            "SELECT status, error, result, input, requested_by, run_as_principal_id"
            " FROM platform.worker_runs WHERE id = :r",
            r=run_id,
        )
        return row

    async def checkpoints(self, run_id: uuid.UUID) -> int:
        [row] = await self.rows(
            "SELECT count(*) AS n FROM platform.run_checkpoints WHERE thread_id = :r", r=run_id
        )
        return int(row.n)


async def past_trigger(conn: Any, trigger: str, statement: str, **values: Any) -> None:
    """``statement`` as a role that bypasses the platform would run it: the
    migrator, owner of `studio.artifact_versions`, with ``trigger`` off for
    this transaction only."""
    table = "studio.artifact_versions"
    await conn.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
    await conn.execute(sa.text(statement), values)
    await conn.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))


def lead_boundary(document: Any) -> DerivedBoundary:
    return DerivedBoundary(
        objects=(ObjectBoundary(LEAD, True, False, False, False, False),),
        fields=tuple(FieldBoundary(LEAD, name, "read") for name in ("name", "phone", "status")),
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(studio_db: DatabaseUrls) -> AsyncIterator[World]:
    from sqlalchemy.ext.asyncio import create_async_engine

    migrator = create_async_engine(studio_db.migrator, poolclass=NullPool)
    app = create_async_engine(studio_db.app, poolclass=NullPool)
    sessions = sessions_of(app)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=1)
        manager = await plant_manager(conn, tenant)
    lead = await publish_object(sessions, manager, LEAD, lead_document())
    campaign = await publish_object(sessions, manager, CAMPAIGN, lead_document())
    async with migrator.begin() as conn:
        base = await plant_holder(conn, tenant, AUTHOR_KEYS)
        fields = {"name": "edit", "phone": "edit", "status": "edit"}
        tester = await holder(
            conn, tenant, lead, {"read": "own", "create": "workspace"}, fields, user=base.id
        )
        await holder(
            conn,
            tenant,
            campaign,
            {"read": "workspace", "create": "workspace"},
            fields,
            user=base.id,
        )
        colleague = await holder(
            conn, tenant, lead, {"read": "workspace", "create": "workspace"}, fields
        )
    clock = SystemClock()
    records = RecordService(
        SqlRecordStore(),
        FieldAccessService(SqlFieldSecurityInputs()),
        InProcessRateLimiter(1, clock),
        ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
        clock,
        Uuid7Generator(),
    )

    async def lead_of(owner: Person, api_name: str = LEAD) -> uuid.UUID:
        created = await records.create(
            person_door(sessions, owner),
            api_name,
            {
                "name": f"Lead {uuid.uuid4().hex[:6]}",
                "fields": {"phone": "09" + str(uuid.uuid4().int)[:8]},
            },
        )
        return created.record.id

    mine = await lead_of(tester)
    theirs = await lead_of(colleague)
    await lead_of(tester, CAMPAIGN)
    yield World(
        migrator,
        app,
        sessions,
        tenant,
        manager,
        tester,
        colleague,
        lead,
        campaign,
        mine,
        theirs,
        records,
    )
    await app.dispose()
    await migrator.dispose()


# ---- what a test builds -----------------------------------------------------------


def toolset(world: World) -> dict[str, Any]:
    return {
        "tools": [
            {"kind": "object_crud", "object": str(world.lead), "operations": ["search", "get"]}
        ]
    }


def document(world: World, instructions: str = "Trả lời ngắn gọn.") -> dict[str, Any]:
    return agent_document(
        model={"profile": PROFILE}, instructions=instructions, toolset=toolset(world)
    )


async def draft_agent(
    world: World, instructions: str = "Trả lời ngắn gọn."
) -> tuple[uuid.UUID, uuid.UUID, int]:
    row, draft = await world.service().create(
        world.tester.context(),
        kind="agent",
        api_name=f"ag_{uuid.uuid4().hex[:12]}",
        labels=[],
        document=document(world, instructions),
    )
    return row.id, draft.id, draft.row_version


async def live_agent(world: World, *, enabled: bool | None = True) -> tuple[uuid.UUID, uuid.UUID]:
    """An agent whose version 1 is live with its published boundary, and a
    settings row saying ``enabled`` (none when None)."""
    artifact, _, row_version = await draft_agent(world)
    result = await sealed(world.service(), world.tester, artifact, row_version)
    # A gated kind reaches `live` only through agent-lifecycle/06's gate,
    # which W1 has not built: the version is planted live past the guard.
    async with world.migrator.begin() as conn:
        await past_trigger(
            conn,
            "guard_version_stage",
            "UPDATE studio.artifact_versions SET stage = 'live', submitted_by = :p,"
            " submitted_at = now(), published_by = :p, published_at = now() WHERE id = :v",
            p=world.manager.id,
            v=result.version_id,
        )
    async with world.app.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=world.t))
        derived = lead_boundary(None)
        await SqlActorBoundaries().record(
            conn,
            "agent",
            result.version_id,
            result.definition_hash,
            derived.objects,
            derived.fields,
        )
    if enabled is not None:
        async with world.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.agent_settings (tenant_id, artifact_id, audience,"
                    " owner_user_id, enabled, row_version) VALUES (:t, :a, CAST(:aud AS jsonb),"
                    " :o, :e, 1)"
                ),
                {
                    "t": world.t,
                    "a": artifact,
                    "aud": '{"schema": "dw.audience/v1", "any_of": []}',
                    "o": world.tester.id,
                    "e": enabled,
                },
            )
    return artifact, result.version_id


async def ask(
    world: World,
    version_id: uuid.UUID,
    trigger: str,
    *,
    door: RunRequestService | None = None,
) -> uuid.UUID:
    result = await (door or world.door()).request(
        RunRequest(
            requester=PersonRequester(world.tester.context()),
            version_id=version_id,
            trigger_kind=trigger,
            source_key=str(uuid.uuid4()),
        )
    )
    return result.run_id


@dataclass
class Stack:
    runner: LangGraphWorkflowRunner
    routes: Routes
    limits: OpenLimits
    usage: InMemoryUsageRecorder
    source: StudioGraphSource


def stack_of(
    world: World,
    *,
    profile: ModelProfile | None = None,
    routes: Routes | None = None,
    threads: Any = None,
    autonomy_executor: bool = False,
) -> Stack:
    runner, _ = build_runner(world.sessions, {})
    limits = OpenLimits()
    runner.limits = limits
    routes = routes or Routes()
    usage = InMemoryUsageRecorder()
    clock = SystemClock()
    sessions = world.sessions
    data = RecordObjectData(
        world.records,
        lambda run: RecordDoor(lambda: agent_record_session(sessions, run), run_id=run.run_id),
    )
    prompts = PromptRegistry()
    prompts.load_directory(REPO / "configs" / "prompts" / "studio")
    compiler = StudioAgentCompiler(
        checkpointer=runner.checkpoint_saver,
        executor=ToolExecutor(
            registry=ToolRegistry(),
            execution_store=SqlToolExecutionStore(sessions),
            uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
            clock=clock,
            id_generator=Uuid7Generator(),
            approval_policy=AutonomyApprovalPolicy(),
            claims=SqlToolClaims(sessions),
            steps=build_tool_executor_steps(),
            run_control=OpenRunControl(),
        ),
        tool_kinds=ObjectToolKinds(
            SqlObjectDefinitionReader(sessions), data, object_tool_copy(REPO)
        ),
        object_fields=data,
        copy=load_runtime_copy(REPO / "configs" / "copy" / "runtime@1.6.0.yaml"),
        prompts=prompts,
        names=SqlRunNames(sessions),
        models=resolver_of(profile or chat_profile(), sessions),
        chat_models=routes,
        limits=limits,
        usage_recorder=usage,
        pricing=FlatPricing(),
        residency=run_gate(),
    )
    source = StudioGraphSource(
        sessions,
        compiler,
        turns={"test": world.conversation, "chat": world.conversation, "eval": world.conversation},
        replies={
            "test": world.conversation,
            "chat": world.conversation,
            "eval": world.conversation,
        },
    )
    runner.studio_agents = StudioAgentPorts(
        source=source, threads=threads or SqlAgentThreads(sessions)
    )
    return Stack(runner, routes, limits, usage, source)


async def run(world: World, stack: Stack, run_id: uuid.UUID) -> RunStatus:
    status: RunStatus = await run_claimed(stack.runner, world.sessions, world.t, run_id)
    return status


async def taken_of(world: World, run_id: uuid.UUID) -> StudioRun:
    token = await claimed(world.sessions, world.t, run_id)
    taken = await SqlStudioRunStore(world.sessions, Uuid7Generator(), SystemClock()).take(
        world.t, run_id, lease_token=token
    )
    assert isinstance(taken, StudioRun)
    return taken


async def tool_turn(stack: Stack, taken: StudioRun) -> list[ToolMessage]:
    """The run's agent driven on its compiled graph at A1: one search of the
    leads, then an answer. The tool messages it got back."""
    stack.routes.script[:] = [
        AIMessage(
            "", tool_calls=[{"name": "obj_mkt_lead__search", "args": {"limit": 50}, "id": "c1"}]
        ),
        AIMessage(ANSWER),
    ]
    built = await stack.source.build(taken)
    context = agent_run_context(_studio_run_context(taken)).model_copy(
        update={"autonomy_level": "A1", "autonomy_ceiling": "A1"}
    )
    state = await built.graph.ainvoke(
        {"messages": [{"role": "user", "content": "Tôi có những lead nào?"}]},
        {
            "configurable": {
                "thread_id": str(uuid.uuid4()),
                "tenant_id": str(taken.tenant_id),
                "workspace_id": str(taken.workspace_id),
            }
        },
        context=context,
    )
    return [m for m in state["messages"] if isinstance(m, ToolMessage)]


def ids_in(messages: Sequence[ToolMessage], *ids: uuid.UUID) -> set[uuid.UUID]:
    text = " ".join(str(m.content) for m in messages)
    return {i for i in ids if str(i) in text}


# ---- R3.1, R3.3 (AB6, AB7): the cache and the hash gate --------------------------


async def test_agent_runtime_r3_1_a_draft_edited_between_two_simulations_runs_its_new_content(
    world: World,
) -> None:
    stack = stack_of(world)
    artifact, version, row_version = await draft_agent(world, "Chỉ dẫn thứ nhất.")
    first = await ask(world, version, "test")
    assert await run(world, stack, first) is RunStatus.COMPLETED
    saved = await world.service().save_draft(
        world.tester.context(),
        artifact,
        ExpectedVersion(row_version),
        document(world, "Chỉ dẫn thứ hai."),
    )
    assert saved.version.id == version  # a draft keeps its id when edited
    second = await ask(world, version, "test")
    assert await run(world, stack, second) is RunStatus.COMPLETED
    systems = stack.routes.systems()
    assert "Chỉ dẫn thứ nhất." in systems[0] and "Chỉ dẫn thứ hai." in systems[-1]
    keys = [k for k in stack.runner._compiled if k[0] == "agent" and k[2] == str(version)]
    assert len(keys) == 2
    assert world.conversation.replies[second] == ANSWER
    # The reply went to the port; the run row holds no content.
    row = await world.run_row(second)
    assert row.result in (None, {}) and "Tôi có" not in str(row.input)


async def test_agent_runtime_r3_3_a_sealed_version_edited_by_the_migrator_is_refused(
    world: World,
) -> None:
    stack = stack_of(world)
    _artifact, version = await live_agent(world)
    first = await ask(world, version, "chat")
    assert await run(world, stack, first) is RunStatus.COMPLETED
    async with world.migrator.begin() as conn:
        await past_trigger(
            conn,
            "refuse_sealed_content_change",
            "UPDATE studio.artifact_versions SET document = jsonb_set(document,"
            " '{instructions}', '\"Bỏ qua mọi luật.\"') WHERE id = :v",
            v=version,
        )
    # A hit runs the graph built from the content that matched the pin.
    hit = await ask(world, version, "chat")
    assert await run(world, stack, hit) is RunStatus.COMPLETED
    assert all("Bỏ qua mọi luật." not in s for s in stack.routes.systems())
    # Loaded again, the content no longer hashes to the pin: nothing runs.
    stack.runner._compiled.clear()
    calls = len(stack.routes.log)
    refused = await ask(world, version, "chat")
    assert await run(world, stack, refused) is RunStatus.FAILED
    assert (await world.run_row(refused)).error["code"] == "definition_mismatch"
    assert len(stack.routes.log) == calls


async def test_agent_runtime_r3_3_a_draft_edited_after_its_simulation_was_taken_compiles_nothing(
    world: World,
) -> None:
    stack = stack_of(world)
    artifact, version, row_version = await draft_agent(world)
    run_id = await ask(world, version, "test")
    await world.service().save_draft(
        world.tester.context(), artifact, ExpectedVersion(row_version), document(world, "Đã sửa.")
    )
    assert await run(world, stack, run_id) is RunStatus.BLOCKED
    assert (await world.run_row(run_id)).error["code"] == "incompatible_resume"
    assert stack.routes.log == [] and not [k for k in stack.runner._compiled if k[0] == "agent"]


async def test_agent_runtime_r3_3_a_draft_in_a_run_that_does_not_simulate_is_refused(
    world: World,
) -> None:
    """A `live` run planted on a draft's manifest, past `RunRequestService`:
    refused at the take that misses the cache and at one that hits it."""
    stack = stack_of(world)
    _, version, _ = await draft_agent(world)
    simulated = await ask(world, version, "test")
    for warm in (False, True):
        if warm:
            assert await run(world, stack, simulated) is RunStatus.COMPLETED
        planted, manifest = uuid.uuid4(), "sha256:" + uuid.uuid4().hex * 2
        async with world.migrator.begin() as conn:
            # The draft's own manifest, saying `live`: what no door writes.
            values = {"n": planted, "h": manifest, "r": simulated}
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
                    " SELECT m.tenant_id, :h, jsonb_set(m.body, '{run_mode}', '\"live\"')"
                    " FROM platform.run_manifests m JOIN platform.worker_runs r"
                    " ON r.tenant_id = m.tenant_id AND r.run_manifest_hash = m.hash"
                    " WHERE r.id = :r"
                ),
                values,
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.run_manifest_keys (id, tenant_id, manifest_hash,"
                    " artifact_version_id, config_version_id)"
                    " SELECT gen_random_uuid(), k.tenant_id, :h, k.artifact_version_id,"
                    " k.config_version_id FROM platform.run_manifest_keys k"
                    " JOIN platform.worker_runs r ON r.tenant_id = k.tenant_id"
                    " AND r.run_manifest_hash = k.manifest_hash WHERE r.id = :r"
                ),
                values,
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                    " worker_id, worker_version, graph_version, requested_by, run_as_principal_id,"
                    " run_mode, run_manifest_hash, artifact_kind, artifact_id,"
                    " artifact_version_id, trigger_kind, request_key, root_run_id, chain_depth,"
                    " status, priority, input)"
                    " SELECT CAST(:n AS uuid), CAST(:n AS uuid), tenant_id, workspace_id,"
                    " worker_id, worker_version, graph_version, requested_by,"
                    " run_as_principal_id, 'live', :h, artifact_kind, artifact_id,"
                    " artifact_version_id, 'manual', 'planted:' || CAST(:n AS text),"
                    " CAST(:n AS uuid), 0, 'queued', 0, '{}'"
                    " FROM platform.worker_runs WHERE id = :r"
                ),
                values,
            )
        calls = len(stack.routes.log)
        assert await run(world, stack, planted) is RunStatus.FAILED
        assert (await world.run_row(planted)).error["code"] == "draft_outside_simulate"
        assert len(stack.routes.log) == calls


# ---- R3.8 (AB17): `enabled`, and the checkpoints of a finished run ----------------


@pytest.mark.parametrize("enabled", [False, None], ids=["disabled", "no_settings_row"])
async def test_agent_runtime_r3_8_a_chat_run_of_an_agent_that_is_off_fails_before_any_call(
    world: World, enabled: bool | None
) -> None:
    stack = stack_of(world)
    _, version = await live_agent(world, enabled=enabled)
    chat = await ask(world, version, "chat")
    assert await run(world, stack, chat) is RunStatus.FAILED
    assert (await world.run_row(chat)).error["code"] == "agent_disabled"
    assert stack.routes.log == [] and stack.limits.calls == []
    simulated = await ask(world, version, "test")
    assert await run(world, stack, simulated) is RunStatus.COMPLETED
    assert stack.routes.log == ["agent-chat-1"]


async def test_agent_runtime_r3_8_a_soft_deleted_agent_is_off(world: World) -> None:
    stack = stack_of(world)
    artifact, version = await live_agent(world)
    chat = await ask(world, version, "chat")
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE studio.artifacts SET deleted_at = now() WHERE id = :a"), {"a": artifact}
        )
    assert await run(world, stack, chat) is RunStatus.FAILED
    assert (await world.run_row(chat)).error["code"] == "agent_disabled"


async def test_agent_runtime_r3_8_finished_runs_leave_no_checkpoint(world: World) -> None:
    """Completed, failed and cancelled: each ended run's thread is empty."""

    class Failing(Routes):
        def for_route(self, route: ModelRoute) -> BaseChatModel:
            raise RuntimeError("the provider is down")

    class Halting(Routes):
        def for_route(self, route: ModelRoute) -> BaseChatModel:
            raise RunHaltedError(HaltReason.ARTIFACT_KILLED, door=RunControlDoor.MODEL)

    _, version = await live_agent(world)
    ended: list[uuid.UUID] = []
    for routes, status in (
        (Routes(), RunStatus.COMPLETED),
        (Failing(), RunStatus.FAILED),
        (Halting(), RunStatus.CANCELLED),
    ):
        run_id = await ask(world, version, "chat")
        assert await run(world, stack_of(world, routes=routes), run_id) is status
        ended.append(run_id)
    assert [(await world.run_row(r)).status for r in ended] == ["completed", "failed", "cancelled"]
    assert (await world.run_row(ended[2])).error["code"] == "artifact_killed"
    for run_id in ended:
        assert await world.checkpoints(run_id) == 0


async def test_agent_runtime_r3_8_a_run_still_waiting_keeps_its_checkpoints(world: World) -> None:
    """The delete's own guard: a thread whose run is not finished keeps every
    checkpoint; once the run has ended they go."""
    stack = stack_of(world, threads=NoThreads())
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat")
    assert await run(world, stack, run_id) is RunStatus.COMPLETED
    kept = await world.checkpoints(run_id)
    assert kept > 0
    threads = SqlAgentThreads(world.sessions)
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.worker_runs SET status = 'waiting_approval' WHERE id = :r"),
            {"r": run_id},
        )
    await threads.forget(world.t, run_id)
    assert await world.checkpoints(run_id) == kept
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.worker_runs SET status = 'failed' WHERE id = :r"),
            {"r": run_id},
        )
    await threads.forget(uuid.uuid4(), run_id)  # another tenant's transaction sees nothing
    assert await world.checkpoints(run_id) == kept
    await threads.forget(world.t, run_id)
    assert await world.checkpoints(run_id) == 0


# ---- R3.5, R3.7 (AB9): the route the manifest pinned ------------------------------


async def test_agent_runtime_r3_5_the_version_profile_is_pinned_and_called(world: World) -> None:
    stack = stack_of(world)
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat")
    [row] = await world.rows(
        "SELECT m.body FROM platform.run_manifests m JOIN platform.worker_runs r"
        " ON r.run_manifest_hash = m.hash AND r.tenant_id = m.tenant_id WHERE r.id = :r",
        r=run_id,
    )
    assert PROFILE in row.body["engine"]["model_routes"]
    assert await run(world, stack, run_id) is RunStatus.COMPLETED
    assert stack.routes.log == ["agent-chat-1"]


async def test_agent_runtime_r3_5_without_the_kind_s_profiles_the_call_is_not_pinned(
    world: World,
) -> None:
    stack = stack_of(world)
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat", door=world.door(profiles=False))
    assert await run(world, stack, run_id) is RunStatus.FAILED
    assert (await world.run_row(run_id)).error["code"] == "key_not_pinned"
    assert stack.routes.log == []


async def test_agent_runtime_r3_5_a_profile_changed_since_the_pin_fails_before_a_call(
    world: World,
) -> None:
    stack = stack_of(world, profile=chat_profile(model="agent-chat-2"))
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat")
    assert await run(world, stack, run_id) is RunStatus.FAILED
    assert (await world.run_row(run_id)).error["code"] == "model_profile_unavailable"
    assert stack.routes.log == [] and stack.limits.calls == []


async def test_agent_runtime_r3_7_a_foreign_route_under_vn_only_holds_no_lease(
    world: World,
) -> None:
    foreign = chat_profile(model="abroad-1", location="foreign")
    stack = stack_of(world, profile=foreign)
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat", door=world.door(profile=foreign))
    assert await run(world, stack, run_id) is RunStatus.FAILED
    assert (await world.run_row(run_id)).error["code"] == "residency_refused"
    assert stack.limits.calls == [] and stack.limits.permits == []
    assert stack.usage.records == [] and stack.routes.log == []


# ---- R3.4 (AB5, AB14): the actor `agent` within the run's boundary ---------------


async def test_agent_runtime_r3_4_a_draft_simulation_reads_the_testers_leads_and_only_them(
    world: World,
) -> None:
    stack = stack_of(world)
    _, version, _ = await draft_agent(world)
    run_id = await ask(world, version, "test")
    taken = await taken_of(world, run_id)
    [boundary] = await world.rows(
        "SELECT run_id FROM studio.actor_boundaries WHERE source_id = :v AND run_id = :r",
        v=version,
        r=run_id,
    )
    assert boundary.run_id == run_id
    messages = await tool_turn(stack, taken)
    assert ids_in(messages, world.mine, world.theirs) == {world.mine}
    # The run's boundary names `mkt_lead` only: the campaign the tester reads
    # is no record of this run's actor.
    run = agent_run_context(_studio_run_context(taken))
    async with agent_record_session(world.sessions, run) as session:
        campaigns = await session.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE object_id = :o"),
            {"o": world.campaign},
        )
        leads = await session.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE object_id = :o"), {"o": world.lead}
        )
    assert (campaigns, leads) == (0, 1)


async def test_agent_runtime_r3_4_without_the_provisional_boundary_the_draft_reads_nothing(
    world: World,
) -> None:
    stack = stack_of(world)
    _, version, _ = await draft_agent(world)
    run_id = await ask(world, version, "test")
    taken = await taken_of(world, run_id)
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM studio.actor_boundaries WHERE run_id = :r"), {"r": run_id}
        )
    messages = await tool_turn(stack, taken)
    assert ids_in(messages, world.mine, world.theirs) == set()


async def test_agent_runtime_r3_4_a_live_run_binds_the_published_boundary(world: World) -> None:
    stack = stack_of(world)
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat")
    taken = await taken_of(world, run_id)
    provisional = await world.rows(
        "SELECT 1 FROM studio.actor_boundaries WHERE run_id = :r", r=run_id
    )
    assert provisional == []
    messages = await tool_turn(stack, taken)
    assert ids_in(messages, world.mine, world.theirs) == {world.mine}
    run = agent_run_context(_studio_run_context(taken))
    async with agent_record_session(world.sessions, run) as session:
        bound = await session.scalar(sa.text("SELECT current_setting('app.boundary_id', true)"))
        published = await session.scalar(
            sa.text(
                "SELECT id FROM studio.actor_boundaries WHERE source_id = :v AND run_id IS NULL"
            ),
            {"v": version},
        )
    assert bound == str(published)


async def test_agent_runtime_r3_4_a_transaction_without_the_actor_reads_no_record(
    world: World,
) -> None:
    async with world.app.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=world.t, principal_id=world.tester.id))
        found = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE object_id = :o"), {"o": world.lead}
        )
    assert found == 0


async def test_agent_runtime_r3_8_a_session_for_another_principal_than_the_runs_binds_nothing(
    world: World,
) -> None:
    _, version = await live_agent(world)
    run_id = await ask(world, version, "chat")
    taken = await taken_of(world, run_id)
    run = agent_run_context(_studio_run_context(taken))
    async with agent_record_session(world.sessions, run) as session:
        user = await session.scalar(sa.text("SELECT current_setting('app.user_id', true)"))
    assert user == str(world.tester.id)
    other = run.model_copy(update={"run_as_principal_id": world.colleague.id})
    with pytest.raises(ActorBindingRefusedError):
        async with agent_record_session(world.sessions, other) as session:
            await session.scalar(sa.text("SELECT count(*) FROM studio.records"))


async def test_agent_runtime_r3_4_a_gate_trial_of_a_candidate_reads_as_its_submitter(
    world: World,
) -> None:
    """The quality gate's trial of a candidate, asked by its lane in the
    submitter's name: the row's principal is the submitter, the provisional
    boundary is the candidate's under its definition hash, and the trial reads
    the submitter's leads and only them."""
    stack = stack_of(world)
    artifact, _, row_version = await draft_agent(world)
    result = await sealed(world.service(), world.tester, artifact, row_version)
    await move_for_test(world.migrator, result.version_id, "evaluating")
    door = world.door()
    asked = await door.request(
        RunRequest(
            requester=door.lanes.requester("studio_gate", world.t),
            version_id=result.version_id,
            trigger_kind="eval",
            source_key=f"case:{uuid.uuid4()}",
            run_as_principal_id=world.tester.id,
        )
    )
    row = await world.run_row(asked.run_id)
    assert (row.requested_by, row.run_as_principal_id) == (world.tester.id, world.tester.id)
    [boundary] = await world.rows(
        "SELECT source_id, source_version FROM studio.actor_boundaries WHERE run_id = :r",
        r=asked.run_id,
    )
    assert (boundary.source_id, boundary.source_version) == (
        result.version_id,
        result.definition_hash,
    )
    taken = await taken_of(world, asked.run_id)
    messages = await tool_turn(stack, taken)
    assert ids_in(messages, world.mine, world.theirs) == {world.mine}
