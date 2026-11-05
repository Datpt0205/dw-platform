"""`platform.limit_policies` and the limit tables' retention, against real
Postgres (usage-and-limits ticket 03: R4.5, R4.8, R4.9, R4.12-R4.16, R5.7;
UL9, UL15, UL17, UL19, UL20).

The constraints are tried from the migrator, which bypasses RLS, and from
`dw_app`: what a CHECK or a composite key refuses, it refuses to both. The
store is driven as the API drives it; the retention lane with fragment sets
written by the test, never the shipped numbers.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_limits_db import NOW, Company, Stack, run

from dw_kernel.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
)
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.limits import LimitExceededError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.retention_policy import RETENTION_POLICY_PATH, load_retention_policy
from dw_usage.adapters.limit_policies_sql import SqlLimitPolicies
from dw_usage.adapters.limits_retention import SqlLimitsRetention
from dw_usage.application.limits import PolicyRef, SetPolicy
from dw_usage.domain.limits import Metric, ScopeType
from dw_usage.domain.windows import WindowKind

pytestmark = pytest.mark.integration


@dataclass
class Policies:
    stack: Stack

    @property
    def store(self) -> SqlLimitPolicies:
        return SqlLimitPolicies(self.stack.sessions, clock=self.stack.clock, ids=Uuid4Generator())

    def ref(
        self,
        company: Company,
        *,
        scope_type: str = "tenant",
        scope_id: uuid.UUID | None = None,
        metric: str = "cost_usd",
        window_kind: str = "month",
    ) -> PolicyRef:
        return PolicyRef(
            tenant_id=company.tenant_id,
            scope_type=cast(ScopeType, scope_type),
            scope_id=scope_id or company.tenant_id,
            metric=cast(Metric, metric),
            window_kind=cast(WindowKind, window_kind),
        )

    async def put(
        self, ref: PolicyRef, value: str, expected: int | None = None
    ) -> tuple[Decimal, int]:
        written = await self.store.put(
            SetPolicy(
                ref=ref,
                limit_value=Decimal(value),
                expected=None if expected is None else ExpectedVersion(expected),
                actor_id=uuid.uuid4(),
                workspace_id=uuid.uuid4(),
            )
        )
        return written.limit_value, written.version

    async def value(self, company: Company) -> list[tuple[Decimal, int]]:
        found = await self.stack.rows(
            company, "SELECT limit_value, version FROM platform.limit_policies"
        )
        return [(row.limit_value, row.version) for row in found]


@pytest.fixture
async def policies(
    usage_db: DatabaseUrls, migrator: AsyncEngine, app_sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[Policies]:
    yield Policies(Stack(migrator=migrator, sessions=app_sessions))


async def artifact(stack: Stack, company: Company, kind: str = "workflow") -> uuid.UUID:
    """A component of `company` (W1 registers `workflow` and `object`; `agent`
    joins with agent-builder)."""
    found = uuid.uuid4()
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name,"
                " owning_workspace_id, row_version) VALUES (:a, :t, :k, :n, :w, 1)"
            ),
            {
                "a": found,
                "t": company.tenant_id,
                "k": kind,
                "n": f"l_{found.hex[:12]}",
                "w": company.main,
            },
        )
    return found


async def insert(conn: Any, company: Company, **columns: Any) -> None:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "t": company.tenant_id,
        "st": "tenant",
        "w": None,
        "a": None,
        "m": "cost_usd",
        "wk": "month",
        "k": "hard",
        "v": Decimal(1),
        "by": uuid.uuid4(),
    }
    values.update(columns)
    await conn.execute(
        sa.text(
            "INSERT INTO platform.limit_policies (id, tenant_id, scope_type, scope_workspace_id,"
            " scope_artifact_id, metric, window_kind, kind, limit_value, created_by)"
            " VALUES (:id, :t, :st, :w, :a, :m, :wk, :k, :v, :by)"
        ),
        values,
    )


# ---- the table (R4.12, R4.13, R4.16, R4.8) -------------------------------------


async def test_a_scope_of_another_company_is_refused_even_by_the_migrator(
    policies: Policies,
) -> None:
    """R4.13 (UL17): the composite keys refuse a workspace or a component of
    company B on company A's row; A's own are accepted."""
    stack = policies.stack
    mine, theirs = await stack.company(), await stack.company()
    their_workflow = await artifact(stack, theirs)
    for columns in (
        {"st": "workspace", "w": theirs.main},
        {"st": "workflow", "a": their_workflow},
    ):
        with pytest.raises(IntegrityError, match="fk_limit_policies_tenant_id_"):
            async with stack.migrator.begin() as conn:
                await insert(conn, mine, **columns)
    async with stack.migrator.begin() as conn:
        await insert(conn, mine, st="workspace", w=mine.main)
        await insert(conn, mine, st="workflow", a=await artifact(stack, mine))


@pytest.mark.parametrize(
    "columns",
    [
        {"st": "workspace"},  # its column NULL
        {"st": "workspace", "a": "agent"},  # the other column set
        {"st": "tenant", "w": "main"},  # a tenant limit naming a workspace
        {"st": "user"},  # W2
        {"m": "tokens", "wk": "day"},  # not a pair of W1 (R4.16)
        {"m": "cost_usd_per_week"},
        {"k": "soft"},  # W2 (R4.8)
        {"v": Decimal(-1)},
    ],
)
async def test_the_checks_refuse_a_row_outside_w1_from_dw_app(
    policies: Policies, columns: dict[str, Any]
) -> None:
    """R4.12, R4.14, R4.16 (UL19), R4.8: as `dw_app`, under its company."""
    stack = policies.stack
    company = await stack.company()
    agent = await artifact(stack, company)
    resolved = {
        key: company.main if value == "main" else agent if value == "agent" else value
        for key, value in columns.items()
    }
    with pytest.raises(IntegrityError, match="ck_limit_policies_"):
        async with stack.sessions() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(company.tenant_id)},
            )
            await insert(session, company, **resolved)


async def test_a_deleted_workspace_or_component_takes_its_policies_with_it(
    policies: Policies,
) -> None:
    """R4.12: in the same statement as the delete, no orphan left."""
    stack = policies.stack
    company = await stack.company(workspaces=2)
    agent = await artifact(stack, company)
    async with stack.migrator.begin() as conn:
        await insert(conn, company, st="workspace", w=company.workspaces[1])
        await insert(conn, company, st="workflow", a=agent)
        await conn.execute(
            sa.text("DELETE FROM platform.workspaces WHERE id = :w"), {"w": company.workspaces[1]}
        )
        # A component is deleted only while its company is offboarding.
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": company.tenant_id},
        )
        await conn.execute(sa.text("DELETE FROM studio.artifacts WHERE id = :a"), {"a": agent})
    assert await policies.value(company) == []


# ---- the store (R4.5, R4.6, R4.8, R4.9, R4.15) ---------------------------------


async def test_a_new_limit_and_a_lowered_one_apply_at_once_and_are_audited(
    policies: Policies,
) -> None:
    """R4.8: one person, `limits.policy.set` with `before` and `after` in the
    write's transaction, `version` up by one."""
    stack = policies.stack
    company = await stack.company()
    ref = policies.ref(company)
    assert await policies.put(ref, "50") == (Decimal(50), 1)
    assert await policies.put(ref, "10", expected=1) == (Decimal(10), 2)
    audits = await stack.rows(
        company,
        "SELECT details FROM platform.audit_events WHERE action = 'limits.policy.set'"
        " ORDER BY occurred_at, (details->>'before') NULLS FIRST",
    )
    assert [(a.details["before"], a.details["after"]) for a in audits] == [
        (None, "50"),
        ("50.00000000", "10"),
    ]


