# ruff: noqa: F811  (the fixtures of test_role_administration_db are imported by name)
"""Integration: object privileges and field permissions in roles, held by the
database for every writer (tenant-rbac ticket 04; migration ef68083f2905).

Raw SQL under the role named, on a migrated Postgres, so a service that forgot
a check cannot hide a trigger or a function that lost one (failure-modes #5).
Worlds are planted as the migrator; a widening write as `dw_app` goes through
a proposal written and confirmed in the test's own transaction, exactly as
`SqlRoleAdminRepository.confirm` does. The API's half of the same criteria is
`apps/api/tests/integration/test_record_privileges_api.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from test_role_administration_db import (  # noqa: F401  (fixtures, used by name)
    app,
    bind,
    confirm,
    migrator,
    propose,
    provisioner,
    refused,
)

from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    grants_of,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    role_id,
    scopes_in,
)
from dw_platform.testing.record_objects import Lead, add_field, plant_object

pytestmark = pytest.mark.integration

_OBJ = "platform.tenant_role_object_privileges"
_FLD = "studio.field_permissions"


@dataclass(frozen=True)
class World:
    """One tenant (two workspaces) with `lead`; `owner_a`, `owner_b` its owners;
    `writer` holds `platform.roles.write` and `obj.lead.read` at workspace in
    ws0; `marketing` is a role nobody but `holder` (ws0) holds; `other` is a
    second tenant with its own `lead`."""

    tenant: PlantedTenant
    lead: Lead
    owner_a: uuid.UUID
    owner_b: uuid.UUID
    writer: uuid.UUID
    writer_role: uuid.UUID
    holder: uuid.UUID
    marketing: uuid.UUID
    other: PlantedTenant
    other_lead: Lead
    other_role: uuid.UUID

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id


async def _person_with(
    conn: AsyncConnection, tenant: PlantedTenant, role: uuid.UUID, workspace: uuid.UUID
) -> uuid.UUID:
    person = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, workspace, person)
    await assign(conn, tenant.tenant_id, workspace, membership, role)
    return person


async def object_row(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    role: uuid.UUID,
    object_id: uuid.UUID,
    action: str,
    depth: str,
) -> None:
    await conn.execute(
        sa.text(
            f"INSERT INTO {_OBJ} (tenant_id, role_id, object_id, action, depth)"
            " VALUES (:t, :r, :o, :a, :d)"
        ),
        {"t": tenant, "r": role, "o": object_id, "a": action, "d": depth},
    )


async def field_row(
    conn: AsyncConnection, tenant: uuid.UUID, role: uuid.UUID, field: uuid.UUID, access: str
) -> None:
    await conn.execute(
        sa.text(
            f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access) VALUES (:t, :r, :f, :a)"
        ),
        {"t": tenant, "r": role, "f": field, "a": access},
    )


@pytest.fixture
async def world(migrator: AsyncEngine) -> World:
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2)
        lead = await plant_object(conn, t)
        owner = await role_id(conn, t.tenant_id, "tenant_owner")
        owner_a = await _person_with(conn, t, owner, t.main)
        owner_b = await _person_with(conn, t, owner, t.main)
        writer_role = await plant_role(
            conn, t.tenant_id, "role_writer", {"platform.roles.write": "tenant"}
        )
        await object_row(conn, t.tenant_id, writer_role, lead.object_id, "read", "workspace")
        writer = await _person_with(conn, t, writer_role, t.main)
        marketing = await plant_role(conn, t.tenant_id, "marketing", {})
        holder = await _person_with(conn, t, marketing, t.main)
        other = await plant_tenant(conn)
        other_lead = await plant_object(conn, other)
        other_role = await plant_role(conn, other.tenant_id, "marketing", {})
    return World(
        t,
        lead,
        owner_a,
        owner_b,
        writer,
        writer_role,
        holder,
        marketing,
        other,
        other_lead,
        other_role,
    )


async def _count(migrator: AsyncEngine, sql: str, **values: object) -> int:
    async with migrator.connect() as conn:
        return int(await conn.scalar(sa.text(sql), values) or 0)


async def _version(migrator: AsyncEngine, role: uuid.UUID) -> int:
    return await _count(migrator, "SELECT version FROM platform.tenant_roles WHERE id = :r", r=role)


async def _access_version(migrator: AsyncEngine, tenant: uuid.UUID) -> int:
    return await _count(
        migrator,
        "SELECT version FROM platform.tenant_access_versions WHERE tenant_id = :t",
        t=tenant,
    )


async def _role_permissions(
    conn: AsyncConnection,
    w: World,
    proposer: uuid.UUID,
    confirmer: uuid.UUID,
    role: uuid.UUID,
    *,
    objects: list[dict[str, str]] | None = None,
    fields: list[dict[str, str]] | None = None,
) -> uuid.UUID:
    """A `role_permissions` proposal carrying ``objects`` and ``fields`` in
    full, confirmed by ``confirmer`` in this transaction: what opens a widening
    write of the new tables."""
    await bind(conn, w.t, proposer)
    version = int(
        await conn.scalar(
            sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": role}
        )
    )
    request = await propose(
        conn,
        w.t,
        proposer,
        "role_permissions",
        {
            "permissions": [],
            "object_privileges": objects or [],
            "field_permissions": fields or [],
        },
        role=role,
        base_version=version,
    )
    await confirm(conn, w.t, confirmer, request)
    return request


# -- R9.2 (RB28) -----------------------------------------------------------------


@pytest.mark.parametrize("action", ["share", "export"])
async def test_r9_2_an_action_not_enforced_is_held_by_no_role_whoever_writes(
    migrator: AsyncEngine, world: World, action: str
) -> None:
    """`share` and `export` are refused by name, the migrator included."""
    async with migrator.connect() as conn:
        with pytest.raises(IntegrityError) as caught:
            await object_row(conn, world.t, world.marketing, world.lead.object_id, action, "tenant")
        await conn.rollback()
    assert refused(caught.value)[0] == "ck_role_object_privileges_action_enforced"
    assert getattr(caught.value.orig, "pgcode", None) == "23514"
    found = await _count(
        migrator, f"SELECT count(*) FROM {_OBJ} WHERE role_id = :r", r=world.marketing
    )
    assert found == 0


async def test_r9_2_the_five_enforced_actions_are_seeded_and_the_two_others_wait(
    migrator: AsyncEngine,
) -> None:
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text("SELECT action, enforced FROM platform.object_actions ORDER BY sort_order")
            )
        ).all()
    assert [(r.action, r.enforced) for r in rows] == [
        ("read", True),
        ("create", True),
        ("update", True),
        ("delete", True),
        ("assign", True),
        ("share", False),
        ("export", False),
    ]


# -- R9.3 (RB31) -----------------------------------------------------------------


async def test_r9_3_deleting_a_definition_removes_its_privileges_in_the_same_transaction(
    migrator: AsyncEngine, world: World
) -> None:
    """The cascade of a hard delete (offboarding's, or the migrator's in a
    test: W1 deletes no definition otherwise) leaves no row and no key."""
    async with migrator.begin() as conn:
        await object_row(conn, world.t, world.marketing, world.lead.object_id, "update", "tenant")
        await field_row(conn, world.t, world.marketing, world.lead["phone"], "edit")
        await field_row(conn, world.t, world.marketing, world.lead["note"], "read")
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM studio.field_defs WHERE id = :f"), {"f": world.lead["phone"]}
        )
    assert (
        await _count(
            migrator, f"SELECT count(*) FROM {_FLD} WHERE field_id = :f", f=world.lead["phone"]
        )
        == 0
    )
    async with migrator.connect() as conn:
        held = {k for k, _ in await grants_of(conn, world.t, world.holder)}
    assert "fld.lead.phone.read" not in held and "fld.lead.note.read" in held
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM studio.field_defs WHERE object_id = :o"),
            {"o": world.lead.object_id},
        )
        await conn.execute(
            sa.text("DELETE FROM studio.object_defs WHERE id = :o"), {"o": world.lead.object_id}
        )
    for table, column in ((_OBJ, "object_id"), (_FLD, "role_id")):
        value = world.lead.object_id if column == "object_id" else world.marketing
        assert (
            await _count(migrator, f"SELECT count(*) FROM {table} WHERE {column} = :v", v=value)
            == 0
        ), table
    async with migrator.connect() as conn:
        held = {k for k, _ in await grants_of(conn, world.t, world.holder)}
        owner = {k for k, _ in await grants_of(conn, world.t, world.owner_a)}
    assert not any(k.startswith(("obj.lead.", "fld.lead.")) for k in held | owner)


# -- R9.8 (RB35) -----------------------------------------------------------------


@pytest.mark.parametrize("which", ["role", "object", "field_role", "field"])
async def test_r9_8_a_row_of_tenant_a_naming_b_is_refused_by_the_composite_key(
    migrator: AsyncEngine, world: World, which: str
) -> None:
    """As the migrator: past RLS and exempt from `rbac_refusals_*`, only the
    composite foreign keys stand between the row and another tenant."""
    async with migrator.connect() as conn:
        with pytest.raises(IntegrityError) as caught:
            if which == "role":
                await object_row(
                    conn, world.t, world.other_role, world.lead.object_id, "read", "tenant"
                )
            elif which == "object":
                await object_row(
                    conn, world.t, world.marketing, world.other_lead.object_id, "read", "tenant"
                )
            elif which == "field_role":
                await field_row(conn, world.t, world.other_role, world.lead["phone"], "read")
            else:
                await field_row(conn, world.t, world.marketing, world.other_lead["phone"], "read")
        await conn.rollback()
    assert getattr(caught.value.orig, "pgcode", None) == "23503"
    assert (
        await _count(
            migrator,
            f"SELECT (SELECT count(*) FROM {_OBJ} WHERE tenant_id = :t)"
            f" + (SELECT count(*) FROM {_FLD} WHERE tenant_id = :t)",
            t=world.t,
        )
        == 1
    )  # the writer's `obj.lead.read`, planted by the world


async def test_r9_8_every_key_of_the_two_tables_is_composite(migrator: AsyncEngine) -> None:
    """A key turned into one column (`object_id` alone) would accept B's object."""
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname, array_length(conkey, 1) AS n,"
                    " confdeltype::text AS on_delete FROM pg_constraint"
                    " WHERE contype = 'f' AND conrelid IN"
                    " ('platform.tenant_role_object_privileges'::regclass,"
                    "  'studio.field_permissions'::regclass)"
                )
            )
        ).all()
    found = {r.conname: (r.n, r.on_delete) for r in rows}
    assert found == {
        "fk_tenant_role_object_privileges_tenant_id_tenant_roles": (2, "c"),
        "fk_tenant_role_object_privileges_tenant_id_object_defs": (2, "c"),
        "fk_tenant_role_object_privileges_action_object_actions": (1, "r"),
        "fk_field_permissions_tenant_id_tenant_roles": (2, "c"),
        "fk_field_permissions_tenant_id_field_defs": (2, "c"),
        "fk_field_permissions_granted_by_users": (1, "n"),
    }


