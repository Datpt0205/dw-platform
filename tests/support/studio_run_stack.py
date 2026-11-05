"""A runner of Studio runs over PostgreSQL, for `dw_studio`'s
`test_studio_runs.py` and the child process it kills (`studio_run_child.py`
beside it): the real `SqlStudioRunStore`,
the real checkpoint saver, `LangGraphWorkflowRunner.run_studio`, and doors that
keep what they did in a JSON file, so what a dead process sent is still there
for the one that takes the run again.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.ports import RunControlPort
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.step_recorder import FakeStepRecorder
from dw_agent_runtime.testing.studio_runs import FakeClaims
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.doors import DoorCall, EffectDoor, StepDoor
from dw_agent_runtime.wflite.node_wrapper import StudioNodePorts, StudioRunPorts
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_observability.telemetry import RecordingTelemetry
from dw_studio.core.adapters.studio_runs import SqlStudioRunStore

DIED = 37


@dataclass
class FileDoor:
    """A door whose sends survive the process: each call and each applied
    key in `path`, written before the door answers. `die_after` names a step
    whose send ends the process at once once applied (K3)."""

    path: Path
    die_after: str | None = None

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"calls": [], "applied": {}}
        loaded: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return loaded

    def _save(self, data: dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())

    async def __call__(self, call: DoorCall) -> Mapping[str, Any]:
        data = self._load()
        data["calls"].append([call.door, call.idempotency_key, call.run_mode])
        held = data["applied"].get(call.idempotency_key)
        if held is not None:
            self._save(data)
            return {**held, "replayed": True}
        answer = {"done": True} if call.door == "tool" else {"record": {}, "replayed": False}
        data["applied"][call.idempotency_key] = answer
        self._save(data)
        if self.die_after is not None and call.idempotency_key.split(":")[2] == self.die_after:
            os._exit(DIED)
        return answer

    def calls(self) -> list[list[str]]:
        found: list[list[str]] = self._load()["calls"]
        return found


def build_runner(
    sessions: async_sessionmaker[AsyncSession],
    doors: Mapping[EffectDoor, StepDoor],
    *,
    run_control: RunControlPort | None = None,
) -> tuple[LangGraphWorkflowRunner, FakeStepRecorder]:
    """`run_control` is the node head's (agent-lifecycle 05 passes a real
    `SqlRunControl`); open by default."""
    clock, ids = SystemClock(), Uuid7Generator()
    graphs = GraphRegistry()
    recorder = FakeStepRecorder()
    nodes = StudioNodePorts(
        doors=dict(doors),
        claims=FakeClaims(),
        run_control=run_control or OpenRunControl(),
        runs=SqlStudioRunStore(sessions, ids, clock),
        recorder=recorder,
        telemetry=RecordingTelemetry(),
        clock=clock,
    )
    runner = LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
        run_store=cast(Any, None),
        uow_factory=cast(Any, None),
        clock=clock,
        id_generator=ids,
        allowance=cast(Any, None),
        budget=RunBudgetLedger(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
        studio=StudioRunPorts(nodes=nodes, registry=fixture_node_registry()),
    )
    return runner, recorder
