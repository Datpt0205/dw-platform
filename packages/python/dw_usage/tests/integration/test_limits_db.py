"""Hard limits as Postgres leases, against real Postgres as `dw_app`
(usage-and-limits ticket 03: R4.1, R4.4, R4.8, R4.10, R5.1-R5.11; UL2, UL3,
UL6, UL8, UL11, UL13).

Each test plants its own plan, company and workspaces as the migrator, then
admits, calls, beats, releases and reaps through `SqlLimits` and the ledger as
`dw_app`, the role the platform runs as. Time is a `FixedClock`, so a lease
expires when the test moves it, not after five real minutes.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import CallEstimate, CallPermit
from dw_kernel.limits import LimitExceededError, LimitsUnavailableError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.domain.audit import system_actor
from dw_usage.adapters.limits_sql import SqlBudgetLeaseReaper, SqlLimits
from dw_usage.adapters.sql import SqlUsageLedger
from dw_usage.domain.events import UsageEvent

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 10:00 in Hanoi
_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")


@dataclass
class Company:
    tenant_id: uuid.UUID
    workspaces: list[uuid.UUID]
    plan_id: str

    @property
    def main(self) -> uuid.UUID:
        return self.workspaces[0]


@dataclass
class Stack:
    migrator: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    clock: FixedClock = field(default_factory=lambda: FixedClock(NOW))

    @property
    def limits(self) -> SqlLimits:
        return SqlLimits(self.sessions, clock=self.clock, ids=Uuid4Generator())

    @property
    def ledger(self) -> SqlUsageLedger:
        return SqlUsageLedger(self.sessions)

    @property
    def reaper(self) -> SqlBudgetLeaseReaper:
        return SqlBudgetLeaseReaper(self.sessions, clock=self.clock, ids=Uuid4Generator())

    async def company(
        self,
        *,
        runs_per_day: int | None = None,
        cost_usd_per_day: str | None = None,
        cost_usd_per_month: str | None = None,
        tokens_per_month: int | None = None,
        max_cost_usd_per_run: str = "2",
        max_tokens_per_run: int = 200_000,
        workspaces: int = 1,
    ) -> Company:
        tenant = uuid.uuid4()
        plan = f"ul3-{tenant.hex[:10]}"
        spaces = [uuid.uuid4() for _ in range(workspaces)]
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO platform.plans (plan_id, name) VALUES (:p, :p)"), {"p": plan}
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.plan_limits (plan_id, runs_per_day, cost_usd_per_day,"
                    " cost_usd_per_month, tokens_per_month, max_cost_usd_per_run,"
                    " max_tokens_per_run, max_steps_per_run, max_model_calls_per_run,"
                    " max_tool_calls_per_run)"
                    " VALUES (:p, :rpd, :cpd, :cpm, :tpm, :mc, :mt, 50, 50, 50)"
                ),
                {
                    "p": plan,
                    "rpd": runs_per_day,
                    "cpd": None if cost_usd_per_day is None else Decimal(cost_usd_per_day),
                    "cpm": None if cost_usd_per_month is None else Decimal(cost_usd_per_month),
                    "tpm": tokens_per_month,
                    "mc": Decimal(max_cost_usd_per_run),
                    "mt": max_tokens_per_run,
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name, status, timezone)"
                    " VALUES (:t, :s, :s, 'active', 'Asia/Ho_Chi_Minh')"
                ),
                {"t": tenant, "s": f"ul3-{tenant.hex[:12]}"},
            )
            for n, ws in enumerate(spaces):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                        " VALUES (:w, :t, :s, :s)"
                    ),
                    {"w": ws, "t": tenant, "s": f"ws{n}"},
                )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
                    " VALUES (:id, :t, :p)"
                ),
                {"id": uuid.uuid4(), "t": tenant, "p": plan},
            )
        return Company(tenant, spaces, plan)

    async def policy(
        self,
        company: Company,
        *,
        metric: str,
        window_kind: str,
        value: str,
        workspace: uuid.UUID | None = None,
    ) -> None:
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.limit_policies (id, tenant_id, scope_type,"
                    " scope_workspace_id, metric, window_kind, kind, limit_value, created_by)"
                    " VALUES (:id, :t, :st, :w, :m, :wk, 'hard', :v, :by)"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": company.tenant_id,
                    "st": "tenant" if workspace is None else "workspace",
                    "w": workspace,
                    "m": metric,
                    "wk": window_kind,
                    "v": Decimal(value),
                    "by": uuid.uuid4(),
                },
            )

    async def spent(
        self, company: Company, usd: str, *, workspace: uuid.UUID | None = None, tokens: int = 0
    ) -> None:
        """A record of this period, as an earlier run left it."""
        await self.ledger.settle(
            UsageEvent(
                id=uuid.uuid4(),
                occurred_at=NOW - timedelta(minutes=30),
                tenant_id=company.tenant_id,
                workspace_id=workspace,
                operation="chat",
                purpose="run",
                payer="platform",
                actor_kind="user",
                provider="openai_compatible",
                model="gpt-4.1",
                input_tokens=tokens,
                output_tokens=0,
                cost_source="computed",
                price_book_version="1.0.0",
                cost_usd=Decimal(usd),
            )
        )

    async def rows(self, company: Company, sql: str, **values: Any) -> list[Any]:
        async with self.sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(company.tenant_id)})
            return list((await session.execute(sa.text(sql), values)).all())

    async def counters(
        self, company: Company
    ) -> dict[tuple[str, str, str], tuple[Decimal, Decimal]]:
        found = await self.rows(
            company,
            "SELECT scope_type, metric, window_kind, used, reserved FROM platform.budget_counters",
        )
        return {(r.scope_type, r.metric, r.window_kind): (r.used, r.reserved) for r in found}

    async def leases(self, company: Company) -> list[Any]:
        return await self.rows(
            company,
            "SELECT * FROM platform.budget_leases ORDER BY opened_at, closed_at NULLS LAST, id",
        )


@pytest.fixture
async def stack(
    usage_db: DatabaseUrls, migrator: AsyncEngine, app_sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[Stack]:
    yield Stack(migrator=migrator, sessions=app_sessions)


def run(company: Company, **overrides: Any) -> RunContext:
    fields: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "tenant_id": company.tenant_id,
        "workspace_id": company.main,
        "actor_id": uuid.uuid4(),
        "worker_id": "dw:test",
        "worker_version": "1.0.0",
        "channel": "test",
        "plan_id": company.plan_id,
        "roles": frozenset(),
        "scopes": frozenset(),
        "trace_id": "ul3",
        "run_mode": "live",
    }
    fields.update(overrides)
    return RunContext(**fields)


def estimate(
    input_tokens: int = 100,
    *,
    input_usd: str | None = "0.01",
    per_token: str | None = "0.001",
    max_output_tokens: int | None = None,
) -> CallEstimate:
    return CallEstimate(
        provider="openai_compatible",
        model="gpt-4.1",
        input_tokens=input_tokens,
        input_cost_usd=None if input_usd is None else Decimal(input_usd),
        output_usd_per_token=None if per_token is None else Decimal(per_token),
        price_book_version="1.0.0",
        max_output_tokens=max_output_tokens,
    )


async def settle(
    stack: Stack,
    context: RunContext,
    permit: CallPermit,
    usd: str,
    *,
    input_tokens: int = 100,
    output_tokens: int = 10,
) -> bool:
    """A call's settlement, as `LedgerUsageRecorder` writes it with its permit."""
    return await stack.ledger.settle(
        UsageEvent(
            id=permit.call_id,
            occurred_at=permit.occurred_at,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            run_id=context.run_id,
            root_run_id=context.lease_root,
            lease_id=permit.lease_id,
            operation="chat",
            purpose="run",
            payer="platform",
            actor_kind="user",
            provider="openai_compatible",
            model="gpt-4.1",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_source="computed",
            price_book_version="1.0.0",
            cost_usd=Decimal(usd),
        )
    )