# -- R9.4 (RB29), the projection ---------------------------------------------------


async def test_r9_4_own_depth_reaches_no_workspace_and_the_projection_keeps_it(
    migrator: AsyncEngine, world: World
) -> None:
    async with migrator.begin() as conn:
        await object_row(conn, world.t, world.marketing, world.lead.object_id, "read", "own")
        await object_row(
            conn, world.t, world.marketing, world.lead.object_id, "update", "workspace"
        )
    async with migrator.connect() as conn:
        reach_own = (
            await conn.execute(
                sa.text("SELECT platform.workspace_reach(:t, :u, 'obj.lead.read') AS w"),
                {"t": world.t, "u": world.holder},
            )
        ).all()
        reach_ws = (
            await conn.execute(
                sa.text("SELECT platform.workspace_reach(:t, :u, 'obj.lead.update') AS w"),
                {"t": world.t, "u": world.holder},
            )
        ).all()
        here = await scopes_in(conn, world.t, world.holder, world.tenant.main)
        there = await scopes_in(conn, world.t, world.holder, world.tenant.workspaces[1])
    assert reach_own == []
    assert [r.w for r in reach_ws] == [world.tenant.main]
    # A record key is projected at every depth and every workspace, like `record`.
    assert {"obj.lead.read", "obj.lead.update"} <= here
    assert {"obj.lead.read", "obj.lead.update"} <= there


