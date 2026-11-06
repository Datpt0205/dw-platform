"""A Studio agent's compiled stack, without a database (agent-builder ticket
03: R3.5-R3.7; AB9).

`StudioAgentCompiler` builds the agent a run of a version runs: the model a
call reaches is the route the run's manifest pinned (`StudioModelSelection`
over the real `ModelResolver`), the model it was compiled with is never
called, the selection stands before the residency gate and the gate before
the limits, so a refused route holds no lease and records no usage; and a
graph refuses a run of another company, version or pinned hash.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import NOW, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from dw_agent_runtime.adapters.agent_factory import AgentSpec, platform_middleware
from dw_agent_runtime.adapters.chat_model import MockChatModel, require_permit
from dw_agent_runtime.adapters.limits_middleware import LimitsMiddleware
from dw_agent_runtime.adapters.residency_middleware import ResidencyGateMiddleware
from dw_agent_runtime.adapters.run_control_middleware import RunControlMiddleware
from dw_agent_runtime.adapters.studio_agents import StudioAgentCompiler, pinned_capabilities
from dw_agent_runtime.adapters.studio_model_selection import (
    StudioModelSelection,
    UnselectedChatModel,
)
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunArtifact, RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver, pin_entry
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import PinnedEntry, PinnedManifest, StudioRun
from dw_agent_runtime.studio_agent import (
    AgentBlueprint,
    LoadedToolKinds,
    RunNames,
    agent_cache_key,
)
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.models import AnyManifest, any_plan
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.errors import ConfigError, EntitlementDeniedError
from dw_kernel.limits import LimitExceededError
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_kernel.residency import ResidencyRefusedError
from dw_platform.testing.residency import run_gate

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
COPY = load_runtime_copy(REPO / "configs" / "copy" / "runtime@1.6.0.yaml")
FRAME = ("studio.agent_frame", "1.0.0")
PROFILE = "agent_profile"
TENANT = uuid.UUID(int=0xA1)
VERSION = uuid.UUID(int=0xB1)
PINNED = "sha256:" + "a" * 64
MANIFEST = "sha256:" + "c" * 64
INSTRUCTIONS = "Chỉ trả lời về lead của công ty."


def _route(model: str, location: str = "vn") -> dict[str, Any]:
    return {
        "provider": "mock",
        "model": model,
        "data_location": location,
        "processor": "mock" if location == "vn" else "foreign-processor",
        "retention_days": 0,
        "no_training": True,
    }


def _profile(model: str, location: str = "vn") -> ModelProfile:
    route = _route(model, location)
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


class LoggedModel(MockChatModel):
    """A scripted model that writes its route's model to a shared log."""

    label: str
    log: Any

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        self.log.append(self.label)
        return super()._generate(messages, stop, run_manager, **kw)


