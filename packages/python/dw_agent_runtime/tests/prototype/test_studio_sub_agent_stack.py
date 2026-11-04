"""A delegated turn passes the child's own run control and model selection
(agent-builder ticket 01, criterion 3; ADR-0117 decision 7).

The parent's middleware does not wrap a child's model call
(`adapters/sub_agents.py`), so each probe below has to be in the child's own
stack to see it. The parent's ledger reaching the child is already pinned by
`tests/unit/test_sub_agents.py::test_a_sub_agent_spends_against_its_callers_ledger`.

Built on the code-defined path (`offered`, tools at the platform layer): a
Studio agent's `pinned` spec refuses sub-agents today (`offered_definitions`),
which ticket 03 has to open.
"""

from __future__ import annotations

import uuid

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from studio_agent_prototype import (
    COPY,
    FRAME,
    FRAME_ID,
    FRAME_VERSION,
    AgentDocument,
    FixedRoutes,
    LoggedModel,
    ProbedRunControl,
    StudioModelSelection,
    before_the_ceiling,
    definition_of,
    executor_over,
    profiles_for,
    register_tools,
    run_context,
    studio_sub_agents,
)

from dw_agent_runtime.adapters.agent_factory import AgentSpec, platform_middleware
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.langchain_tools import platform_tools
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec
from dw_agent_runtime.contracts import RunContext, model_facing_name
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.tools import ToolRegistry

pytestmark = pytest.mark.unit

DOC = AgentDocument.load()
TENANT = uuid.UUID(int=0xA00)
PARENT, CHILD = DOC.profile_id, DOC.sub_agent.profile_id


def _call(name: str, args: dict[str, str], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


async def test_a_child_turn_passes_its_own_run_control_and_model_selection() -> None:
    log: list[str] = []
    registry = ToolRegistry()
    register_tools(registry, DOC, tenant_id=None)
    executor = executor_over(registry, ProbedRunControl(log))
    prompts = PromptRegistry()
    prompts.register(FRAME)
    offered = tuple(definition_of(tool) for tool in DOC.tools)
    parent_default = MockChatModel(responses=[], mock_reply="cha mặc định")
    child_default = MockChatModel(responses=[], mock_reply="con mặc định")
    parent_model = LoggedModel(
        label="parent",
        log=log,
        mock_reply="",
        responses=[
            _call("task", {"description": "tra lead L-1", "subagent_type": "researcher"}, "c1"),
            AIMessage(content="cha xong"),
        ],
    )
    child_model = LoggedModel(
        label="child",
        log=log,
        mock_reply="",
        responses=[
            _call(model_facing_name("lead.get"), {"record_id": "L-1"}, "c2"),
            AIMessage(content="con xong"),
        ],
    )
    spec = AgentSpec(
        model=parent_default,
        offered=offered,
        registry=registry,
        executor=executor,
        copy=COPY,
        approval_type_prefix="studio.agent.",
        prompt_id=FRAME_ID,
        prompt_version=FRAME_VERSION,
        prompts=prompts,
        prompt_variables=lambda request: {"instructions": DOC.instructions},
        budget=RunBudgetLedger(),
        pricing=FlatPricing(),
        profiles=profiles_for(DOC),
        profile_id=PARENT,
    )
    child = SubAgentSpec(
        name=DOC.sub_agent.name,
        description=DOC.sub_agent.description,
        offered=tuple(d for d in offered if d.name in DOC.sub_agent.tools),
        model=child_default,
        profile_id=CHILD,
    )
    routes = FixedRoutes({PARENT: parent_model, CHILD: child_model})
    agent = create_agent(
        model=spec.model,
        tools=platform_tools(
            offered, registry, executor, approval_type_prefix="studio.agent.", copy=COPY
        ),
        middleware=[
            *before_the_ceiling(
                platform_middleware(spec), StudioModelSelection(routes, PARENT, log=log)
            ),
            studio_sub_agents(spec, child, StudioModelSelection(routes, CHILD, log=log)),
        ],
        context_schema=RunContext,
        checkpointer=InMemorySaver(),
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="lead L-1 thế nào?")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
        context=run_context(TENANT),
    )

    assert result["messages"][-1].content == "cha xong"
    child_calls = [i for i, entry in enumerate(log) if entry == "model:child"]
    assert len(child_calls) == 2, log
    for at in child_calls:
        assert log[at - 2 : at] == ["run_control", f"selection:{CHILD}"], log
    assert child_default.calls == [], "the child's default model answered a delegated turn"
    assert parent_default.calls == []
    assert log.count("model:parent") == 2
