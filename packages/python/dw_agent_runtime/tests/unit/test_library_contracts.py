"""Three facts about langchain and deepagents the Studio agent runtime builds on.

Measured on langchain 1.4.1 and deepagents 0.7.15 (`uv.lock`, 5/11/2026;
agent-builder ticket 01). Each is a claim about a library, so it lives here as
a test `make test-unit` runs again on every upgrade, not as a comment that
describes a past version (failure-modes #4):

(a) a middleware that swaps `request.model` in `wrap_model_call` is the only
    model called: the agent's default model receives no call at all. The
    Studio model selection (spec R3.5) is that middleware.
(b) of two middlewares, the one earlier in the list sees the model call first
    and returns last: it is the OUTER layer (M2). The model selection stands
    before the spend ceiling, so the ceiling prices the model the selection
    chose.
(c) `SubAgentMiddleware`, which builds each child on `create_agent`, refuses a
    child that declares no `tools` with `ValueError` ("must specify 'tools'");
    the child does NOT inherit its caller's tools, whatever the docstring of
    `SubAgent.tools` says about `default_tools`. A sub-agent's tools are
    therefore always what the platform hands it (`sub_agent_spec`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from dw_agent_runtime.adapters.chat_model import MockChatModel

pytestmark = pytest.mark.unit


def _model(reply: str) -> MockChatModel:
    return MockChatModel(responses=[AIMessage(content=reply)], mock_reply=reply)


class _SwapModel(AgentMiddleware[Any, Any]):
    """Hands the call to another model, as the Studio model selection does."""

    def __init__(self, chosen: MockChatModel) -> None:
        super().__init__()
        self._chosen = chosen

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(request.override(model=self._chosen))


class _Probe(AgentMiddleware[Any, Any]):
    """Writes when the model call reaches it and when the answer leaves it."""

    def __init__(self, label: str, log: list[str]) -> None:
        super().__init__()
        self._label = label
        self._log = log

    @property
    def name(self) -> str:
        # Two instances of one class in one stack need two names.
        return f"probe_{self._label}"

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        self._log.append(f"{self._label}:in")
        response = handler(request)
        self._log.append(f"{self._label}:out")
        return response


def test_a_middleware_that_swaps_the_model_leaves_the_default_uncalled() -> None:
    """(a) langchain 1.4.1: the swapped-in model takes the one call."""
    default, chosen = _model("mặc định"), _model("được chọn")
    agent = create_agent(model=default, tools=[], middleware=[_SwapModel(chosen)])

    result = agent.invoke({"messages": [HumanMessage(content="chào")]})

    assert len(default.calls) == 0, "the default model was called beside the chosen one"
    assert len(chosen.calls) == 1
    assert result["messages"][-1].content == "được chọn"


def test_the_earlier_middleware_is_the_outer_layer() -> None:
    """(b) langchain 1.4.1, M2: listed first, it sees the call first and
    returns last; the later one sits inside it, closer to the model."""
    log: list[str] = []
    agent = create_agent(
        model=_model("xong"),
        tools=[],
        middleware=[_Probe("first", log), _Probe("second", log)],
    )

    agent.invoke({"messages": [HumanMessage(content="chào")]})

    assert log == ["first:in", "second:in", "second:out", "first:out"]


def test_a_sub_agent_without_tools_is_refused_not_given_its_callers() -> None:
    """(c) deepagents 0.7.15: a child that declares no `tools` is a
    `ValueError` at build time; it never runs with the caller's tools."""
    from deepagents import SubAgent, SubAgentMiddleware
    from deepagents.backends import StateBackend

    child: SubAgent = {
        "name": "researcher",
        "description": "Tra cứu hồ sơ",
        "model": _model("con"),
    }

    with pytest.raises(ValueError, match="must specify 'tools'"):
        SubAgentMiddleware(backend=StateBackend(), subagents=[child])