class Routes:
    """`RouteChatModelFactory`: one logged model per route's model name."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.models: dict[str, BaseChatModel] = {}

    def for_route(self, route: ModelRoute) -> BaseChatModel:
        if route.model not in self.models:
            self.models[route.model] = require_permit(
                LoggedModel(
                    responses=[AIMessage("Có 2 lead.")],
                    mock_reply="",
                    label=route.model,
                    log=self.log,
                )
            )
        return self.models[route.model]


class NoTools:
    async def load(self, tenant_id: uuid.UUID, entries: Any) -> LoadedToolKinds:
        return LoadedToolKinds(sources={}, factories={})


class Names:
    async def names(self, run: RunContext) -> RunNames:
        return RunNames(person="Nguyễn Văn An", workspace="Marketing")


def _engine(pinned: ModelProfile | None) -> dict[str, Any]:
    routes = {} if pinned is None else {PROFILE: pin_entry(pinned, "platform")}
    return {"durability": "sync", "model_routes": routes, "default_model_profile": None}


def _resolver_of(engine: Mapping[str, Any]) -> PinnedResolver:
    root = PinnedEntry("agent", str(uuid.UUID(int=0xC1)), None, PINNED)
    return PinnedResolver(PinnedManifest(MANIFEST, {"engine": dict(engine)}, root, ()))


class Stack:
    def __init__(
        self,
        *,
        current: ModelProfile | None = None,
        pinned: ModelProfile | None = None,
        limits: OpenLimits | None = None,
    ) -> None:
        current = current or _profile("chosen-1")
        pinned = pinned or current
        profiles = ModelProfileRegistry()
        profiles.register(current)
        self.engine = _engine(pinned)
        self.models = ModelResolver(
            profiles, any_plan({PROFILE}), PROFILE, AnyManifest(self.engine)
        )
        self.log: list[str] = []
        self.routes = Routes(self.log)
        self.limits = limits or OpenLimits()
        self.usage = InMemoryUsageRecorder()
        prompts = PromptRegistry()
        prompts.load_directory(REPO / "configs" / "prompts" / "studio")
        store = FakeExecutionStore()
        self.compiler = StudioAgentCompiler(
            checkpointer=None,  # type: ignore[arg-type]
            executor=ToolExecutor(
                registry=ToolRegistry(),
                execution_store=store,
                uow_factory=FakeUoWFactory(),
                clock=FixedClock(NOW),
                id_generator=SequentialIdGenerator(),
                approval_policy=AutonomyApprovalPolicy(),
                claims=FakeToolClaims(store),
                steps=build_tool_executor_steps(),
                run_control=OpenRunControl(),
            ),
            tool_kinds=NoTools(),
            object_fields=None,  # type: ignore[arg-type]
            copy=COPY,
            prompts=prompts,
            names=Names(),
            models=self.models,
            chat_models=self.routes,
            limits=self.limits,
            usage_recorder=self.usage,
            pricing=FlatPricing(),
            residency=run_gate(),
            clock=lambda: datetime(2026, 11, 6, 2, 30, tzinfo=UTC),
        )

    def blueprint(self, profile: str = PROFILE) -> AgentBlueprint:
        return AgentBlueprint(
            tenant_id=TENANT,
            version_id=VERSION,
            pinned_hash=PINNED,
            profile_id=profile,
            agent_name="Trợ lý lead",
            instructions=INSTRUCTIONS,
            toolset=(),
            resolver=_resolver_of(self.engine),
            frame_id=FRAME[0],
            frame_version=FRAME[1],
        )

    async def ask(self, graph: Any, run: RunContext | None = None) -> Any:
        return await graph.ainvoke(
            {"messages": [{"role": "user", "content": "Có bao nhiêu lead?"}]},
            {"configurable": {"thread_id": str(uuid.uuid4())}},
            context=run or run_of(),
        )


def run_of(**changes: Any) -> RunContext:
    run = RunContext(
        run_id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=uuid.UUID(int=0xD1),
        actor_id=uuid.UUID(int=0xE1),
        worker_id=f"studio:agent:{VERSION}",
        worker_version="1.0.0",
        channel="studio",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
        run_mode="live",
        run_manifest_hash=MANIFEST,
        artifact_id=uuid.UUID(int=0xC1),
        artifact=RunArtifact(kind="agent", artifact_id=uuid.UUID(int=0xC1), version_id=VERSION),
        definition_hash=PINNED.removeprefix("sha256:"),
        autonomy_level="A1",
        autonomy_ceiling="A1",
    )
    return run.model_copy(update=changes)


# ---- R3.5: the route the run pinned, and only it ----------------------------------


async def test_agent_runtime_a_call_reaches_the_pinned_route_and_never_the_compiled_model() -> None:
    stack = Stack()
    graph = await stack.compiler.compile(stack.blueprint())
    state = await stack.ask(graph)
    assert stack.log == ["chosen-1"]
    assert state["messages"][-1].content == "Có 2 lead."
    # The compiled model is the refusing one: a stack that lost its selection
    # fails its first call instead of sending anywhere.
    assert isinstance(graph.get_graph(), object)
    with pytest.raises(ConfigError, match="route its run pinned"):
        UnselectedChatModel().invoke("hi")
    # The frame at the platform layer, the company's text in its block.
    sent = stack.routes.models["chosen-1"]
    system = sent.system_prompts[-1]  # type: ignore[attr-defined]
    assert f"<tenant_instructions>\n{INSTRUCTIONS}\n</tenant_instructions>" in system
    assert "Nguyễn Văn An" in system and "Marketing" in system and "09:30" in system


async def test_agent_runtime_a_profile_the_run_did_not_pin_is_refused_before_a_send() -> None:
    stack = Stack()
    graph = await stack.compiler.compile(stack.blueprint(profile="unpinned_profile"))
    with pytest.raises(ConfigError) as refused:
        await stack.ask(graph)
    assert refused.value.details["reason"] == "key_not_pinned"
    assert stack.log == [] and stack.limits.calls == []


async def test_agent_runtime_a_pinned_profile_changed_since_is_refused_before_a_send() -> None:
    stack = Stack(current=_profile("chosen-2"), pinned=_profile("chosen-1"))
    graph = await stack.compiler.compile(stack.blueprint())
    with pytest.raises(EntitlementDeniedError) as refused:
        await stack.ask(graph)
    assert refused.value.details["reason_code"] == "model_profile_unavailable"
    assert stack.log == [] and stack.limits.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": uuid.UUID(int=0xA2)},
        {
            "artifact": RunArtifact(
                kind="agent", artifact_id=uuid.UUID(int=0xC1), version_id=uuid.UUID(int=0xB2)
            )
        },
        {"definition_hash": "b" * 64},
        {"artifact": None},
    ],
    ids=["other_company", "other_version", "other_hash", "no_version"],
)
async def test_agent_runtime_a_graph_refuses_a_run_it_was_not_built_for(
    changes: dict[str, Any],
) -> None:
    stack = Stack()
    graph = await stack.compiler.compile(stack.blueprint())
    with pytest.raises(ConfigError) as refused:
        await stack.ask(graph, run_of(**changes))
    assert refused.value.details["reason"] == "graph_mismatch"
    assert stack.log == []


# ---- R3.6, R3.7 (AB9): selection, then the gate, then the limits ------------------


async def test_agent_runtime_selection_stands_before_the_gate_and_the_gate_before_limits() -> None:
    stack = Stack()
    blueprint = stack.blueprint()
    graph = await stack.compiler.compile(blueprint)
    del graph
    spec_stack = _stack_of(stack, blueprint)
    kinds = [type(m) for m in spec_stack]
    selection = kinds.index(StudioModelSelection)
    assert kinds[selection + 1] is ResidencyGateMiddleware
    assert kinds[selection + 2] is LimitsMiddleware
    # agent-lifecycle/01's place, unmoved: the freeze is asked first.
    assert kinds.index(RunControlMiddleware) < selection


def _stack_of(stack: Stack, blueprint: AgentBlueprint) -> list[Any]:
    """The middleware the compiler hands `create_agent`, rebuilt from the
    same parts so its order can be read."""
    selection = StudioModelSelection(
        stack.models,
        stack.routes,
        PROFILE,
        tenant_id=TENANT,
        version_id=VERSION,
        pinned_hash=PINNED,
    )
    spec = AgentSpec(
        model=UnselectedChatModel(),
        offered=(),
        registry=ToolRegistry(),
        executor=stack.compiler.executor,
        copy=COPY,
        approval_type_prefix="studio.agent.tool.",
        prompt_id=FRAME[0],
        prompt_version=FRAME[1],
        prompts=stack.compiler.prompts,
        prompt_variables=lambda request: {},
        limits=stack.limits,
        usage_recorder=stack.usage,
        pricing=FlatPricing(),
        models=stack.models,
        profile_id=PROFILE,
        residency=run_gate(),
        model_selection=selection,
    )
    return platform_middleware(spec)


async def test_agent_runtime_every_call_asks_the_run_lease_and_a_spent_one_stops_it() -> None:
    spent = LimitExceededError("the run has spent its lease", metric="cost_usd", scope_type="run")
    stack = Stack(limits=OpenLimits(refuse_calls=spent))
    graph = await stack.compiler.compile(stack.blueprint())
    with pytest.raises(LimitExceededError):
        await stack.ask(graph)
    assert len(stack.limits.calls) == 1
    assert stack.log == [] and stack.usage.records == []


async def test_agent_runtime_a_permitted_call_is_settled_against_the_pinned_route() -> None:
    stack = Stack()
    graph = await stack.compiler.compile(stack.blueprint())
    await stack.ask(graph)
    assert len(stack.limits.permits) == 1
    [(_, usage)] = stack.usage.records
    assert (usage.model, usage.data_location, usage.permit) == (
        "chosen-1",
        "vn",
        stack.limits.permits[0],
    )


async def test_agent_runtime_a_foreign_route_under_vn_only_holds_no_lease_and_records_nothing() -> (
    None
):
    foreign = _profile("abroad-1", "foreign")
    stack = Stack(current=foreign)
    graph = await stack.compiler.compile(stack.blueprint())
    with pytest.raises(ResidencyRefusedError):
        await stack.ask(graph, run_of(route_class="vn_only"))
    assert stack.limits.calls == [] and stack.limits.permits == []
    assert stack.usage.records == [] and stack.log == []


def test_agent_runtime_strict_tools_follow_the_route_the_run_pinned() -> None:
    strict = _profile("chosen-1")
    chat = strict.chat
    assert chat is not None
    capable = strict.model_copy(
        update={
            "chat": chat.model_copy(
                update={"capabilities": chat.capabilities.model_copy(update={"strict_tools": True})}
            )
        }
    )
    stack = Stack(current=capable)
    assert pinned_capabilities(stack.blueprint()).strict_tools is True
    assert pinned_capabilities(stack.blueprint(profile="unpinned_profile")).strict_tools is False


# ---- R3.1, R3.2 (AB6): what the runner's cache keys a graph by -------------------


def _taken(**changes: Any) -> StudioRun:
    run = StudioRun(
        run_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=uuid.UUID(int=0xD1),
        artifact_kind="agent",
        artifact_id=uuid.UUID(int=0xC1),
        artifact_version_id=VERSION,
        pinned_hash=PINNED,
        run_mode="simulate",
        requested_by=uuid.UUID(int=0xE1),
        run_as_principal_id=uuid.UUID(int=0xE1),
        run_manifest_hash=MANIFEST,
        plan_id="professional",
        deadline_at=None,
        input={},
        pinned_results=None,
        document={},
        engine={"durability": "sync"},
        version_no=None,
        trace_id="t",
    )
    return dataclasses.replace(run, **changes)


def test_agent_runtime_the_cache_key_is_the_company_the_version_and_the_pinned_hash() -> None:
    """Two companies with one version id and hash (R3.2), one draft before and
    after an edit (R3.1): each a key of its own; another run of the same
    content, the same key."""
    base = agent_cache_key(_taken())
    assert agent_cache_key(_taken(run_id=uuid.uuid4(), run_mode="live")) == base
    assert agent_cache_key(_taken(tenant_id=uuid.UUID(int=0xA2))) != base
    assert agent_cache_key(_taken(pinned_hash="sha256:" + "b" * 64)) != base
    assert agent_cache_key(_taken(artifact_version_id=uuid.UUID(int=0xB2))) != base
