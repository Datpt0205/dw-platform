"""SQL side of placing people in roles (tenant-rbac ticket 03, step 6).

Runs as `dw_app` under the caller's tenant: RLS bounds every read and write,
and the triggers of migration d2b57239ef50 judge each revocation (the hold
rule) and refuse any assignment written here without a confirmed proposal; so
this adapter never inserts an assignment, it proposes one. A refusal the
database makes is read back by `role_write_refusal`.

Lock order (org-and-principals ticket 03, step 4): the role rows a request
touches, by id, `FOR NO KEY UPDATE`, first; then the company row and the
memberships, whose writes bump the tenant's access-version row.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.role_admin_repo import (
    ask_refusals,
    insert_proposal,
    scope_of,
)
from dw_platform.adapters.persistence.role_refusals import role_write_refusal
from dw_platform.adapters.persistence.tenant_member_rows import ensure_tenant_member
from dw_platform.adapters.persistence.tenant_session import tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.role_admin import (
    ACTION_REVOKE,
    AuditFactory,
    NewProposal,
    Refusal,
)
from dw_platform.application.role_assignments import (
    AssignmentOutcome,
    AssignmentPlan,
    HeldRole,
    MemberHoldings,
    MembershipHolding,
    PersonRef,
    TenantRole,
)

_M = tables.memberships
_A = tables.role_assignments
_R = tables.tenant_roles
_ACTION_MEMBERSHIP_GRANT = "platform.membership.grant"
_ACTION_MEMBERSHIP_REVOKE = "platform.membership.revoke"
_ACTION_INVITED = "platform.member.invited"

# `platform.checker_candidates` stays the one owner of who may confirm; the
# filter drops only the person placed, whom `platform.rbac_refusals` already
# forbids to confirm their own grant (R6.4, R7.3; tenant-rbac/16).
_HAS_CHECKER_FOR = sa.text(
    "SELECT EXISTS (SELECT 1 FROM platform.checker_candidates("
    "CAST(:t AS uuid), CAST(:k AS text), CAST(:a AS uuid)) AS c(id)"
    " WHERE c.id IS DISTINCT FROM CAST(:x AS uuid))"
)
_HOLDINGS = sa.text(
    """
    SELECT m.id AS membership_id, m.workspace_id,
           a.id AS assignment_id, r.id AS role_id, r.key, r.kind
    FROM platform.memberships m
    LEFT JOIN platform.role_assignments a
      ON a.tenant_id = m.tenant_id AND a.membership_id = m.id
    LEFT JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
    WHERE m.tenant_id = CAST(:t AS uuid) AND m.user_id = CAST(:u AS uuid)
    """
)
_PERSON = sa.text(
    "SELECT u.kind, platform.is_digital_worker_principal(u.id) AS dw_principal"
    " FROM platform.users u WHERE u.id = CAST(:u AS uuid)"
)
_ROLES = sa.text(
    """
    SELECT r.id, r.key, r.kind, platform.role_is_critical(r.tenant_id, r.id) AS critical
    FROM platform.tenant_roles r
    WHERE r.tenant_id = CAST(:t AS uuid) AND r.key = ANY (CAST(:keys AS text[]))
      AND r.deleted_at IS NULL
    """
)


@dataclass(frozen=True)
class SqlRoleAssignmentRepository:
    """Implements ``RoleAssignmentRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def holdings(self, context: AccessContext, user_id: uuid.UUID) -> MemberHoldings | None:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            return await _holdings(session, context, user_id)

    async def tenant_roles(
        self, context: AccessContext, keys: frozenset[str]
    ) -> Mapping[str, TenantRole]:
        if not keys:
            return {}
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            rows = await session.execute(
                _ROLES, {"t": str(context.tenant_id), "keys": sorted(keys)}
            )
            return {r.key: TenantRole(r.id, r.key, r.kind, bool(r.critical)) for r in rows}

    async def refusals(
        self, context: AccessContext, changes: Sequence[Mapping[str, object]]
    ) -> list[Refusal]:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            return await ask_refusals(session, context, changes)

    async def has_checker(
        self, context: AccessContext, permission: str, *, assignee: uuid.UUID | None = None
    ) -> bool:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            found = await session.scalar(
                _HAS_CHECKER_FOR,
                {
                    "t": str(context.tenant_id),
                    "k": permission,
                    "a": str(context.principal_id),
                    "x": None if assignee is None else str(assignee),
                },
            )
            return bool(found)

    async def find_person(self, email: str) -> PersonRef | None:
        u = tables.users
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    sa.select(u.c.id, u.c.email, u.c.display_name).where(
                        sa.func.lower(u.c.email) == email.strip().lower(), tables.HUMAN
                    )
                )
            ).first()
        return None if row is None else PersonRef(row.id, row.email, row.display_name)

    async def open_grants(self, context: AccessContext, user_id: uuid.UUID) -> list[uuid.UUID]:
        """The person's `assignment_grant` proposals still waiting, oldest first."""
        req = tables.role_change_requests
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            rows = await session.execute(
                sa.select(req.c.id)
                .where(
                    req.c.tenant_id == context.tenant_id,
                    req.c.status == "proposed",
                    req.c.kind == "assignment_grant",
                    req.c.payload["user_id"].astext == str(user_id),
                    req.c.proposed_at > sa.text("now() - interval '7 days'"),
                )
                .order_by(req.c.proposed_at, req.c.id)
            )
            return [row.id for row in rows]

    async def apply(
        self,
        context: AccessContext,
        plan: AssignmentPlan,
        *,
        audits: AuditFactory,
        member_status: Literal["invited", "active"] | None = None,
        department: str = "general",
        effect: PendingEffect | None = None,
    ) -> AssignmentOutcome:
        assert plan.user_id is not None
        try:
            async with tenant_session(self.session_factory, scope_of(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(plan.user_id))
                return await _write(
                    session,
                    context,
                    plan,
                    plan.user_id,
                    audits=audits,
                    member_status=member_status,
                    department=department,
                )
        except IntegrityError as exc:
            raise _refused(exc) from exc

    async def invite(
        self,
        context: AccessContext,
        *,
        display_name: str,
        email: str,
        plan: AssignmentPlan,
        audits: AuditFactory,
        effect: PendingEffect | None = None,
    ) -> tuple[PersonRef, AssignmentOutcome]:
        u = tables.users
        try:
            async with tenant_session(self.session_factory, scope_of(context)) as session:
                await _require_workspaces(session, context, set(plan.new_memberships))
                existing = (
                    await session.execute(
                        sa.select(u.c.id, u.c.email, u.c.display_name).where(
                            sa.func.lower(u.c.email) == email
                        )
                    )
                ).first()
                new_user_id = uuid.uuid4()
                if effect is not None:
                    await claim_effect_key(
                        session, effect.of(existing.id if existing is not None else new_user_id)
                    )
                if existing is None:
                    created = (
                        await session.execute(
                            pg_insert(u)
                            .values(
                                id=new_user_id,
                                subject=f"invite:{uuid.uuid4()}",
                                email=email,
                                display_name=display_name,
                            )
                            .on_conflict_do_nothing(index_elements=["email"])
                            .returning(u.c.id)
                        )
                    ).first()
                    if created is None:
                        raise _already_member()
                    person = PersonRef(created.id, email, display_name)
                else:
                    person = PersonRef(existing.id, existing.email, existing.display_name)
                    in_tenant = await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(_M)
                        .where(_M.c.tenant_id == context.tenant_id, _M.c.user_id == person.user_id)
                    )
                    if in_tenant:
                        raise _already_member()
                outcome = await _write(
                    session,
                    context,
                    plan,
                    person.user_id,
                    audits=audits,
                    member_status="invited",
                    department="general",
                    membership_action=_ACTION_INVITED,
                )
                return person, outcome
        except IntegrityError as exc:
            raise _refused(exc) from exc


