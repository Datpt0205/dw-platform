"""SQL provisioning repository — runs as ``dw_provisioner`` (ADR-002).

That role has BYPASSRLS (needed to create and list every tenant) but is granted
only the platform provisioning tables, so nothing here can reach a business
schema. Kept in its own session factory bound to the provisioner engine; it must
never share the ``dw_app`` pool.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.support_grants import grant_from_row, support_staff_conflict
from dw_platform.adapters.persistence.tenant_member_rows import ensure_tenant_member
from dw_platform.application.provisioning import (
    OffboardingStatus,
    OperatorRef,
    SupportRequestSummary,
    SupportStaffRef,
    TenantSummary,
    UserRef,
)
from dw_platform.application.support_access import (
    GrantStatus,
    SupportGrant,
    SupportRefusal,
)
from dw_platform.domain.audit import AuditEvent

# Matched by name, like every other constraint-driven error mapping in this
# package (see admin_console_repo.py, run_store.py) — Postgres embeds the
# constraint name in the error text, which is more stable to match on than
# parsing SQLSTATE codes for two constraints that need two different answers.
_ACTIVE_REQUEST_INDEX = "uq_tenant_offboarding_requests_active"
_TENANT_FK = "fk_tenant_offboarding_requests_tenant_id_tenants"
# R3.11: the database refuses owner authority to a platform operator or support
# staff member (`platform.guard_operator_tenant_grants`, b5677d345bc1).
_OPERATOR_NOT_OWNER = "ck_role_assignments_operator_not_owner"
_INSTALL_SYSTEM_ROLES = text("SELECT platform.install_system_roles(CAST(:t AS uuid))")
_TENANT_OWNER_ROLE = text(
    "SELECT id FROM platform.tenant_roles"
    " WHERE tenant_id = CAST(:t AS uuid) AND key = 'tenant_owner'"
)


def operator_not_assignable(error: IntegrityError) -> ConflictError | None:
    """The refusal of R3.11 as the 409 the operator's routes give; None for
    any other integrity error."""
    refused = refusal(error)
    if refused is None or refused[0] != _OPERATOR_NOT_OWNER:
        return None
    return ConflictError(
        "a platform operator or support staff member cannot hold owner authority"
        " in a customer's tenant",
        details={"reason_code": "operator_not_assignable"},
    )


def _owner_conflict(error: IntegrityError) -> ConflictError | None:
    return support_staff_conflict(error) or operator_not_assignable(error)


async def _place_owner(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, user_id: UUID
) -> None:
    """`tenant_owner` for the person at `workspace_id`, as an invitation writes
    a member (R3.1, R3.8): the company row `invited` unless one exists, the
    membership unless one exists, and the assignment, idempotent in each."""
    await session.execute(ensure_tenant_member(tenant_id, user_id, "invited"))
    m = tables.memberships
    membership_id = await session.scalar(
        sa.select(m.c.id).where(
            m.c.tenant_id == tenant_id, m.c.workspace_id == workspace_id, m.c.user_id == user_id
        )
    )
    if membership_id is None:
        membership_id = uuid4()
        await session.execute(
            sa.insert(m).values(
                id=membership_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                department="general",
            )
        )
    await session.execute(_INSTALL_SYSTEM_ROLES, {"t": str(tenant_id)})
    role_id = await session.scalar(_TENANT_OWNER_ROLE, {"t": str(tenant_id)})
    await session.execute(
        pg_insert(tables.role_assignments)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            membership_id=membership_id,
            role_id=role_id,
        )
        .on_conflict_do_nothing(constraint="uq_role_assignments_membership_id_role_id")
    )


@dataclass(frozen=True)
class SqlProvisioningRepository:
    """Implements ``ProvisioningRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_tenants(self) -> list[TenantSummary]:
        ws = (
            sa.select(
                tables.workspaces.c.tenant_id,
                sa.func.count().label("n"),
            )
            .group_by(tables.workspaces.c.tenant_id)
            .subquery()
        )
        mem = (
            sa.select(
                tables.memberships.c.tenant_id,
                sa.func.count().label("n"),
            )
            .group_by(tables.memberships.c.tenant_id)
            .subquery()
        )
        stmt = (
            sa.select(
                tables.tenants.c.id,
                tables.tenants.c.slug,
                tables.tenants.c.name,
                tables.tenants.c.status,
                tables.tenants.c.owner_coverage_low_since,
                tables.tenants.c.created_at,
                tables.entitlements.c.plan_id,
                sa.func.coalesce(ws.c.n, 0).label("workspace_count"),
                sa.func.coalesce(mem.c.n, 0).label("member_count"),
            )
            .select_from(
                tables.tenants.outerjoin(
                    tables.entitlements,
                    tables.entitlements.c.tenant_id == tables.tenants.c.id,
                )
                .outerjoin(ws, ws.c.tenant_id == tables.tenants.c.id)
                .outerjoin(mem, mem.c.tenant_id == tables.tenants.c.id)
            )
            .order_by(tables.tenants.c.created_at)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            TenantSummary(
                id=row.id,
                slug=row.slug,
                name=row.name,
                status=row.status,
                plan_id=row.plan_id,
                workspace_count=row.workspace_count,
                member_count=row.member_count,
                created_at=row.created_at,
                owner_coverage_low_since=row.owner_coverage_low_since,
            )
            for row in rows
        ]

    async def list_users(self) -> list[UserRef]:
        stmt = (
            sa.select(
                tables.users.c.id,
                tables.users.c.email,
                tables.users.c.display_name,
            )
            .where(tables.users.c.email.is_not(None))
            .order_by(tables.users.c.display_name)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            UserRef(user_id=row.id, email=row.email, display_name=row.display_name) for row in rows
        ]

    async def slug_exists(self, slug: str) -> bool:
        async with self.session_factory() as session:
            found = (
                await session.execute(
                    sa.select(tables.tenants.c.id).where(tables.tenants.c.slug == slug)
                )
            ).first()
        return found is not None

    async def plan_exists(self, plan_id: str) -> bool:
        async with self.session_factory() as session:
            found = (
                await session.execute(
                    sa.select(tables.plans.c.plan_id).where(tables.plans.c.plan_id == plan_id)
                )
            ).first()
        return found is not None

    async def create_tenant(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        entitlement_id: UUID,
        slug: str,
        name: str,
        plan_id: str,
        owners: Sequence[str],
    ) -> list[UUID]:
        try:
            async with self.session_factory() as session, session.begin():
                # `setup` until the second owner is active (R3.1, R3.10).
                await session.execute(
                    sa.insert(tables.tenants).values(
                        id=tenant_id, slug=slug, name=name, status="setup"
                    )
                )
                await session.execute(
                    sa.insert(tables.workspaces).values(
                        id=workspace_id,
                        tenant_id=tenant_id,
                        slug="main",
                        name="Main workspace",
                    )
                )
                await session.execute(
                    sa.insert(tables.entitlements).values(
                        id=entitlement_id, tenant_id=tenant_id, plan_id=plan_id
                    )
                )
                await session.execute(_INSTALL_SYSTEM_ROLES, {"t": str(tenant_id)})
                owner_ids = [await _owner_user(session, email) for email in owners]
                for user_id in owner_ids:
                    await _place_owner(
                        session, tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id
                    )
        except IntegrityError as exc:
            conflict = _owner_conflict(exc)
            if conflict is None:
                raise
            raise conflict from exc
        return owner_ids

    async def set_tenant_status(
        self, tenant_id: UUID, status: str, *, only_from: frozenset[str] | None = None
    ) -> str | None:
        async with self.session_factory() as session, session.begin():
            # Read under the row lock, so the status checked is the one updated.
            previous = await session.scalar(
                sa.select(tables.tenants.c.status)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            )
            if previous is not None and (only_from is None or previous in only_from):
                await session.execute(
                    sa.update(tables.tenants)
                    .where(tables.tenants.c.id == tenant_id)
                    .values(status=status)
                )
        return previous

    async def create_offboarding_request(
        self, *, request_id: UUID, tenant_id: UUID, requested_by: UUID
    ) -> None:
        try:
            async with self.session_factory() as session, session.begin():
                await session.execute(
                    sa.insert(tables.tenant_offboarding_requests).values(
                        id=request_id, tenant_id=tenant_id, requested_by=requested_by
                    )
                )
        except IntegrityError as exc:
            if _ACTIVE_REQUEST_INDEX in str(exc.orig):
                raise ConflictError(
                    "an offboarding request is already in flight for this tenant",
                    details={"tenant_id": str(tenant_id)},
                ) from exc
            if _TENANT_FK in str(exc.orig):
                raise NotFoundError(
                    "unknown tenant", details={"tenant_id": str(tenant_id)}
                ) from exc
            raise

    async def get_offboarding_status(self, tenant_id: UUID) -> OffboardingStatus | None:
        # A failed (or, once terminal, a completed) request does not block a
        # later retry — only the live-request unique index does — so a tenant
        # can have more than one row here over time. Always the most recent.
        stmt = (
            sa.select(tables.tenant_offboarding_requests)
            .where(tables.tenant_offboarding_requests.c.tenant_id == tenant_id)
            .order_by(tables.tenant_offboarding_requests.c.requested_at.desc())
            .limit(1)
        )
        async with self.session_factory() as session:
            row = (await session.execute(stmt)).first()
        if row is None:
            return None
        return OffboardingStatus(
            request_id=row.id,
            tenant_id=row.tenant_id,
            status=row.status,
            requested_by=row.requested_by,
            requested_at=row.requested_at,
            export_key=row.export_key,
            error=row.error,
            updated_at=row.updated_at,
        )

    async def rename_tenant(self, tenant_id: UUID, name: str) -> bool:
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                sa.update(tables.tenants).where(tables.tenants.c.id == tenant_id).values(name=name)
            )
        assert isinstance(result, CursorResult)
        return bool(result.rowcount)

    async def main_workspace_id(self, tenant_id: UUID) -> UUID | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    sa.select(tables.workspaces.c.id).where(
                        tables.workspaces.c.tenant_id == tenant_id,
                        tables.workspaces.c.slug == "main",
                    )
                )
            ).first()
        return row.id if row else None

    async def find_user_by_email(self, email: str) -> UserRef | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    sa.select(
                        tables.users.c.id,
                        tables.users.c.email,
                        tables.users.c.display_name,
                    ).where(sa.func.lower(tables.users.c.email) == email.strip().lower())
                )
            ).first()
        if row is None:
            return None
        return UserRef(user_id=row.id, email=row.email, display_name=row.display_name)

    async def assign_tenant_owner(
        self, *, tenant_id: UUID, workspace_id: UUID, user_id: UUID
    ) -> None:
        try:
            async with self.session_factory() as session, session.begin():
                await _place_owner(
                    session, tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id
                )
        except IntegrityError as exc:
            conflict = _owner_conflict(exc)
            if conflict is None:
                raise
            raise conflict from exc

    async def list_operators(self) -> list[OperatorRef]:
        stmt = (
            sa.select(
                tables.platform_operators.c.user_id,
                tables.platform_operators.c.note,
                tables.platform_operators.c.created_at,
                tables.users.c.email,
                tables.users.c.display_name,
            )
            .select_from(
                tables.platform_operators.join(
                    tables.users, tables.platform_operators.c.user_id == tables.users.c.id
                )
            )
            .order_by(tables.platform_operators.c.created_at)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            OperatorRef(
                user_id=row.user_id,
                email=row.email,
                display_name=row.display_name,
                note=row.note,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def is_operator(self, user_id: UUID) -> bool:
        async with self.session_factory() as session:
            found = (
                await session.execute(
                    sa.select(tables.platform_operators.c.user_id).where(
                        tables.platform_operators.c.user_id == user_id
                    )
                )
            ).first()
        return found is not None

    async def add_operator(self, *, user_id: UUID, note: str | None, created_by: UUID) -> None:
        try:
            async with self.session_factory() as session, session.begin():
                await session.execute(
                    pg_insert(tables.platform_operators)
                    .values(user_id=user_id, note=note, created_by=created_by)
                    .on_conflict_do_nothing(index_elements=["user_id"])
                )
        except IntegrityError as exc:
            conflict = operator_not_assignable(exc)
            if conflict is None:
                raise
            raise conflict from exc

    async def remove_operator(self, user_id: UUID) -> bool:
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                sa.delete(tables.platform_operators).where(
                    tables.platform_operators.c.user_id == user_id
                )
            )
        assert isinstance(result, CursorResult)
        return bool(result.rowcount)

    async def list_support_staff(self) -> list[SupportStaffRef]:
        staff = tables.support_staff
        stmt = (
            sa.select(
                staff.c.user_id,
                staff.c.note,
                staff.c.added_at,
                tables.users.c.email,
                tables.users.c.display_name,
            )
            .select_from(staff.join(tables.users, staff.c.user_id == tables.users.c.id))
            .order_by(staff.c.added_at)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            SupportStaffRef(
                user_id=row.user_id,
                email=row.email,
                display_name=row.display_name,
                note=row.note,
                added_at=row.added_at,
            )
            for row in rows
        ]

    async def add_support_staff(self, *, user_id: UUID, note: str | None, added_by: UUID) -> None:
        try:
            async with self.session_factory() as session, session.begin():
                await session.execute(
                    pg_insert(tables.support_staff)
                    .values(user_id=user_id, note=note, added_by=added_by)
                    .on_conflict_do_nothing(index_elements=["user_id"])
                )
        except IntegrityError as exc:
            conflict = operator_not_assignable(exc)
            if conflict is None:
                raise
            raise conflict from exc

    async def remove_support_staff(self, user_id: UUID) -> bool:
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                sa.delete(tables.support_staff).where(tables.support_staff.c.user_id == user_id)
            )
        assert isinstance(result, CursorResult)
        return bool(result.rowcount)

    async def list_support_requests(self) -> list[SupportRequestSummary]:
        grants = tables.support_grants
        stmt = (
            sa.select(
                grants.c.id,
                grants.c.code,
                grants.c.tenant_id,
                tables.tenants.c.name.label("tenant_name"),
                grants.c.workspace_id,
                tables.workspaces.c.name.label("workspace_name"),
                grants.c.resource_type,
                grants.c.resource_label,
                grants.c.scope_set_key,
                grants.c.scope_set_label,
                grants.c.duration_hours,
                grants.c.reason,
                grants.c.requested_at,
            )
            .select_from(
                grants.join(tables.tenants, tables.tenants.c.id == grants.c.tenant_id).join(
                    tables.workspaces, tables.workspaces.c.id == grants.c.workspace_id
                )
            )
            .where(grants.c.status == GrantStatus.PENDING_ASSIGNMENT.value)
            .order_by(grants.c.requested_at, grants.c.id)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            SupportRequestSummary(
                grant_id=row.id,
                code=row.code,
                tenant_id=row.tenant_id,
                tenant_name=row.tenant_name,
                workspace_id=row.workspace_id,
                workspace_name=row.workspace_name,
                resource_type=row.resource_type,
                resource_label=row.resource_label,
                scope_set_key=row.scope_set_key,
                scope_set_label=row.scope_set_label,
                duration_hours=row.duration_hours,
                reason=row.reason,
                requested_at=row.requested_at,
            )
            for row in rows
        ]

    async def assign_support_grant(
        self,
        *,
        grant_id: UUID,
        staff_user_id: UUID,
        assigned_by: UUID,
        activated_at: datetime,
        tenant_audit: Callable[[SupportGrant], AuditEvent],
        provisioning_audit_id: UUID,
    ) -> SupportGrant:
        grants = tables.support_grants
        async with self.session_factory() as session, session.begin():
            current = (
                await session.execute(
                    sa.select(grants.c.status, grants.c.duration_hours)
                    .where(grants.c.id == grant_id)
                    .with_for_update()
                )
            ).first()
            if current is None:
                raise NotFoundError("support grant not found", details={"grant_id": str(grant_id)})
            if current.status != GrantStatus.PENDING_ASSIGNMENT.value:
                raise ConflictError(
                    "only a grant waiting for assignment can be assigned",
                    details={
                        "reason_code": SupportRefusal.WRONG_STATUS.value,
                        "status": current.status,
                    },
                )
            # Not locked: someone removed from the list a moment later holds a
            # grant they cannot use, because the support context requires a
            # listed staff member on every request.
            listed = (
                await session.execute(
                    sa.select(tables.support_staff.c.user_id).where(
                        tables.support_staff.c.user_id == staff_user_id
                    )
                )
            ).first()
            if listed is None:
                raise ConflictError(
                    "a grant is only ever assigned to support staff",
                    details={"reason_code": SupportRefusal.STAFF_REQUIRED.value},
                )
            row = (
                await session.execute(
                    sa.update(grants)
                    .where(grants.c.id == grant_id)
                    .values(
                        status=GrantStatus.ACTIVE.value,
                        staff_user_id=staff_user_id,
                        assigned_by=assigned_by,
                        activated_at=activated_at,
                        expires_at=activated_at + timedelta(hours=current.duration_hours),
                    )
                    .returning(*grants.c)
                )
            ).one()
            grant = grant_from_row(row)
            await SqlAuditRepository(session).append(tenant_audit(grant))
            await session.execute(
                sa.insert(tables.provisioning_audit).values(
                    id=provisioning_audit_id,
                    actor_id=assigned_by,
                    action="platform.support_grant.assign",
                    target_type="support_grant",
                    target_id=str(grant_id),
                    details={
                        "tenant_id": str(grant.tenant_id),
                        "code": grant.code,
                        "staff_user_id": str(staff_user_id),
                    },
                    occurred_at=activated_at,
                )
            )
        return grant

    async def record_audit(
        self,
        *,
        audit_id: UUID,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: str | None,
        details: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                sa.insert(tables.provisioning_audit).values(
                    id=audit_id,
                    actor_id=actor_id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    details=details,
                    occurred_at=occurred_at,
                )
            )


async def _owner_user(session: AsyncSession, email: str) -> UUID:
    """The person an owner email names, by its lower-cased address, or a new
    one who has not signed in yet (`invite:<uuid>`), as an invitation creates
    them (`tenant_members.py`); a person already known is reused."""
    found = await session.scalar(
        sa.select(tables.users.c.id).where(sa.func.lower(tables.users.c.email) == email)
    )
    if found is not None:
        return UUID(str(found))
    created = await session.scalar(
        pg_insert(tables.users)
        .values(id=uuid4(), subject=f"invite:{uuid4()}", email=email, display_name=email)
        .returning(tables.users.c.id)
    )
    return UUID(str(created))
