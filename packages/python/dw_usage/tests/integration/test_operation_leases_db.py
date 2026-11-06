"""Leases of model calls outside any run, run limits clamped by the plan, and
the embedding meter, against real Postgres as `dw_app` (usage-and-limits
ticket 04: R6.2, R6.4; UL4; gate 4/11/2026 (a), (b)).

Built on `test_limits_db`'s planting: each test plants its own plan, company
and workspace as the migrator, then admits and spends through `SqlLimits` and
`SqlUsageMeter` as `dw_app`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_limits_db import Company, Stack, estimate, run

from dw_agent_runtime.contracts import DeclaredLimits
from dw_kernel.limits import LeaseInForce, LimitExceededError, MeteredCall
from dw_usage.adapters.limits_sql import SqlRunLease
from dw_usage.adapters.metering import SqlUsageMeter
from dw_usage.adapters.price_book_file import load_price_book

pytestmark = pytest.mark.integration


@pytest.fixture
async def stack(
    usage_db: DatabaseUrls, migrator: AsyncEngine, app_sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[Stack]:
    yield Stack(migrator=migrator, sessions=app_sessions)


async def _operation(
    stack: Stack, company: Company, purpose: str = "ingestion"
) -> tuple[uuid.UUID, SqlRunLease]:
    operation = uuid.uuid4()
    lease = await stack.limits.admit_operation(
        tenant_id=company.tenant_id,
        workspace_id=company.main,
        purpose=purpose,  # type: ignore[arg-type]
        operation_id=operation,
    )
    assert isinstance(lease, SqlRunLease)
    return operation, lease


# ---- R6.2: an operation's lease ------------------------------------------------


async def test_an_operation_on_a_spent_month_is_refused_with_when_it_resets(stack: Stack) -> None:
    """R6.2 (UL4): the lane's ingestion, a retrieval or a builder's assistance
    is refused like a run, with `resets_at`, and holds nothing."""
    company = await stack.company(cost_usd_per_month="10")
    await stack.spent(company, "10")

    with pytest.raises(LimitExceededError) as refused:
        await _operation(stack, company)

    details = refused.value.details
    assert (details["metric"], details["window"]) == ("cost_usd", "month")
    assert details["resets_at"] == "2026-11-30T17:00:00+00:00"
    assert await stack.leases(company) == []


async def test_an_ingestion_lease_counts_no_run(stack: Stack) -> None:
    """R6.2: an operation spends money and tokens of the chain, never `runs`:
    the day's one run is still there after it."""
    company = await stack.company(runs_per_day=1, cost_usd_per_month="100")
    await _operation(stack, company)

    (lease,) = await stack.leases(company)
    assert (lease.purpose, lease.counted_run, lease.run_id) == ("ingestion", False, None)
    assert ("tenant", "runs", "day") not in await stack.counters(company)

    await stack.limits.admit(run(company))
    counters = await stack.counters(company)
    assert counters[("tenant", "runs", "day")][0] == Decimal(1)


async def test_an_operation_is_bounded_by_the_period_not_by_a_runs_ceiling(stack: Stack) -> None:
    """Gate 4/11/2026: a large ingestion costs more than a run may; it holds a
    run's ceiling at first and tops up by what the call lacks, never the whole
    month, so runs admitted beside it still find the rest."""
    company = await stack.company(cost_usd_per_month="100", max_cost_usd_per_run="2")
    _, lease = await _operation(stack, company)
    (opened,) = await stack.leases(company)
    assert opened.reserved_usd == Decimal(2)

    permit = await lease.permit(
        run_id=None,
        cost_ceiling_usd=None,
        estimate=estimate(1000, input_usd="5", per_token="0", max_output_tokens=0),
    )

    assert permit.max_output_tokens == 0
    (grown,) = await stack.leases(company)
    # What the call lacked (3) and a run's ceiling (2) beyond it: 7 of 100.
    assert grown.reserved_usd == Decimal(7)
    counters = await stack.counters(company)
    assert counters[("tenant", "cost_usd", "month")] == (Decimal(0), grown.reserved_usd)
    await stack.limits.admit(run(company))


async def test_an_operation_whose_call_the_month_cannot_hold_sends_nothing(stack: Stack) -> None:
    """R5.10 at an operation: the input does not fit what the month has left."""
    company = await stack.company(cost_usd_per_month="3", max_cost_usd_per_run="2")
    _, lease = await _operation(stack, company)

    with pytest.raises(LimitExceededError):
        await lease.permit(
            run_id=None,
            cost_ceiling_usd=None,
            estimate=estimate(1000, input_usd="5", per_token="0", max_output_tokens=0),
        )
    (held,) = await stack.leases(company)
    assert held.in_flight == {}


# ---- R6.4: the run's limits at each admit and resume ---------------------------


