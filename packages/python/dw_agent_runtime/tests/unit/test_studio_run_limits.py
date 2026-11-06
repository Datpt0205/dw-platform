"""A spent limit stops a Studio run cleanly (usage-and-limits/04: R6.3, UL13;
ADR-0121 decision 6).

Through `run_studio`, the call the `studio_runs` lane makes: a step whose door
meets `LimitExceededError` ends the run `failed` `limit_exceeded`, is tried
once whatever its `retry`, never handed to its `on_error`, the step after it
never runs, and the lane audits `run.limit_stopped` as itself. The door is an
internal one (`records`), whose ordinary failure the wrapper would retry and
route: exactly what a spent limit must not be.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_studio_runner import FakeTake, go, harness, studio_run

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
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
from dw_agent_runtime.wflite.node_wrapper import StudioRunPorts
from dw_kernel.limits import LimitExceededError
from dw_kernel.ports import Uuid4Generator
from dw_platform.domain.audit import AuditEvent, system_actor

pytestmark = pytest.mark.unit


@dataclass
class _Audit:
    events: list[AuditEvent] = field(default_factory=list)

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class _Uow:
    audit: _Audit

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def _runner(h: StudioHarness, store: FakeTake, audit: _Audit) -> LangGraphWorkflowRunner:
    h.runs = cast(Any, store)
    graphs = GraphRegistry()
    return LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=cast(Any, InMemorySaver()),
        run_store=cast(Any, None),
        uow_factory=cast(Any, lambda context: _Uow(audit)),
        clock=h.clock,
        id_generator=Uuid4Generator(),
        limits=OpenLimits(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
        studio=StudioRunPorts(
            nodes=h.ports(),
            registry=fixture_node_registry(),
            binding_review=FakeBindingReview(),
            alerts=RecordingAlerts(),
            expressions=NoExpressions(),
        ),
    )


_SPENT = LimitExceededError(
    "spent", metric="cost_usd", scope_type="tenant", window="month", limit=10, used=10
)


def _two_steps(*, on_error: str = "fail", attempts: int = 1) -> dict[str, Any]:
    return document(
        step(
            "sua",
            "fixture.records@1",
            object="mkt_lead",
            command="update",
            on_error=on_error,
            attempts=attempts,
        ),
        step("gui", "fixture.effect@1"),
    )


async def _stopped(*, on_error: str = "fail", attempts: int = 1) -> tuple[Any, ...]:
    h, sends = harness()
    records = ScriptedDoor([_SPENT, {"record": {}, "replayed": False}])
    h.doors["records"] = records
    store, audit = (
        FakeTake(studio_run(_two_steps(on_error=on_error, attempts=attempts), h)),
        _Audit(),
    )
    status = await go(_runner(h, store, audit))
    return status, store, audit, records, sends


async def test_a_step_that_would_continue_ends_the_run_at_a_spent_limit() -> None:
    """R6.3: `on_error: continue` is not applied to a spent limit; the run is
    `failed` `limit_exceeded` with its metric, and the next step never runs.
    Let `LimitExceededError` fall to `classify` and the run goes on."""
    status, store, _, records, sends = await _stopped(on_error="continue")

    assert status == RunStatus.FAILED
    ((state, error),) = store.finished
    assert state == "failed"
    assert error is not None
    assert (error["code"], error["metric"]) == ("limit_exceeded", "cost_usd")
    assert len(records.calls) == 1
    assert sends.calls == []


async def test_a_step_with_retries_is_tried_once_at_a_spent_limit() -> None:
    """R6.3: `retry: {max_attempts: 3}` gives a spent limit no second attempt."""
    status, _, _, records, _ = await _stopped(attempts=3)

    assert status == RunStatus.FAILED
    assert len(records.calls) == 1


async def test_the_lane_audits_the_stop_as_itself_with_the_metric_and_scope() -> None:
    """Step 2 (gate 4/11/2026 (c)): `run.limit_stopped` by `system:studio_runs`,
    the lane that ran the run, never a person."""
    _, _, audit, _, _ = await _stopped(on_error="route")

    (event,) = [e for e in audit.events if e.action == "run.limit_stopped"]
    assert event.actor_id == system_actor("studio_runs")
    assert event.details["actor"] == "system:studio_runs"
    assert (event.details["metric"], event.details["scope_type"]) == ("cost_usd", "tenant")
    assert event.details["reason_code"] == "limit_exceeded"
    assert isinstance(event.run_id, uuid.UUID)


# ---- the old inline path: the run's actor, as its end audit -------------------


@dataclass
class _Rows:
    statuses: list[tuple[Any, dict[str, Any] | None]] = field(default_factory=list)

    async def set_status(
        self, run_context: Any, run_id: uuid.UUID, status: Any, *, error: Any = None
    ) -> None:
        self.statuses.append((status, error))

    async def tree_running(self, *args: Any, **kwargs: Any) -> bool:
        return False


async def test_on_the_inline_path_the_stop_is_audited_in_the_runs_actors_name() -> None:
    """Gate 4/11/2026 (d): where no lane runs the run, `run.limit_stopped` names
    the run's actor, as the path's `run.failed` does, with the reason code."""
    from test_langchain_tools import make_run_context

    audit = _Audit()
    graphs = GraphRegistry()
    runner = LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=cast(Any, InMemorySaver()),
        run_store=cast(Any, _Rows()),
        uow_factory=cast(Any, lambda context: _Uow(audit)),
        clock=StudioHarness(fixture_node_registry()).clock,
        id_generator=Uuid4Generator(),
        limits=OpenLimits(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
    )
    run = make_run_context()

    await runner._fail(run, run.run_id, _SPENT)

    actions = [event.action for event in audit.events]
    assert actions == ["run.failed", "run.limit_stopped"]
    stopped = audit.events[1]
    assert stopped.actor_id.value == run.actor_id
    assert stopped.details == {
        "reason_code": "limit_exceeded",
        "metric": "cost_usd",
        "scope_type": "tenant",
    }
