"""`platform.limit_policies` in PostgreSQL, as the limits screen reads and sets
them (usage-and-limits R4.5, R4.6, R4.8, R4.9, R4.12-R4.15).

Every statement runs under the caller's company, set per transaction from the
verified context. A workspace or a component of another company is invisible
under that RLS, so it is 404 like one that never existed; the composite
foreign keys of the migration refuse such a row even from a role that bypasses
RLS (R4.13). The write's decision is taken on the row locked `FOR UPDATE`, so
two concurrent lowerings cannot end as one raise (R4.15).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PreconditionFailedError,
)
from dw_kernel.http_conditions import ExpectedVersion, parse_if_match
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.domain.audit import AuditEvent
from dw_usage.adapters.limits_sql import counter_now, period_usage
from dw_usage.application.limits import (
    LIMIT_ABOVE_PLAN,
    SCOPE_KIND_MISMATCH,
    SECOND_PERSON_REQUIRED,
    LimitLine,
    PolicyRef,
    PolicyWrite,
    SetPolicy,
)
from dw_usage.domain.limits import (
    LIMIT_PAIRS,
    PLAN_COLUMNS,
    LimitSource,
    Metric,
    ScopeType,
    scope_rank,
)
from dw_usage.domain.windows import WindowKind, window_bounds

__all__ = ["SqlLimitPolicies"]

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")
_SCOPE_COLUMN = {"workspace": "scope_workspace_id", "agent": "scope_artifact_id"}
_SCOPE_COLUMN["workflow"] = "scope_artifact_id"

_PLAN = sa.text(
    "SELECT t.timezone, l.runs_per_day, l.cost_usd_per_day, l.cost_usd_per_month,"
    " l.tokens_per_month"
    " FROM platform.tenants t"
    " LEFT JOIN platform.entitlements e ON e.tenant_id = t.id"
    " LEFT JOIN platform.plan_limits l ON l.plan_id = e.plan_id"
    " WHERE t.id = :t"
)
_ROW = (
    "SELECT id, limit_value, version FROM platform.limit_policies"
    " WHERE scope_type = :st AND metric = :m AND window_kind = :wk AND {where} FOR UPDATE"
)


def _ref_where(ref: PolicyRef) -> str:
    if ref.scope_type == "tenant":
        return "scope_workspace_id IS NULL AND scope_artifact_id IS NULL"
    return f"{_SCOPE_COLUMN[ref.scope_type]} = :sid"


@dataclass(frozen=True)
class SqlLimitPolicies:
    """Implements `dw_usage.application.limits.LimitPolicyStorePort`."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    ids: IdGenerator

    # ---- the screen --------------------------------------------------------

    async def lines(self, tenant_id: uuid.UUID) -> list[LimitLine]:
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant_id)})
            plan = (await session.execute(_PLAN, {"t": tenant_id})).mappings().first()
            timezone = None if plan is None else plan["timezone"]
            plans: dict[tuple[str, str], Decimal | None] = {
                pair: None if plan is None or plan[col] is None else Decimal(plan[col])
                for pair, col in PLAN_COLUMNS.items()
            }
            policies = (
                await session.execute(
                    sa.text(
                        "SELECT scope_type, scope_workspace_id, scope_artifact_id, metric,"
                        " window_kind, limit_value, version FROM platform.limit_policies"
                    )
                )
            ).all()
            # The company's own limit of each pair: the plan's cap, or a lower
            # policy (one counter serves both, gate 4/11/2026 (p)).
            company: dict[tuple[str, str], tuple[Decimal, LimitSource, Decimal | None, int | None]]
            company = {}
            for pair in LIMIT_PAIRS:
                if plans[pair] is not None:
                    company[pair] = (cast(Decimal, plans[pair]), "plan", None, None)
            rows: list[tuple[ScopeType, uuid.UUID, Any]] = []
            for policy in policies:
                pair = (policy.metric, policy.window_kind)
                if policy.scope_type == "tenant":
                    value = Decimal(policy.limit_value)
                    current = company.get(pair)
                    if current is None or value <= current[0]:
                        company[pair] = (value, "policy", value, policy.version)
                    else:
                        company[pair] = (current[0], current[1], value, policy.version)
                else:
                    scope_id = (
                        policy.scope_workspace_id
                        if policy.scope_type == "workspace"
                        else policy.scope_artifact_id
                    )
                    rows.append((cast(ScopeType, policy.scope_type), scope_id, policy))
            lines: list[LimitLine] = []
            for company_pair, (limit, source, own, version) in company.items():
                lines.append(
                    await self._line(
                        session,
                        tenant_id,
                        "tenant",
                        tenant_id,
                        company_pair,
                        own=own,
                        version=version,
                        plan_limit=plans[company_pair],
                        effective=limit,
                        source=source,
                        timezone=timezone,
                        now=now,
                    )
                )
            for scope_type, scope_id, policy in rows:
                pair = (policy.metric, policy.window_kind)
                own = Decimal(policy.limit_value)
                above = company.get(pair)
                effective = own if above is None else min(own, above[0])
                lines.append(
                    await self._line(
                        session,
                        tenant_id,
                        scope_type,
                        scope_id,
                        pair,
                        own=own,
                        version=policy.version,
                        plan_limit=None,
                        effective=effective,
                        source="policy",
                        timezone=timezone,
                        now=now,
                    )
                )
        return sorted(
            lines,
            key=lambda line: (
                scope_rank(line.scope_type),
                str(line.scope_id),
                line.metric,
                line.window_kind,
            ),
        )

    async def _line(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        scope_type: ScopeType,
        scope_id: uuid.UUID,
        pair: tuple[str, str],
        *,
        own: Decimal | None,
        version: int | None,
        plan_limit: Decimal | None,
        effective: Decimal,
        source: LimitSource,
        timezone: str | None,
        now: Any,
    ) -> LimitLine:
        metric, window_kind = cast(tuple[Metric, WindowKind], pair)
        window = window_bounds(timezone, window_kind, now)
        used, reserved = await counter_now(
            session, tenant_id, scope_type, scope_id, metric, window_kind, window.start, window.end
        )
        return LimitLine(
            scope_type=scope_type,
            scope_id=scope_id,
            metric=metric,
            window_kind=window_kind,
            limit_value=own,
            version=version,
            plan_limit=plan_limit,
            effective_limit=effective,
            limit_source=source,
            used=used,
            reserved=reserved,
            resets_at=window.end,
        )

    # ---- one policy --------------------------------------------------------

    async def put(self, command: SetPolicy) -> PolicyWrite:
        ref = command.ref
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(ref.tenant_id)})
            await self._require_scope(session, ref)
            plan = (await session.execute(_PLAN, {"t": ref.tenant_id})).mappings().first()
            cap = None if plan is None else plan[PLAN_COLUMNS[(ref.metric, ref.window_kind)]]
            if cap is not None and command.limit_value > Decimal(cap):
                raise DomainError(
                    "Hạn mức cao hơn Trần của gói",
                    details={"reason_code": LIMIT_ABOVE_PLAN, "plan_limit": str(cap)},
                )
            row = (
                await session.execute(
                    sa.text(_ROW.format(where=_ref_where(ref))),
                    {
                        "st": ref.scope_type,
                        "m": ref.metric,
                        "wk": ref.window_kind,
                        "sid": ref.scope_id,
                    },
                )
            ).first()
            if row is None:
                if command.expected is not None:
                    raise PreconditionFailedError(
                        "Không có hạn mức ở phiên bản này",
                        details={"header": "If-Match", "reason": "stale"},
                    )
                version = 1
                await session.execute(
                    sa.text(
                        "INSERT INTO platform.limit_policies (id, tenant_id, scope_type,"
                        " scope_workspace_id, scope_artifact_id, metric, window_kind, kind,"
                        " limit_value, version, created_by)"
                        " VALUES (:id, :t, :st, :w, :a, :m, :wk, 'hard', :v, 1, :by)"
                    ),
                    {
                        "id": self.ids.new_uuid(),
                        "t": ref.tenant_id,
                        "st": ref.scope_type,
                        "w": ref.scope_id if ref.scope_type == "workspace" else None,
                        "a": ref.scope_id if ref.scope_type in ("agent", "workflow") else None,
                        "m": ref.metric,
                        "wk": ref.window_kind,
                        "v": command.limit_value,
                        "by": command.actor_id,
                    },
                )
                # Born with the period's usage so far, not zero (gate (o)).
                window = window_bounds(
                    None if plan is None else plan["timezone"], ref.window_kind, now
                )
                await period_usage(
                    session,
                    ref.tenant_id,
                    ref.scope_type,
                    ref.scope_id,
                    ref.metric,
                    ref.window_kind,
                    window.start,
                    window.end,
                    create=True,
                )
                before: str | None = None
            else:
                expected = _required(command.expected)
                if not expected.matches(int(row.version)):
                    raise PreconditionFailedError(
                        "Hạn mức đã đổi kể từ lúc được đọc",
                        details={"header": "If-Match", "reason": "stale"},
                    )
                current = Decimal(row.limit_value)
                if command.limit_value > current:
                    raise ConflictError(
                        "Nới hạn mức cần người thứ hai duyệt, chưa có ở bản này",
                        details={"reason_code": SECOND_PERSON_REQUIRED},
                    )
                version = int(row.version) + (command.limit_value != current)
                await session.execute(
                    sa.text(
                        "UPDATE platform.limit_policies SET limit_value = :v, version = :ver"
                        " WHERE id = :id"
                    ),
                    {"id": row.id, "v": command.limit_value, "ver": version},
                )
                before = str(current)
            if before is None or Decimal(before) != command.limit_value:
                await SqlAuditRepository(session).append(
                    AuditEvent(
                        id=self.ids.new_uuid(),
                        tenant_id=TenantId(ref.tenant_id),
                        workspace_id=WorkspaceId(command.workspace_id),
                        actor_id=UserId(command.actor_id),
                        action="limits.policy.set",
                        resource_type="limit_policy",
                        resource_id=f"{ref.scope_type}:{ref.scope_id}:{ref.metric}:{ref.window_kind}",
                        occurred_at=now,
                        details={
                            "scope_type": ref.scope_type,
                            "scope_id": str(ref.scope_id),
                            "metric": ref.metric,
                            "window_kind": ref.window_kind,
                            "before": before,
                            "after": str(command.limit_value),
                        },
                    )
                )
        return PolicyWrite(ref=ref, limit_value=command.limit_value, version=version)

    async def delete(
        self, ref: PolicyRef, expected: ExpectedVersion | None, *, workspace_id: uuid.UUID
    ) -> None:
        del workspace_id  # nothing is written: no audit to place
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(ref.tenant_id)})
            await self._require_scope(session, ref)
            row = (
                await session.execute(
                    sa.text(_ROW.format(where=_ref_where(ref))),
                    {
                        "st": ref.scope_type,
                        "m": ref.metric,
                        "wk": ref.window_kind,
                        "sid": ref.scope_id,
                    },
                )
            ).first()
            if row is None:
                raise NotFoundError("Không có hạn mức này")
            if not _required(expected).matches(int(row.version)):
                raise PreconditionFailedError(
                    "Hạn mức đã đổi kể từ lúc được đọc",
                    details={"header": "If-Match", "reason": "stale"},
                )
            # Removing a limit loosens it: two people, which W1 does not have.
            raise ConflictError(
                "Gỡ hạn mức cần người thứ hai duyệt, chưa có ở bản này",
                details={"reason_code": SECOND_PERSON_REQUIRED},
            )

    async def _require_scope(self, session: AsyncSession, ref: PolicyRef) -> None:
        """The scope is the caller's company or one of its workspaces or
        components, of the kind the path names (R4.6)."""
        if ref.scope_type == "tenant":
            if ref.scope_id != ref.tenant_id:
                raise NotFoundError("Không có công ty này")
            return
        if ref.scope_type == "workspace":
            found = await session.scalar(
                sa.text("SELECT 1 FROM platform.workspaces WHERE id = :id AND tenant_id = :t"),
                {"id": ref.scope_id, "t": ref.tenant_id},
            )
            if found is None:
                raise NotFoundError("Không có workspace này")
            return
        kind = await session.scalar(
            sa.text("SELECT kind FROM studio.artifacts WHERE id = :id AND tenant_id = :t"),
            {"id": ref.scope_id, "t": ref.tenant_id},
        )
        if kind is None:
            raise NotFoundError("Không có thành phần này")
        if kind != ref.scope_type:
            raise DomainError(
                "Thành phần không đúng loại mà đường dẫn nêu",
                details={"reason_code": SCOPE_KIND_MISMATCH, "kind": str(kind)},
            )


def _required(expected: ExpectedVersion | None) -> ExpectedVersion:
    """An existing policy is written only by a caller naming its version (R4.15)."""
    if expected is None:
        return parse_if_match(None)  # raises 428
    return expected
