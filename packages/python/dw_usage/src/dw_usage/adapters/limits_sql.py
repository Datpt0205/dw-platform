"""`LimitsPort` on PostgreSQL: the scope chain's counters and one lease per root
run (usage-and-limits R4.1, R4.4, R4.8, R4.10, R5.1-R5.11; ADR-0121 decisions
4-6).

Every method is one transaction under the lease's company, its tenant set per
transaction (`set_config(..., true)`), and reads what it decides on in that same
transaction: the policies and the plan (`_chain`), never a cache in this
process, so a limit lowered through the API binds the next admission in the
worker at once (R4.8, failure-modes #7).

Locks, always in one order so two admissions never wait on each other in a
circle: the lease row first, then the counters by scope rank, scope id, metric,
window kind and window start (ADR-0121 decision 5).

What a lease holds of each of its counters is `reserved - rolled`, at least 0
(`held`). Counters move only at admission, a top-up, a heartbeat's roll and the
close; a call's settlement moves the lease alone (`settle_into_lease`, written
with the usage record in one transaction), so a lease's `settled_*` is what its
calls cost and `rolled_*` how much of that the counters' `used` already holds.

An error reading the policies, the plan or the counters is
`LimitsUnavailableError`: no run is admitted on a guess.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, cast

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import CallEstimate, CallPermit, RunLease
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.limits import LEASE_EXPIRED, LimitExceededError, LimitsUnavailableError
from dw_kernel.ports import IdGenerator, UtcClock
from dw_observability.metrics import DW_LIMIT_REFUSALS_TOTAL
from dw_observability.telemetry import NullTelemetry, TelemetryPort
from dw_platform.adapters.persistence.lane_audit import append_across_tenants
from dw_platform.domain.audit import lane_audit_event
from dw_usage.adapters.ledger_rows import insert_usage_event
from dw_usage.domain.events import UsageEvent
from dw_usage.domain.limits import (
    PLAN_COLUMNS,
    CounterKey,
    LeasePurpose,
    Metric,
    PlanCaps,
    PolicyLimit,
    ScopeLimit,
    ScopeType,
    chain_limits,
    held,
    remaining,
)
from dw_usage.domain.windows import WindowKind, window_bounds

__all__ = [
    "LEASE_TTL",
    "SqlBudgetLeaseReaper",
    "SqlLimits",
    "SqlRunLease",
    "counter_now",
    "period_usage",
    "settle_into_lease",
]

_LOG = logging.getLogger("dw_usage.limits")

# A lease not beaten for this long belongs to a process that is gone (R5.9).
LEASE_TTL: Final = timedelta(seconds=300)
_REAPER_LANE: Final = "reaper"
_ZERO: Final = Decimal(0)

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")
_SET_DRAIN = sa.text("SELECT set_config('app.worker_drain', 'on', true)")

# The company's plan is its entitlement's, read now (never the run's copy).
_PLAN = sa.text(
    "SELECT e.plan_id, t.timezone, l.plan_id AS limits_plan, l.runs_per_day,"
    " l.cost_usd_per_day, l.cost_usd_per_month, l.tokens_per_month,"
    " l.max_cost_usd_per_run, l.max_tokens_per_run"
    " FROM platform.tenants t"
    " LEFT JOIN platform.entitlements e ON e.tenant_id = t.id"
    " LEFT JOIN platform.plan_limits l ON l.plan_id = e.plan_id"
    " WHERE t.id = :t"
)
_POLICIES = sa.text(
    "SELECT scope_type, scope_workspace_id, scope_artifact_id, metric, window_kind, limit_value"
    " FROM platform.limit_policies"
    " WHERE scope_type = 'tenant'"
    " OR (scope_type = 'workspace' AND scope_workspace_id = :w)"
    " OR (scope_type IN ('agent', 'workflow') AND scope_artifact_id = :a)"
)
_COUNTER = sa.text(
    "SELECT used, reserved FROM platform.budget_counters"
    " WHERE tenant_id = :t AND scope_type = :st AND scope_id = :sid AND metric = :m"
    " AND window_kind = :wk AND window_start = :ws FOR UPDATE"
)
_NEW_COUNTER = sa.text(
    "INSERT INTO platform.budget_counters"
    " (tenant_id, scope_type, scope_id, metric, window_kind, window_start, window_end,"
    " used, reserved)"
    " VALUES (:t, :st, :sid, :m, :wk, :ws, :we, :used, 0)"
    " ON CONFLICT DO NOTHING"
)
_MOVE_COUNTER = sa.text(
    "UPDATE platform.budget_counters"
    " SET used = used + :used, reserved = GREATEST(reserved + :reserved, 0)"
    " WHERE tenant_id = :t AND scope_type = :st AND scope_id = :sid AND metric = :m"
    " AND window_kind = :wk AND window_start = :ws"
)
_LEASE_COLUMNS: Final = (
    "id, tenant_id, workspace_id, run_id, root_run_id, artifact_id, purpose, payer,"
    " counted_run, counter_keys, cap_usd, cap_tokens, reserved_usd, reserved_tokens,"
    " settled_usd, settled_tokens, rolled_usd, rolled_tokens, in_flight, unpriced, state,"
    " close_reason, expires_at"
)
_OPEN_LEASE = sa.text(
    f"SELECT {_LEASE_COLUMNS} FROM platform.budget_leases"  # nosec B608 - fixed names
    " WHERE tenant_id = :t AND root_run_id = :r AND state = 'open' FOR UPDATE"
)
_LEASE_BY_ID = sa.text(
    f"SELECT {_LEASE_COLUMNS} FROM platform.budget_leases"  # nosec B608 - fixed names
    " WHERE id = :id FOR UPDATE"
)
_LAST_CLOSE = sa.text(
    "SELECT close_reason FROM platform.budget_leases"
    " WHERE tenant_id = :t AND root_run_id = :r ORDER BY opened_at DESC LIMIT 1"
)
_ROOT_SPENT = sa.text(
    "SELECT count(*) AS leases, COALESCE(sum(settled_usd), 0) AS usd,"
    " COALESCE(sum(settled_tokens), 0) AS tokens"
    " FROM platform.budget_leases WHERE tenant_id = :t AND root_run_id = :r"
)
_RUN_SPENT = sa.text(
    "SELECT COALESCE(sum(cost_usd), 0) FROM platform.usage_events"
    " WHERE tenant_id = :t AND run_id = :run"
)
_OPEN = sa.text(
    "INSERT INTO platform.budget_leases"
    " (id, tenant_id, workspace_id, run_id, root_run_id, artifact_id, purpose, payer,"
    " counted_run, counter_keys, cap_usd, cap_tokens, reserved_usd, reserved_tokens,"
    " opened_at, heartbeat_at, expires_at)"
    " VALUES (:id, :t, :w, :run, :r, :a, :purpose, :payer, :counted, CAST(:keys AS jsonb),"
    " :cap_usd, :cap_tokens, :usd, :tokens, :now, :now, :expires)"
)


def _unavailable(exc: Exception) -> LimitsUnavailableError:
    return LimitsUnavailableError(
        "Không đọc được hạn mức của lượt chạy", details={"error_type": type(exc).__name__}
    )


# ---- the chain ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Chain:
    plan: PlanCaps
    limits: list[ScopeLimit]
    timezone: str | None


async def _chain(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    artifact_id: uuid.UUID | None,
) -> _Chain:
    """The plan's caps and every policy of the chain, read now, in this
    transaction (R4.1, R4.8). A plan with no `plan_limits` row refuses (UL1)."""
    row = (await session.execute(_PLAN, {"t": tenant_id})).mappings().first()
    if row is None or row["limits_plan"] is None:
        raise LimitsUnavailableError(
            "Gói của công ty chưa có dòng hạn mức",
            details={"plan_id": None if row is None else row["plan_id"]},
        )
    plan = PlanCaps(
        plan_id=str(row["plan_id"]),
        periods={
            pair: None if row[column] is None else Decimal(row[column])
            for pair, column in PLAN_COLUMNS.items()
        },
        max_cost_usd_per_run=Decimal(row["max_cost_usd_per_run"]),
        max_tokens_per_run=int(row["max_tokens_per_run"]),
    )
    policies = [
        PolicyLimit(
            scope_type=cast(ScopeType, policy.scope_type),
            scope_id=(
                tenant_id
                if policy.scope_type == "tenant"
                else policy.scope_workspace_id
                if policy.scope_type == "workspace"
                else policy.scope_artifact_id
            ),
            metric=cast(Metric, policy.metric),
            window_kind=cast(WindowKind, policy.window_kind),
            limit_value=Decimal(policy.limit_value),
        )
        for policy in (
            await session.execute(_POLICIES, {"w": workspace_id, "a": artifact_id})
        ).all()
    ]
    return _Chain(plan, chain_limits(tenant_id, plan, policies), row["timezone"])


def _key(limit: ScopeLimit, timezone: str | None, at: datetime) -> CounterKey:
    window = window_bounds(timezone, limit.window_kind, at)
    return CounterKey(
        scope_type=limit.scope_type,
        scope_id=limit.scope_id,
        metric=limit.metric,
        window_kind=limit.window_kind,
        window_start=window.start,
        window_end=window.end,
    )


def _key_params(tenant_id: uuid.UUID, key: CounterKey) -> dict[str, Any]:
    return {
        "t": tenant_id,
        "st": key.scope_type,
        "sid": key.scope_id,
        "m": key.metric,
        "wk": key.window_kind,
        "ws": key.window_start,
        "we": key.window_end,
    }


def _key_json(key: CounterKey) -> dict[str, str]:
    return {
        "scope_type": key.scope_type,
        "scope_id": str(key.scope_id),
        "metric": key.metric,
        "window_kind": key.window_kind,
        "window_start": key.window_start.isoformat(),
        "window_end": key.window_end.isoformat(),
    }


def _key_of(value: Mapping[str, Any]) -> CounterKey:
    return CounterKey(
        scope_type=cast(ScopeType, value["scope_type"]),
        scope_id=uuid.UUID(str(value["scope_id"])),
        metric=cast(Metric, value["metric"]),
        window_kind=cast(WindowKind, value["window_kind"]),
        window_start=datetime.fromisoformat(str(value["window_start"])),
        window_end=datetime.fromisoformat(str(value["window_end"])),
    )


_SEEDS: Final[dict[str, str]] = {
    "cost_usd": "COALESCE(sum(cost_usd), 0)",
    "tokens": "COALESCE(sum(input_tokens + output_tokens), 0)",
}
_SEED_SCOPE: Final[dict[str, str]] = {
    "tenant": "",
    "workspace": " AND workspace_id = :sid",
    "agent": " AND artifact_id = :sid",
    "workflow": " AND artifact_id = :sid",
}


async def _seed(session: AsyncSession, tenant_id: uuid.UUID, key: CounterKey) -> Decimal:
    """What a counter is born holding: the window's usage so far at its scope,
    so a limit set mid-period does not count from zero (gate 4/11/2026 (o)).
    `runs` from the roots counted in the window, which their leases record."""
    scope = _SEED_SCOPE[key.scope_type]
    if key.metric == "runs":
        statement = sa.text(
            "SELECT count(*) FROM platform.budget_leases"  # nosec B608 - fixed fragments
            " WHERE tenant_id = :t AND counted_run AND opened_at >= :ws AND opened_at < :we" + scope
        )
    else:
        statement = sa.text(
            f"SELECT {_SEEDS[key.metric]} FROM platform.usage_events"  # nosec B608 - fixed
            " WHERE tenant_id = :t AND occurred_at >= :ws AND occurred_at < :we" + scope
        )
    found = await session.scalar(statement, _key_params(tenant_id, key))
    return Decimal(found or 0)


def _key_at(
    scope_type: ScopeType,
    scope_id: uuid.UUID,
    metric: Metric,
    window_kind: WindowKind,
    start: datetime,
    end: datetime,
) -> CounterKey:
    return CounterKey(scope_type, scope_id, metric, window_kind, start, end)


async def counter_now(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    scope_type: ScopeType,
    scope_id: uuid.UUID,
    metric: Metric,
    window_kind: WindowKind,
    start: datetime,
    end: datetime,
) -> tuple[Decimal, Decimal]:
    """A counter's `used` and `reserved` as they stand, for the screen; a period
    with no counter yet reads the usage its counter would be born with."""
    key = _key_at(scope_type, scope_id, metric, window_kind, start, end)
    row = (
        await session.execute(
            sa.text(
                "SELECT used, reserved FROM platform.budget_counters WHERE tenant_id = :t"
                " AND scope_type = :st AND scope_id = :sid AND metric = :m"
                " AND window_kind = :wk AND window_start = :ws"
            ),
            _key_params(tenant_id, key),
        )
    ).first()
    if row is None:
        return await _seed(session, tenant_id, key), _ZERO
    return Decimal(row.used), Decimal(row.reserved)


async def period_usage(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    scope_type: ScopeType,
    scope_id: uuid.UUID,
    metric: Metric,
    window_kind: WindowKind,
    start: datetime,
    end: datetime,
    *,
    create: bool,
) -> Decimal:
    """The period's counter for a policy just set, born with the usage so far
    (gate 4/11/2026 (o)); an existing counter is kept as it is."""
    key = _key_at(scope_type, scope_id, metric, window_kind, start, end)
    if create:
        return (await _lock_counter(session, tenant_id, key)).used
    used, _reserved = await counter_now(
        session, tenant_id, scope_type, scope_id, metric, window_kind, start, end
    )
    return used


@dataclass(frozen=True, slots=True)
class _Counter:
    key: CounterKey
    used: Decimal
    reserved: Decimal


async def _lock_counter(session: AsyncSession, tenant_id: uuid.UUID, key: CounterKey) -> _Counter:
    params = _key_params(tenant_id, key)
    row = (await session.execute(_COUNTER, params)).first()
    if row is None:
        await session.execute(
            _NEW_COUNTER, {**params, "used": await _seed(session, tenant_id, key)}
        )
        row = (await session.execute(_COUNTER, params)).first()
    if row is None:  # pragma: no cover - the insert above or a rival's commit made it
        raise LimitsUnavailableError(
            "Không đọc được bộ đếm hạn mức", details={"metric": key.metric}
        )
    return _Counter(key, Decimal(row.used), Decimal(row.reserved))


async def _move(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: CounterKey,
    *,
    used: Decimal = _ZERO,
    reserved: Decimal = _ZERO,
) -> None:
    if used or reserved:
        await session.execute(
            _MOVE_COUNTER, {**_key_params(tenant_id, key), "used": used, "reserved": reserved}
        )


# ---- the lease row ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Lease:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    run_id: uuid.UUID | None
    root_run_id: uuid.UUID
    artifact_id: uuid.UUID | None
    purpose: str
    payer: str
    keys: tuple[CounterKey, ...]
    cap_usd: Decimal
    cap_tokens: int
    reserved_usd: Decimal
    reserved_tokens: int
    settled_usd: Decimal
    settled_tokens: int
    rolled_usd: Decimal
    rolled_tokens: int
    in_flight: dict[str, dict[str, Any]]
    unpriced: bool
    state: str
    expires_at: datetime

    @property
    def flying_usd(self) -> Decimal:
        return sum((Decimal(str(c["usd"])) for c in self.in_flight.values()), _ZERO)

    @property
    def flying_tokens(self) -> int:
        return sum(int(c["tokens"]) for c in self.in_flight.values())


def _lease(row: Any) -> _Lease:
    keys = row.counter_keys or []
    return _Lease(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        root_run_id=row.root_run_id,
        artifact_id=row.artifact_id,
        purpose=row.purpose,
        payer=row.payer,
        keys=tuple(sorted((_key_of(k) for k in keys), key=lambda k: k.order)),
        cap_usd=Decimal(row.cap_usd),
        cap_tokens=int(row.cap_tokens),
        reserved_usd=Decimal(row.reserved_usd),
        reserved_tokens=int(row.reserved_tokens),
        settled_usd=Decimal(row.settled_usd),
        settled_tokens=int(row.settled_tokens),
        rolled_usd=Decimal(row.rolled_usd),
        rolled_tokens=int(row.rolled_tokens),
        in_flight=dict(row.in_flight or {}),
        unpriced=bool(row.unpriced),
        state=row.state,
        expires_at=row.expires_at,
    )


RollMode = Literal["beat", "close", "closed"]


async def _roll(session: AsyncSession, lease: _Lease, mode: RollMode) -> None:
    """Move what the lease settled since its last roll into its counters'
    `used` and out of their `reserved` (R5.9), under the lease row's lock.
    `close` gives back all it still holds; `closed` is a lease already given
    back, whose late settlement reaches `used` alone."""
    spent = {"cost_usd": lease.settled_usd - lease.rolled_usd}
    spent["tokens"] = Decimal(lease.settled_tokens - lease.rolled_tokens)
    holds = {
        "cost_usd": (lease.reserved_usd, lease.rolled_usd),
        "tokens": (Decimal(lease.reserved_tokens), Decimal(lease.rolled_tokens)),
    }
    for key in lease.keys:
        if key.metric == "runs":
            continue
        reserved, rolled = holds[key.metric]
        delta = spent[key.metric]
        before = held(reserved, rolled)
        if mode == "closed":
            given_back = _ZERO
        elif mode == "close":
            given_back = before
        else:
            given_back = before - held(reserved, rolled + delta)
        await _move(session, lease.tenant_id, key, used=delta, reserved=-given_back)
    await session.execute(
        sa.text(
            "UPDATE platform.budget_leases SET rolled_usd = settled_usd,"
            " rolled_tokens = settled_tokens WHERE id = :id"
        ),
        {"id": lease.id},
    )


async def _close(session: AsyncSession, lease: _Lease, reason: str, now: datetime) -> None:
    await _roll(session, lease, "close")
    await session.execute(
        sa.text(
            "UPDATE platform.budget_leases SET state = 'closed', close_reason = :reason,"
            " closed_at = :now WHERE id = :id"
        ),
        {"id": lease.id, "reason": reason, "now": now},
    )


async def settle_into_lease(session: AsyncSession, event: UsageEvent) -> None:
    """A permitted call's record, just written, moved into its lease (R5.11):
    its cost and tokens settled, its in-flight hold gone, an unpriced call
    marking the lease so the next call is refused (R2.5). Called by the ledger
    in the record's own transaction, only when the record was new: a record the
    reaper already wrote is the one settlement, never a second."""
    if event.lease_id is None:
        return
    row = (await session.execute(_LEASE_BY_ID, {"id": event.lease_id})).first()
    if row is None:
        return
    lease = _lease(row)
    flying = lease.in_flight.get(str(event.id))
    unpriced = event.cost_source == "unpriced"
    cost = (
        Decimal(str(flying["usd"])) if unpriced and flying is not None else event.cost_usd or _ZERO
    )
    await session.execute(
        sa.text(
            "UPDATE platform.budget_leases SET settled_usd = settled_usd + :usd,"
            " settled_tokens = settled_tokens + :tokens, in_flight = in_flight - :call,"
            " unpriced = unpriced OR :unpriced WHERE id = :id"
        ),
        {
            "id": lease.id,
            "usd": cost,
            "tokens": event.input_tokens + event.output_tokens,
            "call": str(event.id),
            "unpriced": unpriced,
        },
    )
    if lease.state != "open":
        # Given back already: the counters' `used` takes it directly.
        settled = replace(
            lease,
            settled_usd=lease.settled_usd + cost,
            settled_tokens=lease.settled_tokens + event.input_tokens + event.output_tokens,
        )
        await _roll(session, settled, "closed")


# ---- the port -------------------------------------------------------------


@dataclass(frozen=True)
class SqlLimits:
    """Implements `dw_agent_runtime.ports.LimitsPort`."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    ids: IdGenerator
    telemetry: TelemetryPort = field(default_factory=NullTelemetry)

    async def admit(self, run_context: RunContext, *, counts_run: bool = True) -> RunLease:
        return await self._open(
            run_context,
            purpose="run",
            counts_run=counts_run and run_context.run_mode == "live",
        )

    async def resume(self, run_context: RunContext) -> RunLease:
        return await self._open(run_context, purpose="run", counts_run=False)

    async def admit_gate(
        self,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        gate_run_id: uuid.UUID,
        ceiling_usd: Decimal,
        payer: Literal["tenant", "platform"],
    ) -> RunLease:
        return await self._open_for(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=None,
            root=gate_run_id,
            artifact_id=None,
            purpose="eval_offline",
            payer=payer,
            counts_run=False,
            cap_usd=ceiling_usd,
        )

    def lease(self, run_context: RunContext) -> RunLease:
        return SqlRunLease(self, run_context.tenant_id, run_context.lease_root)

    async def _open(
        self, run_context: RunContext, *, purpose: LeasePurpose, counts_run: bool
    ) -> RunLease:
        return await self._open_for(
            tenant_id=run_context.tenant_id,
            workspace_id=run_context.workspace_id,
            run_id=run_context.run_id,
            root=run_context.lease_root,
            artifact_id=run_context.artifact_id,
            purpose=purpose,
            payer="tenant",
            counts_run=counts_run,
            cap_usd=None,
        )

    async def _open_for(
        self,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID | None,
        root: uuid.UUID,
        artifact_id: uuid.UUID | None,
        purpose: LeasePurpose,
        payer: Literal["tenant", "platform"],
        counts_run: bool,
        cap_usd: Decimal | None,
    ) -> RunLease:
        now = self.clock.now()
        try:
            async with self.session_factory() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": str(tenant_id)})
                if (await session.execute(_OPEN_LEASE, {"t": tenant_id, "r": root})).first():
                    # A root re-taken while its lease is open (a process died and
                    # the run was handed out again, two children going on at once)
                    # joins it, and is not counted again (gate 4/11/2026 (l)).
                    return SqlRunLease(self, tenant_id, root)
                chain = await _chain(session, tenant_id, workspace_id, artifact_id)
                spent = (await session.execute(_ROOT_SPENT, {"t": tenant_id, "r": root})).one()
                # `runs` counts once per root, at its first lease (R5.1).
                count = counts_run and int(spent.leases) == 0
                # A gate the platform pays for reaches no counter of the company.
                limits = [] if payer == "platform" else chain.limits
                by_key: dict[CounterKey, ScopeLimit] = {}
                counters: list[_Counter] = []
                for limit in limits:
                    if limit.metric == "runs" and not count:
                        continue
                    counter = await _lock_counter(
                        session, tenant_id, _key(limit, chain.timezone, now)
                    )
                    by_key[counter.key] = limit
                    counters.append(counter)
                cap = cap_usd if cap_usd is not None else chain.plan.max_cost_usd_per_run
                hold_usd = self._hold(
                    counters, by_key, "cost_usd", cap - Decimal(spent.usd), cap, Decimal(spent.usd)
                )
                hold_tokens = int(
                    self._hold(
                        counters,
                        by_key,
                        "tokens",
                        Decimal(chain.plan.max_tokens_per_run - int(spent.tokens)),
                        Decimal(chain.plan.max_tokens_per_run),
                        Decimal(spent.tokens),
                    )
                )
                for counter in counters:
                    if counter.key.metric == "runs":
                        self._require(counter, by_key[counter.key], need=Decimal(1))
                        await _move(session, tenant_id, counter.key, used=Decimal(1))
                    elif counter.key.metric == "cost_usd":
                        await _move(session, tenant_id, counter.key, reserved=hold_usd)
                    else:
                        await _move(session, tenant_id, counter.key, reserved=Decimal(hold_tokens))
                await session.execute(
                    _OPEN,
                    {
                        "id": self.ids.new_uuid(),
                        "t": tenant_id,
                        "w": workspace_id,
                        "run": run_id,
                        "r": root,
                        "a": artifact_id,
                        "purpose": purpose,
                        "payer": payer,
                        "counted": count,
                        "keys": json.dumps([_key_json(c.key) for c in counters]),
                        "cap_usd": cap,
                        "cap_tokens": chain.plan.max_tokens_per_run,
                        "usd": hold_usd,
                        "tokens": hold_tokens,
                        "now": now,
                        "expires": now + LEASE_TTL,
                    },
                )
        except LimitExceededError as refused:
            self.telemetry.add_metric(
                DW_LIMIT_REFUSALS_TOTAL, 1, {"reason": str(refused.details["metric"])}
            )
            raise
        except LimitsUnavailableError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable(exc) from exc
        return SqlRunLease(self, tenant_id, root)

    def _hold(
        self,
        counters: Sequence[_Counter],
        by_key: Mapping[CounterKey, ScopeLimit],
        metric: Metric,
        run_left: Decimal,
        cap: Decimal,
        used_by_run: Decimal,
    ) -> Decimal:
        """No more than every counter of `metric` and the run's own ceiling have
        left (R5.8); nothing left of either refuses (R4.10)."""
        hold = run_left
        for counter in counters:
            if counter.key.metric != metric:
                continue
            self._require(counter, by_key[counter.key], need=_ZERO)
            left = remaining(by_key[counter.key].limit, counter.used, counter.reserved)
            hold = min(hold, left)
        if run_left <= 0:
            raise LimitExceededError(
                "Lượt chạy đã dùng hết trần của nó",
                metric=metric,
                scope_type="run",
                limit=cap,
                used=used_by_run,
            )
        return hold

    @staticmethod
    def _require(counter: _Counter, limit: ScopeLimit, *, need: Decimal) -> None:
        """Money and tokens need more than nothing left (`need` 0); a run needs
        a whole one (`need` 1; R5.1)."""
        left = remaining(limit.limit, counter.used, counter.reserved)
        if (left >= need) if need else (left > 0):
            return
        raise LimitExceededError(
            "Đã dùng hết hạn mức của kỳ này",
            metric=limit.metric,
            scope_type=limit.scope_type,
            window=limit.window_kind,
            limit=limit.limit,
            used=counter.used + counter.reserved,
            resets_at=counter.key.window_end,
            limit_source=limit.source,
        )


