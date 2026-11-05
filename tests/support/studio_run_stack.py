"""A runner of Studio runs over PostgreSQL, for `dw_studio`'s
`test_studio_runs.py` and the child process it kills (`studio_run_child.py`
beside it): the real `SqlStudioRunStore`,
the real checkpoint saver, `LangGraphWorkflowRunner.run_studio`, and doors that
keep what they did in a JSON file, so what a dead process sent is still there
for the one that takes the run again. `claimed` takes one queued run under a
claim, as the `studio_runs` lane's claim does (workflow-engine/04), so a test
runs exactly the run it means.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.studio_run_queue import SqlStudioRunQueue
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.ports import (
    BindingReviewPort,
    HeldRunAlertPort,
    LimitsPort,
    ReapedRuns,
    RunControlPort,
    StudioClaim,
)
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.step_recorder import FakeStepRecorder
from dw_agent_runtime.testing.studio_runs import FakeBindingReview, FakeClaims, RecordingAlerts
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.doors import DoorCall, EffectDoor, StepDoor
from dw_agent_runtime.wflite.node_wrapper import StudioNodePorts, StudioRunPorts
from dw_kernel.expressions import ExpressionEngine
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_studio.core.adapters.cel.engine import CelCppEngine
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


_CLAIM_ONE = sa.text(
    "UPDATE platform.worker_runs SET status = 'running',"
    " lease_owner = 'test:' || gen_random_uuid()::text, lease_until = now() + interval '60 s'"
    " WHERE id = :run_id AND status = 'queued' RETURNING lease_owner"
)


async def claimed(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """Claim `run_id` as `dw_app` under its tenant, and return the token."""
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        token = await session.scalar(_CLAIM_ONE, {"run_id": run_id})
    assert token is not None, "the run is not a queued run of this tenant"
    return str(token)


async def run_claimed(
    runner: LangGraphWorkflowRunner,
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> Any:
    """Claim the run, then run it as the lane would."""
    token = await claimed(sessions, tenant_id, run_id)
    return await runner.run_studio(tenant_id=tenant_id, run_id=run_id, lease_token=token)


def build_runner(
    sessions: async_sessionmaker[AsyncSession],
    doors: Mapping[EffectDoor, StepDoor],
    *,
    run_control: RunControlPort | None = None,
    dispatch_control: RunControlPort | None = None,
    limits: LimitsPort | None = None,
    binding_review: BindingReviewPort | None = None,
    alerts: HeldRunAlertPort | None = None,
    expressions: ExpressionEngine | None = None,
) -> tuple[LangGraphWorkflowRunner, FakeStepRecorder]:
    """`run_control` is the node head's (agent-lifecycle 05 passes a real
    `SqlRunControl`) and `dispatch_control` the one dispatch asks; open by
    default, as are the limits. A trigger's run is let on by the binding
    review unless a test passes one."""
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
        run_store=SqlWorkerRunStore(sessions, stale_run_after_seconds=300),
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        clock=clock,
        id_generator=ids,
        limits=limits or OpenLimits(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=dispatch_control or OpenRunControl(),
        studio=StudioRunPorts(
            nodes=nodes,
            registry=fixture_node_registry(),
            binding_review=binding_review or FakeBindingReview(),
            alerts=alerts or RecordingAlerts(),
            expressions=expressions or CelCppEngine(),
        ),
    )
    return runner, recorder


@dataclass
class ScopedQueue:
    """`SqlStudioRunQueue` seen from the tenants a test planted: the three
    reads across tenants keep the function's order and drop every other
    tenant, so runs other suites left in the database are never taken."""

    inner: SqlStudioRunQueue
    tenants: frozenset[uuid.UUID]

    async def _mine(self, found: list[uuid.UUID], limit: int) -> list[uuid.UUID]:
        return [t for t in found if t in self.tenants][:limit]

    async def scopes_due(self, limit: int) -> list[uuid.UUID]:
        return await self._mine(await self.inner.scopes_due(100_000), limit)

    async def orphans_due(self, limit: int) -> list[uuid.UUID]:
        return await self._mine(await self.inner.orphans_due(100_000), limit)

    async def deadlines_due(self, limit: int, *, unclaimed_after: timedelta) -> list[uuid.UUID]:
        found = await self.inner.deadlines_due(100_000, unclaimed_after=unclaimed_after)
        return await self._mine(found, limit)

    async def claim(
        self, tenant_id: uuid.UUID, *, limit: int, worker: str, lease: timedelta
    ) -> list[StudioClaim]:
        return await self.inner.claim(tenant_id, limit=limit, worker=worker, lease=lease)

    async def beat(self, claim: StudioClaim, *, lease: timedelta) -> bool:
        return await self.inner.beat(claim, lease=lease)

    async def release(self, claim: StudioClaim) -> bool:
        return await self.inner.release(claim)

    async def requeue_orphans(
        self, tenant_id: uuid.UUID, *, max_requeues: int, backoff: Callable[[int], timedelta]
    ) -> ReapedRuns:
        return await self.inner.requeue_orphans(
            tenant_id, max_requeues=max_requeues, backoff=backoff
        )

    async def cancel_overdue(
        self, tenant_id: uuid.UUID, *, unclaimed_after: timedelta
    ) -> ReapedRuns:
        return await self.inner.cancel_overdue(tenant_id, unclaimed_after=unclaimed_after)


def scoped_queue(
    sessions: async_sessionmaker[AsyncSession], tenants: frozenset[uuid.UUID]
) -> ScopedQueue:
    return ScopedQueue(SqlStudioRunQueue(sessions, Uuid7Generator(), SystemClock()), tenants)