async def test_a_versions_value_above_the_plan_is_clamped_and_a_lowered_plan_binds_the_resume(
    stack: Stack,
) -> None:
    """R6.4: what the version declares, never above the plan; a field it does
    not declare is the plan's; the plan as it stands at the resume binds it."""
    company = await stack.company(max_cost_usd_per_run="2")
    context = run(
        company,
        declared_limits=DeclaredLimits(max_steps=400, max_tool_calls=7, max_cost_usd=Decimal(9)),
    )

    admitted = await stack.limits.admit(context)
    assert admitted.run_limits is not None
    assert (admitted.run_limits.max_steps, admitted.run_limits.max_tool_calls) == (50, 7)
    assert admitted.run_limits.max_cost_usd == Decimal(2)
    assert admitted.run_limits.max_model_calls == 50
    (lease,) = await stack.leases(company)
    assert lease.cap_usd == Decimal(2)

    await admitted.release("paused")
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.plan_limits SET max_steps_per_run = 12,"
                " max_cost_usd_per_run = 1 WHERE plan_id = :p"
            ),
            {"p": company.plan_id},
        )
    resumed = await stack.limits.resume(context)

    assert resumed.run_limits is not None
    assert (resumed.run_limits.max_steps, resumed.run_limits.max_cost_usd) == (12, Decimal(1))


# ---- R6.1, R6.2: the embedding meter --------------------------------------------


async def test_an_embedding_is_settled_into_its_operations_lease_under_its_purpose(
    stack: Stack,
) -> None:
    """The meter's permit and record: `embeddings`, the lease's purpose, the
    uploader named, priced by the book, settled into the lease."""
    company = await stack.company(cost_usd_per_month="100")
    operation, _ = await _operation(stack, company)
    actor = uuid.uuid4()
    holder = LeaseInForce(
        tenant_id=company.tenant_id,
        workspace_id=company.main,
        lease_root=operation,
        run_id=None,
        purpose="ingestion",
        actor_id=actor,
        actor_kind="user",
    )
    meter = SqlUsageMeter(
        limits=stack.limits, ledger=stack.ledger, pricing=load_price_book(), clock=stack.clock
    )
    call = MeteredCall(
        operation="embeddings",
        provider="openai_compatible",
        model="text-embedding-3-large",
        input_tokens=1_000_000,
        units={"embedding_input": 1_000_000},
        data_location="foreign",
        processor="fpt_ai_gateway",
    )

    permit = await meter.before_call(holder, call)
    await meter.settle(holder, permit, call)

    (event,) = await stack.rows(
        company,
        "SELECT * FROM platform.usage_events WHERE id = :id",
        id=permit.call_id,
    )
    assert (event.operation, event.purpose, event.user_id) == ("embeddings", "ingestion", actor)
    assert (event.root_run_id, event.run_id, event.lease_id) == (operation, None, permit.lease_id)
    assert (event.cost_source, event.cost_usd) == ("estimated", Decimal("0.13"))
    assert event.units == {"embedding_input": 1_000_000}
    (lease,) = await stack.leases(company)
    assert (lease.settled_usd, lease.settled_tokens) == (Decimal("0.13"), 1_000_000)
    assert lease.in_flight == {}


async def test_an_embedding_that_never_answered_holds_nothing(stack: Stack) -> None:
    company = await stack.company(cost_usd_per_month="100")
    operation, _ = await _operation(stack, company)
    holder = LeaseInForce(
        tenant_id=company.tenant_id,
        workspace_id=company.main,
        lease_root=operation,
        run_id=None,
        purpose="ingestion",
        actor_id=None,
        actor_kind="system",
    )
    meter = SqlUsageMeter(
        limits=stack.limits, ledger=stack.ledger, pricing=load_price_book(), clock=stack.clock
    )
    call = MeteredCall(
        operation="embeddings",
        provider="mock",
        model="hash-embedding",
        input_tokens=10,
        units={"embedding_input": 10},
        data_location=None,
        processor=None,
    )

    permit = await meter.before_call(holder, call)
    (flying,) = await stack.leases(company)
    assert str(permit.call_id) in flying.in_flight
    await meter.abandon(holder, permit)

    (lease,) = await stack.leases(company)
    assert lease.in_flight == {}
    assert lease.settled_usd == Decimal(0)


async def test_another_companys_holder_finds_no_lease_to_spend(stack: Stack) -> None:
    """Tenant isolation at the meter: a holder naming company B and company A's
    operation reads no lease under B's RLS, so the call is refused and A's
    lease is untouched."""
    owner = await stack.company(cost_usd_per_month="100")
    other = await stack.company(cost_usd_per_month="100")
    operation, _ = await _operation(stack, owner)
    meter = SqlUsageMeter(
        limits=stack.limits, ledger=stack.ledger, pricing=load_price_book(), clock=stack.clock
    )
    intruder = LeaseInForce(
        tenant_id=other.tenant_id,
        workspace_id=other.main,
        lease_root=operation,
        run_id=None,
        purpose="ingestion",
        actor_id=None,
        actor_kind="system",
    )
    call = MeteredCall(
        operation="embeddings",
        provider="mock",
        model="hash-embedding",
        input_tokens=10,
        units={"embedding_input": 10},
        data_location=None,
        processor=None,
    )

    with pytest.raises(LimitExceededError):
        await meter.before_call(intruder, call)

    (lease,) = await stack.leases(owner)
    assert lease.in_flight == {}
    assert await stack.leases(other) == []
