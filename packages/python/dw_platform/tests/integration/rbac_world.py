"""Two administrators of one tenant, for the tests that place people in roles
through the services (tenant-rbac ticket 03).

Since migration d2b57239ef50 a role assigned as `dw_app` is a proposal, applied
only when a second holder of `platform.roles.bind` confirms it, and the database
judges the hold rule against the actor's real grants. So the person a test acts
as is a real member of the tenant holding a real role, planted as the migrator
with `dw_platform.testing.rbac`, and a second one stands ready to confirm.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.role_admin_repo import SqlRoleAdminRepository
from dw_platform.adapters.persistence.role_assignments_repo import SqlRoleAssignmentRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.role_admin import ROLES_BIND, RoleAdminService
from dw_platform.application.role_assignments import RoleAssignmentService
from dw_platform.testing.rbac import assign, plant_membership, plant_person

# What the `org_admin` template carries that these tests ask the authorization
# port about; the database reads the role's real privileges.
ADMIN_SCOPES = frozenset(
    {
        "directory.read",
        "platform.members.read",
        "platform.members.write",
        "platform.roles.read",
        ROLES_BIND,
    }
)


@dataclass(frozen=True)
class Admins:
    """`maker` proposes, `checker` confirms; both hold `role_key` in `workspace_id`."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    maker: uuid.UUID
    checker: uuid.UUID

    def context(
        self,
        user: uuid.UUID | None = None,
        *,
        scopes: frozenset[str] = ADMIN_SCOPES,
        workspace_id: uuid.UUID | None = None,
    ) -> AccessContext:
        return AccessContext(
            tenant_id=self.tenant_id,
            workspace_id=workspace_id or self.workspace_id,
            principal_id=user or self.maker,
            roles=frozenset({"org_admin"}),
            scopes=scopes,
            plan_id="professional",
        )

    @property
    def maker_context(self) -> AccessContext:
        return self.context(self.maker)

    @property
    def checker_context(self) -> AccessContext:
        return self.context(self.checker)


async def tenant_role(migrator: AsyncEngine, tenant_id: uuid.UUID, key: str) -> uuid.UUID:
    """The tenant's role `key`, cloned from its template when it has none yet."""
    async with migrator.begin() as conn:
        found = await conn.scalar(
            sa.text("SELECT id FROM platform.tenant_roles WHERE tenant_id = :t AND key = :k"),
            {"t": tenant_id, "k": key},
        )
        if found is None:
            found = await conn.scalar(
                sa.text("SELECT platform.install_role_template(:t, :k)"),
                {"t": tenant_id, "k": key},
            )
    return uuid.UUID(str(found))


async def plant_admins(
    migrator: AsyncEngine,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    role_key: str = "org_admin",
) -> Admins:
    """Two active members of `tenant_id`, each holding `role_key` in `workspace_id`."""
    role = await tenant_role(migrator, tenant_id, role_key)
    people: list[uuid.UUID] = []
    async with migrator.begin() as conn:
        for _ in range(2):
            person = await plant_person(conn, tenant_id)
            membership = await plant_membership(conn, tenant_id, workspace_id, person)
            await assign(conn, tenant_id, workspace_id, membership, role)
            people.append(person)
    return Admins(tenant_id, workspace_id, people[0], people[1])


def assignment_service(engine: AsyncEngine) -> RoleAssignmentService:
    return RoleAssignmentService(
        SqlRoleAssignmentRepository(async_sessionmaker(engine, expire_on_commit=False)),
        ScopeAuthorizationService(),
        SystemClock(),
        Uuid4Generator(),
    )


def role_admin_service(engine: AsyncEngine) -> RoleAdminService:
    return RoleAdminService(
        SqlRoleAdminRepository(async_sessionmaker(engine, expire_on_commit=False)),
        ScopeAuthorizationService(),
        SystemClock(),
        Uuid4Generator(),
    )


async def confirm_all(
    engine: AsyncEngine, checker: AccessContext, proposals: Iterable[uuid.UUID]
) -> None:
    """The second person confirms each proposal, in their own transaction."""
    service = role_admin_service(engine)
    for request_id in proposals:
        await service.confirm(checker, request_id)


async def assigned_roles(
    migrator: AsyncEngine, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> dict[uuid.UUID, list[str]]:
    """Workspace -> the sorted keys of the roles assigned there (an empty list
    for a membership holding none), read past RLS."""
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT m.workspace_id, r.key FROM platform.memberships m"
                " LEFT JOIN platform.role_assignments a"
                "   ON a.tenant_id = m.tenant_id AND a.membership_id = m.id"
                " LEFT JOIN platform.tenant_roles r"
                "   ON r.tenant_id = a.tenant_id AND r.id = a.role_id"
                " WHERE m.tenant_id = :t AND m.user_id = :u"
            ),
            {"t": tenant_id, "u": user_id},
        )
        found: dict[uuid.UUID, list[str]] = {}
        for row in rows:
            keys = found.setdefault(row.workspace_id, [])
            if row.key is not None:
                keys.append(row.key)
    return {ws: sorted(keys) for ws, keys in found.items()}


async def open_proposals(migrator: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with migrator.connect() as conn:
        found = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.role_change_requests"
                " WHERE tenant_id = :t AND status = 'proposed'"
            ),
            {"t": tenant_id},
        )
    return int(found or 0)
