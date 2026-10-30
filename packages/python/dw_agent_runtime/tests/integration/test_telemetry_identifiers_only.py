"""A run's telemetry, logs and audit trail carry identifiers only (spec R1.1-R1.3, R1.5).

One run end to end, through the runner and the approval flow the processes
wire: it starts, pauses for an approval, is approved and resumes. Its input
carries a phone number. What it leaves behind is read where each kind of trail
is kept: the spans and metrics handed to the telemetry port, every log line the
identifier-only formatter writes, and the audit rows in PostgreSQL.
"""

from __future__ import annotations

import io
import logging
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from runtime_harness import TENANT_A, WORKSPACE_A, RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import RunStatus, SqlWorkerRunStore
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML, build_demo_graph
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_observability.logs import IdentifierOnlyJsonFormatter
from dw_observability.metrics import DW_APPROVAL_WAIT_SECONDS, DW_RUN_DURATION_SECONDS
from dw_observability.semconv import contract_violations, load_snapshot, snapshot_path
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[5]
# Spaced as people write it; the digits alone are what must not appear.
PHONE = "0912 345 678"
DIGITS = "0912345678"


class _UnmeteredPlan:
    def runs_per_day(self, plan_id: str) -> int | None:
        return None

    def spend_usd_per_day(self, plan_id: str) -> Decimal | None:
        return None


@pytest.fixture
def log_lines() -> Iterator[io.StringIO]:
    """Every record any logger emits, as the processes' formatter writes it."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(IdentifierOnlyJsonFormatter())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield buffer
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


async def test_a_phone_number_in_the_input_reaches_no_span_log_or_audit_row(
    urls: RuntimeUrls, tmp_path: Path, log_lines: io.StringIO
) -> None:
    worker_config = tmp_path / "demo_approval.yaml"
    worker_config.write_text(DEMO_WORKER_YAML, encoding="utf-8")
    engine = create_async_engine(urls.app, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    graphs = GraphRegistry()
    graphs.register("demo_approval", "1.0.0", build_demo_graph)
    workers = WorkerRegistry(graph_registry=graphs)
    workers.load_file(worker_config)
    telemetry = RecordingTelemetry()
    uow_factory = SqlPlatformUnitOfWorkFactory(sessions)
    run_store = SqlWorkerRunStore(sessions, stale_run_after_seconds=3600)
    runner = LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
        run_store=run_store,
        uow_factory=uow_factory,
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
        allowance=_UnmeteredPlan(),
        budget=RunBudgetLedger(),
        approval_policy=AutonomyApprovalPolicy(),
        telemetry=telemetry,
    )
    approvals = ApproveAndResumeService(
        uow_factory=uow_factory,
        runner=runner,
        run_store=run_store,
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
        telemetry=telemetry,
    )
    run = make_run_context(workspace=WORKSPACE_A)

    await runner.start(run_context=run, input_payload={"subject": f"Gọi lại {PHONE}"})
    paused = await run_store.get(run, run.run_id)
    assert paused.status is RunStatus.WAITING_APPROVAL
    assert paused.approval_request_id is not None
    await approvals.decide(
        approval_id=paused.approval_request_id,
        approve=True,
        comment="ok",
        context=AccessContext(
            tenant_id=TENANT_A,
            workspace_id=WORKSPACE_A,
            principal_id=uuid.uuid4(),
            roles=frozenset({"approver"}),
            scopes=frozenset({"approvals.read", "approvals.decide", "runs.read"}),
            plan_id="professional",
        ),
        authorization=ScopeAuthorizationService(),
    )
    assert (await run_store.get(run, run.run_id)).status is RunStatus.COMPLETED

    # The value is really in the run: what follows proves it went nowhere else.
    assert "345" in str((await run_store.get(run, run.run_id)).input)

    # Telemetry: the pinned names only, and two passes plus one wait measured.
    assert contract_violations(load_snapshot(snapshot_path(REPO_ROOT)), telemetry) == []
    assert [name for name, _ in telemetry.spans] == ["invoke_workflow demo_approval"] * 2
    assert [name for name, _, _ in telemetry.histograms] == [
        DW_RUN_DURATION_SECONDS,
        DW_APPROVAL_WAIT_SECONDS,
        DW_RUN_DURATION_SECONDS,
    ]
    emitted = repr(telemetry.spans) + repr(telemetry.metrics) + repr(telemetry.histograms)
    assert "345" not in emitted

    lines = log_lines.getvalue()
    assert "345" not in lines and DIGITS not in lines

    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)}
        )
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT action, details::text, resource_id FROM platform.audit_events"
                    " WHERE run_id = :r"
                ),
                {"r": run.run_id},
            )
        ).all()
    assert {row.action for row in rows} >= {"run.started", "run.completed"}
    assert all("345" not in f"{row.details} {row.resource_id}" for row in rows)
    await engine.dispose()
