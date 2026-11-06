"""The one place a platform agent is assembled.

Every bounded context used to build its own: `create_agent(...)` with whichever
middleware its author remembered. The middlewares in this package each close a
hole that was found in production — a builtin tool that bypassed the executor,
a tool nobody declared passing a scope check by not being declared, a worker
prompt that silently deleted the skills catalogue, a sibling approval nobody was
shown, a tool failure that killed the turn and lost the transcript, a binary
file that made the provider reject the whole request. A context that assembles
its own agent and forgets one reopens that hole, and nothing tells it so.

So assembly is a platform artifact, not a per-context habit.

What is and is not a contract here, measured rather than assumed. All 720
orderings of the first six were run against the properties they protect, and not
one ordering broke any of them: none of these middlewares reads what another one
writes, so their order is free. The seventh, the spend ceiling, was added after
that measurement and was not put through it — it reads only the model's own
response, which none of the others write to. What is NOT free is PRESENCE:
removing any single one of the seven breaks exactly the property it owns. That is
what this factory guarantees and what `test_agent_factory.py` pins.

The obvious candidate for a first real ordering contract was a summariser that
had to see files already stripped. Measured: it is not one — the summariser
serialises history to text before sending it, so no file block reaches it. An
order becomes a contract the day a test shows one breaking, and not before.

Built on `create_agent`, not `create_deep_agent`. Measured on the pinned
deepagents: the deep variant installs eight builtin tools on its own —
`delete`, `edit_file`, `glob`, `grep`, `ls`, `read_file`, `task`, `write_file` —
every one of which reaches outside the run without passing `ToolExecutor`, and
therefore without authorization, idempotency or audit. The set is not even
stable: comments written against an earlier release named `execute` and not
`delete`. Installing a library's tools and then stripping them is a denylist
against a list the library is free to change. `create_agent` installs nothing,
so the platform adds exactly what it controls.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from dw_agent_runtime.adapters.context_compaction import PlatformSummarizationMiddleware
from dw_agent_runtime.adapters.langchain_tools import (
    OfferedToolsOnlyMiddleware,
    OneApprovalPerStepMiddleware,
    PlatformToolErrorsMiddleware,
    ScopedToolsMiddleware,
    UnreadableFilesMiddleware,
    platform_tools,
)
from dw_agent_runtime.adapters.limits_middleware import LimitsMiddleware
from dw_agent_runtime.adapters.model_retry import ModelRetryMiddleware
from dw_agent_runtime.adapters.recalled_memory import MemoryRecallPort, RecalledMemoryMiddleware
from dw_agent_runtime.adapters.residency_middleware import ResidencyGateMiddleware
from dw_agent_runtime.adapters.run_control_middleware import RunControlMiddleware
from dw_agent_runtime.adapters.studio_tools import (
    FIELD_NARROWING,
    FieldSecurityToolSchemaMiddleware,
    PinnedTools,
    StrictToolsMiddleware,
)
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec, sub_agent_middleware
from dw_agent_runtime.adapters.system_prompt import WorkerSystemPrompt
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.model.gateway import UsageRecorderPort
from dw_agent_runtime.model.pricing import PricingPort
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.ports import LimitsPort, ObjectFieldsPort
from dw_agent_runtime.registry import ConfigError
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.residency import ResidencyGate
from dw_platform.application.ports import PlatformUnitOfWorkFactory

__all__ = [
    "AgentSpec",
    "CompactionSpec",
    "build_agent",
    "offered_definitions",
    "platform_middleware",
]


def _utc_now() -> datetime:
    """The default clock for recall. A named function, not a lambda, so the
    default a host gets is greppable."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class CompactionSpec:
    """How a worker that runs long enough to need it compacts its history.

    Optional, unlike the spend ceiling. A ceiling is a safety control every agent
    carries; compaction is a capability that costs a model call and only earns it
    for a run that outgrows its context window. A worker answering one question
    at a time would pay for summaries of conversations that fit.
    """

    # Usually a cheaper model than the worker's own: summarising is not the work.
    model: BaseChatModel
    # Whose price a summary is charged at. The ceiling it counts against is the
    # worker's, from `AgentSpec.profile_id`.
    summary_profile_id: str
    uow_factory: PlatformUnitOfWorkFactory
    clock: UtcClock
    ids: IdGenerator
    # When to compact, and how much recent history to keep verbatim.
    trigger: ContextSize
    keep: ContextSize