# -- R9.6, R9.15, R9.7 ---------------------------------------------------------------


async def test_r9_6_r9_15_field_keys_add_up_over_roles_and_edit_gives_read(
    migrator: AsyncEngine, world: World
) -> None:
    async with migrator.begin() as conn:
        role_a = await plant_role(conn, world.t, "role_a", {})
        role_b = await plant_role(conn, world.t, "role_b", {})
        await field_row(conn, world.t, role_a, world.lead["phone"], "read")
        await field_row(conn, world.t, role_b, world.lead["note"], "edit")
        person = await _person_with(conn, world.tenant, role_a, world.tenant.main)
        membership = await conn.scalar(
            sa.text("SELECT id FROM platform.memberships WHERE user_id = :u"), {"u": person}
        )
        await assign(conn, world.t, world.tenant.main, membership, role_b)
        held = await grants_of(conn, world.t, person)
    assert {
        ("fld.lead.phone.read", "tenant"),
        ("fld.lead.note.read", "tenant"),
        ("fld.lead.note.edit", "tenant"),
    } <= held
    assert ("fld.lead.phone.edit", "tenant") not in held


async def test_r9_7_the_owner_holds_every_field_key_computed_and_none_stored(
    migrator: AsyncEngine, world: World
) -> None:
    async with migrator.connect() as conn:
        owner = await grants_of(conn, world.t, world.owner_a)
    for field in ("phone", "cccd", "note"):
        for access in ("read", "edit"):
            assert (f"fld.lead.{field}.{access}", "tenant") in owner, (field, access)
    for action in ("read", "create", "update", "delete", "assign"):
        assert (f"obj.lead.{action}", "tenant") in owner
    assert not {k for k, _ in owner if k in ("obj.lead.share", "obj.lead.export")}
    # Another tenant's object never reaches this owner.
    assert (
        await _count(migrator, f"SELECT count(*) FROM {_FLD} WHERE tenant_id = :t", t=world.t) == 0
    )
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM studio.field_defs WHERE id = :f"), {"f": world.lead["phone"]}
        )
        owner = await grants_of(conn, world.t, world.owner_a)
    assert not {k for k, _ in owner if k.startswith("fld.lead.phone.")}