@dataclass(frozen=True)
class SqlRunLease:
    """Implements `dw_agent_runtime.ports.RunLease`: the open lease of one root,
    found anew by every call, so a resume's new lease is the one it spends."""

    limits: SqlLimits
    tenant_id: uuid.UUID
    root: uuid.UUID

    @property
    def root_run_id(self) -> uuid.UUID:
        return self.root

    async def before_call(self, run_context: RunContext, estimate: CallEstimate) -> CallPermit:
        now = self.limits.clock.now()
        try:
            async with self.limits.session_factory() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": str(self.tenant_id)})
                permit = await self._permit(session, run_context, estimate, now)
        except LimitExceededError as refused:
            self.limits.telemetry.add_metric(
                DW_LIMIT_REFUSALS_TOTAL, 1, {"reason": str(refused.details["metric"])}
            )
            raise
        except LimitsUnavailableError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable(exc) from exc
        return permit

    async def _permit(
        self,
        session: AsyncSession,
        run_context: RunContext,
        estimate: CallEstimate,
        now: datetime,
    ) -> CallPermit:
        row = (await session.execute(_OPEN_LEASE, {"t": self.tenant_id, "r": self.root})).first()
        if row is None:
            last = await session.scalar(_LAST_CLOSE, {"t": self.tenant_id, "r": self.root})
            raise LimitExceededError(
                "Lượt chạy không còn phần giữ trước nào đang mở",
                metric="cost_usd",
                scope_type="run",
                reason=LEASE_EXPIRED if last == "expired" else "lease_closed",
            )
        lease = _lease(row)
        if lease.unpriced:
            # A call of this run could not be priced: its cost is unknown, not
            # zero, so the run is at its ceiling (R2.5).
            raise LimitExceededError(
                "Một lời gọi của lượt chạy chưa có giá",
                metric="cost_usd",
                scope_type="run",
                reason="unpriced_call",
            )
        input_usd = estimate.input_cost_usd if estimate.input_cost_usd is not None else _ZERO
        need_tokens = estimate.input_tokens + 1
        avail_usd = lease.reserved_usd - lease.settled_usd - lease.flying_usd
        avail_tokens = lease.reserved_tokens - lease.settled_tokens - lease.flying_tokens
        if avail_usd <= input_usd or avail_tokens < need_tokens:
            lease = await self._top_up(session, lease, now)
            avail_usd = lease.reserved_usd - lease.settled_usd - lease.flying_usd
            avail_tokens = lease.reserved_tokens - lease.settled_tokens - lease.flying_tokens
        if run_context.cost_ceiling_usd is not None and run_context.run_id is not None:
            spent = Decimal(
                await session.scalar(_RUN_SPENT, {"t": self.tenant_id, "run": run_context.run_id})
                or 0
            )
            flying = sum(
                (
                    Decimal(str(c["usd"]))
                    for c in lease.in_flight.values()
                    if c.get("run_id") == str(run_context.run_id)
                ),
                _ZERO,
            )
            ceiling_left = run_context.cost_ceiling_usd - spent - flying
            if ceiling_left <= input_usd:
                raise LimitExceededError(
                    "Lần thử đã dùng hết trần chi phí của nó",
                    metric="cost_usd",
                    scope_type="run",
                    limit=run_context.cost_ceiling_usd,
                    used=spent,
                    reason="cost_ceiling",
                )
            avail_usd = min(avail_usd, ceiling_left)
        if avail_usd <= input_usd:
            raise LimitExceededError(
                "Phần giữ trước không đủ cho đầu vào của lời gọi",
                metric="cost_usd",
                scope_type="run",
                limit=lease.reserved_usd,
                used=lease.settled_usd,
            )
        if avail_tokens < need_tokens:
            raise LimitExceededError(
                "Phần giữ trước không đủ token cho đầu vào của lời gọi",
                metric="tokens",
                scope_type="run",
                limit=Decimal(lease.reserved_tokens),
                used=Decimal(lease.settled_tokens),
            )
        allowed = avail_tokens - estimate.input_tokens
        price = estimate.output_usd_per_token
        if price is not None and price > 0:
            allowed = min(allowed, math.floor((avail_usd - input_usd) / price))
        if estimate.max_output_tokens is not None:
            allowed = min(allowed, estimate.max_output_tokens)
        if allowed < 1:
            raise LimitExceededError(
                "Phần giữ trước không còn chỗ cho câu trả lời",
                metric="cost_usd",
                scope_type="run",
                limit=lease.reserved_usd,
                used=lease.settled_usd,
            )
        call_id = self.limits.ids.new_uuid()
        flying_usd = input_usd + (price or _ZERO) * allowed
        await session.execute(
            sa.text(
                "UPDATE platform.budget_leases SET in_flight = in_flight || CAST(:entry AS jsonb)"
                " WHERE id = :id"
            ),
            {
                "id": lease.id,
                "entry": json.dumps(
                    {
                        str(call_id): {
                            "at": now.isoformat(),
                            "usd": str(flying_usd),
                            "tokens": estimate.input_tokens + allowed,
                            "input_tokens": estimate.input_tokens,
                            "output_tokens": allowed,
                            "run_id": str(run_context.run_id),
                            "provider": estimate.provider,
                            "model": estimate.model,
                            "price_book_version": estimate.price_book_version,
                        }
                    }
                ),
            },
        )
        return CallPermit(
            lease_id=lease.id, call_id=call_id, occurred_at=now, max_output_tokens=allowed
        )

    async def _top_up(self, session: AsyncSession, lease: _Lease, now: datetime) -> _Lease:
        """Take more from the counters, up to what every scope and the run's
        ceiling still have left, under their locks in canonical order (R5.8)."""
        spent = (await session.execute(_ROOT_SPENT, {"t": self.tenant_id, "r": self.root})).one()
        prior_usd = Decimal(spent.usd) - lease.settled_usd
        prior_tokens = int(spent.tokens) - lease.settled_tokens
        limits: dict[tuple[str, uuid.UUID, str, str], ScopeLimit] = {}
        if lease.payer != "platform":
            chain = await _chain(session, self.tenant_id, lease.workspace_id, lease.artifact_id)
            limits = {
                (each.scope_type, each.scope_id, each.metric, each.window_kind): each
                for each in chain.limits
            }
        room: dict[str, Decimal] = {
            "cost_usd": lease.cap_usd
            - prior_usd
            - max(lease.reserved_usd, lease.settled_usd + lease.flying_usd),
            "tokens": Decimal(
                lease.cap_tokens
                - prior_tokens
                - max(lease.reserved_tokens, lease.settled_tokens + lease.flying_tokens)
            ),
        }
        counters: list[_Counter] = []
        for key in lease.keys:
            if key.metric == "runs":
                continue
            counter = await _lock_counter(session, self.tenant_id, key)
            counters.append(counter)
            limit = limits.get((key.scope_type, key.scope_id, key.metric, key.window_kind))
            if limit is not None:
                room[key.metric] = min(
                    room[key.metric], remaining(limit.limit, counter.used, counter.reserved)
                )
        extra_usd = max(room["cost_usd"], _ZERO)
        extra_tokens = max(int(room["tokens"]), 0)
        if not extra_usd and not extra_tokens:
            return lease
        grown = replace(
            lease,
            reserved_usd=lease.reserved_usd + extra_usd,
            reserved_tokens=lease.reserved_tokens + extra_tokens,
        )
        for counter in counters:
            if counter.key.metric == "cost_usd":
                delta = held(grown.reserved_usd, lease.rolled_usd) - held(
                    lease.reserved_usd, lease.rolled_usd
                )
            else:
                delta = held(Decimal(grown.reserved_tokens), Decimal(lease.rolled_tokens)) - held(
                    Decimal(lease.reserved_tokens), Decimal(lease.rolled_tokens)
                )
            await _move(session, self.tenant_id, counter.key, reserved=delta)
        await session.execute(
            sa.text(
                "UPDATE platform.budget_leases SET reserved_usd = :usd, reserved_tokens = :tokens"
                " WHERE id = :id"
            ),
            {"id": lease.id, "usd": grown.reserved_usd, "tokens": grown.reserved_tokens},
        )
        return grown

    async def abandon(self, permit: CallPermit) -> None:
        async with self.limits.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(self.tenant_id)})
            await session.execute(
                sa.text(
                    "UPDATE platform.budget_leases SET in_flight = in_flight - :call WHERE id = :id"
                ),
                {"id": permit.lease_id, "call": str(permit.call_id)},
            )

    async def beat(self) -> bool:
        now = self.limits.clock.now()
        async with self.limits.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(self.tenant_id)})
            row = (
                await session.execute(_OPEN_LEASE, {"t": self.tenant_id, "r": self.root})
            ).first()
            if row is None:
                return False
            lease = _lease(row)
            await _roll(session, lease, "beat")
            await session.execute(
                sa.text(
                    "UPDATE platform.budget_leases SET heartbeat_at = :now, expires_at = :expires"
                    " WHERE id = :id"
                ),
                {"id": lease.id, "now": now, "expires": now + LEASE_TTL},
            )
        return True

    async def release(self, reason: str) -> bool:
        now = self.limits.clock.now()
        async with self.limits.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(self.tenant_id)})
            row = (
                await session.execute(_OPEN_LEASE, {"t": self.tenant_id, "r": self.root})
            ).first()
            if row is None:
                return False
            await _close(session, _lease(row), reason, now)
        return True