async def test_a_raise_or_a_removal_takes_a_second_person_and_changes_nothing(
    policies: Policies,
) -> None:
    """R4.9 (UL15): 409 `second_person_required`, the effective limit stays 10."""
    stack = policies.stack
    company = await stack.company()
    ref = policies.ref(company)
    await policies.put(ref, "10")
    with pytest.raises(ConflictError) as raised:
        await policies.put(ref, "50", expected=1)
    assert raised.value.details["reason_code"] == "second_person_required"
    with pytest.raises(ConflictError) as removed:
        await policies.store.delete(ref, ExpectedVersion(1), workspace_id=company.main)
    assert removed.value.details["reason_code"] == "second_person_required"
    assert await policies.value(company) == [(Decimal(10), 1)]


async def test_a_limit_above_the_plans_cap_is_refused(policies: Policies) -> None:
    """R4.5 (UL9), R4.14: 422 `limit_above_plan`; a pair whose plan column is
    NULL takes any value."""
    stack = policies.stack
    company = await stack.company(tokens_per_month=1000)
    with pytest.raises(DomainError) as refused:
        await policies.put(policies.ref(company, metric="tokens", window_kind="month"), "1001")
    assert refused.value.details["reason_code"] == "limit_above_plan"
    assert await policies.value(company) == []
    await policies.put(policies.ref(company, metric="runs", window_kind="day"), "999999")


