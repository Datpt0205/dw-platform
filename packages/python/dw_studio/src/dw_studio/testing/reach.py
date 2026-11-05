"""A test-only oracle of record reach (record-access ticket 02, step 8).

`expected_scope` says, in Python, what `studio.compute_principal_scope()` must
put in a principal's ledger row: the union of every role assignment's object
privileges at its depth (ADR-0104 decision 3), per action and arm, the
workspaces the principal belongs to and the earliest expiry behind it. It is
written from the ticket, not from the SQL, so the differential test compares
two independent answers. `random_organisation` draws an organisation, and
`plant` writes it, as the migrator, in the caller's transaction. Ticket 03
added the default-access arm: a `public_read` or `public_read_write` object in
the read tenant arm of a holder of read at any W1 depth, a `public_read_write`
one in the update tenant arm of a holder of update (ADR-0105 decision 2 (a)).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa

from dw_platform.testing.members import MemberStatus
from dw_platform.testing.rbac import (
    Conn,
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    role_id,
)
from dw_platform.testing.record_objects import plant_object

ACTIONS = ("read", "create", "update", "delete", "assign")
ARMS = ("own", "keys", "tenant")
DEPTHS = ("own", "workspace", "tenant")
OWNER = "tenant_owner"
DEFAULT_ACCESS = ("private", "public_read", "public_read_write")
# The tenant arm each default access opens, by action (gate (c): read-write
# includes read; neither ever opens delete or assign).
_OPENS: dict[str, frozenset[str]] = {
    "read": frozenset({"public_read", "public_read_write"}),
    "update": frozenset({"public_read_write"}),
}


def access_key(object_id: uuid.UUID, workspace_id: uuid.UUID) -> uuid.UUID:
    """`studio.access_key`: md5 of `<object>/<workspace>` read as a uuid."""
    digest = hashlib.md5(f"{object_id}/{workspace_id}".encode(), usedforsecurity=False)
    return uuid.UUID(digest.hexdigest())


@dataclass(frozen=True)
class Role:
    id: uuid.UUID
    key: str
    # (object_id, action, depth)
    privileges: tuple[tuple[uuid.UUID, str, str], ...] = ()


@dataclass(frozen=True)
class Assignment:
    workspace_id: uuid.UUID
    role_id: uuid.UUID
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    status: str
    workspaces: tuple[uuid.UUID, ...]
    assignments: tuple[Assignment, ...] = ()


@dataclass(frozen=True)
class Organisation:
    tenant_id: uuid.UUID
    status: str
    workspaces: tuple[uuid.UUID, ...]
    archived: frozenset[uuid.UUID]
    objects: tuple[uuid.UUID, ...]
    roles: Mapping[uuid.UUID, Role]
    people: tuple[Person, ...]
    # object -> `studio.object_defs.default_access`; `private` when absent.
    default_access: Mapping[uuid.UUID, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Scope:
    """What the ledger row holds for one principal; empty sets when nothing."""

    workspace_ids: frozenset[uuid.UUID] = frozenset()
    arms: Mapping[tuple[str, str], frozenset[uuid.UUID]] = field(default_factory=dict)
    create_own_keys: frozenset[uuid.UUID] = frozenset()
    valid_until: datetime | None = None

    def arm(self, action: str, arm: str) -> frozenset[uuid.UUID]:
        return self.arms.get((action, arm), frozenset())


def _grants(
    org: Organisation, person: Person, now: datetime
) -> list[tuple[uuid.UUID, str, str, uuid.UUID, datetime | None]]:
    """(object, action, depth, anchor, expires_at) of every live assignment."""
    if org.status != "active" or person.status != "active":
        return []
    found = []
    for a in person.assignments:
        if a.workspace_id in org.archived or a.workspace_id not in person.workspaces:
            continue
        if a.expires_at is not None and a.expires_at <= now:
            continue
        role = org.roles[a.role_id]
        privileges = (
            tuple((o, action, "tenant") for o in org.objects for action in ACTIONS)
            if role.key == OWNER
            else role.privileges
        )
        found += [
            (o, action, depth, a.workspace_id, a.expires_at) for o, action, depth in privileges
        ]
    return found


def expected_scope(org: Organisation, person_id: uuid.UUID, now: datetime) -> Scope:
    person = next((p for p in org.people if p.id == person_id), None)
    if person is None:
        return Scope()
    arms: dict[tuple[str, str], set[uuid.UUID]] = {}
    create_own: set[uuid.UUID] = set()
    expiries = []
    for o, action, depth, anchor, expires_at in _grants(org, person, now):
        if depth not in DEPTHS:
            continue
        arms.setdefault((action, "own"), set()).add(o)
        if depth == "workspace":
            arms.setdefault((action, "keys"), set()).add(access_key(o, anchor))
        if depth == "tenant" or org.default_access.get(o, "private") in _OPENS.get(
            action, frozenset()
        ):
            arms.setdefault((action, "tenant"), set()).add(o)
        if action == "create" and depth == "own":
            create_own.add(access_key(o, anchor))
        if expires_at is not None:
            expiries.append(expires_at)
    belongs = org.status == "active" and person.status == "active"
    return Scope(
        workspace_ids=frozenset(w for w in person.workspaces if w not in org.archived)
        if belongs
        else frozenset(),
        arms={k: frozenset(v) for k, v in arms.items()},
        create_own_keys=frozenset(create_own),
        valid_until=min(expiries, default=None),
    )


# -- drawing and planting ----------------------------------------------------------


async def _run(conn: Conn, sql: str, values: Mapping[str, object]) -> None:
    await conn.execute(sa.text(sql), dict(values))


async def plant_random_organisation(conn: Conn, rng: random.Random, now: datetime) -> Organisation:
    """An organisation drawn from `rng`, planted as the caller's role (the
    migrator). Two calls with equal seeds draw the same structure, api names
    included, under fresh ids."""
    tenant = await plant_tenant(conn, workspaces=rng.randint(1, 4))
    t = tenant.tenant_id
    archived = frozenset(w for w in tenant.workspaces[1:] if rng.random() < 0.2)
    for w in archived:
        await _run(
            conn, "UPDATE platform.workspaces SET archived_at = now() WHERE id = :w", {"w": w}
        )
    objects = []
    default_access: dict[uuid.UUID, str] = {}
    for n in range(rng.randint(1, 3)):
        planted = await plant_object(conn, PlantedTenant(t, tenant.workspaces), f"obj{n}", {})
        objects.append(planted.object_id)
        default_access[planted.object_id] = rng.choice(DEFAULT_ACCESS)
        if default_access[planted.object_id] != "private":
            await _run(
                conn,
                "UPDATE studio.object_defs SET default_access = :d WHERE id = :o",
                {"d": default_access[planted.object_id], "o": planted.object_id},
            )

    roles: dict[uuid.UUID, Role] = {}
    owner = await role_id(conn, t, OWNER)
    roles[owner] = Role(owner, OWNER)
    for n in range(rng.randint(1, 3)):
        rid = await plant_role(conn, t, f"r{n}", {})
        privileges = {
            (o, action): rng.choice(DEPTHS)
            for o in objects
            for action in ACTIONS
            if rng.random() < 0.35
        }
        for (o, action), depth in privileges.items():
            await _run(
                conn,
                "INSERT INTO platform.tenant_role_object_privileges"
                " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, :d)",
                {"t": t, "r": rid, "o": o, "a": action, "d": depth},
            )
        roles[rid] = Role(
            rid, f"r{n}", tuple((o, action, depth) for (o, action), depth in privileges.items())
        )

    people = []
    owner_given = False
    for _ in range(rng.randint(1, 4)):
        member: MemberStatus = rng.choices(("active", "suspended", "invited"), weights=(8, 1, 1))[0]
        person = await plant_person(conn, t, status=member)
        spaces = tuple(w for w in tenant.workspaces if rng.random() < 0.6) or (tenant.main,)
        assignments = []
        for w in spaces:
            membership = await plant_membership(conn, t, w, person)
            for rid, role in roles.items():
                if role.key == OWNER:
                    if owner_given or rng.random() > 0.15:
                        continue
                    owner_given, expires = True, None
                elif rng.random() < 0.5:
                    continue
                else:
                    expires = rng.choice(
                        (
                            None,
                            None,
                            now - timedelta(hours=1),
                            now + timedelta(days=rng.randint(1, 9)),
                        )
                    )
                await assign(
                    conn,
                    t,
                    w,
                    membership,
                    rid,
                    expires_at=expires,
                    assigned_at=now - timedelta(hours=2) if expires is not None else None,
                )
                assignments.append(Assignment(w, rid, expires))
        people.append(Person(person, member, spaces, tuple(assignments)))

    status = "locked" if rng.random() < 0.05 else "active"
    if status != "active":
        await _run(
            conn, "UPDATE platform.tenants SET status = :s WHERE id = :t", {"s": status, "t": t}
        )
    return Organisation(
        t,
        status,
        tenant.workspaces,
        archived,
        tuple(objects),
        roles,
        tuple(people),
        default_access,
    )
