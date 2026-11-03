"""A company with two workspaces and people at each depth of the fixture keys,
and a second company, planted as the migrator for Studio's integration tests.

People (all members of `ws1` unless said otherwise):

- `writer`: read and write at workspace depth in `ws1`;
- `reader`: read only, at workspace depth in `ws1`;
- `tenant_reader`: read at tenant depth (anchored in `ws1`): reaches both;
- `ws2_writer`: read and write at workspace depth in `ws2`, a member there;
- `outsider`: read and write in the other company's workspace.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncConnection

from dw_platform.application.access_context import AccessContext
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_studio.testing.fixture_kinds import FIXTURE_READ, FIXTURE_SUBMIT, FIXTURE_WRITE


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID

    @property
    def subject(self) -> str:
        return f"rbac-{self.id}"

    def context(self, workspace_id: uuid.UUID | None = None) -> AccessContext:
        return AccessContext(
            tenant_id=self.tenant_id,
            workspace_id=workspace_id or self.workspace_id,
            principal_id=self.id,
            roles=frozenset(),
            plan_id="professional",
        )


@dataclass
class StudioWorld:
    tenant: PlantedTenant
    other: PlantedTenant
    people: dict[str, Person] = field(default_factory=dict)

    @property
    def ws1(self) -> uuid.UUID:
        return self.tenant.workspaces[0]

    @property
    def ws2(self) -> uuid.UUID:
        return self.tenant.workspaces[1]

    def __getitem__(self, name: str) -> Person:
        return self.people[name]


_WRITE = (FIXTURE_READ, FIXTURE_WRITE, FIXTURE_SUBMIT)


async def _person(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    workspace: uuid.UUID,
    keys: tuple[str, ...],
    depth: str,
) -> Person:
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, workspace, user)
    role = await plant_role(
        conn, tenant.tenant_id, f"studio_t_{user.hex[:12]}", dict.fromkeys(keys, depth)
    )
    await assign(conn, tenant.tenant_id, workspace, membership, role)
    return Person(user, tenant.tenant_id, workspace)


async def plant_world(conn: AsyncConnection) -> StudioWorld:
    """Needs the fixture keys in the catalogue (`planted_fixture_kinds`)."""
    tenant = await plant_tenant(conn, workspaces=2)
    other = await plant_tenant(conn, workspaces=1)
    world = StudioWorld(tenant, other)
    ws1, ws2 = tenant.workspaces
    world.people["writer"] = await _person(conn, tenant, ws1, _WRITE, "workspace")
    world.people["reader"] = await _person(conn, tenant, ws1, (FIXTURE_READ,), "workspace")
    world.people["tenant_reader"] = await _person(conn, tenant, ws1, (FIXTURE_READ,), "tenant")
    world.people["ws2_writer"] = await _person(conn, tenant, ws2, _WRITE, "workspace")
    world.people["outsider"] = await _person(conn, other, other.main, _WRITE, "workspace")
    return world