@dataclass(frozen=True)
class AgentSpec:
    """Everything one worker's agent is built from.

    `offered` is the resolved toolset — the definitions this worker pins, not
    every tool the registry holds. It is handed to the tool builder and to every
    middleware as one list, which is the point: a scope filter reading the whole
    registry while the tool list reads the toolset is how a tool registered for
    another worker becomes callable here.
    """

    model: BaseChatModel
    offered: Sequence[ToolDefinition]
    registry: ToolRegistry
    executor: ToolExecutor
    copy: RuntimeCopy
    # Prefixes the approval type a gated tool raises, so the approvals screen
    # can route a decision back to the context that owns it.
    approval_type_prefix: str
    # The worker prompt: a registry artifact, pinned. Pass the worker
    # definition's `agent_prompt_id`/`agent_prompt_version` - the pin the runner
    # bills this loop under - rather than naming a version a second time.
    prompt_id: str
    prompt_version: str
    prompts: PromptRegistry
    # Rendered per model call, not once at build: the prompt names today's date
    # and the screen in view, and the agent is compiled once per process.
    prompt_variables: Callable[[ModelRequest[Any]], dict[str, str]]
    # The hard limits every model call of this agent asks first
    # (usage-and-limits R5.2): `RuntimeSeam.limits`, the process's one port.
    limits: LimitsPort
    # Where a permitted call's usage is recorded, which settles it into its
    # lease (R5.11): `RuntimeSeam.usage_recorder`, the gateway's own recorders.
    usage_recorder: UsageRecorderPort
    # The price book every call of this worker is priced by (usage-and-limits
    # R2.1): the composition root's one instance, `RuntimeSeam.pricing`.
    pricing: PricingPort
    # The one resolver every model door of this agent asks, per call, with the
    # run's context (model-connections R1.1): `RuntimeSeam.models`.
    models: ModelResolver
    profile_id: str
    # The one residency gate of the process (compliance-pdpl R2.3): the agent
    # loop's model calls, a sub-agent's and a summary's ask it before sending.
    residency: ResidencyGate
    compaction: CompactionSpec | None = None
    # What this worker already learned about the record in view. Optional the
    # same way compaction is: a context that stores no memory wires none, and a
    # run with no `subject_ref` recalls nothing even when it is wired.
    recall: MemoryRecallPort | None = None
    # Narrower agents this worker may delegate to. Empty by default: the `task`
    # tool only exists when a context names something to delegate TO, and an
    # agent that can spawn is a larger surface than one that cannot.
    sub_agents: Sequence[SubAgentSpec] = ()
    # Only read when `recall` is set. Passed rather than taken from a module
    # global so a test can pin the moment a validity window is judged against.
    clock: Callable[[], datetime] | None = None
    # A Studio agent's tools, built from what its run pinned
    # (`adapters.studio_tools`; tools-and-skills R4.1). Set, they are the
    # agent's only tools and their definitions are what every middleware is
    # built from: `offered` stays empty and `registry` is not read.
    pinned: PinnedTools | None = None
    # What the run's actor reads of each object now, which a Studio agent's
    # object tools are narrowed to at every model call (tools-and-skills R6.3).
    # Required once a pinned tool lists an object's fields.
    object_fields: ObjectFieldsPort | None = None


def offered_definitions(spec: AgentSpec) -> list[ToolDefinition]:
    """The one list the tools and every middleware are built from: a Studio
    agent's pinned definitions, or a code-defined worker's toolset."""
    if spec.pinned is None:
        return list(spec.offered)
    if spec.offered:
        raise ConfigError(
            "a Studio agent offers only what its run pinned",
            details={"offered": [definition.name for definition in spec.offered]},
        )
    if spec.sub_agents:
        raise ConfigError("a Studio agent's sub-agents are not built from a toolset")
    return list(spec.pinned.definitions)


