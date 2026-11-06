"""`StudioAgentCompiler`: a Studio agent version compiled (agent-builder
ticket 03 steps 1-4; ADR-0117 decision 5; ADR-0116 decision 3).

`AgentCompilerPort` of `dw_agent_runtime.studio_agent`, injected into
`dw_studio.agents.adapters.StudioGraphSource` at the worker's composition
root, since `dw_studio` imports no LangChain. Called once per graph the runner
caches, after the source's hash gate passed, with what the run pinned:

- the tools of the version's `toolset`, each resolved through the run's
  `PinnedResolver` and built by its kind's source and factory, loaded for the
  run's company (`ToolKindsLoaderPort`), the actor of each object tool's call
  bound by its kind (`agent_record_session`, record-access/04 step 5);
- the platform stack (`platform_middleware`, the one assembly) with the
  version's own system message (`ContainedAgentPrompt`) and its per-call model
  (`StudioModelSelection`), placed before `ResidencyGateMiddleware` and
  `LimitsMiddleware`, so a call the gate refuses holds no lease and is recorded
  nowhere (R3.7; usage-and-limits R6.5); `RunControlMiddleware` stays where
  agent-lifecycle/01 put it;
- one approval per step from each tool's own `approval_policy`, asked of
  `ToolExecutor` (ADR-0116), under `studio.agent.tool.`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain.agents.middleware import ModelRequest
from langgraph.checkpoint.base import BaseCheckpointSaver

from dw_agent_runtime.adapters.agent_factory import AgentSpec, build_agent
from dw_agent_runtime.adapters.studio_model_selection import (
    RouteChatModelFactory,
    StudioModelSelection,
    UnselectedChatModel,
)
from dw_agent_runtime.adapters.studio_tools import studio_tools
from dw_agent_runtime.adapters.system_prompt import ContainedAgentPrompt, utc_now
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.model.gateway import UsageRecorderPort
from dw_agent_runtime.model.pricing import PricingPort
from dw_agent_runtime.model.profiles import ModelCapabilities, ModelRoute
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.ports import LimitsPort, ObjectFieldsPort
from dw_agent_runtime.studio_agent import (
    AGENT_TOOL_APPROVAL_PREFIX,
    AgentBlueprint,
    RunNamesPort,
    ToolKindsLoaderPort,
)
from dw_agent_runtime.tool_kinds import ToolAssembler
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.residency import ResidencyGate

__all__ = ["StudioAgentCompiler", "pinned_capabilities"]


def pinned_capabilities(blueprint: AgentBlueprint) -> ModelCapabilities:
    """The capabilities of the chat route the run pinned for the version's
    profile, which decide strict tools (tools-and-skills R4.4); a profile the
    run did not pin has the plain ones, and its first call is refused
    `key_not_pinned` by the resolver anyway."""
    engine = blueprint.resolver.body.get("engine") or {}
    pin = (engine.get("model_routes") or {}).get(blueprint.profile_id) or {}
    chat = (pin.get("routes") or {}).get("chat")
    return ModelCapabilities() if chat is None else ModelRoute.model_validate(chat).capabilities


def _no_variables(request: ModelRequest[Any]) -> dict[str, str]:
    # `ContainedAgentPrompt` renders the frame's values itself.
    return {}


@dataclass(frozen=True)
class StudioAgentCompiler:
    checkpointer: BaseCheckpointSaver[Any]
    executor: ToolExecutor
    tool_kinds: ToolKindsLoaderPort
    object_fields: ObjectFieldsPort
    copy: RuntimeCopy
    # Holds the platform layer of every containment frame a version may pin.
    prompts: PromptRegistry
    names: RunNamesPort
    models: ModelResolver
    chat_models: RouteChatModelFactory
    limits: LimitsPort
    usage_recorder: UsageRecorderPort
    pricing: PricingPort
    residency: ResidencyGate
    clock: Callable[[], datetime] = field(default=utc_now)

    async def compile(self, blueprint: AgentBlueprint) -> Any:
        loaded = await self.tool_kinds.load(blueprint.tenant_id, blueprint.toolset)
        pinned = studio_tools(
            blueprint.toolset,
            blueprint.resolver,
            ToolAssembler(registry=ToolRegistry(), kinds=loaded.factories),
            loaded.sources,
            self.executor,
            capabilities=pinned_capabilities(blueprint),
            approval_type_prefix=AGENT_TOOL_APPROVAL_PREFIX,
            copy=self.copy,
        )
        spec = AgentSpec(
            model=UnselectedChatModel(),
            offered=(),
            registry=ToolRegistry(),
            executor=self.executor,
            copy=self.copy,
            approval_type_prefix=AGENT_TOOL_APPROVAL_PREFIX,
            prompt_id=blueprint.frame_id,
            prompt_version=blueprint.frame_version,
            prompts=self.prompts,
            prompt_variables=_no_variables,
            limits=self.limits,
            usage_recorder=self.usage_recorder,
            pricing=self.pricing,
            models=self.models,
            profile_id=blueprint.profile_id,
            residency=self.residency,
            pinned=pinned,
            object_fields=self.object_fields,
            system_prompt=ContainedAgentPrompt(
                self.prompts,
                blueprint.frame_id,
                blueprint.frame_version,
                instructions=blueprint.instructions,
                agent_name=blueprint.agent_name,
                names=self.names,
                clock=self.clock,
            ),
            model_selection=StudioModelSelection(
                self.models,
                self.chat_models,
                blueprint.profile_id,
                tenant_id=blueprint.tenant_id,
                version_id=blueprint.version_id,
                pinned_hash=blueprint.pinned_hash,
            ),
        )
        return build_agent(spec, checkpointer=self.checkpointer)
