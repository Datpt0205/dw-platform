"""A measured prototype of the Studio agent runtime (agent-builder ticket 01).

Test code only, never imported by `src/`: ticket 03 builds the real runtime and
deletes this directory in the same change. What it stands in for, and what it
answers for that ticket:

* `StudioGraphSource`: the agent of one (company, version) compiled from a
  version document (here a JSON fixture) and kept in an LRU of at most
  `CACHE_CAPACITY` graphs keyed `(tenant_id, agent_version_id, pinned_hash)`
  (ADR-0117 decision 5; spec R3.1). It does not go through the runner (the
  ticket changes no runner code): it compiles with the checkpointer it is
  given, and a test invokes the graph directly.
* `StudioModelSelection`: the model a run pinned (spec R3.5) chosen per call
  by a resolver, standing before `LimitsMiddleware` so the lease prices
  the chosen model (M2, `tests/unit/test_library_contracts.py`).
* `studio_sub_agents`: a child whose own stack carries the run control and its
  own model selection, because the parent's middleware does not wrap a child
  turn (`adapters/sub_agents.py`; ADR-0117 decision 7).

The tools of a version are registered for the version's company in the
`ToolRegistry` and resolved under that company when the graph is built, then
handed to the executor as pinned (`adapters/studio_tools.py` builds a Studio
tool the same way): a key naming another company resolves nothing.
"""

from __future__ import annotations

import json
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fakes import NOW, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.runtime import get_runtime
from pydantic import BaseModel, create_model

from dw_agent_runtime.adapters.agent_factory import AgentSpec, platform_middleware
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.langchain_tools import tool_call
from dw_agent_runtime.adapters.limits_middleware import LimitsMiddleware
from dw_agent_runtime.adapters.studio_tools import PinnedTools
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec, sub_agent_spec
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition, model_facing_name
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver as PlatformModelResolver
from dw_agent_runtime.ports import RunControlPort
from dw_agent_runtime.run_control import HaltReason, RunControlDoor
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.models import resolver as model_resolver
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_kernel.ids import TenantId
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_platform.testing.residency import run_gate

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "studio_agent.json"
COPY = load_runtime_copy(HERE.parents[4] / "configs" / "copy" / "runtime@1.6.0.yaml")

# ADR-0117 (Accepted) decision 5: the ceiling the measurement of step 4 checks.
CACHE_CAPACITY = 256

# The platform's frame around a tenant's instructions (ADR-0117 decision 3),
# standing in for `studio.agent_frame`, which ticket 02 ships. The tenant's
# text is a variable, so the registry wraps it in an `<input>` block.
FRAME_ID = "studio.agent_frame"
FRAME_VERSION = "0.0.1"
FRAME = PromptArtifact(
    schema_version="1.0",
    prompt_id=FRAME_ID,
    version=FRAME_VERSION,
    system="Bạn là một agent do công ty cấu hình trên nền tảng.",
    template="Chỉ dẫn của công ty:\n{instructions}",
    variables=frozenset({"instructions"}),
)