async def test_an_existing_policy_needs_its_version(policies: Policies) -> None:
    """R4.15 (UL20): 428 without `If-Match`, 412 stale; nothing changes."""
    stack = policies.stack
    company = await stack.company()
    ref = policies.ref(company)
    await policies.put(ref, "50")
    with pytest.raises(PreconditionRequiredError):
        await policies.put(ref, "40")
    with pytest.raises(PreconditionFailedError):
        await policies.put(ref, "40", expected=7)
    assert await policies.value(company) == [(Decimal(50), 1)]


async def test_two_lowerings_at_one_version_are_one_write_and_one_412(policies: Policies) -> None:
    """R4.15 (UL20): from 50, one to 30 and one to 40, both naming version 1:
    one lands, one is 412, and 40 never overwrites 30 as a raise."""
    stack = policies.stack
    company = await stack.company()
    ref = policies.ref(company)
    await policies.put(ref, "50")
    outcomes = await asyncio.gather(
        policies.put(ref, "30", expected=1),
        policies.put(ref, "40", expected=1),
        return_exceptions=True,
    )
    landed = [o for o in outcomes if isinstance(o, tuple)]
    failed = [o for o in outcomes if isinstance(o, PreconditionFailedError)]
    assert len(landed) == 1 and len(failed) == 1, outcomes
    assert await policies.value(company) == [(landed[0][0], 2)]


async def test_another_companys_workspace_or_a_component_of_the_wrong_kind(
    policies: Policies,
) -> None:
    """R4.6: another company's workspace is 404 like one that never existed;
    an `agent` limit set at a workflow is 422 `scope_kind_mismatch`; the company id
    of the path must be the caller's."""
    stack = policies.stack
    mine, theirs = await stack.company(), await stack.company()
    with pytest.raises(NotFoundError):
        await policies.put(policies.ref(mine, scope_type="workspace", scope_id=theirs.main), "1")
    with pytest.raises(NotFoundError):
        await policies.put(policies.ref(mine, scope_id=theirs.tenant_id), "1")
    workflow = await artifact(stack, mine)
    with pytest.raises(DomainError) as mismatch:
        await policies.put(policies.ref(mine, scope_type="agent", scope_id=workflow), "1")
    assert mismatch.value.details["reason_code"] == "scope_kind_mismatch"
    assert await policies.value(mine) == []
    assert await policies.value(theirs) == []


async def test_a_limit_set_mid_month_counts_what_the_month_already_spent(
    policies: Policies,
) -> None:
    """R4.8 (gate 4/11/2026 (o)): USD 40 spent in workspace W, then a USD 10
    limit for W: the next run in W is `limit_exceeded`."""
    stack = policies.stack
    company = await stack.company()
    await stack.spent(company, "40", workspace=company.main)
    await policies.put(policies.ref(company, scope_type="workspace", scope_id=company.main), "10")
    with pytest.raises(LimitExceededError) as refused:
        await stack.limits.admit(run(company))
    assert refused.value.details["scope_type"] == "workspace"