async def _holdings(
    session: AsyncSession, context: AccessContext, user_id: uuid.UUID
) -> MemberHoldings | None:
    rows = (
        await session.execute(_HOLDINGS, {"t": str(context.tenant_id), "u": str(user_id)})
    ).all()
    if not rows:
        return None
    person = (await session.execute(_PERSON, {"u": str(user_id)})).one()
    memberships: dict[uuid.UUID, tuple[uuid.UUID, dict[str, HeldRole]]] = {}
    for row in rows:
        _, roles = memberships.setdefault(row.workspace_id, (row.membership_id, {}))
        if row.assignment_id is not None:
            roles[row.key] = HeldRole(row.assignment_id, row.role_id, row.key, row.kind)
    return MemberHoldings(
        user_id=user_id,
        kind=cast(Any, person.kind),
        dw_principal=bool(person.dw_principal),
        memberships={
            ws: MembershipHolding(membership_id=mid, roles=roles)
            for ws, (mid, roles) in memberships.items()
        },
    )


async def _write(
    session: AsyncSession,
    context: AccessContext,
    plan: AssignmentPlan,
    user_id: uuid.UUID,
    *,
    audits: AuditFactory,
    member_status: Literal["invited", "active"] | None,
    department: str,
    membership_action: str = _ACTION_MEMBERSHIP_GRANT,
) -> AssignmentOutcome:
    """One audit event per membership made (`membership_action`: an invitation's
    own, or a placement's), per role revoked, per membership dropped and per
    role proposed."""
    role_ids = sorted({r.role_id for r in plan.revokes} | {g.role_id for g in plan.grants}, key=str)
    versions: dict[uuid.UUID, int] = {}
    if role_ids:
        locked = await session.execute(
            sa.select(_R.c.id, _R.c.version)
            .where(_R.c.id.in_(role_ids))
            .order_by(_R.c.id)
            .with_for_update(key_share=True)
        )
        versions = {r.id: int(r.version) for r in locked}
    await _require_workspaces(session, context, set(plan.new_memberships))
    if member_status is not None:
        await session.execute(ensure_tenant_member(context.tenant_id, user_id, member_status))
    audit = SqlAuditRepository(session)
    for ws in plan.new_memberships:
        created = await session.scalar(
            pg_insert(_M)
            .values(
                id=uuid.uuid4(),
                tenant_id=context.tenant_id,
                workspace_id=ws,
                user_id=user_id,
                department=department,
            )
            .on_conflict_do_nothing(constraint="uq_memberships_scope_user")
            .returning(_M.c.id)
        )
        if created is not None:
            await audit.append(
                audits.event(
                    membership_action,
                    "membership",
                    user_id,
                    {
                        "user_id": str(user_id),
                        "workspace_id": str(ws),
                        "membership_id": str(created),
                    },
                    workspace_id=ws,
                )
            )
    for revoke in plan.revokes:
        await session.execute(sa.delete(_A).where(_A.c.id == revoke.assignment_id))
        await audit.append(
            audits.event(
                ACTION_REVOKE,
                "role_assignment",
                revoke.assignment_id,
                {
                    "role_id": str(revoke.role_id),
                    "role_key": revoke.role_key,
                    "workspace_id": str(revoke.workspace_id),
                    "user_id": str(user_id),
                },
                workspace_id=revoke.workspace_id,
            )
        )
    for ws in plan.dropped_memberships:
        await session.execute(
            sa.delete(_M).where(
                _M.c.tenant_id == context.tenant_id,
                _M.c.workspace_id == ws,
                _M.c.user_id == user_id,
            )
        )
        await audit.append(
            audits.event(
                _ACTION_MEMBERSHIP_REVOKE,
                "membership",
                user_id,
                {"user_id": str(user_id), "workspace_id": str(ws)},
                workspace_id=ws,
            )
        )
    proposals: list[uuid.UUID] = []
    for grant in plan.grants:
        membership_id = await session.scalar(
            sa.select(_M.c.id).where(
                _M.c.tenant_id == context.tenant_id,
                _M.c.workspace_id == grant.workspace_id,
                _M.c.user_id == user_id,
            )
        )
        proposal = NewProposal(
            id=uuid.uuid4(),
            kind="assignment_grant",
            role_id=grant.role_id,
            base_version=versions.get(grant.role_id),
            payload={
                "membership_id": str(membership_id),
                "workspace_id": str(grant.workspace_id),
                "user_id": str(user_id),
                "role_key": grant.role_key,
            },
        )
        written = await insert_proposal(session, context, proposal, proposal.base_version)
        await audit.append(audits.proposed(proposal))
        proposals.append(written.id)
    return AssignmentOutcome(user_id=user_id, applied=plan.revokes, proposals=tuple(proposals))


async def _require_workspaces(
    session: AsyncSession, context: AccessContext, workspace_ids: set[uuid.UUID]
) -> None:
    if not workspace_ids:
        return
    w = tables.workspaces
    found = set(
        (
            await session.execute(
                sa.select(w.c.id).where(
                    w.c.tenant_id == context.tenant_id, w.c.id.in_(workspace_ids)
                )
            )
        ).scalars()
    )
    missing = workspace_ids - found
    if missing:
        raise NotFoundError(
            "workspace not found in this tenant",
            details={"workspace_ids": sorted(str(ws) for ws in missing)},
        )


def _already_member() -> ConflictError:
    return ConflictError(
        "a person with that email is already a member of this organisation",
        details={"reason_code": "member_email_exists_in_tenant"},
    )


def _refused(error: IntegrityError) -> Exception:
    known = role_write_refusal(error)
    return known if known is not None else error
