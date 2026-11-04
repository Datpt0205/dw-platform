"""`hosts` answers one question: can this process resume that exact run.

It has to consult both registries. When it asked only about the graph, a deploy
that retired a worker version let the approval guard pass, the decision commit,
and the resume then fail -- stranding a run that could no longer be decided.
"""

from pathlib import Path
from typing import Any, cast

import pytest

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML
from dw_agent_runtime.testing.run_control import OpenRunControl

pytestmark = pytest.mark.unit

WORKER = "demo_approval"
WORKER_VERSION = "1.0.0"
GRAPH_VERSION = "1.0.0"


@pytest.fixture
def runner(tmp_path: Path) -> LangGraphWorkflowRunner:
    config = tmp_path / f"{WORKER}.yaml"
    config.write_text(DEMO_WORKER_YAML, encoding="utf-8")

    graphs = GraphRegistry()
    graphs.register(WORKER, GRAPH_VERSION, cast(Any, lambda: None))
    workers = WorkerRegistry(graph_registry=graphs)
    workers.load_file(config)

    return LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=cast(Any, None),
        run_store=cast(Any, None),
        uow_factory=cast(Any, None),
        clock=cast(Any, None),
        id_generator=cast(Any, None),
        allowance=cast(Any, None),
        budget=RunBudgetLedger(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
    )


def test_a_run_whose_versions_are_both_registered_is_hosted(
    runner: LangGraphWorkflowRunner,
) -> None:
    assert (
        runner.hosts(worker_id=WORKER, worker_version=WORKER_VERSION, graph_version=GRAPH_VERSION)
        is True
    )


def test_an_unregistered_worker_is_not_hosted(runner: LangGraphWorkflowRunner) -> None:
    assert (
        runner.hosts(worker_id="other", worker_version=WORKER_VERSION, graph_version=GRAPH_VERSION)
        is False
    )


def test_an_unregistered_graph_version_is_not_hosted(runner: LangGraphWorkflowRunner) -> None:
    """A worker whose config moved on leaves older runs to a host that has them."""
    assert (
        runner.hosts(worker_id=WORKER, worker_version=WORKER_VERSION, graph_version="0.9.0")
        is False
    )


def test_a_retired_worker_version_is_not_hosted(runner: LangGraphWorkflowRunner) -> None:
    """The half that used to be missing: resume() needs this version's settings.

    The graph is still registered here, so asking only about `graph_version`
    answered yes and the caller went on to spend the approval.
    """
    assert (
        runner.hosts(worker_id=WORKER, worker_version="2.0.0", graph_version=GRAPH_VERSION) is False
    )
