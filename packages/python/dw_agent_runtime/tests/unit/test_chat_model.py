import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from dw_agent_runtime.adapters.chat_model import (
    MockChatModel,
    MockChatModelFactory,
    OpenAICompatibleChatModelFactory,
)
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry, ModelRoute
from dw_agent_runtime.registry import ConfigError
from dw_agent_runtime.testing.models import resolver as model_resolver
from dw_agent_runtime.testing.models import route as test_route

pytestmark = pytest.mark.unit

MOCK_REPLY = "[mock model for tests]"


@tool
def upsert_lead(company: str) -> str:
    """Create a new lead in the CRM."""
    return f"lead:{company}"


def make_registry(chat: ModelRoute | None) -> ModelProfileRegistry:
    registry = ModelProfileRegistry()
    registry.register(
        ModelProfile(
            schema_version="2.0",
            profile_id="sales",
            routing_policy_version="1.0.0",
            structured_extraction=test_route(provider="mock", model="extract"),
            reasoning=test_route(provider="mock", model="reason"),
            chat=chat,
        )
    )
    return registry


def make_factory(chat: ModelRoute | None) -> OpenAICompatibleChatModelFactory:
    return OpenAICompatibleChatModelFactory(
        models=model_resolver(make_registry(chat), "sales"),
        base_url="http://litellm:4000/v1",
        api_key="test-key",
    )


def test_factory_applies_the_chat_route() -> None:
    model = make_factory(
        test_route(
            provider="openai_compatible", model="sales-chat", temperature=0.3, timeout_seconds=45
        )
    ).resolve("sales")
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "sales-chat"
    assert model.temperature == 0.3


def test_reasoning_route_uses_the_responses_api() -> None:
    """The Responses dialect carries effort inside `reasoning`, never beside it.

    `langchain_openai` folds `reasoning_effort` into `reasoning` only when
    `reasoning` is absent, so a model carrying both sends `reasoning_effort` as
    a top-level key the Responses endpoint does not accept, and sends no effort
    at all inside `reasoning`.
    """
    model = make_factory(
        test_route(
            provider="openai_responses",
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            reasoning_summary="auto",
        )
    ).resolve("sales")
    assert isinstance(model, ChatOpenAI)
    assert model.use_responses_api is True
    assert model.reasoning == {"effort": "medium", "summary": "auto"}
    assert model.reasoning_effort is None


def test_a_responses_route_without_reasoning_sends_no_reasoning_object() -> None:
    """An empty object asks the provider to reason with no effort stated."""
    model = make_factory(test_route(provider="openai_responses", model="gpt-5.6-luna")).resolve(
        "sales"
    )
    assert isinstance(model, ChatOpenAI)
    assert model.reasoning is None


def test_chat_completions_route_keeps_reasoning_effort_beside_the_request() -> None:
    """The other dialect is the mirror image: effort is its own parameter."""
    model = make_factory(
        test_route(provider="openai_compatible", model="sales-chat", reasoning_effort="low")
    ).resolve("sales")
    assert isinstance(model, ChatOpenAI)
    assert model.use_responses_api is False
    assert model.reasoning_effort == "low"
    assert model.reasoning is None


def test_profile_without_a_chat_route_fails_loudly() -> None:
    with pytest.raises(ConfigError, match="no chat route"):
        make_factory(None).resolve("sales")


def test_non_openai_compatible_provider_is_refused() -> None:
    factory = make_factory(test_route(provider="mock", model="sales-chat"))
    with pytest.raises(ConfigError, match="not OpenAI-compatible"):
        factory.resolve("sales")


def test_mock_model_replays_the_script_and_records_bound_tools() -> None:
    script = [
        AIMessage(
            content="",
            tool_calls=[{"name": "upsert_lead", "args": {"company": "Alpha"}, "id": "call_1"}],
        ),
        AIMessage(content="Đã tạo lead cho Alpha."),
    ]
    factory = MockChatModelFactory(mock_reply=MOCK_REPLY, scripts={"sales": script})
    model = factory.resolve("sales").bind_tools([upsert_lead])

    history = [HumanMessage("tạo lead cho Alpha")]
    first = model.invoke(history)
    assert first.tool_calls[0]["name"] == "upsert_lead"

    # The second model call carries the first reply, the way an agent loop does.
    second = model.invoke([*history, first, HumanMessage("xong chưa")])
    assert second.content == "Đã tạo lead cho Alpha."
    assert factory.models["sales"].bound_tool_names == ["upsert_lead"]


def test_mock_model_without_a_script_still_answers() -> None:
    reply = (
        MockChatModelFactory(mock_reply=MOCK_REPLY).resolve("sales").invoke([HumanMessage("hi")])
    )
    assert reply.content == MOCK_REPLY


def test_a_new_conversation_restarts_the_script() -> None:
    """One compiled agent holds one model for the life of the process.

    The reply due is a property of the conversation, not of how many times this
    object has been called: an instance counter gave the last scripted reply to
    every turn of every conversation after the first.
    """
    model = MockChatModel(
        responses=[AIMessage(content="một"), AIMessage(content="hai")], mock_reply="mặc định"
    )

    first = model.invoke([HumanMessage(content="chào")])
    second = model.invoke([HumanMessage(content="chào"), first, HumanMessage(content="nữa")])
    assert [first.content, second.content] == ["một", "hai"]

    # A different conversation on the same instance starts the script over.
    assert model.invoke([HumanMessage(content="hội thoại khác")]).content == "một"


def test_a_script_that_runs_out_repeats_its_last_reply() -> None:
    """An agent that loops must not crash the fake."""
    model = MockChatModel(responses=[AIMessage(content="chỉ một")], mock_reply="mặc định")
    history: list[BaseMessage] = [HumanMessage(content="chào")]
    for _ in range(3):
        reply = model.invoke(history)
        assert reply.content == "chỉ một"
        history = [*history, reply]