async def test_the_screen_lists_each_limit_with_its_counter_and_reset(
    policies: Policies,
) -> None:
    """`GET /api/v1/limits`: the plan's caps, the policies, the effective limit."""
    stack = policies.stack
    company = await stack.company(cost_usd_per_month="100")
    await stack.spent(company, "2", workspace=company.main)
    await policies.put(policies.ref(company, scope_type="workspace", scope_id=company.main), "7")
    lines = {
        (line.scope_type, line.metric, line.window_kind): line
        for line in await policies.store.lines(company.tenant_id)
    }
    company_line = lines[("tenant", "cost_usd", "month")]
    assert (company_line.limit_source, company_line.effective_limit, company_line.limit_value) == (
        "plan",
        Decimal(100),
        None,
    )
    workspace_line = lines[("workspace", "cost_usd", "month")]
    assert (workspace_line.effective_limit, workspace_line.version) == (Decimal(7), 1)
    assert workspace_line.used == Decimal(2)
    assert workspace_line.resets_at == datetime(2026, 11, 30, 17, tzinfo=UTC)


# ---- retention (R5.7) -----------------------------------------------------------


def _fragments(directory: Path, counters: int | None, leases: int | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, days in (("platform.budget_counters", counters), ("platform.budget_leases", leases)):
        path = directory / f"{name}.yaml"
        if days is None:
            path.unlink(missing_ok=True)
            continue
        path.write_text(
            f"days: {days}\npurger: row_delete\nenforced: true\ndescription: probe\n",
            encoding="utf-8",
        )
    return directory


async def _plant_counter(stack: Stack, company: Company, window_end: datetime) -> None:
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.budget_counters (tenant_id, scope_type, scope_id, metric,"
                " window_kind, window_start, window_end) VALUES (:t, 'tenant', :t, 'cost_usd',"
                " 'day', :s, :e)"
            ),
            {"t": company.tenant_id, "s": window_end - timedelta(days=1), "e": window_end},
        )


async def _plant_lease(stack: Stack, company: Company, closed_at: datetime | None) -> uuid.UUID:
    lease = uuid.uuid4()
    async with stack.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.budget_leases (id, tenant_id, workspace_id, root_run_id,"
                " purpose, payer, cap_usd, cap_tokens, state, close_reason, opened_at,"
                " heartbeat_at, expires_at, closed_at)"
                " VALUES (:id, :t, :w, :r, 'run', 'tenant', 1, 1, :state, :reason, :o, :o, :o,"
                " :c)"
            ),
            {
                "id": lease,
                "t": company.tenant_id,
                "w": company.main,
                "r": uuid.uuid4(),
                "state": "open" if closed_at is None else "closed",
                "reason": None if closed_at is None else "completed",
                "o": (closed_at or NOW) - timedelta(hours=1),
                "c": closed_at,
            },
        )
    return lease


async def test_the_lane_prunes_on_the_fragments_terms_and_only_them(
    policies: Policies, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """R5.7: 395 and 30 days: a counter ended 396 days ago and a lease closed
    31 days ago go; one ended 394 days ago and an open lease stay. A new number
    in the fragment is followed with no code change; without the leases'
    fragment no lease goes and the lane says so."""
    stack = policies.stack
    company = await stack.company()
    await _plant_counter(stack, company, NOW - timedelta(days=396))
    await _plant_counter(stack, company, NOW - timedelta(days=394))
    old = await _plant_lease(stack, company, NOW - timedelta(days=31))
    young = await _plant_lease(stack, company, NOW - timedelta(days=29))
    open_lease = await _plant_lease(stack, company, None)

    def lane(directory: Path) -> SqlLimitsRetention:
        return SqlLimitsRetention(
            session_factory=stack.sessions,
            policy=load_retention_policy(RETENTION_POLICY_PATH, directory),
            clock=FixedClock(NOW),
        )

    await lane(_fragments(tmp_path / "a", 395, 30)).prune()
    ends = await stack.rows(company, "SELECT window_end FROM platform.budget_counters")
    assert [row.window_end for row in ends] == [NOW - timedelta(days=394)]
    leases = {row.id for row in await stack.leases(company)}
    assert leases == {young, open_lease}

    await lane(_fragments(tmp_path / "b", 395, 28)).prune()
    assert {row.id for row in await stack.leases(company)} == {open_lease}

    again = await _plant_lease(stack, company, NOW - timedelta(days=60))
    with caplog.at_level("ERROR", logger="dw_usage.limits_retention"):
        await lane(_fragments(tmp_path / "c", 395, None)).prune()
    assert {row.id for row in await stack.leases(company)} == {open_lease, again}
    assert "configuration error" in caplog.text and "platform.budget_leases" in caplog.text
    assert old not in leases