async def test_the_role_privileges_of_the_owner_match_its_effective_grants(
    migrator: AsyncEngine, world: World
) -> None:
    """One owner: what `role_privileges` says the owner carries is what the
    owner holds, record keys included."""
    async with migrator.connect() as conn:
        owner_role = await role_id(conn, world.t, "tenant_owner")
        carried = {
            (r.permission_key, r.depth)
            for r in await conn.execute(
                sa.text("SELECT * FROM platform.role_privileges(:t, :r)"),
                {"t": world.t, "r": owner_role},
            )
        }
        held = await grants_of(conn, world.t, world.owner_a)
    assert carried == held


# -- R9.5 (RB30), R9.10 (RB45), raw SQL under dw_app -------------------------------------


async def test_r9_10_a_widening_write_without_a_confirmed_proposal_is_refused(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    """The owner holds every key, and still no row enters alone."""
    for write in ("object", "field"):
        async with app.connect() as conn:
            await bind(conn, world.t, world.owner_a)
            with pytest.raises(IntegrityError) as caught:
                if write == "object":
                    await object_row(
                        conn, world.t, world.marketing, world.lead.object_id, "read", "tenant"
                    )
                else:
                    await field_row(conn, world.t, world.marketing, world.lead["phone"], "read")
            await conn.rollback()
        table = "tenant_role_object_privileges" if write == "object" else "field_permissions"
        assert refused(caught.value) == (f"rbac_refusals_{table}", "rbac_two_people")
    assert (
        await _count(migrator, f"SELECT count(*) FROM {_FLD} WHERE role_id = :r", r=world.marketing)
        == 0
    )


async def test_r9_10_a_confirmed_proposal_opens_exactly_its_rows_and_narrowing_needs_one(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    async with app.begin() as conn:
        await _role_permissions(
            conn,
            world,
            world.owner_a,
            world.owner_b,
            world.marketing,
            objects=[
                {"object_id": str(world.lead.object_id), "action": "read", "depth": "workspace"}
            ],
            fields=[{"field_id": str(world.lead["phone"]), "access": "read"}],
        )
        await object_row(conn, world.t, world.marketing, world.lead.object_id, "read", "workspace")
        await field_row(conn, world.t, world.marketing, world.lead["phone"], "read")
        # The same proposal does not open a row it does not carry.
        with pytest.raises(IntegrityError) as caught:
            async with conn.begin_nested():
                await field_row(conn, world.t, world.marketing, world.lead["note"], "read")
    assert refused(caught.value) == ("rbac_refusals_field_permissions", "rbac_two_people")
    async with migrator.connect() as conn:
        held = await grants_of(conn, world.t, world.holder)
    assert {("obj.lead.read", "workspace"), ("fld.lead.phone.read", "tenant")} <= held
    # Removing and lowering need only the person, who holds what they remove.
    async with app.begin() as conn:
        await bind(conn, world.t, world.owner_a)
        await conn.execute(
            sa.text(f"UPDATE {_OBJ} SET depth = 'own' WHERE role_id = :r"), {"r": world.marketing}
        )
        await conn.execute(
            sa.text(f"DELETE FROM {_FLD} WHERE role_id = :r"), {"r": world.marketing}
        )
    async with migrator.connect() as conn:
        held = await grants_of(conn, world.t, world.holder)
    assert ("obj.lead.read", "own") in held
    assert not {k for k, _ in held if k.startswith("fld.")}


async def test_r9_10_raising_depth_and_read_to_edit_widen(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    async with migrator.begin() as conn:
        await object_row(conn, world.t, world.marketing, world.lead.object_id, "read", "own")
        await field_row(conn, world.t, world.marketing, world.lead["phone"], "read")
    for statement in (
        f"UPDATE {_OBJ} SET depth = 'tenant' WHERE role_id = :r",
        f"UPDATE {_FLD} SET access = 'edit' WHERE role_id = :r",
    ):
        async with app.connect() as conn:
            await bind(conn, world.t, world.owner_a)
            with pytest.raises(IntegrityError) as caught:
                await conn.execute(sa.text(statement), {"r": world.marketing})
            await conn.rollback()
        assert refused(caught.value)[1] == "rbac_two_people", statement


async def test_r9_5_a_wider_depth_than_held_or_a_field_key_not_held_is_refused(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    """The writer holds `obj.lead.read` at workspace and no field key; the
    proposal is the owner's, so only the hold rule of the confirming writer
    is judged."""
    cases: tuple[tuple[list[dict[str, str]], list[dict[str, str]], str], ...] = (
        (
            [{"object_id": str(world.lead.object_id), "action": "read", "depth": "tenant"}],
            [],
            "obj.lead.read:tenant",
        ),
        ([], [{"field_id": str(world.lead["phone"]), "access": "edit"}], "fld.lead.phone.edit"),
    )
    for objects, fields, missing in cases:
        async with app.connect() as conn:
            await _role_permissions(
                conn,
                world,
                world.owner_a,
                world.writer,
                world.marketing,
                objects=objects,
                fields=fields,
            )
            with pytest.raises(IntegrityError) as caught:
                if objects:
                    await object_row(
                        conn, world.t, world.marketing, world.lead.object_id, "read", "tenant"
                    )
                else:
                    await field_row(conn, world.t, world.marketing, world.lead["phone"], "edit")
            await conn.rollback()
        assert refused(caught.value)[1] == "rbac_escalation"
        assert missing in (getattr(refused_cause(caught.value), "hint", "") or "")
    # At the depth the writer holds, the same write passes.
    async with app.begin() as conn:
        await _role_permissions(
            conn,
            world,
            world.owner_a,
            world.writer,
            world.marketing,
            objects=[
                {"object_id": str(world.lead.object_id), "action": "read", "depth": "workspace"}
            ],
        )
        await object_row(conn, world.t, world.marketing, world.lead.object_id, "read", "workspace")


def refused_cause(error: BaseException) -> object:
    return getattr(getattr(error, "orig", None), "__cause__", None)


async def test_r9_15_a_holder_of_edit_hands_out_read(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    """`edit` gives `.read` too, so its holder may grant `.read` alone."""
    async with migrator.begin() as conn:
        editor_role = await plant_role(
            conn, world.t, "phone_editor", {"platform.roles.write": "tenant"}
        )
        await field_row(conn, world.t, editor_role, world.lead["phone"], "edit")
        editor = await _person_with(conn, world.tenant, editor_role, world.tenant.main)
    async with app.begin() as conn:
        await _role_permissions(
            conn,
            world,
            world.owner_a,
            editor,
            world.marketing,
            fields=[{"field_id": str(world.lead["phone"]), "access": "read"}],
        )
        await field_row(conn, world.t, world.marketing, world.lead["phone"], "read")


async def test_a_key_of_a_definition_that_is_not_live_is_refused_never_passed(
    app: AsyncEngine, world: World
) -> None:
    """`platform.rbac_refusals` refuses a record key no live definition gives."""
    async with app.connect() as conn:
        await bind(conn, world.t, world.owner_a)
        found = (
            await conn.execute(
                sa.text(
                    "SELECT r.reason_code FROM platform.rbac_refusals(:t, :a, CAST(:c AS jsonb),"
                    " false) r"
                ),
                {
                    "t": world.t,
                    "a": world.owner_a,
                    "c": f'{{"op": "add", "role_id": "{world.marketing}",'
                    ' "permission_key": "obj.ghost.read", "depth": "tenant"}',
                },
            )
        ).all()
        await conn.rollback()
    assert [r.reason_code for r in found] == ["rbac_not_grantable"]


# -- R6.8 (RB33), R9.9 (RB44) ---------------------------------------------------------


async def test_r6_8_bind_does_not_cover_a_role_reading_a_sensitive_field(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    async with migrator.begin() as conn:
        binder_role = await plant_role(conn, world.t, "binder", {"platform.roles.bind": "tenant"})
        binder = await _person_with(conn, world.tenant, binder_role, world.tenant.main)
        reads_cccd = await plant_role(conn, world.t, "reads_cccd", {})
        await field_row(conn, world.t, reads_cccd, world.lead["cccd"], "read")
        reads_phone = await plant_role(conn, world.t, "reads_phone", {})
        await field_row(conn, world.t, reads_phone, world.lead["phone"], "read")
        grantee = await plant_person(conn, world.t)
        membership = await plant_membership(conn, world.t, world.tenant.main, grantee)
        critical = {
            r: await conn.scalar(
                sa.text("SELECT platform.role_is_critical(:t, :r)"), {"t": world.t, "r": r}
            )
            for r in (reads_cccd, reads_phone)
        }
    assert critical == {reads_cccd: True, reads_phone: False}

    async def grant(role: uuid.UUID) -> None:
        async with app.begin() as conn:
            request = await propose(
                conn,
                world.t,
                world.owner_a,
                "assignment_grant",
                {
                    "membership_id": str(membership),
                    "workspace_id": str(world.tenant.main),
                    "user_id": str(grantee),
                },
                role=role,
                base_version=1,
            )
            await confirm(conn, world.t, binder, request)
            await assign(conn, world.t, world.tenant.main, membership, role)

    with pytest.raises(IntegrityError) as caught:
        await grant(reads_cccd)
    assert refused(caught.value) == ("rbac_refusals_role_assignments", "rbac_escalation")
    assert "fld.lead.cccd.read" in (getattr(refused_cause(caught.value), "hint", "") or "")
    await grant(reads_phone)


async def _service_holder(conn: AsyncConnection, w: World, role: uuid.UUID) -> uuid.UUID:
    """A service account of the tenant holding ``role``."""
    service = await plant_person(conn, w.t, kind="service")
    await conn.execute(
        sa.text(
            "INSERT INTO platform.service_principals (user_id, tenant_id, name, owner_user_id,"
            " owning_workspace_id) VALUES (:u, :t, :n, :o, :w)"
        ),
        {"u": service, "t": w.t, "n": f"svc-{service.hex[:8]}", "o": w.owner_a, "w": w.tenant.main},
    )
    membership = await plant_membership(conn, w.t, w.tenant.main, service)
    await assign(conn, w.t, w.tenant.main, membership, role)
    return service


async def test_r9_9_a_sensitive_field_permission_never_reaches_a_service_account(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    async with migrator.begin() as conn:
        svc_role = await plant_role(conn, world.t, "svc_reader", {})
        await field_row(conn, world.t, svc_role, world.lead["note"], "read")
        await _service_holder(conn, world, svc_role)
    async with app.connect() as conn:
        await _role_permissions(
            conn,
            world,
            world.owner_a,
            world.owner_b,
            svc_role,
            fields=[
                {"field_id": str(world.lead["note"]), "access": "read"},
                {"field_id": str(world.lead["cccd"]), "access": "read"},
            ],
        )
        with pytest.raises(IntegrityError) as caught:
            await field_row(conn, world.t, svc_role, world.lead["cccd"], "read")
        await conn.rollback()
    assert refused(caught.value)[0] == "ck_role_assignments_service_not_critical"
    assert (
        await _count(
            migrator,
            f"SELECT count(*) FROM {_FLD} WHERE role_id = :r AND field_id = :f",
            r=svc_role,
            f=world.lead["cccd"],
        )
        == 0
    )
    # A publish making `note` sensitive while the service account reads it.
    async with app.connect() as conn:
        await bind(conn, world.t, world.owner_a)
        with pytest.raises(IntegrityError) as caught:
            await conn.execute(
                sa.text(
                    "UPDATE studio.field_defs SET pd_category = 'sensitive',"
                    " sensitive_type = 'identity_credentials' WHERE id = :f"
                ),
                {"f": world.lead["note"]},
            )
        await conn.rollback()
    assert refused(caught.value)[0] == "ck_role_assignments_service_not_critical"
    # With no service account behind the role, the same publish passes.
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE studio.field_defs SET pd_category = 'sensitive',"
                " sensitive_type = 'identity_credentials' WHERE id = :f"
            ),
            {"f": world.lead["phone"]},
        )


# -- R9.11, R9.12: versions ------------------------------------------------------------


async def test_r9_11_every_write_of_the_two_tables_moves_the_role_version(
    migrator: AsyncEngine, world: World
) -> None:
    steps = (
        f"INSERT INTO {_OBJ} (tenant_id, role_id, object_id, action, depth)"
        " VALUES (:t, :r, :o, 'read', 'own')",
        f"UPDATE {_OBJ} SET depth = 'tenant' WHERE role_id = :r",
        f"DELETE FROM {_OBJ} WHERE role_id = :r",
        f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access) VALUES (:t, :r, :f, 'read')",
        f"UPDATE {_FLD} SET access = 'edit' WHERE role_id = :r",
        f"DELETE FROM {_FLD} WHERE role_id = :r",
    )
    for statement in steps:
        role_before = await _version(migrator, world.marketing)
        access_before = await _access_version(migrator, world.t)
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(statement),
                {
                    "t": world.t,
                    "r": world.marketing,
                    "o": world.lead.object_id,
                    "f": world.lead["phone"],
                },
            )
        assert await _version(migrator, world.marketing) == role_before + 1, statement
        assert await _access_version(migrator, world.t) > access_before, statement


async def test_r9_12_a_definition_added_or_removed_moves_the_access_version_at_commit(
    migrator: AsyncEngine, world: World
) -> None:
    before = await _access_version(migrator, world.t)
    async with migrator.begin() as conn:
        email = await add_field(conn, world.t, world.lead.object_id, "email", "basic", 9)
        # Deferred: the version row is not taken before commit.
        assert (
            await conn.scalar(
                sa.text("SELECT version FROM platform.tenant_access_versions WHERE tenant_id = :t"),
                {"t": world.t},
            )
            == before
        )
    after_insert = await _access_version(migrator, world.t)
    assert after_insert == before + 1
    async with migrator.connect() as conn:
        assert ("fld.lead.email.read", "tenant") in await grants_of(conn, world.t, world.owner_a)
    async with migrator.begin() as conn:
        await conn.execute(sa.text("DELETE FROM studio.field_defs WHERE id = :f"), {"f": email})
    assert await _access_version(migrator, world.t) == after_insert + 1


async def test_r9_12_a_publish_and_a_role_change_take_their_locks_in_one_order(
    db_urls: DatabaseUrls, migrator: AsyncEngine, world: World
) -> None:
    """A publish adds a field and makes another sensitive (locking the roles
    holding it); a role change locks its role and writes a privilege (taking
    the access-version row). Interleaved so that, were the definitions' bump
    immediate, each would hold what the other waits for (40P01). Deferred to
    commit, the version row is taken last, and both commit."""
    async with migrator.begin() as conn:
        await field_row(conn, world.t, world.marketing, world.lead["note"], "read")
    app_engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with app_engine.connect() as publish, migrator.connect() as change:
            await publish.begin()
            await bind(publish, world.t, world.owner_a)
            await add_field(publish, world.t, world.lead.object_id, "email", "basic", 9)
            await change.begin()
            await change.execute(
                sa.text("SELECT 1 FROM platform.tenant_roles WHERE id = :r FOR NO KEY UPDATE"),
                {"r": world.marketing},
            )

            async def make_sensitive() -> None:
                await publish.execute(
                    sa.text(
                        "UPDATE studio.field_defs SET pd_category = 'sensitive',"
                        " sensitive_type = 'identity_credentials' WHERE id = :f"
                    ),
                    {"f": world.lead["note"]},
                )
                await publish.commit()

            async def grant() -> None:
                await asyncio.sleep(0.3)  # the publish waits on the role row first
                await object_row(
                    change, world.t, world.marketing, world.lead.object_id, "read", "tenant"
                )
                await change.commit()

            # Each side holds one row and asks for the other's, were the version
            # row taken at the definition's write; the database then breaks the
            # cycle with 40P01, which a timeout bounds should it not.
            await asyncio.wait_for(asyncio.gather(make_sensitive(), grant()), timeout=20)
    except DBAPIError as exc:  # pragma: no cover - the failure this guards against
        pytest.fail(f"the publish and the role change deadlocked: {exc}")
    finally:
        await app_engine.dispose()
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM studio.field_defs WHERE id = :f AND pd_category = 'sensitive'",
            f=world.lead["note"],
        )
        == 1
    )


# -- the provisioner, the RLS of the two tables --------------------------------------------


async def test_the_provisioner_assigns_an_owner_where_objects_live_and_reaches_no_studio_table(
    migrator: AsyncEngine, provisioner: AsyncEngine, world: World
) -> None:
    """Its writes meet the definer guards, which read the definitions as their
    owner; the provisioner itself holds nothing in schema `studio` (R2.3)."""
    async with migrator.begin() as conn:
        person = await plant_person(conn, world.t)
        membership = await plant_membership(conn, world.t, world.tenant.main, person)
        owner = await role_id(conn, world.t, "tenant_owner")
    async with provisioner.begin() as conn:
        await assign(conn, world.t, world.tenant.main, membership, owner)
    async with migrator.connect() as conn:
        held = {k for k, _ in await grants_of(conn, world.t, person)}
        reach = await conn.scalar(
            sa.text(
                "SELECT has_schema_privilege('dw_provisioner', 'studio', 'USAGE')"
                " OR has_table_privilege('dw_provisioner', 'studio.field_permissions', 'SELECT')"
            )
        )
    assert "fld.lead.cccd.read" in held and "obj.lead.assign" in held
    assert reach is False


@pytest.mark.parametrize("table", [_OBJ, _FLD])
async def test_rows_of_another_tenant_are_invisible_and_unwritable(
    app: AsyncEngine, migrator: AsyncEngine, world: World, table: str
) -> None:
    async with migrator.begin() as conn:
        if table == _OBJ:
            await object_row(
                conn,
                world.other.tenant_id,
                world.other_role,
                world.other_lead.object_id,
                "read",
                "tenant",
            )
        else:
            await field_row(
                conn, world.other.tenant_id, world.other_role, world.other_lead["phone"], "read"
            )
    async with app.connect() as conn:
        await bind(conn, world.t, world.owner_a)
        seen = await conn.scalar(
            sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id = :o"),
            {"o": world.other.tenant_id},
        )
        gone = (
            await conn.execute(
                sa.text(f"DELETE FROM {table} WHERE tenant_id = :o"), {"o": world.other.tenant_id}
            )
        ).rowcount
        await conn.rollback()
    assert (seen, gone) == (0, 0)