# ---- admission (R4.1, R4.4, R4.10, R5.1, R5.8) --------------------------------


async def test_a_run_passes_only_while_the_plan_the_company_and_the_workspace_have_some_left(
    stack: Stack,
) -> None:
    """R4.1: three scopes with a limit, each counted; the lease holds the least."""
    company = await stack.company(cost_usd_per_month="100", max_cost_usd_per_run="2")
    await stack.policy(company, metric="cost_usd", window_kind="month", value="50")
    await stack.policy(
        company, metric="cost_usd", window_kind="month", value="1.5", workspace=company.main
    )
    await stack.limits.admit(run(company))
    (lease,) = await stack.leases(company)
    assert lease.reserved_usd == Decimal("1.5")
    counters = await stack.counters(company)
    assert counters[("tenant", "cost_usd", "month")] == (Decimal(0), Decimal("1.5"))
    assert counters[("workspace", "cost_usd", "month")] == (Decimal(0), Decimal("1.5"))


async def test_a_spent_period_refuses_with_its_numbers_and_changes_nothing(stack: Stack) -> None:
    """R4.10: `limit_exceeded` with the metric, scope, window, limit, used and
    `resets_at`; no lease, no counter moved."""
    company = await stack.company()
    await stack.policy(company, metric="cost_usd", window_kind="month", value="10")
    await stack.spent(company, "10")
    with pytest.raises(LimitExceededError) as refused:
        await stack.limits.admit(run(company))
    details = refused.value.details
    assert details["reason_code"] == "limit_exceeded"
    assert (details["metric"], details["scope_type"], details["window"]) == (
        "cost_usd",
        "tenant",
        "month",
    )
    assert (details["limit"], details["used"]) == ("10.00000000", "10.00000000")
    # The company's next month, in its own zone: 1 December 00:00 in Hanoi.
    assert details["resets_at"] == "2026-11-30T17:00:00+00:00"
    assert details["limit_source"] == "policy"
    assert await stack.leases(company) == []
    assert await stack.counters(company) == {}