@dataclass(frozen=True)
class SqlBudgetLeaseReaper:
    """The `budget_leases` target of the reaper lane (R5.4, R5.9): every open
    lease past `expires_at`, of every company, closed `expired`. Each call it
    was holding for becomes one `unsettled_estimate` record keyed as its permit
    was, so a late settlement from a process still alive meets that key and is
    not counted twice (R5.11). Audited `limits.lease.expired` as
    `system:reaper` (ADR 0011). Satisfies the reaper's `StaleReaperPort`."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    ids: IdGenerator

    async def reap_stale(self, *, older_than: datetime) -> Sequence[uuid.UUID]:
        del older_than  # a lease says when it expires; the lane's window is not its own
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            due = (
                await session.execute(
                    sa.text(
                        "SELECT id, tenant_id FROM platform.budget_leases"
                        " WHERE state = 'open' AND expires_at < :now ORDER BY expires_at"
                    ),
                    {"now": now},
                )
            ).all()
        closed: list[uuid.UUID] = []
        for lease_id, tenant_id in due:
            try:
                if await self._expire(lease_id, tenant_id, now):
                    closed.append(lease_id)
            except Exception:
                _LOG.exception(
                    "an expired lease could not be closed", extra={"lease_id": str(lease_id)}
                )
        return closed

    async def _expire(self, lease_id: uuid.UUID, tenant_id: uuid.UUID, now: datetime) -> bool:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant_id)})
            row = (await session.execute(_LEASE_BY_ID, {"id": lease_id})).first()
            if row is None:
                return False
            lease = _lease(row)
            if lease.state != "open" or lease.expires_at >= now:
                # Beaten since the list was read: alive after all.
                return False
            usd, tokens = _ZERO, 0
            for call_id, call in lease.in_flight.items():
                usd += Decimal(str(call["usd"]))
                tokens += int(call["tokens"])
                await self._estimate(session, lease, uuid.UUID(call_id), call)
            await session.execute(
                sa.text(
                    "UPDATE platform.budget_leases SET settled_usd = settled_usd + :usd,"
                    " settled_tokens = settled_tokens + :tokens, in_flight = '{}'::jsonb"
                    " WHERE id = :id"
                ),
                {"id": lease.id, "usd": usd, "tokens": tokens},
            )
            await _close(
                session,
                replace(
                    lease,
                    settled_usd=lease.settled_usd + usd,
                    settled_tokens=lease.settled_tokens + tokens,
                    in_flight={},
                ),
                "expired",
                now,
            )
            await append_across_tenants(
                session,
                [
                    lane_audit_event(
                        lane=_REAPER_LANE,
                        event_id=self.ids.new_uuid(),
                        tenant_id=TenantId(lease.tenant_id),
                        workspace_id=WorkspaceId(lease.workspace_id),
                        action="limits.lease.expired",
                        resource_type="budget_lease",
                        resource_id=str(lease.id),
                        occurred_at=now,
                        details={
                            "root_run_id": str(lease.root_run_id),
                            "unsettled_calls": len(lease.in_flight),
                            "unsettled_usd": str(usd),
                        },
                        run_id=lease.run_id,
                    )
                ],
            )
        return True

    async def _estimate(
        self, session: AsyncSession, lease: _Lease, call_id: uuid.UUID, call: Mapping[str, Any]
    ) -> None:
        priced = call.get("price_book_version") not in (None, "")
        await insert_usage_event(
            session,
            UsageEvent(
                id=call_id,
                occurred_at=datetime.fromisoformat(str(call["at"])),
                tenant_id=lease.tenant_id,
                workspace_id=lease.workspace_id,
                run_id=uuid.UUID(str(call["run_id"])) if call.get("run_id") else None,
                root_run_id=lease.root_run_id,
                lease_id=lease.id,
                operation="unsettled_estimate",
                purpose=lease.purpose,
                payer="platform",
                actor_kind="system",
                user_id=None,
                provider=str(call.get("provider") or "unknown"),
                model=str(call.get("model") or "unknown"),
                input_tokens=int(call.get("input_tokens", 0)),
                output_tokens=int(call.get("output_tokens", 0)),
                units={},
                cost_source="estimated" if priced else "unpriced",
                cost_usd=Decimal(str(call["usd"])) if priced else None,
                price_book_version=str(call.get("price_book_version") or "unpriced"),
                price_entry_ids=(),
            ),
        )
