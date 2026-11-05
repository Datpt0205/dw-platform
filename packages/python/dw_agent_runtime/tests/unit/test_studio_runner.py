"""`LangGraphWorkflowRunner.run_studio` and the one graph cache
(workflow-engine/03: R4.1, R4.2, R4.24, R4.25, R6.14; WE39).

The run store is a fake that hands out a `StudioRun` the way
`SqlStudioRunStore.take` reads it; the row, the manifest and the boundary
against PostgreSQL are `dw_studio/tests/integration/test_studio_runs.py`'s.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from dw_agent_runtime.adapters import langgraph_runner
from dw_agent_runtime.adapters.langgraph_runner import GRAPH_CACHE_SIZE, LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.dispatch import OutcomeUnknownError
from dw_agent_runtime.ports import StudioRun, StudioRunBlocked
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.run_control import HaltReason, RunControlDoor
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.studio_runs import (
    FakeBindingReview,
    NoExpressions,
    RecordingAlerts,
    ScriptedDoor,
    StudioHarness,
    document,
    step,
)
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.compile import COMPILER_VERSION
from dw_agent_runtime.wflite.node_wrapper import StudioRunPorts
from dw_kernel.residency import ResidencyRefusedError

pytestmark = pytest.mark.unit


TOKEN = "worker-1:claim"


@dataclass
class FakeTake:
    """`StudioRunStorePort` whose `take` hands out one prepared run, as the
    claim under `TOKEN` reads it."""

    taken: StudioRun | StudioRunBlocked
    finished: list[tuple[str, Mapping[str, Any] | None]] = field(default_factory=list)
    cancelled: list[uuid.UUID] = field(default_factory=list)
    outcomes: list[list[str]] = field(default_factory=list)
    held: list[tuple[timedelta, datetime | None]] = field(default_factory=list)
    deadlines: list[datetime] = field(default_factory=list)

    async def take(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> StudioRun | StudioRunBlocked:
        assert lease_token == TOKEN
        return self.taken

    async def admitted(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str, deadline: timedelta
    ) -> datetime:
        assert isinstance(self.taken, StudioRun)
        found = self.taken.deadline_at or datetime.now(UTC) + deadline
        self.deadlines.append(found)
        return found

    async def hold(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        lease_token: str,
        delay: timedelta,
        until: datetime | None = None,
    ) -> None:
        self.held.append((delay, until))

    async def finish(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        status: Any,
        *,
        lease_token: str,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
    ) -> None:
        assert lease_token == TOKEN
        self.finished.append((status, error))
        self.outcomes.append(list(outcomes))

    async def cancel_past_deadline(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> bool:
        self.cancelled.append(run_id)
        return True


def studio_run(doc: Mapping[str, Any], harness: StudioHarness, **over: Any) -> StudioRun:
    run_id = uuid.uuid4()
    base = StudioRun(
        run_id=run_id,
        thread_id=run_id,
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        artifact_kind="workflow",
        artifact_id=uuid.uuid4(),
        artifact_version_id=uuid.uuid4(),
        pinned_hash="sha256:" + "c" * 64,
        run_mode="live",
        requested_by=uuid.uuid4(),
        run_as_principal_id=uuid.uuid4(),
        run_manifest_hash="sha256:" + "e" * 64,
        plan_id="professional",
        deadline_at=harness.clock.now() + timedelta(hours=1),
        input={},
        pinned_results=None,
        document=doc,
        engine={"durability": "sync"},
        version_no=1,
        trace_id="t",
        trigger_kind="manual",
    )
    return replace(base, **over)


async def go(runner: LangGraphWorkflowRunner) -> RunStatus:
    """The run, as the `studio_runs` lane hands it over under its claim."""
    return await runner.run_studio(tenant_id=uuid.uuid4(), run_id=uuid.uuid4(), lease_token=TOKEN)


def runner_of(harness: StudioHarness, store: FakeTake) -> LangGraphWorkflowRunner:
    harness.runs = cast(Any, store)
    graphs = GraphRegistry()
    return LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=cast(Any, InMemorySaver()),
        run_store=cast(Any, None),
        uow_factory=cast(Any, None),
        clock=harness.clock,
        id_generator=cast(Any, None),
        limits=OpenLimits(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
        studio=StudioRunPorts(
            nodes=harness.ports(),
            registry=fixture_node_registry(),
            binding_review=FakeBindingReview(),
            alerts=RecordingAlerts(),
            expressions=NoExpressions(),
        ),
    )


def two_sends() -> dict[str, Any]:
    return document(step("mot", "fixture.effect@1"), step("hai", "fixture.effect@1"))


def harness() -> tuple[StudioHarness, ScriptedDoor]:
    h = StudioHarness(fixture_node_registry())
    door = ScriptedDoor()
    h.doors["tool"] = door
    return h, door


class Spy:
    """A compiled graph that records how it is invoked."""

    def __init__(self, nxt: tuple[str, ...] = ()) -> None:
        self.nodes = {"a": None, "b": None}
        self.next = nxt
        self.invoked: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return SimpleNamespace(next=self.next, values={})

    async def ainvoke(self, payload: Any, config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.invoked.append((payload, config, kwargs))
        return {}


# ---- R4.25, R4.1: what every invocation carries ------------------------------------


@pytest.mark.parametrize("durability", ["sync", "async"])
async def test_the_run_takes_its_durability_from_the_manifests_engine(durability: str) -> None:
    h, _ = harness()
    store = FakeTake(studio_run(two_sends(), h, engine={"durability": durability}))
    runner = runner_of(h, store)
    spy = Spy()
    runner._compiled[runner_key(store.taken)] = spy
    assert await go(runner) == RunStatus.COMPLETED
    ((payload, config, kwargs),) = spy.invoked
    assert kwargs["durability"] == durability
    assert config["recursion_limit"] == len(spy.nodes) + 1
    assert payload == {"work": {}}


def runner_key(taken: Any) -> tuple[str, ...]:
    return (
        "studio",
        str(taken.tenant_id),
        str(taken.artifact_version_id),
        taken.pinned_hash,
        COMPILER_VERSION,
    )


async def test_a_manifest_without_its_durability_runs_nothing() -> None:
    h, door = harness()
    store = FakeTake(studio_run(two_sends(), h, engine={}))
    status = await go(runner_of(h, store))
    assert status == RunStatus.FAILED
    assert store.finished == [("failed", {"code": "engine_unpinned"})]
    assert door.calls == []


async def test_a_run_with_a_checkpoint_goes_on_from_it() -> None:
    """Taken again after a crash: `None`, never the input a second time."""
    h, _ = harness()
    store = FakeTake(studio_run(two_sends(), h))
    runner = runner_of(h, store)
    spy = Spy(nxt=("hai",))
    runner._compiled[runner_key(store.taken)] = spy
    await go(runner)
    assert spy.invoked[0][0] is None


# ---- outcomes ---------------------------------------------------------------------


async def test_a_run_that_completes_is_recorded_completed() -> None:
    h, door = harness()
    store = FakeTake(studio_run(two_sends(), h))
    status = await go(runner_of(h, store))
    assert status == RunStatus.COMPLETED and len(door.calls) == 2
    assert store.finished == [("completed", None)]


async def test_outcome_unknown_fails_the_run_before_workflow_engine_08() -> None:
    """R4.24: `failed` with `outcome_unknown`, never `dead_lettered`, so the
    reaper never takes it again; never `completed`."""
    h, door = harness()
    door.script = [OutcomeUnknownError("may have been applied")]
    store = FakeTake(studio_run(two_sends(), h))
    status = await go(runner_of(h, store))
    assert status == RunStatus.FAILED
    assert store.finished == [("failed", {"code": "outcome_unknown", "step_id": "mot"})]


async def test_a_blocked_take_compiles_nothing() -> None:
    h, door = harness()
    store = FakeTake(StudioRunBlocked(uuid.uuid4(), "incompatible_resume"))
    runner = runner_of(h, store)
    assert await go(runner) == RunStatus.BLOCKED
    assert runner._compiled == {} and door.calls == [] and store.finished == []


async def test_past_the_deadline_the_run_is_cancelled_by_the_store_alone() -> None:
    h, door = harness()
    store = FakeTake(studio_run(two_sends(), h, deadline_at=h.clock.now()))
    status = await go(runner_of(h, store))
    assert status == RunStatus.CANCELLED
    assert len(store.cancelled) == 1 and store.finished == [] and door.calls == []


async def test_a_runner_with_no_studio_ports_refuses() -> None:
    h, _ = harness()
    runner = runner_of(h, FakeTake(studio_run(two_sends(), h)))
    runner.studio = None
    with pytest.raises(Exception, match="no Studio run"):
        await go(runner)


# ---- R4.2: one LRU of 256 for every graph -----------------------------------------


def _graph_factory() -> StateGraph:  # type: ignore[type-arg]
    graph: StateGraph = StateGraph(dict)  # type: ignore[type-arg]

    async def noop(state: Any) -> dict[str, Any]:
        return {}

    graph.add_node("a", noop)
    graph.add_edge(START, "a")
    graph.add_edge("a", END)
    return graph


def test_three_hundred_graphs_keep_at_most_256_code_and_studio_alike() -> None:
    h, _ = harness()
    runner = runner_of(h, FakeTake(studio_run(two_sends(), h)))
    for n in range(150):
        runner.graph_registry.register(f"code_{n}", "1.0.0", _graph_factory)
        runner._graph(f"code_{n}", "1.0.0")
    for n in range(150):
        runner._studio_graph(
            cast(StudioRunPorts, runner.studio),
            studio_run(two_sends(), h, artifact_version_id=uuid.UUID(int=n)),
        )
    assert len(runner._compiled) == GRAPH_CACHE_SIZE
    # The least recently used went first: the oldest code graphs.
    assert ("code_0", "1.0.0") not in runner._compiled
    assert any(key[0] == "studio" for key in runner._compiled)
    assert any(key[0].startswith("code_") for key in runner._compiled)


def test_the_studio_key_is_tenant_version_pinned_hash_and_compiler_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h, _ = harness()
    runner = runner_of(h, FakeTake(studio_run(two_sends(), h)))
    ports = cast(StudioRunPorts, runner.studio)
    taken = studio_run(two_sends(), h)
    first = runner._studio_graph(ports, taken)
    assert runner._studio_graph(ports, taken) is first
    # Another tenant's run of a version with the same id is another graph.
    assert runner._studio_graph(ports, replace(taken, tenant_id=uuid.uuid4())) is not first
    monkeypatch.setattr(langgraph_runner, "COMPILER_VERSION", "2")
    assert runner._studio_graph(ports, taken) is not first


def test_an_edited_draft_compiles_again_from_its_new_content() -> None:
    """A draft keeps its id and changes its pinned hash: the new run's graph
    is the new content's, never the cached old one."""
    h, _ = harness()
    runner = runner_of(h, FakeTake(studio_run(two_sends(), h)))
    ports = cast(StudioRunPorts, runner.studio)
    old = studio_run(two_sends(), h, version_no=None)
    old_graph = runner._studio_graph(ports, old)
    edited = replace(
        old,
        pinned_hash="sha256:" + "f" * 64,
        document=document(step("ba", "fixture.effect@1")),
    )
    new_graph = runner._studio_graph(ports, edited)
    assert new_graph is not old_graph
    assert "ba" in new_graph.nodes and "ba" not in old_graph.nodes