async def test_a_workspace_above_its_spent_company_is_still_held_by_the_company(
    stack: Stack,
) -> None:
    """R4.4 (UL8): the company's USD 10 is spent; its workspace's USD 50 does
    not let a run through. W1 has no workspace tree, so a workspace's parent
    is its company."""
    company = await stack.company()
    await stack.policy(company, metric="cost_usd", window_kind="month", value="10")
    await stack.policy(
        company, metric="cost_usd", window_kind="month", value="50", workspace=company.main
    )
    await stack.spent(company, "10", workspace=company.main)
    with pytest.raises(LimitExceededError) as refused:
        await stack.limits.admit(run(company))
    assert refused.value.details["scope_type"] == "tenant"


async def test_a_month_with_one_dollar_left_admits_a_two_dollar_run_holding_one(
    stack: Stack,
) -> None:
    """R5.8 (UL2): the lease holds no more than every scope has left."""
    company = await stack.company(max_cost_usd_per_run="2")
    await stack.policy(company, metric="cost_usd", window_kind="month", value="5")
    await stack.spent(company, "4")
    await stack.limits.admit(run(company))
    (lease,) = await stack.leases(company)
    assert lease.reserved_usd == Decimal("1")


async def test_a_month_with_nothing_left_refuses(stack: Stack) -> None:
    """R5.8: USD 0 left is `limit_exceeded`, not a lease of nothing."""
    company = await stack.company()
    await stack.policy(company, metric="cost_usd", window_kind="month", value="5")
    await stack.spent(company, "5")
    with pytest.raises(LimitExceededError):
        await stack.limits.admit(run(company))


async def test_ten_runs_at_once_with_three_left_admit_exactly_three(stack: Stack) -> None:
    """R5.1 (UL2): the counters are locked in one order, so ten admissions at
    once never let a fourth through."""
    company = await stack.company(runs_per_day=3)
    outcomes = await asyncio.gather(
        *(stack.limits.admit(run(company)) for _ in range(10)), return_exceptions=True
    )
    refused = [o for o in outcomes if isinstance(o, LimitExceededError)]
    assert len(refused) == 7, outcomes
    assert len(await stack.leases(company)) == 3
    assert (await stack.counters(company))[("tenant", "runs", "day")][0] == Decimal(3)


async def test_ten_runs_at_once_never_reserve_more_than_the_month_has(stack: Stack) -> None:
    """R5.8 (UL2): USD 3 left, USD 1 a run: the sum held is at most 3."""
    company = await stack.company(max_cost_usd_per_run="1")
    await stack.policy(company, metric="cost_usd", window_kind="month", value="3")
    await asyncio.gather(
        *(stack.limits.admit(run(company)) for _ in range(10)), return_exceptions=True
    )
    leases = await stack.leases(company)
    assert sum(lease.reserved_usd for lease in leases) <= Decimal(3)
    assert (await stack.counters(company))[("tenant", "cost_usd", "month")][1] <= Decimal(3)


