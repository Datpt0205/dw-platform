"""The model a Studio agent's run pinned, chosen per call (agent-builder R3.5,
R3.6; ADR-0117 decision 5; ADR-0118).

A Studio agent is compiled once per `(company, version, pinned hash)` and
serves every run of it, so its model cannot be fixed at build: each call asks
`ModelResolver` for the route the run's manifest pinned for the version's
profile (`engine.model_routes`, refused `key_not_pinned` or
`model_profile_unavailable` before anything is sent) and hands the call to a
chat model of that route. The model `create_agent` was built with is
`UnselectedChatModel`, which refuses: a stack that lost its selection fails its
first call rather than sending to a model nobody pinned.

`StudioModelSelection` stands directly before `ResidencyGateMiddleware` and
`LimitsMiddleware` (`platform_middleware`, `AgentSpec.model_selection`): the
outer layer, so the residency gate and the lease see the call the chosen route
makes (M2, `tests/unit/test_library_contracts.py`). Every per-route model
refuses a call made without a lease's permit (`require_permit`), so the route
is reached only through the lease.

It also holds what its graph was built from and refuses a run of another
company, version or pinned hash (`RunContext.artifact`,
`RunContext.definition_hash`): a cache key that lost a part is a failed call,
never one company's agent, or an older content's, answering another's run.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langgraph.runtime import get_runtime

from dw_agent_runtime.adapters.chat_model import (
    CHAT_PROVIDERS,
    MockChatModel,
    openai_chat_model,
    require_permit,
)
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.resolver import ModelResolver
from dw_kernel.errors import ConfigError

__all__ = [
    "MockRouteModels",
    "OpenAICompatibleRouteModels",
    "RouteChatModelFactory",
    "StudioModelSelection",
    "UnselectedChatModel",
]

# Chat models a process keeps, one per distinct route: few in practice, bounded
# all the same (failure-modes #6).
_ROUTE_MODELS: Final = 64


class RouteChatModelFactory(Protocol):
    """A chat model that calls exactly ``route``, refusing a call no lease
    permitted."""

    def for_route(self, route: ModelRoute) -> BaseChatModel: ...


def _route_key(route: ModelRoute) -> str:
    return route.model_dump_json()


@dataclass
class OpenAICompatibleRouteModels:
    """Routes of the OpenAI-compatible dialects, through the deployment's
    endpoint (`openai_chat_model`)."""

    base_url: str
    api_key: str
    _built: OrderedDict[str, BaseChatModel] = field(default_factory=OrderedDict, repr=False)

    def for_route(self, route: ModelRoute) -> BaseChatModel:
        if route.provider not in CHAT_PROVIDERS:
            raise ConfigError(
                "chat route provider is not OpenAI-compatible",
                details={"provider": route.provider, "model": route.model},
            )
        key = _route_key(route)
        found = self._built.get(key)
        if found is not None:
            self._built.move_to_end(key)
            return found
        built = require_permit(
            openai_chat_model(route, base_url=self.base_url, api_key=self.api_key)
        )
        self._built[key] = built
        while len(self._built) > _ROUTE_MODELS:
            self._built.popitem(last=False)
        return built


@dataclass(frozen=True)
class MockRouteModels:
    """The mock profile's models (local and test only, as the provider is):
    every route answers `mock_reply`."""

    mock_reply: str

    def for_route(self, route: ModelRoute) -> BaseChatModel:
        return require_permit(MockChatModel(responses=[], mock_reply=self.mock_reply))


class UnselectedChatModel(BaseChatModel):
    """What a Studio agent is compiled with: refuses every call, since the
    model of a call is the route its run pinned (`StudioModelSelection`)."""

    @property
    def _llm_type(self) -> str:
        return "unselected"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise ConfigError(
            "a Studio agent's model is the route its run pinned",
            details={"reason": "model_unselected"},
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> UnselectedChatModel:
        return self


class StudioModelSelection(AgentMiddleware[Any, Any]):
    """Hands every model call of its agent to the route its run pinned."""

    def __init__(
        self,
        models: ModelResolver,
        chat_models: RouteChatModelFactory,
        profile_id: str,
        *,
        tenant_id: UUID,
        version_id: UUID,
        pinned_hash: str,
    ) -> None:
        super().__init__()
        self._models = models
        self._chat_models = chat_models
        self._profile_id = profile_id
        self._tenant_id = tenant_id
        self._version_id = version_id
        self._definition_hash = pinned_hash.removeprefix("sha256:")

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        artifact = run_context.artifact
        if (
            run_context.tenant_id != self._tenant_id
            or artifact is None
            or artifact.version_id != self._version_id
            or run_context.definition_hash != self._definition_hash
        ):
            raise ConfigError(
                "this agent was built for another company's or version's run",
                details={"reason": "graph_mismatch"},
            )
        resolved = await self._models.resolve(run_context, self._profile_id, "chat")
        chosen = self._chat_models.for_route(resolved.route)
        return await handler(request.override(model=chosen))
