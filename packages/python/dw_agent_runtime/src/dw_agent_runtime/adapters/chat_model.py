"""Chat model port for tool-calling agent harnesses.

``ModelGateway`` answers one structured question per call. An agent harness
needs the other shape: a multi-turn model that emits tool calls. Both read the
same ``configs/models`` profiles — an agent picks a profile and gets its
``chat`` route. A pack's agent is compiled once per process, so its model is
built from the platform layer (``ModelResolver.platform_profile``); what each
call of it may spend, and whether the run's plan allows the profile at all, is
the budget door's per-call ``ModelResolver.resolve`` (model-connections R1.1).
Choosing a model per tenant for an agent is ``StudioModelSelection``
(agent-builder/03).

LangChain types stay behind this adapter (import-linter enforced).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import Field

from dw_agent_runtime.model.profiles import ModelRoute, Provider
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.registry import ConfigError


class ChatModelFactory(Protocol):
    """Builds the chat model a worker profile asks for."""

    def resolve(self, profile_id: str) -> BaseChatModel: ...


CHAT_PROVIDERS = (Provider.OPENAI_COMPATIBLE, Provider.OPENAI_RESPONSES)


@dataclass(frozen=True)
class OpenAICompatibleChatModelFactory:
    """Talks one dialect to any OpenAI-compatible endpoint.

    Point ``base_url`` at a LiteLLM proxy and provider selection, keys and
    fallbacks become proxy configuration the application never sees.
    """

    models: ModelResolver
    base_url: str
    api_key: str

    def resolve(self, profile_id: str) -> BaseChatModel:
        route = self.models.platform_profile(profile_id).chat
        if route is None:
            # A profile without a chat route cannot run an agent loop at all.
            raise ConfigError("model profile has no chat route", details={"profile_id": profile_id})
        if route.provider not in CHAT_PROVIDERS:
            raise ConfigError(
                "chat route provider is not OpenAI-compatible",
                details={"profile_id": profile_id, "provider": route.provider},
            )
        return openai_chat_model(route, base_url=self.base_url, api_key=self.api_key)


def openai_chat_model(route: ModelRoute, *, base_url: str, api_key: str) -> ChatOpenAI:
    """One route as a LangChain chat model: the factory's agent model, and what
    `make check-model` probes each route's capabilities through."""
    responses = route.provider == Provider.OPENAI_RESPONSES
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=route.model,
        temperature=None if route.temperature is None else float(route.temperature),
        timeout=route.timeout_seconds,
        use_responses_api=responses,
        # The two dialects spell reasoning differently, and they cannot both
        # be sent: `langchain_openai` folds `reasoning_effort` into
        # `reasoning` only when `reasoning` is absent. Sending both leaves
        # `reasoning_effort` as a top-level key on a Responses request, where
        # it is not a parameter, and the effort never reaches `reasoning`.
        reasoning=_reasoning_block(route) if responses else None,
        reasoning_effort=None if responses else route.reasoning_effort,
    )


def _reasoning_block(route: ModelRoute) -> dict[str, str] | None:
    """The Responses dialect's reasoning object, or None when it would be empty.

    An empty object is not the same as an absent one: the provider reads it as a
    request to reason with no effort stated, which is not what an unset route
    means.
    """
    block: dict[str, str] = {
        key: value
        for key, value in (
            ("effort", route.reasoning_effort),
            ("summary", route.reasoning_summary),
        )
        if value is not None
    }
    return block or None


class MockChatModel(BaseChatModel):
    """Replays scripted assistant turns; the last one repeats if the agent loops.

    Which reply is due is read from the conversation itself rather than counted
    on the instance. The agent is compiled once per process and holds one model,
    so an instance counter never restarted: a script of two replies gave the
    second one to every turn of every later conversation.

    LangChain's own fakes cannot ``bind_tools``, and tests need to assert which
    tools a run was allowed to offer the model.
    """

    responses: list[AIMessage]
    mock_reply: str
    bound_tool_names: list[str] = Field(default_factory=list)
    # The tool OBJECTS, not just their names. A name says a tool was offered;
    # only the object says which arguments the model was shown, which is what a
    # test asserting "the model cannot name a tenant" has to read.
    bound_tools: list[Any] = Field(default_factory=list)
    # What `bind_tools` was asked besides the tools (`tool_choice`, `strict`):
    # handed with `bound_tools` to a provider's own `bind_tools`, it gives the
    # definitions that provider would send.
    bound_kwargs: dict[str, Any] = Field(default_factory=dict)
    # Every turn's messages, in order. Lets a test assert what actually reached
    # the model — a prompt rendered per call is otherwise unobservable.
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    # The system message of every call, in order. Same reason as
    # `bound_tool_names`: a middleware stack decides what the model is told,
    # and the only honest way to assert on that is to read what arrived.
    system_prompts: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "mock"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> MockChatModel:
        self.bound_tool_names = [t.name if isinstance(t, BaseTool) else str(t) for t in tools]
        self.bound_tools = list(tools)
        self.bound_kwargs = dict(kwargs)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        self.system_prompts.append(
            "\n".join(m.text for m in messages if isinstance(m, SystemMessage))
        )
        turn = sum(1 for message in messages if isinstance(message, AIMessage))
        scripted = (
            self.responses[min(turn, len(self.responses) - 1)]
            if self.responses
            else AIMessage(content=self.mock_reply)
        )
        # Synthetic-but-deterministic usage, same ~4-chars-per-token rule the
        # mock provider adapter uses: the usage meter (F6) must see tokens on
        # the mock stack too, or metering is untestable offline.
        input_tokens = max(1, sum(len(str(message.content)) for message in messages) // 4)
        output_tokens = max(1, len(str(scripted.content)) // 4)
        priced = scripted.model_copy(
            update={
                "id": f"mock-{turn}",
                "usage_metadata": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                # The usage callback keys by model_name and drops rows
                # without one — real providers always send it.
                "response_metadata": {"model_name": "mock"},
            }
        )
        return ChatResult(generations=[ChatGeneration(message=priced)])


@dataclass
class MockChatModelFactory:
    """Deterministic chat models for tests and the mock profile.

    Without a script it still answers, so the mock profile is a runnable stack
    rather than one that fails on the first turn.
    """

    mock_reply: str
    scripts: dict[str, list[AIMessage]] = field(default_factory=dict)
    models: dict[str, MockChatModel] = field(default_factory=dict)

    def resolve(self, profile_id: str) -> BaseChatModel:
        model = MockChatModel(
            responses=list(self.scripts.get(profile_id, [])), mock_reply=self.mock_reply
        )
        self.models[profile_id] = model
        return model