async def test_a_test_run_or_a_call_outside_a_run_spends_money_but_counts_no_run(
    stack: Stack,
) -> None:
    """R5.1: only a `live` root counts toward `runs`; a `test` run and a call no
    run holds (`counts_run=False`) reserve money all the same."""
    company = await stack.company(runs_per_day=1, cost_usd_per_month="100")
    await stack.limits.admit(run(company, run_mode="test"))
    await stack.limits.admit(run(company), counts_run=False)
    counters = await stack.counters(company)
    assert ("tenant", "runs", "day") not in counters
    assert counters[("tenant", "cost_usd", "month")][1] == Decimal(4)
    await stack.limits.admit(run(company))
    with pytest.raises(LimitExceededError) as refused:
        await stack.limits.admit(run(company))
    assert refused.value.details["metric"] == "runs"


async def test_a_root_taken_again_joins_its_open_lease_and_is_not_counted_twice(
    stack: Stack,
) -> None:
    """R5.1 (gate 4/11/2026 (l)): a process died and the run was handed out
    again while its lease is open."""
    company = await stack.company(runs_per_day=5)
    context = run(company)
    await stack.limits.admit(context)
    await stack.limits.admit(context)
    assert len(await stack.leases(company)) == 1
    assert (await stack.counters(company))[("tenant", "runs", "day")][0] == Decimal(1)


async def test_a_child_run_spends_its_roots_lease(stack: Stack) -> None:
    """R5.6: a child finds its root's lease, opens none of its own."""
    company = await stack.company()
    root = run(company)
    await stack.limits.admit(root)
    child = run(company, root_run_id=root.run_id)
    permit = await stack.limits.lease(child).before_call(child, estimate())
    (lease,) = await stack.leases(company)
    assert permit.lease_id == lease.id


async def test_unreadable_policies_refuse_with_limits_unavailable(stack: Stack) -> None:
    """R4.10: the policies cannot be read; nothing admitted, nothing written."""
    company = await stack.company()

    class Broken:
        def __call__(self) -> Any:
            raise sa.exc.OperationalError("SELECT", {}, Exception("down"))

    broken = SqlLimits(
        cast(async_sessionmaker[AsyncSession], Broken()), clock=stack.clock, ids=Uuid4Generator()
    )
    with pytest.raises(LimitsUnavailableError) as refused:
        await broken.admit(run(company))
    assert refused.value.details["reason_code"] == "limits_unavailable"
    assert await stack.leases(company) == []


async def test_a_company_whose_plan_has_no_limits_row_is_refused(stack: Stack) -> None:
    """UL1: a missing `plan_limits` row refuses, never reads as no limit."""
    company = await stack.company()
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.plan_limits WHERE plan_id = :p"), {"p": company.plan_id}
        )
    with pytest.raises(LimitsUnavailableError):
        await stack.limits.admit(run(company))