CacheKey = tuple[uuid.UUID, uuid.UUID, str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class SubAgentDoc:
    name: str
    description: str
    tools: tuple[str, ...]
    profile_id: str


@dataclass(frozen=True)
class AgentDocument:
    """What the prototype reads in place of a sealed `dw.agent/v1` version."""

    agent_version_id: uuid.UUID
    # The hash the run manifest pinned (spec R3.1): a sealed version's
    # `definition_hash`, or a draft's provisional hash under `simulate`.
    pinned_hash: str
    profile_id: str
    instructions: str
    tools: tuple[ToolSpec, ...]
    sub_agent: SubAgentDoc

    @classmethod
    def load(cls, path: Path = FIXTURE) -> AgentDocument:
        raw = json.loads(path.read_text(encoding="utf-8"))
        child = raw["sub_agent"]
        return cls(
            agent_version_id=uuid.UUID(raw["agent_version_id"]),
            pinned_hash=raw["pinned_hash"],
            profile_id=raw["profile_id"],
            instructions=raw["instructions"],
            tools=tuple(
                ToolSpec(t["name"], t["version"], t["description"], tuple(t["fields"]))
                for t in raw["tools"]
            ),
            sub_agent=SubAgentDoc(
                child["name"], child["description"], tuple(child["tools"]), child["profile_id"]
            ),
        )

    def variant(self, n: int, *, pinned_hash: str | None = None) -> AgentDocument:
        """The n-th version of this fixture: its own id, wording and hash."""
        return AgentDocument(
            agent_version_id=uuid.uuid5(self.agent_version_id, str(n)),
            pinned_hash=pinned_hash or f"{n:064x}",
            profile_id=self.profile_id,
            instructions=f"{self.instructions} (phiên bản {n})",
            tools=self.tools,
            sub_agent=self.sub_agent,
        )


def definition_of(spec: ToolSpec) -> ToolDefinition:
    """A read-only tool, as W1's assistant offers only reads."""
    return ToolDefinition(
        name=spec.name,
        version=spec.version,
        description=spec.description,
        input_schema_ref=f"studio/{spec.name}@{spec.version}/input",
        output_schema_ref=f"studio/{spec.name}@{spec.version}/output",
        required_scopes=frozenset(),
        side_effect_level="none",
        approval_policy="never",
        timeout_seconds=10,
        max_retries=0,
        idempotent=True,
        data_classification=frozenset({"internal"}),
    )


class ToolAnswer(BaseModel):
    text: str


Handler = Callable[[BaseModel, RunContext], Any]


async def answer(payload: BaseModel, run_context: RunContext) -> ToolAnswer:
    return ToolAnswer(text=f"{type(payload).__name__}: {payload.model_dump_json()}")


def register_tools(
    registry: ToolRegistry,
    document: AgentDocument,
    *,
    tenant_id: uuid.UUID | None,
    handler: Handler = answer,
) -> None:
    """The version's tools, registered for one company (`None`: the platform
    layer, which only the code-defined sub-agent path reads)."""
    for spec in document.tools:
        args = create_model(  # type: ignore[call-overload]
            f"{model_facing_name(spec.name)}_input",
            **dict.fromkeys(spec.fields, (str, ...)),
        )
        registry.register(
            RegisteredTool(
                definition=definition_of(spec),
                behaviour=pydantic_behaviour(args, ToolAnswer, handler),
            ),
            tenant_id=None if tenant_id is None else TenantId(tenant_id),
        )


def models_for(document: AgentDocument) -> PlatformModelResolver:
    profiles = ModelProfileRegistry()
    route = {
        "provider": "mock",
        "model": "mock-1",
        "data_location": "vn",
        "processor": "mock",
        "retention_days": 0,
        "no_training": True,
    }
    for profile_id in (document.profile_id, document.sub_agent.profile_id):
        profiles.register(
            ModelProfile.model_validate(
                {
                    "schema_version": "2.0",
                    "profile_id": profile_id,
                    "routing_policy_version": "1.0.0",
                    "structured_extraction": route,
                    "reasoning": route,
                    "chat": route,
                }
            )
        )
    return model_resolver(profiles, document.profile_id)


def executor_over(registry: ToolRegistry, run_control: RunControlPort) -> ToolExecutor:
    store = FakeExecutionStore()
    return ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=FakeUoWFactory(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
        steps=build_tool_executor_steps(),
        run_control=run_control,
    )


def run_context(tenant_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> RunContext:
    """A live chat run of the fixture agent, at A4: every tool is a read."""
    return RunContext(
        run_id=uuid.uuid4(),
        run_mode="live",
        tenant_id=tenant_id,
        workspace_id=workspace_id or uuid.UUID(int=tenant_id.int + 1),
        actor_id=uuid.UUID(int=0xAC7),
        worker_id="studio.agent",
        worker_version="1.0.0",
        channel="chat",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset(),
        trace_id="trace-proto",
        autonomy_level="A4",
        autonomy_ceiling="A4",
    )


# ---------------------------------------------------------------------------
# Model selection and the probes that watch a stack
# ---------------------------------------------------------------------------


class ModelResolver(Protocol):
    """The route a run pinned, as a chat model (ticket 03 reads the manifest)."""

    def model_for(self, tenant_id: uuid.UUID, profile_id: str) -> BaseChatModel: ...


@dataclass
class FixedRoutes:
    """A fake resolver: one model per profile, whatever the company."""

    models: Mapping[str, BaseChatModel]

    def model_for(self, tenant_id: uuid.UUID, profile_id: str) -> BaseChatModel:
        return self.models[profile_id]


class StudioModelSelection(AgentMiddleware[Any, Any]):
    """Hands every model call of its stack to the model its run pinned."""

    def __init__(
        self, resolver: ModelResolver, profile_id: str, *, log: list[str] | None = None
    ) -> None:
        super().__init__()
        self._resolver = resolver
        self._profile_id = profile_id
        self._log = log

    @property
    def name(self) -> str:
        # A parent and a child each carry one; langchain needs distinct names.
        return f"studio_model_selection_{self._profile_id}"

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        if self._log is not None:
            self._log.append(f"selection:{self._profile_id}")
        chosen = self._resolver.model_for(run_context.tenant_id, self._profile_id)
        response: ModelResponse[Any] = await handler(request.override(model=chosen))
        return response


def before_the_ceiling(
    stack: Sequence[AgentMiddleware[Any, Any]], selection: StudioModelSelection
) -> list[AgentMiddleware[Any, Any]]:
    """`stack` with `selection` directly before `LimitsMiddleware`: outer to
    it, so the lease sees the chosen model (M2). The full order with
    `ResidencyGate` is agent-builder/03's."""
    out = list(stack)
    at = next(i for i, m in enumerate(out) if isinstance(m, LimitsMiddleware))
    out.insert(at, selection)
    return out


@dataclass
class ProbedRunControl:
    """An open `RunControlPort` that writes each model door it is asked."""

    log: list[str]

    async def require_open(
        self, run_context: RunContext, *, door: RunControlDoor, artifacts: Sequence[uuid.UUID] = ()
    ) -> None:
        if door is RunControlDoor.MODEL:
            self.log.append("run_control")

    async def admission_state(
        self, tenant_id: uuid.UUID, artifacts: Sequence[uuid.UUID] = ()
    ) -> HaltReason | None:
        return None


class LoggedModel(MockChatModel):
    """A scripted model that writes its label to a shared log when called."""

    label: str
    # `Any`, not `list[str]`: pydantic copies a validated list, and the log
    # has to be the one the other probes write to.
    log: Any

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.log.append(f"model:{self.label}")
        return super()._generate(messages, stop, run_manager, **kwargs)


# ---------------------------------------------------------------------------
# The source and its cache
# ---------------------------------------------------------------------------


def cache_key(tenant_id: uuid.UUID, document: AgentDocument) -> CacheKey:
    return (tenant_id, document.agent_version_id, document.pinned_hash)


@dataclass
class StudioGraphSource:
    """Compiled agents of (company, version), at most `capacity` of them."""

    registry: ToolRegistry
    executor: ToolExecutor
    default_model: BaseChatModel
    routes: ModelResolver
    checkpointer: BaseCheckpointSaver[Any] | None = None
    capacity: int = CACHE_CAPACITY
    compiled: OrderedDict[CacheKey, Any] = field(default_factory=OrderedDict)
    builds: int = 0

    def graph(self, tenant_id: uuid.UUID, document: AgentDocument) -> Any:
        key = cache_key(tenant_id, document)
        if key in self.compiled:
            self.compiled.move_to_end(key)
            return self.compiled[key]
        built = self._build(tenant_id, document)
        self.builds += 1
        self.compiled[key] = built
        while len(self.compiled) > self.capacity:
            self.compiled.popitem(last=False)
        return built

    def _build(self, tenant_id: uuid.UUID, document: AgentDocument) -> Any:
        pinned = self._pinned_tools(tenant_id, document)
        prompts = PromptRegistry()
        prompts.register(FRAME)
        instructions = document.instructions
        spec = AgentSpec(
            residency=run_gate(),
            model=self.default_model,
            offered=(),
            registry=self.registry,
            executor=self.executor,
            copy=COPY,
            approval_type_prefix="studio.agent.",
            prompt_id=FRAME_ID,
            prompt_version=FRAME_VERSION,
            prompts=prompts,
            prompt_variables=lambda request: {"instructions": instructions},
            limits=OpenLimits(),
            usage_recorder=InMemoryUsageRecorder(),
            pricing=FlatPricing(),
            models=models_for(document),
            profile_id=document.profile_id,
            pinned=pinned,
        )
        stack = before_the_ceiling(
            platform_middleware(spec), StudioModelSelection(self.routes, document.profile_id)
        )
        return create_agent(
            model=spec.model,
            tools=list(pinned.tools),
            middleware=stack,
            context_schema=RunContext,
            checkpointer=self.checkpointer,
        )

    def _pinned_tools(self, tenant_id: uuid.UUID, document: AgentDocument) -> PinnedTools:
        """Each tool resolved under the key's company, never the platform's or
        another company's, and handed to the executor as pinned."""
        tools: list[StructuredTool] = []
        definitions: list[ToolDefinition] = []
        for spec in document.tools:
            registered = self.registry.resolve(
                spec.name, spec.version, tenant_id=TenantId(tenant_id)
            )
            tools.append(
                StructuredTool(
                    name=model_facing_name(spec.name),
                    description=spec.description,
                    args_schema=registered.behaviour.args_schema,
                    coroutine=tool_call(
                        registered,
                        self.executor,
                        "studio.agent.",
                        COPY,
                        pinned=True,
                        present=lambda result: result.output.model_dump_json(),
                        rejected=lambda text: text,
                    ),
                )
            )
            definitions.append(registered.definition)
        return PinnedTools(tuple(tools), tuple(definitions))


# ---------------------------------------------------------------------------
# A sub-agent with its own stack
# ---------------------------------------------------------------------------


def studio_sub_agents(
    parent: AgentSpec, child: SubAgentSpec, selection: StudioModelSelection
) -> AgentMiddleware[Any, Any]:
    """`sub_agent_middleware` with the child's own model selection added.

    The child's stack is `sub_agent_spec`'s (the run control, the parent's
    ledger, the tool gates) with `selection` before its ceiling.
    `sub_agent_middleware` takes no middleware of a caller's, so the prototype
    composes its two lines itself; that seam is ticket 03's.
    """
    from deepagents import SubAgent, SubAgentMiddleware
    from deepagents.backends import StateBackend

    built = sub_agent_spec(parent, child)
    built["middleware"] = before_the_ceiling(built["middleware"], selection)
    subagent: SubAgent = built  # type: ignore[assignment]
    return SubAgentMiddleware(backend=StateBackend(), subagents=[subagent])
