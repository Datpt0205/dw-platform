import uuid
from typing import Any, TypedDict, cast

import pytest
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, StateGraph

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry

pytestmark = pytest.mark.unit


class LoopState(TypedDict, total=False):
    steps: int


def looping_graph() -> Any:
    graph: StateGraph = StateGraph(LoopState)  # type: ignore[type-arg]
    graph.add_node("step", lambda state: {"steps": state.get("steps", 0) + 1})
    graph.add_edge(START, "step")
    graph.add_edge("step", "step")
    return graph.compile()


def make_run_context() -> RunContext:
    return RunContext(
        run_id=uuid.UUID(int=1),
        # A real run: its tools act (tenant-config R4.3).
        run_mode="live",
        tenant_id=uuid.UUID(int=2),
        workspace_id=uuid.UUID(int=3),
        actor_id=uuid.UUID(int=4),
        worker_id="sales_chat",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset(),
        trace_id="trace-1",
    )


def test_a_ceiling_below_the_default_actually_stops_a_run() -> None:
    with pytest.raises(GraphRecursionError):
        looping_graph().invoke({"steps": 0}, {"recursion_limit": 3})


def test_the_runner_puts_the_worker_ceiling_on_every_invocation() -> None:
    graphs = GraphRegistry()
    runner = LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=cast(Any, None),
        run_store=cast(Any, None),
        uow_factory=cast(Any, None),
        clock=cast(Any, None),
        id_generator=cast(Any, None),
        allowance=cast(Any, None),
        budget=RunBudgetLedger(),
        approval_policy=AutonomyApprovalPolicy(),
    )
    config = runner._config(make_run_context(), uuid.UUID(int=1), 7)
    assert config["recursion_limit"] == 7