async def test_a_lowered_limit_binds_an_admission_in_another_process_at_once(
    stack: Stack, usage_db: DatabaseUrls
) -> None:
    """R4.8: a run held USD 5 under a monthly 50; the limit is lowered to 3 on
    another connection; the next admission, here and in a fresh process, holds
    3. Nothing of the first admission's limits is kept in a process."""
    company = await stack.company(max_cost_usd_per_run="5")
    await stack.policy(company, metric="cost_usd", window_kind="month", value="50")
    first = await stack.limits.admit(run(company))
    await first.release("completed")
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.limit_policies SET limit_value = 3 WHERE tenant_id = :t"),
            {"t": company.tenant_id},
        )
    here = run(company)
    await stack.limits.admit(here)
    (held,) = await stack.rows(
        company,
        "SELECT reserved_usd FROM platform.budget_leases WHERE root_run_id = :r",
        r=here.run_id,
    )
    assert held.reserved_usd == Decimal(3)
    await stack.limits.lease(here).release("completed")
    probe = Path(__file__).with_name("limits_admit_probe.py")
    done = subprocess.run(
        [sys.executable, str(probe), usage_db.app, str(company.tenant_id), str(company.main)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    assert Decimal(answer["reserved_usd"]) == Decimal(3), answer


# ---- calls (R5.2, R5.5, R5.8, R5.10) -------------------------------------------


async def test_a_lease_with_room_for_a_hundred_output_tokens_permits_no_more(
    stack: Stack,
) -> None:
    """R5.2 (UL3): `max_output_tokens` is what the lease has left after the input."""
    company = await stack.company(max_cost_usd_per_run="0.11")
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate(input_usd="0.01", per_token="0.001"))
    assert permit.max_output_tokens <= 100


async def test_an_input_the_lease_cannot_pay_tops_up_from_a_period_with_money_left(
    stack: Stack,
) -> None:
    """R5.8: 0.4 of input on a lease holding 0.3, the month has more: topped up."""
    company = await stack.company(max_cost_usd_per_run="2")
    context = run(company)
    lease = await stack.limits.admit(context)
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.budget_leases SET reserved_usd = 0.3 WHERE tenant_id = :t"),
            {"t": company.tenant_id},
        )
    permit = await lease.before_call(context, estimate(input_usd="0.4", per_token="0.001"))
    assert permit.max_output_tokens >= 1
    (row,) = await stack.leases(company)
    assert row.reserved_usd > Decimal("0.4")


async def test_an_input_neither_the_lease_nor_the_period_can_pay_is_refused_before_the_call(
    stack: Stack,
) -> None:
    """R5.10 (UL3): 0.4 of input, 0.3 held, the month spent: refused, and the
    ledger has no record of a call."""
    company = await stack.company(max_cost_usd_per_run="2")
    await stack.policy(company, metric="cost_usd", window_kind="month", value="0.3")
    context = run(company)
    lease = await stack.limits.admit(context)
    with pytest.raises(LimitExceededError) as refused:
        await lease.before_call(context, estimate(input_usd="0.4"))
    assert refused.value.details["metric"] == "cost_usd"
    assert await stack.rows(company, "SELECT 1 FROM platform.usage_events") == []


async def test_a_spent_run_ceiling_stops_the_next_call_and_names_the_run(stack: Stack) -> None:
    """R5.5 (UL13): the per-run ceiling spent mid-run stops the next call with
    `limit_exceeded`; the caller decides nothing cheaper."""
    company = await stack.company(max_cost_usd_per_run="0.05")
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate(input_usd="0.01", per_token="0.001"))
    assert await settle(stack, context, permit, "0.05")
    with pytest.raises(LimitExceededError) as refused:
        await lease.before_call(context, estimate(input_usd="0.01"))
    assert refused.value.details["scope_type"] == "run"


async def test_an_attempts_own_ceiling_stops_it_though_its_gate_lease_has_money(
    stack: Stack,
) -> None:
    """R5.6: an attempt of a gate run at USD 0.10 of its own ceiling."""
    company = await stack.company()
    gate = uuid.uuid4()
    await stack.limits.admit_gate(
        tenant_id=company.tenant_id,
        workspace_id=company.main,
        gate_run_id=gate,
        ceiling_usd=Decimal(2),
        payer="tenant",
    )
    attempt = run(company, gate_run_id=gate, cost_ceiling_usd=Decimal("0.10"))
    lease = stack.limits.lease(attempt)
    permit = await lease.before_call(attempt, estimate(input_usd="0.01"))
    assert await settle(stack, attempt, permit, "0.10")
    with pytest.raises(LimitExceededError) as refused:
        await lease.before_call(attempt, estimate(input_usd="0.01"))
    assert refused.value.details["reason"] == "cost_ceiling"
    assert len(await stack.leases(company)) == 1


async def test_a_gate_holds_its_ceiling_counts_no_run_and_refuses_on_a_spent_month(
    stack: Stack,
) -> None:
    """R5.6: USD 2 of a month with USD 5 left; then a month with nothing."""
    company = await stack.company(runs_per_day=1, cost_usd_per_month="5")
    await stack.limits.admit_gate(
        tenant_id=company.tenant_id,
        workspace_id=company.main,
        gate_run_id=uuid.uuid4(),
        ceiling_usd=Decimal(2),
        payer="tenant",
    )
    (lease,) = await stack.leases(company)
    assert (lease.purpose, lease.reserved_usd, lease.counted_run) == (
        "eval_offline",
        Decimal(2),
        False,
    )
    spent = await stack.company(cost_usd_per_month="5")
    await stack.spent(spent, "5")
    with pytest.raises(LimitExceededError):
        await stack.limits.admit_gate(
            tenant_id=spent.tenant_id,
            workspace_id=spent.main,
            gate_run_id=uuid.uuid4(),
            ceiling_usd=Decimal(2),
            payer="tenant",
        )
    assert await stack.leases(spent) == []


