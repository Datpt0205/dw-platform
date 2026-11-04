"""SQL side of role administration (tenant-rbac ticket 03).

Runs as `dw_app` under the caller's tenant (`tenant_session`), so RLS bounds
every read and write to it and the triggers of migration d2b57239ef50 judge
the caller in `app.user_id`. The service asks `platform.rbac_refusals` before a
write; the triggers ask it again for the write itself, and a refusal there is
read back by `role_write_refusal`.

Lock order (org-and-principals ticket 03, step 4): a write that touches a role
locks its row `FOR NO KEY UPDATE` before anything bumps the tenant's
access-version row. The confirmation locks the proposal, then the role, then
writes.

A confirmation applies its proposal in this caller's transaction, after the
proposal turned `confirmed` and `app.role_change_id` names it, never inside a
savepoint: the guard compares the proposal row's `xmin` with this
transaction's id, and a savepoint's write would carry another.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import (
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
)
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.keyset import after_position, newest_first
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.role_refusals import role_write_refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.role_admin import (
    CatalogueKey,
    ConfirmAudits,
    ConfirmOutcome,
    NewProposal,
    Privilege,
    Proposal,
    ProposalKind,
    ProposalStatus,
    Refusal,
    RoleAssignmentRow,
    RoleDetail,
    RoleSummary,
    RoleTemplate,
    conflict,
    diff_privileges,
    rbac_refusal_error,
)
from dw_platform.domain.audit import AuditEvent

_R = tables.tenant_roles
_P = tables.tenant_role_permissions
_A = tables.role_assignments
_REQ = tables.role_change_requests

# `platform.rbac_refusals` for many changes in one round trip; a preview, so
# it takes no lock (the trigger takes it for the write).
REFUSALS = sa.text(
    """
    SELECT r.reason_code, r.permission_key, r.depth
    FROM jsonb_array_elements(CAST(:changes AS jsonb)) c(change)
    CROSS JOIN LATERAL platform.rbac_refusals(
        CAST(:t AS uuid), CAST(:a AS uuid), c.change, false
    ) r
    """
)
HAS_CHECKER = sa.text(
    "SELECT EXISTS (SELECT 1 FROM platform.checker_candidates("
    "CAST(:t AS uuid), CAST(:k AS text), CAST(:a AS uuid)))"
)
HOLDS = sa.text(
    "SELECT EXISTS (SELECT 1 FROM platform.effective_grants(CAST(:t AS uuid), CAST(:u AS uuid)) g"
    " WHERE g.permission_key = CAST(:k AS text))"
)
_ROLES = sa.text(
    """
    SELECT r.id, r.key, r.name, r.description, r.kind, r.is_system, r.template_key,
           r.version, r.updated_at,
           (SELECT count(DISTINCT m.user_id)
            FROM platform.role_assignments a
            JOIN platform.memberships m ON m.tenant_id = a.tenant_id AND m.id = a.membership_id
            WHERE a.tenant_id = r.tenant_id AND a.role_id = r.id) AS holder_count,
           NOT EXISTS (
               SELECT 1 FROM platform.rbac_refusals(
                   r.tenant_id, CAST(:a AS uuid),
                   jsonb_build_object('op', 'grant', 'role_id', r.id,
                                      'workspace_id', CAST(:w AS uuid)),
                   false)
           ) AS assignable_by_me
    FROM platform.tenant_roles r
    WHERE r.tenant_id = CAST(:t AS uuid) AND r.deleted_at IS NULL
    ORDER BY r.key
    """
)
_ROLE = sa.text(
    """
    SELECT r.id, r.key, r.name, r.description, r.kind, r.is_system, r.template_key,
           r.version, r.updated_at, r.deleted_at,
           (SELECT count(DISTINCT m.user_id)
            FROM platform.role_assignments a
            JOIN platform.memberships m ON m.tenant_id = a.tenant_id AND m.id = a.membership_id
            WHERE a.tenant_id = r.tenant_id AND a.role_id = r.id) AS holder_count,
           (SELECT coalesce(jsonb_agg(jsonb_build_array(g.permission_key, g.depth)
                                      ORDER BY g.permission_key), '[]'::jsonb)
            FROM platform.role_privileges(r.tenant_id, r.id) g) AS privileges
    FROM platform.tenant_roles r
    WHERE r.tenant_id = CAST(:t AS uuid)
    """
)
_TEMPLATES = sa.text(
    """
    SELECT t.key, t.name, t.kind,
           (SELECT coalesce(jsonb_agg(jsonb_build_array(g.permission_key, g.depth)
                                      ORDER BY g.permission_key), '[]'::jsonb)
            FROM platform.role_template_privileges(t.key) g
            JOIN platform.permissions p ON p.key = g.permission_key
            WHERE p.status <> 'retired') AS privileges
    FROM (
        SELECT key, name, scopes, 'role' AS kind FROM platform.roles
        UNION ALL
        SELECT s.key, s.name, s.scopes, 'permission_set' FROM platform.permission_sets s
        WHERE NOT EXISTS (SELECT 1 FROM platform.roles r WHERE r.key = s.key)
    ) t
    -- A template carrying a key no tenant may hold (`platform_admin`) is not
    -- offered; a retired key is dropped from what a new role would start with.
    WHERE NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(t.scopes) k(key)
        JOIN platform.permissions p ON p.key = k.key
        WHERE NOT p.tenant_grantable
    )
    ORDER BY t.key
    """
)


def scope_of(context: AccessContext) -> TenantScope:
    return TenantScope.from_access_context(context)


def _detail(row: Any) -> RoleDetail:
    return RoleDetail(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        kind=row.kind,
        is_system=row.is_system,
        template_key=row.template_key,
        holder_count=int(row.holder_count),
        version=int(row.version),
        updated_at=row.updated_at,
        deleted=row.deleted_at is not None,
        privileges=tuple(Privilege(k, d) for k, d in row.privileges),
    )


def proposal_of(row: Any) -> Proposal:
    return Proposal(
        id=row.id,
        kind=cast(ProposalKind, row.kind),
        role_id=row.role_id,
        base_version=row.base_version,
        payload=dict(row.payload),
        required_permission=row.required_permission,
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
        expires_at=row.expires_at,
        status=cast(ProposalStatus, row.status),
        confirmed_by=row.confirmed_by,
        decided_at=row.decided_at,
    )


async def ask_refusals(
    session: AsyncSession, context: AccessContext, changes: Sequence[Mapping[str, object]]
) -> list[Refusal]:
    if not changes:
        return []
    rows = await session.execute(
        REFUSALS,
        {
            "changes": json.dumps(list(changes), default=str),
            "t": str(context.tenant_id),
            "a": str(context.principal_id),
        },
    )
    return [Refusal(r.reason_code, r.permission_key, r.depth) for r in rows]


async def lock_role(session: AsyncSession, role_id: uuid.UUID) -> Any:
    """The role row, `FOR NO KEY UPDATE`: the one lock per role (step 2)."""
    return (
        await session.execute(
            sa.select(_R.c.id, _R.c.key, _R.c.version, _R.c.deleted_at)
            .where(_R.c.id == role_id)
            .with_for_update(key_share=True)
        )
    ).first()


async def insert_proposal(
    session: AsyncSession, context: AccessContext, proposal: NewProposal, base_version: int | None
) -> Proposal:
    row = (
        await session.execute(
            sa.insert(_REQ)
            .values(
                id=proposal.id,
                tenant_id=context.tenant_id,
                kind=proposal.kind,
                payload=dict(proposal.payload),
                role_id=proposal.role_id,
                base_version=base_version,
                required_permission=proposal.required_permission,
                proposed_by=context.principal_id,
                expires_at=sa.text("now() + interval '7 days'"),
                status="proposed",
            )
            .returning(*_REQ.c)
        )
    ).one()
    return proposal_of(row)


@dataclass(frozen=True)
class SqlRoleAdminRepository:
    """Implements ``RoleAdminRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_roles(self, context: AccessContext) -> list[RoleSummary]:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            rows = await session.execute(
                _ROLES,
                {
                    "t": str(context.tenant_id),
                    "a": str(context.principal_id),
                    "w": str(context.workspace_id),
                },
            )
            return [
                RoleSummary(
                    id=r.id,
                    key=r.key,
                    name=r.name,
                    description=r.description,
                    kind=r.kind,
                    is_system=r.is_system,
                    template_key=r.template_key,
                    holder_count=int(r.holder_count),
                    version=int(r.version),
                    assignable_by_me=bool(r.assignable_by_me),
                    updated_at=r.updated_at,
                )
                for r in rows
            ]

    async def get_role(self, context: AccessContext, role_id: uuid.UUID) -> RoleDetail | None:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            return await _role(session, context, sa.text("r.id = CAST(:id AS uuid)"), id=role_id)

    async def role_by_key(self, context: AccessContext, key: str) -> RoleDetail | None:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            return await _role(session, context, sa.text("r.key = CAST(:key AS text)"), key=key)

    async def list_assignments(
        self, context: AccessContext, role_id: uuid.UUID
    ) -> list[RoleAssignmentRow]:
        m = tables.memberships
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            rows = await session.execute(
                sa.select(
                    _A.c.id,
                    _A.c.membership_id,
                    _A.c.workspace_id,
                    m.c.user_id,
                    _A.c.assigned_at,
                    _A.c.expires_at,
                )
                .select_from(
                    _A.join(
                        m, sa.and_(m.c.tenant_id == _A.c.tenant_id, m.c.id == _A.c.membership_id)
                    )
                )
                .where(_A.c.tenant_id == context.tenant_id, _A.c.role_id == role_id)
                .order_by(_A.c.assigned_at, _A.c.id)
            )
            return [
                RoleAssignmentRow(
                    id=r.id,
                    membership_id=r.membership_id,
                    workspace_id=r.workspace_id,
                    user_id=r.user_id,
                    assigned_at=r.assigned_at,
                    expires_at=r.expires_at,
                )
                for r in rows
            ]

    async def list_templates(self) -> list[RoleTemplate]:
        async with self.session_factory() as session:
            rows = await session.execute(_TEMPLATES)
            return [
                RoleTemplate(
                    key=r.key,
                    name=r.name,
                    kind=r.kind,
                    privileges=tuple(Privilege(k, d) for k, d in r.privileges),
                )
                for r in rows
            ]

    async def catalogue(self, keys: frozenset[str]) -> Mapping[str, CatalogueKey]:
        if not keys:
            return {}
        k = tables.permissions
        async with self.session_factory() as session:
            rows = await session.execute(
                sa.select(k.c.key, k.c.scope_kind, k.c.status, k.c.tenant_grantable).where(
                    k.c.key.in_(sorted(keys))
                )
            )
            return {
                r.key: CatalogueKey(r.key, r.scope_kind, r.status, r.tenant_grantable) for r in rows
            }

    async def refusals(
        self, context: AccessContext, changes: Sequence[Mapping[str, object]]
    ) -> list[Refusal]:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            return await ask_refusals(session, context, changes)

    async def has_checker(self, context: AccessContext, permission: str) -> bool:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            found = await session.scalar(
                HAS_CHECKER,
                {"t": str(context.tenant_id), "k": permission, "a": str(context.principal_id)},
            )
            return bool(found)

    async def propose(
        self,
        context: AccessContext,
        proposal: NewProposal,
        *,
        expected: ExpectedVersion | None,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> Proposal:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(proposal.id))
            base = proposal.base_version
            if proposal.role_id is not None:
                role = await lock_role(session, proposal.role_id)
                if role is None or role.deleted_at is not None:
                    raise NotFoundError("no such role")
                if expected is not None and not expected.matches(role.version):
                    raise _stale()
                if base is None:
                    base = int(role.version)
            written = await insert_proposal(session, context, proposal, base)
            await SqlAuditRepository(session).append(audit)
            return written

    async def apply_narrowing(
        self,
        context: AccessContext,
        role_id: uuid.UUID,
        *,
        expected: ExpectedVersion,
        target: Sequence[Privilege] | None,
        delete: bool,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> RoleDetail:
        try:
            async with tenant_session(self.session_factory, scope_of(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(role_id))
                role = await lock_role(session, role_id)
                if role is None or role.deleted_at is not None:
                    raise NotFoundError("no such role")
                if not expected.matches(role.version):
                    raise _stale()
                if delete:
                    held = await session.scalar(
                        sa.select(sa.func.count()).select_from(_A).where(_A.c.role_id == role_id)
                    )
                    if held:
                        raise conflict(
                            "this role is still assigned", "role_in_use", holder_count=int(held)
                        )
                    await session.execute(
                        sa.update(_R).where(_R.c.id == role_id).values(deleted_at=sa.func.now())
                    )
                else:
                    await _set_privileges(session, context, role_id, target or ())
                await SqlAuditRepository(session).append(audit)
                found = await _role(
                    session, context, sa.text("r.id = CAST(:id AS uuid)"), id=role_id
                )
                assert found is not None
                return found
        except IntegrityError as exc:
            raise _refused(exc) from exc

    async def get_proposal(self, context: AccessContext, request_id: uuid.UUID) -> Proposal | None:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            row = (await session.execute(sa.select(_REQ).where(_REQ.c.id == request_id))).first()
            return None if row is None else proposal_of(row)

    async def list_open_proposals(
        self, context: AccessContext, request: PageRequest
    ) -> Page[Proposal]:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            rows = (
                await session.execute(
                    sa.select(_REQ)
                    .where(
                        _REQ.c.tenant_id == context.tenant_id,
                        _REQ.c.status == "proposed",
                        # `expires_at` is `proposed_at` + 7 days (a CHECK), so the
                        # window reads through the list's index.
                        _REQ.c.proposed_at > sa.text("now() - interval '7 days'"),
                        after_position(_REQ.c.proposed_at, _REQ.c.id, request.after),
                    )
                    .order_by(*newest_first(_REQ.c.proposed_at, _REQ.c.id))
                    .limit(request.fetch_limit)
                )
            ).all()
        return build_page(
            [proposal_of(r) for r in rows],
            request=request,
            position_of=lambda p: CursorPosition(sort_value=p.proposed_at, tiebreaker=p.id),
        )

    async def confirm(
        self,
        context: AccessContext,
        request_id: uuid.UUID,
        *,
        audits: ConfirmAudits,
        effect: PendingEffect | None = None,
    ) -> ConfirmOutcome:
        try:
            async with tenant_session(self.session_factory, scope_of(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(request_id))
                proposal = await _locked_open_proposal(session, context, request_id)
                role_id = await _check_still_true(session, context, proposal)
                await _refuse_for_confirmer(session, context, proposal)
                await session.execute(
                    sa.update(_REQ)
                    .where(_REQ.c.id == request_id)
                    .values(
                        status="confirmed",
                        confirmed_by=context.principal_id,
                        decided_at=sa.func.now(),
                    )
                )
                await session.execute(
                    sa.text("SELECT set_config('app.role_change_id', :id, true)"),
                    {"id": str(request_id)},
                )
                details = await _apply(session, context, proposal)
                audit = SqlAuditRepository(session)
                await audit.append(audits.confirmed(proposal))
                await audit.append(audits.applied(proposal, details))
                return ConfirmOutcome(proposal=proposal, role_id=role_id)
        except IntegrityError as exc:
            raise _refused(exc) from exc

    async def withdraw(
        self,
        context: AccessContext,
        request_id: uuid.UUID,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> Proposal:
        async with tenant_session(self.session_factory, scope_of(context)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(request_id))
            row = (
                await session.execute(
                    sa.select(_REQ).where(_REQ.c.id == request_id).with_for_update()
                )
            ).first()
            if row is None:
                raise NotFoundError("no such role change request")
            if row.status != "proposed":
                raise conflict("this proposal is closed", "proposal_closed")
            done = (
                await session.execute(
                    sa.update(_REQ)
                    .where(_REQ.c.id == request_id)
                    .values(status="withdrawn", decided_at=sa.func.now())
                    .returning(*_REQ.c)
                )
            ).one()
            await SqlAuditRepository(session).append(audit)
            return proposal_of(done)


async def _role(
    session: AsyncSession, context: AccessContext, where: sa.TextClause, **params: object
) -> RoleDetail | None:
    query = sa.text(f"{_ROLE.text} AND {where.text}")
    row = (
        await session.execute(
            query, {"t": str(context.tenant_id), **{k: str(v) for k, v in params.items()}}
        )
    ).first()
    return None if row is None else _detail(row)


async def _locked_open_proposal(
    session: AsyncSession, context: AccessContext, request_id: uuid.UUID
) -> Proposal:
    """The proposal under `FOR UPDATE`, refused in the ticket's order."""
    row = (
        await session.execute(
            sa.select(_REQ, (sa.func.now() >= _REQ.c.expires_at).label("expired"))
            .where(_REQ.c.id == request_id)
            .with_for_update(of=_REQ)
        )
    ).first()
    if row is None:
        raise NotFoundError("no such role change request")
    proposal = proposal_of(row)
    holds = await session.scalar(
        HOLDS,
        {
            "t": str(context.tenant_id),
            "u": str(context.principal_id),
            "k": proposal.required_permission,
        },
    )
    if not holds:
        raise PermissionDeniedError(
            "action not permitted",
            details={
                "action": proposal.required_permission,
                "resource_type": "role_change_request",
            },
        )
    if proposal.proposed_by == context.principal_id:
        raise conflict("a second person confirms a role change", "second_person_required")
    if proposal.status != "proposed":
        raise conflict("this proposal is closed", "proposal_closed")
    if row.expired:
        raise conflict("this proposal has expired", "proposal_expired")
    return proposal


async def _check_still_true(
    session: AsyncSession, context: AccessContext, proposal: Proposal
) -> uuid.UUID | None:
    """What the proposal read is still so (R8.7): its proposer an active holder
    of its permission, its role at the version they read (under the role's
    lock), and for an assignment the membership still there."""
    stale = conflict("what this proposal was made on has changed", "proposal_stale")
    still_holds = await session.scalar(
        HOLDS,
        {
            "t": str(context.tenant_id),
            "u": str(proposal.proposed_by),
            "k": proposal.required_permission,
        },
    )
    if not still_holds:
        raise stale
    if proposal.role_id is None:
        return uuid.UUID(str(proposal.payload["role_id"]))
    role = await lock_role(session, proposal.role_id)
    if role is None or role.deleted_at is not None or role.version != proposal.base_version:
        raise stale
    if proposal.kind == "assignment_grant":
        member = tables.memberships
        present = await session.scalar(
            sa.select(sa.func.count())
            .select_from(member)
            .where(member.c.id == uuid.UUID(str(proposal.payload["membership_id"])))
        )
        if not present:
            raise stale
    return proposal.role_id


async def _refuse_for_confirmer(
    session: AsyncSession, context: AccessContext, proposal: Proposal
) -> None:
    """`platform.rbac_refusals` for the confirming person, before a write, so
    a refusal reads as its reason (self-assignment at the confirmation, R6.4);
    the triggers ask again for each write."""
    payload = proposal.payload
    changes: list[dict[str, object]]
    if proposal.kind == "assignment_grant":
        changes = [
            {
                "op": "grant",
                "role_id": str(proposal.role_id),
                "workspace_id": str(payload["workspace_id"]),
                "user_id": str(payload["user_id"]),
            }
        ]
    elif proposal.kind == "role_create":
        changes = [
            {"op": "role_create", "role_id": str(payload["role_id"]), "role_key": payload["key"]}
        ] + [
            {
                "op": "add",
                "role_id": str(payload["role_id"]),
                "permission_key": p["key"],
                "depth": p["depth"],
            }
            for p in _privileges(payload)
        ]
    elif proposal.kind == "role_permissions":
        from dw_platform.application.role_admin import privilege_changes

        assert proposal.role_id is not None
        current = await _current_privileges(session, proposal.role_id)
        changes = privilege_changes(proposal.role_id, diff_privileges(current, _target(payload)))
    else:
        changes = []
    error = rbac_refusal_error(await ask_refusals(session, context, changes))
    if error is not None:
        raise error


async def _apply(
    session: AsyncSession, context: AccessContext, proposal: Proposal
) -> dict[str, object]:
    """The payload's change, exactly, in the confirming transaction."""
    payload = proposal.payload
    if proposal.kind == "role_create":
        role_id = uuid.UUID(str(payload["role_id"]))
        await session.execute(
            sa.insert(_R).values(
                id=role_id,
                tenant_id=context.tenant_id,
                key=payload["key"],
                name=payload["name"],
                description=payload.get("description"),
                kind=payload["kind"],
                template_key=payload.get("template_key"),
                created_by=proposal.proposed_by,
            )
        )
        await _set_privileges(session, context, role_id, _target(payload))
        return {"role_key": payload["key"]}
    assert proposal.role_id is not None
    role_key = await session.scalar(sa.select(_R.c.key).where(_R.c.id == proposal.role_id))
    if proposal.kind == "role_update":
        await session.execute(
            sa.update(_R)
            .where(_R.c.id == proposal.role_id)
            .values(name=payload["name"], description=payload.get("description"))
        )
        return {"role_key": role_key}
    if proposal.kind == "role_permissions":
        current = await _current_privileges(session, proposal.role_id)
        diff = diff_privileges(current, _target(payload))
        await _set_privileges(session, context, proposal.role_id, _target(payload))
        return {
            "role_key": role_key,
            "added": [p.as_json() for p in diff.added],
            "raised": [p.as_json() for p in diff.raised],
            "removed": [p.as_json() for p in diff.removed],
            "lowered": [p.as_json() for p in diff.lowered],
        }
    assignment_id = uuid.uuid4()
    await session.execute(
        sa.insert(_A).values(
            id=assignment_id,
            tenant_id=context.tenant_id,
            workspace_id=uuid.UUID(str(payload["workspace_id"])),
            membership_id=uuid.UUID(str(payload["membership_id"])),
            role_id=proposal.role_id,
            assigned_by=context.principal_id,
        )
    )
    return {
        "assignment_id": str(assignment_id),
        "role_key": role_key,
        "membership_id": str(payload["membership_id"]),
        "workspace_id": str(payload["workspace_id"]),
        "user_id": str(payload["user_id"]),
    }


def _privileges(payload: Mapping[str, object]) -> list[Mapping[str, str]]:
    return cast(list[Mapping[str, str]], payload.get("permissions") or [])


def _target(payload: Mapping[str, object]) -> tuple[Privilege, ...]:
    return tuple(sorted(Privilege(p["key"], p["depth"]) for p in _privileges(payload)))


async def _current_privileges(session: AsyncSession, role_id: uuid.UUID) -> tuple[Privilege, ...]:
    rows = await session.execute(
        sa.select(_P.c.permission_key, _P.c.depth).where(_P.c.role_id == role_id)
    )
    return tuple(sorted(Privilege(r.permission_key, r.depth) for r in rows))


async def _set_privileges(
    session: AsyncSession,
    context: AccessContext,
    role_id: uuid.UUID,
    target: Sequence[Privilege],
) -> None:
    """Move the role's rows to ``target``: removed, re-depthed, added."""
    current = {p.key: p.depth for p in await _current_privileges(session, role_id)}
    wanted = {p.key: p.depth for p in target}
    gone = sorted(set(current) - set(wanted))
    if gone:
        await session.execute(
            sa.delete(_P).where(_P.c.role_id == role_id, _P.c.permission_key.in_(gone))
        )
    for key, depth in sorted(wanted.items()):
        if key in current and current[key] != depth:
            await session.execute(
                sa.update(_P)
                .where(_P.c.role_id == role_id, _P.c.permission_key == key)
                .values(depth=depth)
            )
    added = [
        {"tenant_id": context.tenant_id, "role_id": role_id, "permission_key": k, "depth": d}
        for k, d in sorted(wanted.items())
        if k not in current
    ]
    if added:
        await session.execute(sa.insert(_P), added)


def _stale() -> PreconditionFailedError:
    return PreconditionFailedError(
        "the role changed since you read it", details={"header": "If-Match"}
    )


def _refused(error: IntegrityError) -> Exception:
    known = role_write_refusal(error)
    return known if known is not None else error
