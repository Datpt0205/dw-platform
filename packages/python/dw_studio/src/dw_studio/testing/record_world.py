"""Objects published the real way, people holding object and field privileges,
and a run's door, for the record service's tests (custom-objects ticket 03).

`publish_object` takes a `dw.object/v1` document live through the legal path
(the envelope, a seal, an approved publish, the kind's hook), so its fields
have the slots and `field_no`s the hook gives. `holder` plants a member
whose role carries `obj.<object>.<action>` at a depth and `fld.*` on fields,
as the migrator, the way `test_field_access_db.py` does. `person_door` is the
API's door (`user_session`); `plant_run` and `run_door` are a workflow's or
an agent's, bound from the run row the way the runtime binds them (the run
row itself is planted by the test, `tests/support/studio_planted_runs.py`:
only the run door inserts a Studio run in source, `test_run_request_door.py`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.application.access_context import AccessContext
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
)
from dw_studio.core.adapters.artifact_store import SqlArtifactStore, SqlArtifactTx
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.records.adapters.user_session import user_session
from dw_studio.records.application.record_service import RecordDoor
from dw_studio.testing.lifecycle import publish_on
from dw_studio.testing.objects import running_kinds
from dw_studio.testing.records import act_as_run
from dw_studio.testing.world import Person

RunKind = Literal["agent", "workflow"]


def sessions_of(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def publish_object(
    sessions: async_sessionmaker[AsyncSession],
    manager: Person,
    api_name: str,
    document: Mapping[str, Any],
) -> uuid.UUID:
    """``document`` live as ``api_name`` of the manager's company, applied by
    the kind's hook in the publish transaction; the object's id."""
    ids = Uuid7Generator()
    registry = ArtifactKindRegistry(running_kinds())
    service = ArtifactService(SqlArtifactStore(sessions, ids), registry, SystemClock(), ids)
    context = manager.context()
    row, draft = await service.create(
        context, kind="object", api_name=api_name, labels=[], document=dict(document)
    )
    async with service.store.transaction(context) as tx:
        sealed = await service.seal(tx, row.id, draft.row_version)
    entry = registry.get("object")
    assert entry is not None and entry.publish_hook is not None
    async with service.store.transaction(context) as tx:
        assert isinstance(tx, SqlArtifactTx)
        await publish_on(tx.session, sealed.version_id)
        await entry.publish_hook(tx, sealed.version_id)
    return row.id


async def publish_next(
    sessions: async_sessionmaker[AsyncSession],
    manager: Person,
    object_id: uuid.UUID,
    document: Mapping[str, Any],
) -> uuid.UUID:
    """A next version of the object, ``document``, live the same legal way as
    `publish_object`'s (a draft from the live version, a seal, an approved
    publish, the kind's hook); the new version's id."""
    ids = Uuid7Generator()
    registry = ArtifactKindRegistry(running_kinds())
    service = ArtifactService(SqlArtifactStore(sessions, ids), registry, SystemClock(), ids)
    context = manager.context()
    row = await service.get(context, object_id)
    draft = await service.create_draft(context, object_id, ExpectedVersion(row.row_version))
    saved = await service.save_draft(
        context, object_id, ExpectedVersion(draft.row_version), dict(document)
    )
    async with service.store.transaction(context) as tx:
        sealed = await service.seal(tx, object_id, saved.version.row_version)
    entry = registry.get("object")
    assert entry is not None and entry.publish_hook is not None
    async with service.store.transaction(context) as tx:
        assert isinstance(tx, SqlArtifactTx)
        await publish_on(tx.session, sealed.version_id)
        await entry.publish_hook(tx, sealed.version_id)
    return sealed.version_id


async def field_ids(conn: AsyncConnection, object_id: uuid.UUID) -> dict[str, uuid.UUID]:
    rows = await conn.execute(
        sa.text("SELECT api_name, id FROM studio.field_defs WHERE object_id = :o"),
        {"o": object_id},
    )
    return {r.api_name: r.id for r in rows}


async def holder(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    object_id: uuid.UUID,
    actions: Mapping[str, str],
    fields: Mapping[str, str] | None = None,
    *,
    workspace: uuid.UUID | None = None,
    user: uuid.UUID | None = None,
    kind: str = "human",
) -> Person:
    """A member of ``workspace`` (the main one) whose new role carries
    ``actions`` (action -> depth) on the object and ``fields`` (api_name ->
    read or edit), as the migrator."""
    t, workspace = tenant.tenant_id, workspace or tenant.main
    if user is None:
        user = await plant_person(conn, t, kind=kind)
    else:
        joined = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"
            ),
            {"t": t, "u": user},
        )
        if not joined:
            await add_tenant_member(conn, t, user)
    membership = await conn.scalar(
        sa.text(
            "SELECT id FROM platform.memberships"
            " WHERE tenant_id = :t AND workspace_id = :w AND user_id = :u"
        ),
        {"t": t, "w": workspace, "u": user},
    )
    if membership is None:
        membership = await plant_membership(conn, t, workspace, user)
    role = await plant_role(conn, t, f"r{uuid.uuid4().hex[:10]}", {})
    for action, depth in actions.items():
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_object_privileges"
                " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, :d)"
            ),
            {"t": t, "r": role, "o": object_id, "a": action, "d": depth},
        )
    known = await field_ids(conn, object_id)
    for api_name, access in (fields or {}).items():
        await conn.execute(
            sa.text(
                "INSERT INTO studio.field_permissions (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :r, :f, :a)"
            ),
            {"t": t, "r": role, "f": known[api_name], "a": access},
        )
    await assign(conn, t, workspace, membership, role)
    return Person(user, t, workspace)


def person_door(sessions: async_sessionmaker[AsyncSession], person: Person) -> RecordDoor:
    """The API's door: each transaction is the person's request (`user_session`)."""
    context: AccessContext = person.context()
    return RecordDoor(lambda: user_session(sessions, context))


@asynccontextmanager
async def _run_session(
    sessions: async_sessionmaker[AsyncSession],
    tenant: PlantedTenant,
    principal: uuid.UUID,
    run: uuid.UUID,
    kind: RunKind,
) -> AsyncIterator[AsyncSession]:
    async with sessions() as session, session.begin():
        await act_as_run(
            session, tenant.tenant_id, principal, run, kind=kind, workspace_id=tenant.main
        )
        yield session


def run_door(
    sessions: async_sessionmaker[AsyncSession],
    tenant: PlantedTenant,
    principal: uuid.UUID,
    run: uuid.UUID,
    kind: RunKind = "workflow",
) -> RecordDoor:
    """A step's or a tool's door: each transaction bound from the run's row."""
    return RecordDoor(lambda: _run_session(sessions, tenant, principal, run, kind), run_id=run)
