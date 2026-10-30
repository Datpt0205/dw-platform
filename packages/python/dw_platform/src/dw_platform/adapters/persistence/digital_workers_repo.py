"""SQL implementation of the Digital Worker ports (digital-worker R1, R2).

Every statement runs under the caller's tenant and workspace RLS. A DW and its
principal are written in one transaction, in the order the keys demand: the
service user, its principal row (the trigger checks the Business Owner, R1.16),
its membership (before the DW row exists, so the trigger that fixes a DW
principal's roles lets the first one in, R1.17), the DW, its decision classes,
and the audit event. A refusal the database makes is read back by the
constraint it names.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.keyset import after_position, newest_first
from dw_platform.adapters.persistence.membership_lookup import effective_scopes
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.separation_of_duties import (
    refusal,
    separation_of_duties_conflict,
)
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.digital_workers import DecisionLevels, Standing
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import (
    DecisionClass,
    DigitalWorker,
    DwConfiguration,
    DwPeople,
    DwState,
)
from dw_platform.domain.work_item import IN_FLIGHT, sources_of

_DW = tables.digital_workers
_CLASSES = tables.dw_decision_classes
_PRINCIPALS = tables.service_principals

_KEY_TAKEN = "uq_digital_workers_tenant_id_key"
_OWNER = "ck_service_principals_accountable_owner"
_ROLES_FIXED = "ck_memberships_dw_principal_roles_fixed"


def dw_principal_roles_conflict(error: IntegrityError) -> ConflictError | None:
    """409 `dw_principal_roles_fixed` when the database refused a role, a
    permission set or a workspace added to a DW principal (R1.17); None for
    any other integrity failure."""
    refused = refusal(error)
    if refused is None or refused[0] != _ROLES_FIXED:
        return None
    return ConflictError(
        "the roles of a digital worker's principal are fixed when it is made",
        details={"reason_code": "dw_principal_roles_fixed"},
    )


def _scope(context: AccessContext) -> TenantScope:
    return TenantScope.from_access_context(context)


def _refused(error: IntegrityError) -> Exception | None:
    conflict = separation_of_duties_conflict(error)
    if conflict is not None:
        return conflict
    refused = refusal(error)
    if refused is None:
        return None
    if refused[0] == _KEY_TAKEN:
        return ConflictError(
            "this tenant already has a digital worker with that key",
            details={"reason_code": "dw_key_taken"},
        )
    if refused[0] == _OWNER:
        return DomainError(
            "the business owner is a human member of this tenant",
            details={"reason_code": "owner_not_member"},
        )
    return None


@dataclass(frozen=True)
class SqlDigitalWorkerRepository:
    """Implements ``DigitalWorkerRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def create(
        self,
        context: AccessContext,
        worker: DigitalWorker,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        config = worker.configuration
        try:
            async with tenant_session(self.session_factory, _scope(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(worker.id))
                await session.execute(
                    sa.insert(tables.users).values(
                        id=worker.principal_user_id,
                        subject=f"service:{worker.principal_user_id}",
                        email=None,
                        display_name=config.name,
                        kind="service",
                        owner_tenant_id=worker.tenant_id,
                    )
                )
                await session.execute(
                    sa.insert(_PRINCIPALS).values(
                        user_id=worker.principal_user_id,
                        tenant_id=worker.tenant_id,
                        owning_workspace_id=worker.workspace_id,
                        name=config.name,
                        owner_user_id=worker.people.business_owner_id,
                    )
                )
                await session.execute(
                    sa.insert(tables.memberships).values(
                        id=uuid.uuid4(),
                        tenant_id=worker.tenant_id,
                        workspace_id=worker.workspace_id,
                        user_id=worker.principal_user_id,
                        role_keys=sorted(config.role_keys),
                    )
                )
                await session.execute(
                    sa.insert(_DW).values(
                        id=worker.id,
                        tenant_id=worker.tenant_id,
                        workspace_id=worker.workspace_id,
                        principal_user_id=worker.principal_user_id,
                        key=config.key,
                        name=config.name,
                        mandate=config.mandate,
                        work_kinds=list(config.work_kinds),
                        allowed_tools=list(config.allowed_tools),
                        workflow_key=config.workflow_key,
                        workflow_version=config.workflow_version,
                        parameters=dict(config.parameters),
                        state=worker.state,
                        technical_owner_id=worker.people.technical_owner_id,
                        work_assigner_id=worker.people.work_assigner_id,
                        validator_id=worker.people.validator_id,
                        created_by=worker.created_by,
                        created_at=worker.created_at,
                        updated_at=worker.updated_at,
                    )
                )
                if config.decision_classes:
                    await session.execute(
                        sa.insert(_CLASSES),
                        [
                            {
                                "dw_id": worker.id,
                                "key": c.key,
                                "tenant_id": worker.tenant_id,
                                "workspace_id": worker.workspace_id,
                                "effect_level": c.effect_level,
                                "reversible": c.reversible,
                                "ceiling": c.ceiling,
                                "earned_level": c.earned_level,
                            }
                            for c in config.decision_classes
                        ],
                    )
                await SqlAuditRepository(session).append(audit)
        except IntegrityError as exc:
            known = _refused(exc)
            if known is not None:
                raise known from exc
            raise

    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker | None:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            row = (await session.execute(_select_workers().where(_DW.c.id == dw_id))).first()
            if row is None:
                return None
            classes = await _classes_of(session, [dw_id])
        return _worker_of(row, classes.get(dw_id, ()))

    async def list(self, context: AccessContext, request: PageRequest) -> Page[DigitalWorker]:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            rows = (
                await session.execute(
                    _select_workers()
                    .where(
                        _DW.c.workspace_id == context.workspace_id,
                        after_position(_DW.c.created_at, _DW.c.id, request.after),
                    )
                    .order_by(*newest_first(_DW.c.created_at, _DW.c.id))
                    .limit(request.fetch_limit)
                )
            ).all()
            classes = await _classes_of(session, [row.id for row in rows])
        return build_page(
            [_worker_of(row, classes.get(row.id, ())) for row in rows],
            request=request,
            position_of=_position,
        )

    async def change_state(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        *,
        current: DwState,
        target: DwState,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(dw_id))
            if target == "retired":
                await _retire_work(session, dw_id)
            moved = (
                await session.execute(
                    sa.update(_DW)
                    .where(_DW.c.id == dw_id, _DW.c.state == current)
                    .values(state=target)
                    .returning(_DW.c.id)
                )
            ).first()
            if moved is None:
                return False
            if target == "retired":
                await session.execute(sa.select(sa.func.platform.retire_dw_principal(dw_id)))
            await SqlAuditRepository(session).append(audit)
        return True

    async def digital_worker(self, scope: WorkScope, dw_id: uuid.UUID) -> DigitalWorker | None:
        """Implements ``DwLookupPort``: the DW under a verified scope rather
        than a signed-in caller (the lane, an intake, a run)."""
        bound = TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)
        async with tenant_session(self.session_factory, bound) as session:
            row = (await session.execute(_select_workers().where(_DW.c.id == dw_id))).first()
            if row is None:
                return None
            classes = await _classes_of(session, [dw_id])
        return _worker_of(row, classes.get(dw_id, ()))

    async def replace_people(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        people: DwPeople,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        try:
            async with tenant_session(self.session_factory, _scope(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(dw_id))
                principal = (
                    await session.execute(
                        sa.update(_DW)
                        .where(_DW.c.id == dw_id)
                        .values(
                            technical_owner_id=people.technical_owner_id,
                            work_assigner_id=people.work_assigner_id,
                            validator_id=people.validator_id,
                        )
                        .returning(_DW.c.principal_user_id)
                    )
                ).scalar_one_or_none()
                if principal is None:
                    return False
                await session.execute(
                    sa.update(_PRINCIPALS)
                    .where(_PRINCIPALS.c.user_id == principal)
                    .values(owner_user_id=people.business_owner_id)
                )
                await SqlAuditRepository(session).append(audit)
        except IntegrityError as exc:
            known = _refused(exc)
            if known is not None:
                raise known from exc
            raise
        return True


async def _retire_work(session: AsyncSession, dw_id: uuid.UUID) -> None:
    """R1.12, R1.14: under the DW's row lock, which the lane's claim waits on
    (`FOR SHARE`), refuse while any of its work is in flight, and cancel what
    is still open, before the state changes."""
    await session.execute(sa.select(_DW.c.id).where(_DW.c.id == dw_id).with_for_update())
    w = tables.work_items
    busy = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(w)
            .where(w.c.dw_id == dw_id, w.c.status.in_(sorted(IN_FLIGHT)))
        )
    ).scalar_one()
    if busy:
        raise ConflictError(
            "this digital worker still has work in progress or waiting",
            details={"reason_code": "dw_has_work_in_flight", "items": int(busy)},
        )
    await session.execute(
        sa.update(w)
        .where(w.c.dw_id == dw_id, w.c.status.in_(sorted(sources_of("cancelled", "retire"))))
        .values(status="cancelled", closed_at=sa.func.now())
    )


def _select_workers() -> sa.Select[Any]:
    """A DW with its Business Owner and its principal's roles, which live on
    the principal row and the principal's membership in the DW's workspace
    (none once that membership is removed)."""
    m = tables.memberships
    return sa.select(
        _DW,
        _PRINCIPALS.c.owner_user_id,
        sa.func.coalesce(m.c.role_keys, sa.text("'[]'::jsonb")).label("role_keys"),
    ).select_from(
        _DW.join(_PRINCIPALS, _PRINCIPALS.c.user_id == _DW.c.principal_user_id).outerjoin(
            m,
            sa.and_(m.c.user_id == _DW.c.principal_user_id, m.c.workspace_id == _DW.c.workspace_id),
        )
    )


async def _classes_of(
    session: AsyncSession, dw_ids: Sequence[uuid.UUID]
) -> Mapping[uuid.UUID, tuple[DecisionClass, ...]]:
    if not dw_ids:
        return {}
    rows = (
        await session.execute(
            sa.select(_CLASSES).where(_CLASSES.c.dw_id.in_(dw_ids)).order_by(_CLASSES.c.key)
        )
    ).all()
    found: dict[uuid.UUID, list[DecisionClass]] = {}
    for row in rows:
        found.setdefault(row.dw_id, []).append(
            DecisionClass(
                key=row.key,
                effect_level=row.effect_level,
                reversible=row.reversible,
                ceiling=row.ceiling,
                earned_level=row.earned_level,
            )
        )
    return {dw_id: tuple(classes) for dw_id, classes in found.items()}


def _worker_of(row: sa.Row[Any], classes: Iterable[DecisionClass]) -> DigitalWorker:
    return DigitalWorker(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        principal_user_id=row.principal_user_id,
        configuration=DwConfiguration(
            key=row.key,
            name=row.name,
            mandate=row.mandate,
            work_kinds=tuple(row.work_kinds),
            allowed_tools=tuple(row.allowed_tools),
            workflow_key=row.workflow_key,
            workflow_version=row.workflow_version,
            parameters=dict(row.parameters),
            role_keys=frozenset(row.role_keys),
            decision_classes=tuple(classes),
        ),
        people=DwPeople(
            business_owner_id=row.owner_user_id,
            technical_owner_id=row.technical_owner_id,
            work_assigner_id=row.work_assigner_id,
            validator_id=row.validator_id,
        ),
        state=cast(DwState, row.state),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _position(worker: DigitalWorker) -> CursorPosition:
    return CursorPosition(sort_value=worker.created_at, tiebreaker=worker.id)


@dataclass(frozen=True)
class SqlDwMembershipCheck:
    """Implements ``MembershipCheckPort``: a user's membership in the caller's
    workspace, the user's kind, and the scopes the membership holds, read the
    one way the access context reads them (`effective_scopes`)."""

    session_factory: async_sessionmaker[AsyncSession]

    async def standing(self, context: AccessContext, user_id: uuid.UUID) -> Standing | None:
        return await self._standing(
            TenantScope.from_access_context(context), context.workspace_id, user_id
        )

    async def is_person_in(self, scope: WorkScope, user_id: uuid.UUID) -> bool:
        """Implements ``PersonCheckPort`` (R4.3)."""
        bound = TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)
        found = await self._standing(bound, scope.workspace_id, user_id)
        return found is not None and found.kind == "human"

    async def _standing(
        self, bound: TenantScope, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> Standing | None:
        m = tables.memberships
        async with tenant_session(self.session_factory, bound) as session:
            row = (
                await session.execute(
                    sa.select(tables.users.c.kind, m.c.role_keys, m.c.permission_set_keys)
                    .select_from(m.join(tables.users, tables.users.c.id == m.c.user_id))
                    .where(m.c.workspace_id == workspace_id, m.c.user_id == user_id)
                )
            ).first()
            if row is None:
                return None
            scopes = await effective_scopes(
                session, frozenset(row.role_keys), frozenset(row.permission_set_keys)
            )
        return Standing(kind="service" if row.kind == "service" else "human", scopes=scopes)


@dataclass(frozen=True)
class SqlDecisionLevels:
    """Implements ``DecisionLevelsPort``: one class's levels and its tenant's
    ceiling, in one statement, under the DW's own tenant and workspace."""

    session_factory: async_sessionmaker[AsyncSession]

    async def levels(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> DecisionLevels | None:
        scope = TenantScope(tenant_id=tenant_id, workspace_id=workspace_id)
        async with tenant_session(self.session_factory, scope) as session:
            row = (
                await session.execute(
                    sa.select(
                        _CLASSES.c.effect_level,
                        _CLASSES.c.reversible,
                        _CLASSES.c.ceiling,
                        _CLASSES.c.earned_level,
                        tables.tenants.c.max_autonomy_level,
                    )
                    .select_from(
                        _CLASSES.join(tables.tenants, tables.tenants.c.id == _CLASSES.c.tenant_id)
                    )
                    .where(_CLASSES.c.dw_id == dw_id, _CLASSES.c.key == key)
                )
            ).first()
        if row is None:
            return None
        return DecisionLevels(
            effect_level=row.effect_level,
            reversible=row.reversible,
            ceiling=row.ceiling,
            earned_level=row.earned_level,
            tenant_ceiling=row.max_autonomy_level,
        )
