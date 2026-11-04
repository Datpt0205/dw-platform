"""The prototype's compiled-agent cache: one entry per (company, version,
pinned hash), never more than 256 (agent-builder ticket 01, criterion 1;
spec R3.1, R3.2; ADR-0117 decision 5)."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from studio_agent_prototype import (
    CACHE_CAPACITY,
    AgentDocument,
    FixedRoutes,
    ProbedRunControl,
    StudioGraphSource,
    executor_over,
    register_tools,
    run_context,
)

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.errors import NotFoundError

pytestmark = pytest.mark.unit

DOC = AgentDocument.load()
TENANT_A, TENANT_B = uuid.UUID(int=0xA00), uuid.UUID(int=0xB00)


def source(*tenants: uuid.UUID, chosen: MockChatModel | None = None) -> StudioGraphSource:
    registry = ToolRegistry()
    for tenant in tenants:
        register_tools(registry, DOC, tenant_id=tenant)
    return StudioGraphSource(
        registry=registry,
        executor=executor_over(registry, ProbedRunControl([])),
        default_model=MockChatModel(responses=[], mock_reply="mặc định"),
        routes=FixedRoutes({DOC.profile_id: chosen or MockChatModel(responses=[], mock_reply="")}),
        checkpointer=InMemorySaver(),
    )


def test_two_companies_on_one_version_and_hash_hold_two_entries() -> None:
    graphs = source(TENANT_A, TENANT_B)

    first = graphs.graph(TENANT_A, DOC)
    second = graphs.graph(TENANT_B, DOC)

    assert first is not second
    assert len(graphs.compiled) == 2
    assert graphs.graph(TENANT_A, DOC) is first, "a hit compiles nothing"
    assert graphs.builds == 2


def test_one_version_under_two_pinned_hashes_holds_two_entries() -> None:
    """A draft keeps its id while it is edited; its provisional hash moves."""
    graphs = source(TENANT_A)
    edited = replace(DOC, instructions=f"{DOC.instructions} Sửa.", pinned_hash="f" * 64)

    assert graphs.graph(TENANT_A, DOC) is not graphs.graph(TENANT_A, edited)
    assert len(graphs.compiled) == 2


def test_the_257th_key_evicts_the_least_recently_used() -> None:
    graphs = source(TENANT_A, TENANT_B)
    tenants = (TENANT_A, TENANT_B)
    for n in range(CACHE_CAPACITY):
        graphs.graph(tenants[n % 2], DOC.variant(n))
    # Used again, so the oldest entry is now the second one built.
    graphs.graph(TENANT_A, DOC.variant(0))

    graphs.graph(TENANT_B, DOC.variant(CACHE_CAPACITY))

    assert len(graphs.compiled) == CACHE_CAPACITY
    held = set(graphs.compiled)
    assert (TENANT_A, DOC.variant(0).agent_version_id, DOC.variant(0).pinned_hash) in held
    assert (TENANT_B, DOC.variant(1).agent_version_id, DOC.variant(1).pinned_hash) not in held


def test_a_key_resolves_only_its_own_companys_tools() -> None:
    """The company in the key is the company whose tools are built: one with
    none registered builds nothing, never another's or the platform's."""
    graphs = source(TENANT_A)

    with pytest.raises(NotFoundError):
        graphs.graph(TENANT_B, DOC)
    assert len(graphs.compiled) == 0


async def test_a_cached_agent_answers_with_the_model_its_run_pinned() -> None:
    """Step 2 on the parent: the selection stands before the ceiling, and the
    agent's default model is never called."""
    chosen = MockChatModel(responses=[AIMessage(content="đã chọn")], mock_reply="")
    graphs = source(TENANT_A, chosen=chosen)
    agent = graphs.graph(TENANT_A, DOC)

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="lead mới hôm nay?")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
        context=run_context(TENANT_A),
    )

    assert result["messages"][-1].content == "đã chọn"
    assert len(chosen.calls) == 1
    assert isinstance(graphs.default_model, MockChatModel)
    assert graphs.default_model.calls == []
    assert len(chosen.bound_tool_names) == 10