# ---- agent-lifecycle 05: the run's own component at its node head ------------------


async def test_every_node_head_asks_with_the_component_the_run_was_taken_for() -> None:
    """agent-lifecycle R8.1: the context each node head hands the port names
    the run's own component, from its row, and the node names no other, so a
    kill of it refuses the run without the node naming it."""
    h, _ = harness()
    store = FakeTake(studio_run(two_sends(), h))
    await go(runner_of(h, store))
    assert isinstance(store.taken, StudioRun)
    asked = [(c.artifact_id, c.run_mode, extra) for c, extra in h.run_control.contexts]
    assert asked == [(store.taken.artifact_id, "live", ())] * 2


async def test_a_kill_at_the_node_head_cancels_the_run_before_any_door() -> None:
    """agent-lifecycle R8.1: `cancelled` with `artifact_killed` and the door,
    no send."""
    h, door = harness()
    h.run_control.refuse(HaltReason.ARTIFACT_KILLED, doors=[RunControlDoor.NODE])
    store = FakeTake(studio_run(two_sends(), h))
    status = await go(runner_of(h, store))
    assert status == RunStatus.CANCELLED
    assert store.finished == [("cancelled", {"code": "artifact_killed", "door": "node"})]
    assert door.calls == []


# ---- compliance-pdpl 03: the data route ---------------------------------------------


async def test_a_studio_run_carries_the_class_its_row_pinned() -> None:
    """R2.1: read from the row at the take, never computed again."""
    h, _ = harness()
    store = FakeTake(studio_run(two_sends(), h, data_route_class="cross_border_minimised"))
    await go(runner_of(h, store))
    assert {c.route_class for c, _ in h.run_control.contexts} == {"cross_border_minimised"}


async def test_a_residency_refusal_fails_the_run_and_is_never_retried_or_routed() -> None:
    """R2.2: `failed` with `residency_refused`, one attempt, no later step: a
    policy answer is not a step's error for its retry or its error lane."""
    h, door = harness()
    door.script = [ResidencyRefusedError("not here")]
    store = FakeTake(studio_run(two_sends(), h))
    status = await go(runner_of(h, store))
    assert status == RunStatus.FAILED
    assert store.finished == [("failed", {"code": "residency_refused"})]
    assert len(door.calls) == 1