async def test_a_gate_the_platform_pays_for_moves_no_counter_of_the_company(
    stack: Stack,
) -> None:
    """DO-29.2 (a): a re-evaluation the platform caused."""
    company = await stack.company(cost_usd_per_month="5")
    await stack.spent(company, "5")
    await stack.limits.admit_gate(
        tenant_id=company.tenant_id,
        workspace_id=company.main,
        gate_run_id=uuid.uuid4(),
        ceiling_usd=Decimal(2),
        payer="platform",
    )
    assert await stack.counters(company) == {}


# ---- settlement, waits, heartbeat, the reaper (R5.3, R5.4, R5.9, R5.11) --------


async def test_a_wait_gives_the_hold_back_and_the_resume_keeps_what_was_spent(
    stack: Stack,
) -> None:
    """R5.3 (UL11): paused, the run holds nothing; going on, its spent part
    still counts against its ceiling across leases, and `runs` is not counted
    again."""
    company = await stack.company(runs_per_day=5, max_cost_usd_per_run="1")
    await stack.policy(company, metric="cost_usd", window_kind="month", value="10")
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate())
    assert await settle(stack, context, permit, "0.4")
    assert await lease.release("paused")
    counters = await stack.counters(company)
    assert counters[("tenant", "cost_usd", "month")] == (Decimal("0.4"), Decimal(0))
    await stack.limits.resume(context)
    leases = await stack.leases(company)
    assert [row.state for row in leases] == ["closed", "open"]
    assert leases[1].reserved_usd == Decimal("0.6")
    assert (await stack.counters(company))[("tenant", "runs", "day")][0] == Decimal(1)


async def test_a_resume_on_a_spent_month_is_refused_as_an_admission(stack: Stack) -> None:
    """R5.3: the same `limit_exceeded`; `runs` does not move."""
    company = await stack.company(runs_per_day=5)
    await stack.policy(company, metric="cost_usd", window_kind="month", value="1")
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate(input_usd="0.01", per_token="0.001"))
    assert await settle(stack, context, permit, "1")
    await lease.release("paused")
    with pytest.raises(LimitExceededError):
        await stack.limits.resume(context)
    assert (await stack.counters(company))[("tenant", "runs", "day")][0] == Decimal(1)


async def test_a_beat_rolls_what_was_settled_once_however_many_beat_at_once(
    stack: Stack,
) -> None:
    """R5.9: two processes of one tree beat together; `used` moves once."""
    company = await stack.company()
    await stack.policy(company, metric="cost_usd", window_kind="month", value="10")
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate())
    await settle(stack, context, permit, "0.25")
    await asyncio.gather(lease.beat(), stack.limits.lease(context).beat())
    used, reserved = (await stack.counters(company))[("tenant", "cost_usd", "month")]
    assert used == Decimal("0.25")
    assert reserved == Decimal("1.75")


async def test_a_beaten_lease_outlives_a_six_minute_call(stack: Stack) -> None:
    """R5.9: beaten every minute, the reaper never closes it."""
    company = await stack.company()
    context = run(company)
    lease = await stack.limits.admit(context)
    await lease.before_call(context, estimate())
    (row,) = await stack.leases(company)
    for minute in range(1, 7):
        stack.clock.advance_to(NOW + timedelta(minutes=minute))
        assert await lease.beat()
        # Other tests' leases share the database; this one is never among them.
        assert row.id not in await stack.reaper.reap_stale(older_than=stack.clock.now())
    (row,) = await stack.leases(company)
    assert row.state == "open"


