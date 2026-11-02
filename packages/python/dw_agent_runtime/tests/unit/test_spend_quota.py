"""The per-tenant daily spend guard: mechanism only, gated by a plan's number.

Same shape as test_run_quota.py, and for the same reason: the gate sits in the
runner rather than an API dependency, so a worker reacting to an inbound event
is bound by it too. Every plan ships `spend_usd_per_day=None` today (no dollar
thresholds decided) and `spend_store` defaults to `None` on the runner itself
(any wiring that predates this guard) — both are exercised here as "the gate
is off", not treated as edge cases to skip.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
NOW = datetime(2026, 9, 22, 15, 30, tzinfo=UTC)


class _PassedTheGateError(Exception):
    """Raised by the fake store to mark the claim being reached."""


@dataclass
class _FakeRunStore:
    """Never refuses on run count — every test here is about the spend gate."""

    async def started_since(self, tenant_id: uuid.UUID, since: datetime) -> int:
        return 0

    async def create(self, *args: Any, **kwargs: Any) -> None:
        raise _PassedTheGateError


@dataclass
class _FakeSpendStore:
    spent: Decimal
    queried_for: list[date] = field(default_factory=list)

    async def spend_today(self, tenant_id: uuid.UUID, day: date) -> Decimal:
        self.queried_for.append(day)
        return self.spent


@dataclass(frozen=True)
class _FakePlan:
    spend_limit: Decimal | None

    async def runs_per_day(self, plan_id: str) -> int | None:
        return None

    async def spend_usd_per_day(self, plan_id: str) -> Decimal | None:
        return self.spend_limit


@dataclass(frozen=True)
class _FrozenClock:
    def now(self) -> datetime:
        return NOW


def _runner(
    tmp_path: Path,
    *,
    spend_limit: Decimal | None,
    spent: Decimal,
    spend_store: _FakeSpendStore | None,
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
        run_store=cast(Any, _FakeRunStore()),
        uow_factory=cast(Any, None),
        clock=cast(Any, _FrozenClock()),
        id_generator=cast(Any, None),
        allowance=_FakePlan(spend_limit),
        budget=RunBudgetLedger(),
        approval_policy=AutonomyApprovalPolicy(),
        spend_store=cast(Any, spend_store),
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


async def test_a_tenant_at_its_daily_spend_limit_is_refused(tmp_path: Path) -> None:
    store = _FakeSpendStore(spent=Decimal("10.0000"))
    runner = _runner(tmp_path, spend_limit=Decimal(10), spent=Decimal(10), spend_store=store)

    with pytest.raises(QuotaExceededError) as raised:
        await runner.start(run_context=_run_context(), input_payload={})

    assert raised.value.details["quota"] == "spend_usd_per_day"
    assert raised.value.details["limit"] == "10"
    assert raised.value.details["used"] == "10.0000"


async def test_a_tenant_below_its_daily_spend_limit_is_allowed(tmp_path: Path) -> None:
    store = _FakeSpendStore(spent=Decimal("9.9999"))
    runner = _runner(tmp_path, spend_limit=Decimal(10), spent=Decimal("9.9999"), spend_store=store)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})


async def test_a_plan_with_no_spend_limit_is_never_queried(tmp_path: Path) -> None:
    """Unlimited is the shape every plan ships in today — must not cost a query."""
    store = _FakeSpendStore(spent=Decimal(999_999))
    runner = _runner(tmp_path, spend_limit=None, spent=Decimal(999_999), spend_store=store)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})

    assert store.queried_for == []


async def test_a_runner_wired_without_a_spend_store_has_no_gate(tmp_path: Path) -> None:
    """Every wiring that predates this guard passes `spend_store=None` implicitly."""
    runner = _runner(tmp_path, spend_limit=Decimal(1), spent=Decimal(999_999), spend_store=None)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})


async def test_a_spend_store_failure_refuses_rather_than_allows(tmp_path: Path) -> None:
    """Fail closed: a lookup that cannot answer must not be read as "no spend yet".

    The opposite of the recorder's contract on purpose. A recorder that raises
    must not take the run down (test_usage_recorders.py) because the model has
    already answered and the smaller loss is not recording it. This is before
    the model is ever called — the gate exists to decide whether to spend more
    money at all, and a dependency that cannot say how much has already been
    spent must not be treated as "zero".
    """

    @dataclass
    class _BrokenSpendStore:
        async def spend_today(self, tenant_id: uuid.UUID, day: date) -> Decimal:
            raise RuntimeError("database is down")

    runner = _runner(
        tmp_path,
        spend_limit=Decimal(10),
        spent=Decimal(0),
        spend_store=cast(Any, _BrokenSpendStore()),
    )

    with pytest.raises(RuntimeError, match="database is down"):
        await runner.start(run_context=_run_context(), input_payload={})


async def test_the_window_is_todays_utc_date(tmp_path: Path) -> None:
    store = _FakeSpendStore(spent=Decimal(0))
    runner = _runner(tmp_path, spend_limit=Decimal(10), spent=Decimal(0), spend_store=store)

    with pytest.raises(_PassedTheGateError):
        await runner.start(run_context=_run_context(), input_payload={})

    assert store.queried_for == [date(2026, 9, 22)]
