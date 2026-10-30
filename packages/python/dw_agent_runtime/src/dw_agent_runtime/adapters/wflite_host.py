"""What every process that hosts wf-lite graphs builds the same way (wf-lite
R6.1, R6.13, R6.17, R6.20).

Two processes host every pinned workflow: the worker starts the run of the work
its `dw_work` lane claims and resumes the run its `dw_timers` lane wakes; the
API resumes the run a person decided. A run paused in one resumes in the
other, so both must hold the same graphs, the same tool door and the same
nodes' ports. One builder, the way `model_stack` is one for the gateway:

- `build_tool_executor`: the one `ToolExecutor` shape, with a DW's boundary and
  the decision checks of R6.17 always wired. An executor without them refuses
  every DW decision call (`approval_missing`), so a root that forgot them
  would fail closed, but every DW run in it would hand off;
- `build_wflite_ports` and `register_workflows`: each document of the catalog
  as `dw:<key>` at its version, in `GraphRegistry` and `WorkerRegistry`;
- `build_run_starter`: the `dw_work` lane's starter;
- `RunTrailReader`: a work item's `trail`, from its run (R6.13).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.tool_claims import SqlToolClaims
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.ports import ModelGateway, WorkflowRunnerPort
from dw_agent_runtime.registry import GraphRegistry, LoadedWorker, WorkerRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.wflite.catalog import PackCatalog, PinnedWorkflow
from dw_agent_runtime.wflite.compile import WfPorts, compile_workflow, worker_definition_of
from dw_agent_runtime.wflite.starter import WorkflowRunStarter
from dw_kernel.errors import ConfigError, NotFoundError
from dw_kernel.ports import IdGenerator, UtcClock
from dw_observability.telemetry import TelemetryPort
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlApprovedDecisions,
    SqlDecisionLevels,
    SqlDigitalWorkerRepository,
    SqlDwBoundary,
    SqlScopedAudit,
    SqlTenantRunFacts,
)
from dw_platform.application.decision_gate import DecisionGate
from dw_platform.application.digital_workers import DecisionAutonomy
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.application.work_queue import WorkQueue

# The fallback of an unknown code; the copy file must carry it.
FALLBACK_CODE = "step_failed"
_TRAIL_FIELDS = ("step_id", "type", "status", "at")


def build_tool_executor(
    *,
    tools: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    uow_factory: PlatformUnitOfWorkFactory,
    approval_policy: AutonomyApprovalPolicy,
    telemetry: TelemetryPort,
    clock: UtcClock,
    ids: IdGenerator,
) -> ToolExecutor:
    """The door to every tool effect of this process. A Digital Worker's run
    is held to its DW (operating, its allowed tools, its principal's scopes
    now; digital-worker R6), and a call taken for a DW decision runs only as
    its class's level allows now, or with this run's approved decision of the
    same content (wf-lite R6.17)."""
    return ToolExecutor(
        registry=tools,
        execution_store=SqlToolExecutionStore(session_factory),
        uow_factory=uow_factory,
        clock=clock,
        id_generator=ids,
        approval_policy=approval_policy,
        claims=SqlToolClaims(session_factory),
        telemetry=telemetry,
        dw_boundary=SqlDwBoundary(session_factory),
        decision_autonomy=DecisionAutonomy(SqlDecisionLevels(session_factory)),
        approved_decisions=SqlApprovedDecisions(session_factory),
    )


class _HandoffCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    copy_id: str
    version: str
    recommendations: dict[str, str]

    @model_validator(mode="after")
    def _has_fallback(self) -> _HandoffCopy:
        if not self.recommendations.get(FALLBACK_CODE, "").strip():
            raise ValueError(f"recommendations.{FALLBACK_CODE} is required")
        if any(not text.strip() for text in self.recommendations.values()):
            raise ValueError("a recommendation is empty")
        return self


def load_handoff_copy(path: Path) -> Mapping[str, str]:
    """`configs/copy/wflite_handoff.yaml`: the recommendation of a hand-off by
    code (R6.20). A file without the fallback, or with an empty sentence,
    refuses to load: a packet's `recommendation` is never empty."""
    try:
        loaded = _HandoffCopy.model_validate(yaml.safe_load(path.read_bytes()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"hand-off copy {path.name} invalid: {exc}") from exc
    return {code: " ".join(text.split()) for code, text in loaded.recommendations.items()}


def build_wflite_ports(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: ModelGateway,
    executor: ToolExecutor,
    tools: ToolRegistry,
    queue: WorkQueue,
    recommendations: Mapping[str, str],
    clock: UtcClock,
    ids: IdGenerator,
) -> WfPorts:
    workers = SqlDigitalWorkerRepository(session_factory)
    return WfPorts(
        gateway=gateway,
        executor=executor,
        tools=tools,
        gate=DecisionGate(
            autonomy=DecisionAutonomy(SqlDecisionLevels(session_factory)),
            workers=workers,
            audit=SqlScopedAudit(session_factory),
            clock=clock,
            id_generator=ids,
        ),
        queue=queue,
        workers=workers,
        clock=clock,
        recommendations=recommendations,
    )


def register_workflows(
    catalog: PackCatalog, ports: WfPorts, *, graphs: GraphRegistry, workers: WorkerRegistry
) -> None:
    """R6.1: every pinned document as `dw:<key>` at its version. The graph is
    compiled on its first run, so the tools a context registers after this
    call are the ones its approvals' proposal schemas are read from."""
    for pinned in catalog.all():
        definition = worker_definition_of(pinned)
        graphs.register(definition.worker_id, definition.graph_version, _factory(pinned, ports))
        workers.register(
            LoadedWorker(
                definition=definition, checksum=pinned.sha256, source_path=str(pinned.path)
            )
        )


def _factory(pinned: PinnedWorkflow, ports: WfPorts) -> Any:
    return lambda: compile_workflow(pinned, ports)


def build_run_starter(
    *,
    catalog: PackCatalog,
    session_factory: async_sessionmaker[AsyncSession],
    tools: ToolRegistry,
    runner: WorkflowRunnerPort,
) -> WorkflowRunStarter:
    return WorkflowRunStarter(
        catalog=catalog,
        workers=SqlDigitalWorkerRepository(session_factory),
        boundary=SqlDwBoundary(session_factory),
        tenants=SqlTenantRunFacts(session_factory),
        tools=tools,
        runner=runner,
    )


@dataclass(frozen=True)
class RunTrailReader:
    """R6.13: the `trail` of a work item's run, read under its reader's tenant
    and workspace: from the run's latest checkpoint while it is live (its item
    in progress or waiting), from its result once it ended. One read per call:
    the item already says which (measured 30/10/2026: reading the run row first
    to decide cost P95 +57% on a waiting run). A DW's run is its own thread
    (`run_context_for` names none). Only `{step_id, type, status, at}` of each
    entry leaves here (R6.6), whatever else a checkpoint holds."""

    run_store: SqlWorkerRunStore
    checkpoints: SqlAlchemyCheckpointSaver

    async def trail(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, run_id: uuid.UUID, live: bool
    ) -> list[dict[str, str]]:
        raw: Any
        if live:
            found = await self.checkpoints.aget_tuple(
                {
                    "configurable": {
                        "thread_id": str(run_id),
                        "tenant_id": str(tenant_id),
                        "workspace_id": str(workspace_id),
                    }
                }
            )
            raw = None if found is None else found.checkpoint["channel_values"].get("trail")
        else:
            try:
                record = await self.run_store.get_in(
                    tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id
                )
            except NotFoundError:
                return []
            raw = (record.result or {}).get("trail")
        return [
            {name: str(entry.get(name, "")) for name in _TRAIL_FIELDS}
            for entry in raw or []
            if isinstance(entry, Mapping)
        ]