async def test_a_dead_process_lease_is_closed_its_call_estimated_and_audited_as_the_reaper(
    stack: Stack,
) -> None:
    """R5.4, R5.9 (UL6): five minutes without a beat; the call in flight
    becomes an `unsettled_estimate` keyed as its permit; the old run's next call
    is `lease_expired`."""
    company = await stack.company()
    await stack.policy(company, metric="cost_usd", window_kind="month", value="10")
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate(input_usd="0.01", per_token="0.001"))
    stack.clock.advance_to(NOW + timedelta(minutes=6))
    reaped = await stack.reaper.reap_stale(older_than=stack.clock.now())
    (row,) = await stack.leases(company)
    assert row.id in reaped
    assert (row.state, row.close_reason) == ("closed", "expired")
    (estimated,) = await stack.rows(
        company,
        "SELECT id, occurred_at, operation, cost_usd FROM platform.usage_events"
        " WHERE lease_id = :l",
        l=row.id,
    )
    assert (estimated.id, estimated.occurred_at) == (permit.call_id, permit.occurred_at)
    assert estimated.operation == "unsettled_estimate"
    used, reserved = (await stack.counters(company))[("tenant", "cost_usd", "month")]
    assert (used, reserved) == (estimated.cost_usd, Decimal(0))
    (audit,) = await stack.rows(
        company,
        "SELECT actor_id, details FROM platform.audit_events WHERE action = 'limits.lease.expired'",
    )
    assert audit.actor_id == system_actor("reaper").value
    assert audit.details["actor"] == "system:reaper"
    with pytest.raises(LimitExceededError) as refused:
        await lease.before_call(context, estimate())
    assert refused.value.details["reason"] == "lease_expired"


async def test_a_late_settlement_after_the_reaper_is_not_counted_twice(stack: Stack) -> None:
    """R5.11 (UL6): the live process's `after_call` meets the estimate's key."""
    company = await stack.company()
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate())
    stack.clock.advance_to(NOW + timedelta(minutes=6))
    await stack.reaper.reap_stale(older_than=stack.clock.now())
    assert await settle(stack, context, permit, "0.02") is False
    rows = await stack.rows(
        company, "SELECT id FROM platform.usage_events WHERE id = :c", c=permit.call_id
    )
    assert len(rows) == 1


async def test_the_reaper_closes_the_expired_leases_of_two_companies(stack: Stack) -> None:
    """R5.4: under `app.worker_drain` it finds both; each closes under its own tenant."""
    first, second = await stack.company(), await stack.company()
    for company in (first, second):
        await stack.limits.admit(run(company))
    stack.clock.advance_to(NOW + timedelta(minutes=6))
    assert len(await stack.reaper.reap_stale(older_than=stack.clock.now())) >= 2
    for company in (first, second):
        assert [row.state for row in await stack.leases(company)] == ["closed"]


async def test_an_unpriced_call_stops_the_runs_next_call(stack: Stack) -> None:
    """R2.5 with leases: an unknown cost is never zero."""
    company = await stack.company()
    context = run(company)
    lease = await stack.limits.admit(context)
    permit = await lease.before_call(context, estimate(input_usd=None, per_token=None))
    written = await stack.ledger.settle(
        UsageEvent(
            id=permit.call_id,
            occurred_at=permit.occurred_at,
            tenant_id=company.tenant_id,
            workspace_id=company.main,
            run_id=context.run_id,
            lease_id=permit.lease_id,
            operation="chat",
            purpose="run",
            payer="platform",
            actor_kind="user",
            provider="openai_compatible",
            model="gpt-4.1",
            input_tokens=10,
            output_tokens=1,
            cost_source="unpriced",
            price_book_version="1.0.0",
            cost_usd=None,
        )
    )
    assert written
    with pytest.raises(LimitExceededError) as refused:
        await lease.before_call(context, estimate())
    assert refused.value.details["reason"] == "unpriced_call"


async def test_another_companys_lease_is_never_reached(stack: Stack) -> None:
    """UL7: a lease is found under its own company only; another company's root
    id reads as no lease, and its rows are invisible."""
    mine, theirs = await stack.company(), await stack.company()
    context = run(theirs)
    await stack.limits.admit(context)
    intruder = run(mine, run_id=context.run_id)
    with pytest.raises(LimitExceededError):
        await stack.limits.lease(intruder).before_call(intruder, estimate())
    assert await stack.leases(mine) == []
    (row,) = await stack.leases(theirs)
    assert row.in_flight == {}
