"""The per-tenant daily run quota: the plan's number, enforced where runs begin.

The gate sits in the runner rather than in an API dependency on purpose, so
these tests drive it through `start` — a worker reacting to an inbound event
starts runs no HTTP request ever touched, and a quota only the API enforced
would be one a connector walks around.

The run itself is not the subject here. The fake store refuses to go further
than the claim, which is exactly the line being tested: a refused run must not
reach it, and an allowed one must.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML, build_demo_graph
from dw_kernel.errors import QuotaExceededError

pytestmark = pytest.mark.unit

WORKER = "demo_approval"

# Mid-afternoon, so "since the start of today" is a different instant from "now"
# and a gate that passed the wrong one would count the wrong window.
NOW = datetime(2026, 9, 17, 15, 30, tzinfo=UTC)


class _PassedTheGateError(Exception):
    """Raised by the fake store to mark the claim being reached."""


@dataclass
class _FakeRunStore:
    started_today: int
    counted_since: list[datetime] = field(default_factory=list)

    async def started_since(self, tenant_id: uuid.UUID, since: datetime) -> int:
        self.counted_since.append(since)
        return self.started_today

    async def create(self, *args: Any, **kwargs: Any) -> None:
        raise _PassedTheGateError


@dataclass(frozen=True)
class _FakePlan:
    limit: int | None

    async def runs_per_day(self, plan_id: str) -> int | None:
        return self.limit

    async def spend_usd_per_day(self, plan_id: str) -> Decimal | None:
        return None


@dataclass(frozen=True)
class _FrozenClock:
    def now(self) -> datetime:
        return NOW


def _runner(
    tmp_path: Path,
    *,
    limit: int | None,
    started_today: int,
) -> LangGraphWorkflowRunner:
    config = tmp_path / f"{WORKER}.yaml"
    config.write_text(DEMO_WORKER_YAML, encoding="utf-8")
    graphs = GraphRegistry()
    graphs.register(WORKER, "1.0.0", build_demo_graph)
    workers = WorkerRegistry(graph_registry=graphs)
    workers.load_file(config)
    return LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=cast(Any, None),
        run_store=cast(Any, _FakeRunStore(started_today=started_today)),
        uow_factory=cast(Any, None),
        clock=cast(Any, _FrozenClock()),
        id_generator=cast(Any, None),
        allowance=_FakePlan(limit),
        budget=RunBudgetLedger(),
        approval_policy=AutonomyApprovalPolicy(),
    )


def _run_context() -> RunContext:
    return RunContext(
        run_id=uuid.UUID(int=1),
        tenant_id=uuid.UUID(int=2),
        workspace_id=uuid.UUID(int=3),
        actor_id=uuid.UUID(int=4),
        worker_id=WORKER,
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset(),
        trace_id="trace-1",
    )


async def test_a_tenant_at_its_daily_limit_is_refused(tmp_path: Path) -> None:
    runner = _runner(tmp_path, limit=20, started_today=20)

    with pytest.raises(QuotaExceededError) as raised:
        await runner.start(run_context=_run_context(), input_payload={})

    # What the caller needs to act: the number, and when it comes back.
    assert raised.value.details["limit"] == "20"
    assert raised.value.details["resets_at"] == "2026-09-18T00:00:00+00:00"


async def test_the_run_that_reaches_the_limit_is_still_allowed(tmp_path: Path) -> None:
    """Nineteen used out of twenty means the twentieth runs, not that it is the last refused."""
    runner = _runner(tmp_path, limit=20, started_today=19)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})


async def test_a_plan_with_no_limit_is_never_counted(tmp_path: Path) -> None:
    """Unlimited is a real answer, and it must not cost a query per run."""
    runner = _runner(tmp_path, limit=None, started_today=10_000)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})

    assert cast(_FakeRunStore, runner.run_store).counted_since == []


async def test_the_window_starts_at_midnight_utc_not_an_hour_ago(tmp_path: Path) -> None:
    """A rolling window would refuse a tenant that used its quota yesterday evening."""
    runner = _runner(tmp_path, limit=20, started_today=0)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})

    assert cast(_FakeRunStore, runner.run_store).counted_since == [
        datetime(2026, 9, 17, tzinfo=UTC)
    ]