def platform_middleware(spec: AgentSpec) -> list[AgentMiddleware[Any, Any]]:
    """The middleware stack every platform agent carries.

    Seven are unconditional — the safety controls, each closing a hole found in
    production. Two more are wired only when the spec asks: context compaction,
    and recall of what this worker already learned about the record in view. The
    count in this docstring used to be the contract; it is not, and saying
    "seven" while building eight is how a reader stops trusting the comment.
    What IS the contract is that none of the unconditional ones may be dropped.

    Exposed on its own so a context that must add middleware of its own extends
    this list rather than rebuilding it — rebuilding is exactly how one gets
    dropped.

    Any middleware added to this list must let `GraphBubbleUp` through. Measured:
    a single `awrap_tool_call` that catches `BaseException` and returns a message
    swallows the `interrupt()` an approval raises, and the run carries on as if
    a person had said yes. `PlatformToolErrorsMiddleware` is safe because it
    subclasses `ToolErrorMiddleware`, which re-raises it; a hand-written
    `try/except` is not.
    """
    offered = offered_definitions(spec)
    stack: list[AgentMiddleware[Any, Any]] = [
        WorkerSystemPrompt(
            spec.prompts, spec.prompt_id, spec.prompt_version, spec.prompt_variables
        ),
        # Directly after the worker prompt: the prompt says what this worker is,
        # and recall appends what it happens to know about the record in view.
        # Both are system-message work, so keeping them adjacent means one place
        # to look when asking what the model was told.
        *(
            [
                RecalledMemoryMiddleware(
                    spec.recall,
                    copy=spec.copy,
                    clock=spec.clock if spec.clock is not None else _utc_now,
                )
            ]
            if spec.recall is not None
            else []
        ),
        UnreadableFilesMiddleware(),
        OfferedToolsOnlyMiddleware(offered),
        *_field_security(spec),
        ScopedToolsMiddleware(offered),
        # Decides which tools are gated per call from the run's autonomy, not once
        # here from the tool. It used to freeze that set at build time, and an
        # agent is compiled once per process, so one set served every tenant at
        # every level. Handed the executor's own policy so this gate, the tool
        # wrapper and the executor cannot disagree about a call.
        OneApprovalPerStepMiddleware(offered, copy=spec.copy, approvals=spec.executor),
        PlatformToolErrorsMiddleware(offered, copy=spec.copy),
        # The freeze at the model call (agent-lifecycle R7.1): the executor's
        # own port, the one instance this process asks at every door.
        RunControlMiddleware(spec.executor.run_control),
        # The data route (compliance-pdpl R2.2, R2.3): after the freeze and
        # before the limits, so a refused call holds and spends nothing
        # (usage-and-limits R6.5).
        ResidencyGateMiddleware(spec.residency, spec.models, spec.profile_id),
        # The hard limits on the path that can loop (usage-and-limits R5.2):
        # every call asks the run's lease first. Without it an agent run is
        # bounded by `recursion_limit`, which counts steps and not money.
        LimitsMiddleware(
            spec.limits, spec.models, spec.profile_id, spec.pricing, spec.usage_recorder
        ),
        # A Studio agent's strict schemas go with `strict=True` on the provider's
        # tool definitions, and only with them (tools-and-skills R4.4).
        *([StrictToolsMiddleware()] if spec.pinned is not None and spec.pinned.strict else []),
        # Last, so it sits closest to the model: a retry re-runs only the call
        # that failed. A failed attempt produces no response and therefore no
        # usage, so the lease above settles nothing for one.
        ModelRetryMiddleware(),
    ]
    if spec.sub_agents:
        # Last, and only when asked. It adds the `task` tool, so it changes what
        # the model may do — see `sub_agents` for what the platform re-applies
        # inside a delegated turn, and why none of it is inherited.
        stack.append(sub_agent_middleware(spec, spec.sub_agents))
    if spec.compaction is not None:
        stack.append(
            PlatformSummarizationMiddleware(
                spec.compaction.model,
                copy=spec.copy,
                uow_factory=spec.compaction.uow_factory,
                clock=spec.compaction.clock,
                ids=spec.compaction.ids,
                # The same lease the limits middleware above asks, so a summary
                # and an agent step spend against one run's limits.
                limits=spec.limits,
                usage_recorder=spec.usage_recorder,
                pricing=spec.pricing,
                models=spec.models,
                profile_id=spec.profile_id,
                summary_profile_id=spec.compaction.summary_profile_id,
                trigger=spec.compaction.trigger,
                keep=spec.compaction.keep,
                run_control=spec.executor.run_control,
                residency=spec.residency,
            )
        )
    return stack


def _field_security(spec: AgentSpec) -> list[AgentMiddleware[Any, Any]]:
    """A Studio agent's object tools narrowed to what its actor reads, at
    every model call (tools-and-skills R6.3). Closed on a gap: a pinned tool
    that lists an object's fields and no port to ask is a `ConfigError`, never
    a model shown fields nobody checked."""
    if spec.pinned is None:
        return []
    narrowed = [
        tool.name for tool in spec.pinned.tools if (tool.metadata or {}).get(FIELD_NARROWING)
    ]
    if spec.object_fields is None:
        if narrowed:
            raise ConfigError(
                "an object tool needs the run's field access to be shown",
                details={"tools": narrowed},
            )
        return []
    return [FieldSecurityToolSchemaMiddleware(spec.object_fields)]


def build_agent(
    spec: AgentSpec,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    store: BaseStore | None = None,
) -> Any:
    """Assemble a platform agent from one worker's spec.

    Returns the compiled graph `create_agent` produces. The checkpointer is
    optional because a graph a runner hosts is compiled by the runner, which
    passes its own; one built for a test or a one-shot call has none.
    """
    offered = offered_definitions(spec)
    tools: list[Any] = (
        list(spec.pinned.tools)
        if spec.pinned is not None
        else list(
            platform_tools(
                offered,
                spec.registry,
                spec.executor,
                approval_type_prefix=spec.approval_type_prefix,
                copy=spec.copy,
            )
        )
    )
    middleware = platform_middleware(spec)
    # Refused here as well as dropped per call: a tool the platform did not build
    # reaches the model without ToolExecutor (ADR-0116 decision 3).
    foreign = [
        type(tool).__name__
        for tool in [*tools, *(t for m in middleware for t in getattr(m, "tools", ()))]
        if not isinstance(tool, BaseTool)
    ]
    if foreign:
        raise ConfigError(
            "an agent may only carry platform tools", details={"entry_types": foreign}
        )
    return create_agent(
        model=spec.model,
        tools=tools,
        middleware=middleware,
        context_schema=RunContext,
        checkpointer=checkpointer,
        store=store,
    )
