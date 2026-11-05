"""A Studio run's graph in memory, for the tests of the node wrapper and the
golden traces (workflow-engine/03).

- `ScriptedDoor` is a `StepDoor` that answers from a script, one entry per
  call (an output, or an exception to raise), and records every `DoorCall`;
  `hangs` makes a call sleep past any timeout, `sends` counts what reached the
  provider (a call whose script entry is an output or `OutcomeUnknownError`);
- `FakeClaims` answers `has_unresolved_dispatch` by key, as the dispatch log
  would after a send that never closed;
- `FakeStudioRuns` records what the wrapper asks of the run store;
- `ManualClock` is a clock a test moves;
- `StudioHarness` compiles a document with the Studio wrapper over these, on
  an in-memory saver, and runs it; `langgraph_trace` runs one golden case
  (`dw_studio.workflows.testing.golden`) on it.

None of them is wired into the API or the worker.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.dispatch import OutcomeUnknownError
from dw_agent_runtime.ports import BindingHold, StudioRun
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.step_recorder import FakeStepRecorder
from dw_agent_runtime.wflite.compile import StudioWorkflow, compile_workflow
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.doors import DoorCall, EffectDoor, StepDoor
from dw_agent_runtime.wflite.node_wrapper import (
    StudioNodePorts,
    StudioRunContext,
    StudioRunFailedError,
)
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_kernel.expressions import ExpressionEnv
from dw_kernel.run_mode import RunMode
from dw_observability.telemetry import RecordingTelemetry

Answer = Mapping[str, Any] | BaseException


@dataclass
class ScriptedDoor:
    """Answers each call with the next script entry; the last one repeats."""

    script: list[Answer] = field(default_factory=lambda: [{"done": True}])
    calls: list[DoorCall] = field(default_factory=list)
    hangs: bool = False
    sends: int = 0

    async def __call__(self, call: DoorCall) -> Mapping[str, Any]:
        self.calls.append(call)
        answer = self.script[min(len(self.calls), len(self.script)) - 1]
        if self.hangs:
            self.sends += 1
            await asyncio.sleep(3600)
        if isinstance(answer, BaseException):
            if isinstance(answer, OutcomeUnknownError):
                self.sends += 1
            raise answer
        self.sends += 1
        return answer

    @property
    def keys(self) -> list[str]:
        return [call.idempotency_key for call in self.calls]


@dataclass
class FakeClaims:
    unresolved: set[str] = field(default_factory=set)
    asked: list[tuple[str, str]] = field(default_factory=list)

    async def claim(self, *args: Any, **kwargs: Any) -> uuid.UUID | None:
        raise NotImplementedError("not exercised by the node wrapper")

    async def release(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("not exercised by the node wrapper")

    async def dispatch(self, *args: Any, **kwargs: Any) -> bool:
        raise NotImplementedError("not exercised by the node wrapper")

    async def has_unresolved_dispatch(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> bool:
        self.asked.append((tool_name, idempotency_key))
        return idempotency_key in self.unresolved


@dataclass
class FakeStudioRuns:
    cancelled: list[uuid.UUID] = field(default_factory=list)
    finished: list[tuple[uuid.UUID, str, Mapping[str, Any] | None]] = field(default_factory=list)

    async def take(self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str) -> Any:
        raise NotImplementedError("not exercised by the node wrapper")

    async def admitted(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str, deadline: timedelta
    ) -> datetime:
        raise NotImplementedError("not exercised by the node wrapper")

    async def hold(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        lease_token: str,
        delay: timedelta,
        until: datetime | None = None,
    ) -> None:
        raise NotImplementedError("not exercised by the node wrapper")

    async def finish(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        status: Literal["completed", "failed", "cancelled"],
        *,
        lease_token: str,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
    ) -> None:
        self.finished.append((run_id, status, error))

    async def cancel_past_deadline(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> bool:
        self.cancelled.append(run_id)
        return True


@dataclass
class FakeBindingReview:
    """`BindingReviewPort` by its contract: a hold for each principal named in
    `holds` (its `grants_changed_at`), None for every other run; `fails`
    raises as a broken port would. Records each run asked about."""

    holds: dict[uuid.UUID, datetime] = field(default_factory=dict)
    fails: bool = False
    asked: list[uuid.UUID] = field(default_factory=list)

    async def review(self, run: StudioRun) -> BindingHold | None:
        self.asked.append(run.run_id)
        if self.fails:
            raise ConnectionError("the binding review could not be read")
        at = self.holds.get(run.run_as_principal_id)
        return None if at is None else BindingHold(at)


@dataclass
class RecordingAlerts:
    """`HeldRunAlertPort` that records what it was asked to tell."""

    told: list[tuple[str, uuid.UUID, uuid.UUID]] = field(default_factory=list)

    async def principal_inactive(
        self, tenant_id: uuid.UUID, *, workspace_id: uuid.UUID, principal_id: uuid.UUID
    ) -> None:
        self.told.append(("principal_inactive", tenant_id, principal_id))

    async def binding_needs_review(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        artifact_id: uuid.UUID,
        principal_id: uuid.UUID,
        grants_changed_at: datetime,
    ) -> None:
        self.told.append(("binding_needs_review", tenant_id, principal_id))


class NoExpressions:
    """An `ExpressionEngine` for a runner whose documents name no
    `outcomes[]`: asked anything, it says so."""

    def check(self, source: str, env: ExpressionEnv) -> Any:
        raise NotImplementedError("not exercised: the document has no outcomes")

    async def evaluate(self, checked: Any, activation: Mapping[str, object]) -> Any:
        raise NotImplementedError("not exercised: the document has no outcomes")


@dataclass
class ManualClock:
    at: datetime = field(default_factory=lambda: datetime(2026, 11, 5, 9, tzinfo=UTC))

    def now(self) -> datetime:
        return self.at


def studio_run_context(
    *,
    run_mode: RunMode = "live",
    tenant_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> RunContext:
    return RunContext(
        run_id=run_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="studio:workflow:test",
        worker_version="1.0.0",
        channel="studio",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
        run_mode=run_mode,
        run_manifest_hash="sha256:" + "a" * 64,
    )


@dataclass
class StudioHarness:
    registry: Mapping[str, NodeTypeSpec]
    doors: dict[EffectDoor, StepDoor] = field(default_factory=dict)
    claims: FakeClaims = field(default_factory=FakeClaims)
    run_control: OpenRunControl = field(default_factory=OpenRunControl)
    runs: FakeStudioRuns = field(default_factory=FakeStudioRuns)
    recorder: FakeStepRecorder = field(default_factory=FakeStepRecorder)
    telemetry: RecordingTelemetry = field(default_factory=RecordingTelemetry)
    clock: ManualClock = field(default_factory=ManualClock)
    retryable: frozenset[str] = frozenset()
    slept: list[float] = field(default_factory=list)
    compiled: int = 0

    async def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    def ports(self) -> StudioNodePorts:
        retryable = self.retryable
        return StudioNodePorts(
            doors=self.doors,
            claims=self.claims,
            run_control=self.run_control,
            runs=self.runs,
            recorder=self.recorder,
            telemetry=self.telemetry,
            clock=self.clock,
            retryable_rejections=lambda step: retryable,
            sleep=self._sleep,
        )

    def compile(
        self, document: Mapping[str, Any], *, saver: BaseCheckpointSaver[Any] | None = None
    ) -> Any:
        self.compiled += 1
        workflow = StudioWorkflow(
            WorkflowDocument.model_validate(document), "sha256:" + "b" * 64, self.registry
        )
        return compile_workflow(workflow, self.ports()).compile(
            checkpointer=saver if saver is not None else InMemorySaver()
        )

    def context(
        self,
        run: RunContext,
        *,
        pinned_results: Mapping[str, Any] | None = None,
        approval_decisions: Mapping[str, str] | None = None,
        deadline_at: datetime | None = None,
    ) -> StudioRunContext:
        return StudioRunContext(
            run=run,
            deadline_at=deadline_at or self.clock.now() + timedelta(hours=1),
            pinned_results=pinned_results,
            approval_decisions=dict(approval_decisions or {}),
        )

    async def run(
        self,
        document: Mapping[str, Any] | Any,
        *,
        run: RunContext | None = None,
        work: Mapping[str, Any] | None = None,
        graph: Any = None,
        durability: Literal["sync", "async", "exit"] = "sync",
        resume: bool = False,
        **context: Any,
    ) -> dict[str, Any]:
        run = run or studio_run_context()
        graph = graph if graph is not None else self.compile(document)
        config = {
            "recursion_limit": len(graph.nodes) + 2,
            "configurable": {"thread_id": str(run.run_id)},
        }
        payload = None if resume else {"work": dict(work or {})}
        result: dict[str, Any] = await graph.ainvoke(
            payload, config, context=self.context(run, **context), durability=durability
        )
        return result


def trail_of(state: Mapping[str, Any]) -> list[str]:
    return [str(entry["step_id"]) for entry in state.get("trail") or []]


def step(
    step_id: str, type_: str, *, on_error: str = "fail", attempts: int = 1, **config: Any
) -> dict[str, Any]:
    """A Studio step with its policy; `config` as given."""
    return {
        "id": step_id,
        "type": type_,
        "config": dict(config),
        "retry": {"max_attempts": attempts, "backoff": "fixed"},
        "timeout_s": 30,
        "on_error": on_error,
    }


def document(*steps: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "dw.workflow/v1",
        "triggers": [{"id": "khi_chay", "type": "fixture.trigger@1", "config": {"source": "x"}}],
        "steps": list(steps),
    }


def with_error_lane(
    step_doc: dict[str, Any], lane: Sequence[Mapping[str, Any]] | None
) -> dict[str, Any]:
    return {**step_doc, "error_lane": None if lane is None else list(lane)}


async def langgraph_trace(
    document: Mapping[str, Any],
    registry: Mapping[str, NodeTypeSpec],
    *,
    tool_script: Sequence[Answer],
    approval_decisions: Mapping[str, str],
    run_mode: RunMode,
    work: Mapping[str, Any],
) -> tuple[tuple[str, ...], str | None]:
    """A document's trace on LangGraph through `compile_workflow`, the compiler
    `LangGraphWorkflowRunner` caches and runs, with `durability` `sync`: the
    nodes run (joins included) and the run's failure code, or None. The golden
    traces' runner on this implementation (workflow-engine R7.1)."""
    harness = StudioHarness(registry)
    harness.doors["tool"] = ScriptedDoor(list(tool_script))
    graph = harness.compile(document)
    run = studio_run_context(run_mode=run_mode)
    try:
        state = await harness.run(
            document, run=run, graph=graph, work=work, approval_decisions=approval_decisions
        )
    except StudioRunFailedError as failed:
        snapshot = await graph.aget_state({"configurable": {"thread_id": str(run.run_id)}})
        return tuple(trail_of(snapshot.values)), failed.code
    return tuple(trail_of(state)), None
