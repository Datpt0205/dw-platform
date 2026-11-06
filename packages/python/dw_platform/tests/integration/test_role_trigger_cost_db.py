"""Integration: the three role triggers of tenant-rbac ticket 08 (migration
a7ca12c36ec7) cost by anchors and rules, and answer every write as before.

Two databases of this lane, one migrated to the revision before a7ca12c36ec7
and one to head; neither is ever downgraded, so a revision above this one is
never touched, and both are dropped after the module. A fixed set of writes,
shaped like `make bench-rbac` at a small size, runs on both: each on a tenant
planted fresh as `dw_migrator`, then written in its own transaction as
`dw_app`, the way the services write (`app.tenant_id`, `app.user_id`, a
widening write under a proposal another holder confirms in that very
transaction). Each write gives one result: accepted, or SQLSTATE, constraint,
DETAIL (the reason code, or the people in breach) and HINT (the missing keys,
or the rule); the owner group adds whether `owner_coverage_low_since` is set
and how many `platform.tenant.owner_coverage_low` events the write itself
caused, both read after its commit. People are compared by the name the test
gave them, so the random ids of the two databases never differ a row. The two
lists are equal row by row except the one answer the ticket changes on purpose:
a fall below two holders that the same transaction undoes is told before and
not after (step 1).

The controls K1-K3 of the ticket and its call counts are tested on their own
below, with `track_functions = 'all'` on both databases, as `db/bench/rbac`
sets it, so a count of 0 means "not called".

When a later revision rewrites one of the three functions, `_BEFORE` moves to
that revision's `down_revision` in the same commit (gate (h) of the ticket).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import REPO_ROOT, DatabaseUrls, database_urls, recreate_database, run_alembic
from pg_test_db import ensure_provisioner
from pg_test_db import test_db_name as suffixed  # not collected as a test
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
)
from dw_platform.testing.record_objects import Lead, plant_object

pytestmark = pytest.mark.integration

_BEFORE = "fece6611d786"  # a7ca12c36ec7's down_revision
_NAMES = ("dw_test_trbac08_before", "dw_test_trbac08_after")

KEY = "test.d08.key"
CLOSED = "test.d08.closed"  # in the catalogue, no tenant may hold it
LEFT, RIGHT, OUTSIDE = "test.d08.left", "test.d08.right", "test.d08.outside"
WLEFT, WRIGHT = "test.d08.wleft", "test.d08.wright"
STRICT_RULE, WAIVABLE_RULE = "sod_d08_strict", "sod_d08_waivable"
COVERAGE_EVENT = "platform.tenant.owner_coverage_low"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

ACCEPTED: tuple[str] = ("accepted",)
Result = tuple[Any, ...]
Steps = Callable[[AsyncConnection], Awaitable[None]]


# ---- the two databases ------------------------------------------------------------


async def _prepare(urls: DatabaseUrls, name: str) -> None:
    """Function counters on, the test keys and two rules: one strict, one waivable."""
    admin = create_async_engine(urls.admin, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(
                sa.text(f"ALTER DATABASE {suffixed(name)} SET track_functions = 'all'")
            )
    finally:
        await admin.dispose()
    migrator = create_async_engine(urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            for key in (KEY, LEFT, RIGHT, OUTSIDE, WLEFT, WRIGHT):
                await register_key(conn, key)
            await register_key(conn, CLOSED, tenant_grantable=False)
            for rule, left, right, waivable in (
                (STRICT_RULE, LEFT, RIGHT, False),
                (WAIVABLE_RULE, WLEFT, WRIGHT, True),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.sod_rules (key, description, left_scopes,"
                        " right_scopes, waivable) VALUES (:k, :k, CAST(:l AS jsonb),"
                        " CAST(:r AS jsonb), :w)"
                    ),
                    {"k": rule, "l": json.dumps([left]), "r": json.dumps([right]), "w": waivable},
                )
    finally:
        await migrator.dispose()


async def _drop(admin_url: str, name: str) -> None:
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f"DROP DATABASE IF EXISTS {suffixed(name)} WITH (FORCE)"))
    finally:
        await admin.dispose()


@pytest.fixture(scope="module")
def pair() -> Iterator[tuple[DatabaseUrls, DatabaseUrls]]:
    made: list[DatabaseUrls] = []
    try:
        for name, target in zip(_NAMES, (_BEFORE, "head"), strict=True):
            urls = database_urls(name)
            asyncio.run(recreate_database(urls.admin, name))
            asyncio.run(ensure_provisioner(urls.admin))
            migrated = run_alembic(["upgrade", target], urls.migrator)
            if migrated.returncode != 0:
                pytest.fail(f"upgrade {target} failed:\n{migrated.stdout}\n{migrated.stderr}")
            asyncio.run(_prepare(urls, name))
            made.append(urls)
        yield made[0], made[1]
    finally:
        for name in _NAMES:
            asyncio.run(_drop(database_urls(name).admin, name))


@dataclass
class Db:
    label: str
    migrator: AsyncEngine
    app: AsyncEngine


@pytest.fixture
async def dbs(pair: tuple[DatabaseUrls, DatabaseUrls]) -> AsyncIterator[tuple[Db, Db]]:
    made = [
        Db(
            label,
            create_async_engine(urls.migrator, poolclass=NullPool),
            create_async_engine(urls.app, poolclass=NullPool),
        )
        for label, urls in zip(("before", "after"), pair, strict=True)
    ]
    yield made[0], made[1]
    for db in made:
        await db.migrator.dispose()
        await db.app.dispose()


# ---- a company, planted as the migrator ----------------------------------------------


@dataclass
class Company:
    """A fresh tenant with workspaces A, B, C; people, roles and assignments by
    the names the test gives them."""

    tenant: PlantedTenant
    people: dict[str, uuid.UUID] = field(default_factory=dict)
    roles: dict[str, uuid.UUID] = field(default_factory=dict)
    memberships: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    assignments: dict[tuple[str, str, str], uuid.UUID] = field(default_factory=dict)
    lead: Lead | None = None

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id

    def ws(self, name: str) -> uuid.UUID:
        return self.tenant.workspaces["ABC".index(name)]

    @property
    def names(self) -> dict[uuid.UUID, str]:
        return {user: name for name, user in self.people.items()}


async def company(conn: AsyncConnection, *, owners: int = 2, lead: bool = False) -> Company:
    co = Company(await plant_tenant(conn, workspaces=3))
    co.roles["owner"] = await role_id(conn, co.t, "tenant_owner")
    if lead:
        co.lead = await plant_object(conn, co.tenant)
    for n in range(1, owners + 1):
        await person(conn, co, f"owner_{n}", ("owner", "A"))
    return co


async def role(conn: AsyncConnection, co: Company, name: str, keys: dict[str, str]) -> uuid.UUID:
    co.roles[name] = await plant_role(conn, co.t, f"r_{name}", keys)
    return co.roles[name]


async def membership(conn: AsyncConnection, co: Company, who: str, ws: str) -> uuid.UUID:
    if (who, ws) not in co.memberships:
        co.memberships[(who, ws)] = await plant_membership(conn, co.t, co.ws(ws), co.people[who])
    return co.memberships[(who, ws)]


async def hold(
    conn: AsyncConnection,
    co: Company,
    who: str,
    role_name: str,
    ws: str,
    *,
    expired: bool = False,
) -> None:
    """`who` holds `role_name` at `ws`; `expired`: held two days ago, for one."""
    m = await membership(conn, co, who, ws)
    now = datetime.now(UTC)
    co.assignments[(who, role_name, ws)] = await assign(
        conn,
        co.t,
        co.ws(ws),
        m,
        co.roles[role_name],
        expires_at=now - timedelta(days=1) if expired else None,
        assigned_at=now - timedelta(days=2) if expired else None,
    )


async def person(conn: AsyncConnection, co: Company, who: str, *holds: tuple[str, str]) -> None:
    co.people[who] = await plant_person(conn, co.t)
    await membership(conn, co, who, holds[0][1] if holds else "A")
    for role_name, ws in holds:
        await hold(conn, co, who, role_name, ws)


async def object_row(
    conn: AsyncConnection, co: Company, role_name: str, depth: str, action: str = "read"
) -> None:
    assert co.lead is not None
    await conn.execute(
        sa.text(
            "INSERT INTO platform.tenant_role_object_privileges"
            " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, :d)"
        ),
        {"t": co.t, "r": co.roles[role_name], "o": co.lead.object_id, "a": action, "d": depth},
    )


async def field_row(conn: AsyncConnection, co: Company, role_name: str, access: str) -> None:
    assert co.lead is not None
    await conn.execute(
        sa.text(
            "INSERT INTO studio.field_permissions (tenant_id, role_id, field_id, access)"
            " VALUES (:t, :r, :f, :a)"
        ),
        {"t": co.t, "r": co.roles[role_name], "f": co.lead["phone"], "a": access},
    )


async def restored_breach(
    conn: AsyncConnection, co: Company, who: str, left: str, right: str, ws: str = "B"
) -> None:
    """`who` already holds `left`; a role carrying `right` is assigned to them
    while soft-deleted and then restored as the migrator: the restore passes no
    separation-of-duties trigger, so `who` is in breach before any test write."""
    name = f"restored_{right.rsplit('.', 1)[1]}"
    restored = await role(conn, co, name, {right: "workspace"})
    await conn.execute(
        sa.text("UPDATE platform.tenant_roles SET deleted_at = now() WHERE id = :r"),
        {"r": restored},
    )
    await hold(conn, co, who, name, ws)
    await conn.execute(
        sa.text("UPDATE platform.tenant_roles SET deleted_at = NULL WHERE id = :r"),
        {"r": restored},
    )


async def waive(conn: AsyncConnection, co: Company, rule: str) -> None:
    """A confirmed waiver of `rule` in the company, as two people grant one."""
    await conn.execute(
        sa.text(
            "INSERT INTO platform.sod_waivers (id, tenant_id, rule_key, reason, granted_by)"
            " VALUES (gen_random_uuid(), :t, :k, 'nhỏ', :g)"
        ),
        {"t": co.t, "k": rule, "g": co.people["owner_1"]},
    )
    await conn.execute(
        sa.text(
            "UPDATE platform.sod_waivers SET confirmed_at = now(), confirmed_by = :c,"
            " confirm_reason = 'đồng ý' WHERE tenant_id = :t AND rule_key = :k"
        ),
        {"t": co.t, "k": rule, "c": co.people["owner_2"]},
    )


# ---- writing as dw_app, the way the services write ------------------------------------


async def bind(
    conn: AsyncConnection, co: Company, who: str, request: uuid.UUID | None = None
) -> None:
    await conn.execute(
        sa.text(
            "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true),"
            " set_config('app.role_change_id', :r, true)"
        ),
        {"t": str(co.t), "u": str(co.people[who]), "r": str(request or "")},
    )


async def proposed(
    conn: AsyncConnection,
    co: Company,
    proposer: str,
    confirmer: str,
    kind: str,
    role_name: str,
    payload: dict[str, object],
) -> None:
    """A proposal by `proposer`, confirmed by `confirmer` in this transaction,
    which leaves `confirmer` the actor of the write that follows."""
    request = uuid.uuid4()
    role_uuid = co.roles[role_name]
    await bind(conn, co, proposer)
    version = (
        1
        if kind == "assignment_grant"
        else await conn.scalar(
            sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": role_uuid}
        )
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.role_change_requests (id, tenant_id, kind, payload, role_id,"
            " base_version, required_permission, proposed_by, expires_at, status)"
            " VALUES (:id, :t, :k, CAST(:p AS jsonb), :r, :v, :perm, :by,"
            " now() + interval '7 days', 'proposed')"
        ),
        {
            "id": request,
            "t": co.t,
            "k": kind,
            "p": json.dumps(payload, default=str),
            "r": role_uuid,
            "v": version,
            "perm": "platform.roles.bind" if kind == "assignment_grant" else "platform.roles.write",
            "by": co.people[proposer],
        },
    )
    await bind(conn, co, confirmer, request)
    await conn.execute(
        sa.text(
            "UPDATE platform.role_change_requests"
            " SET status = 'confirmed', confirmed_by = :c, decided_at = now() WHERE id = :id"
        ),
        {"c": co.people[confirmer], "id": request},
    )


def permissions(
    keys: list[dict[str, str]] | None = None,
    objects: list[dict[str, str]] | None = None,
    fields: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "permissions": keys or [],
        "object_privileges": objects or [],
        "field_permissions": fields or [],
    }


async def add_key(
    conn: AsyncConnection, co: Company, actor: str, role_name: str, key: str, depth: str
) -> None:
    """A catalogue key added to a role: proposed by `owner_1`, confirmed by `actor`."""
    await proposed(
        conn,
        co,
        "owner_1",
        actor,
        "role_permissions",
        role_name,
        permissions(keys=[{"key": key, "depth": depth}]),
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key,"
            " depth) VALUES (:t, :r, :k, :d)"
        ),
        {"t": co.t, "r": co.roles[role_name], "k": key, "d": depth},
    )


async def grant_role(
    conn: AsyncConnection,
    co: Company,
    proposer: str,
    actor: str,
    role_name: str,
    who: str,
    ws: str = "A",
) -> uuid.UUID:
    """`role_name` assigned to `who` at `ws`: an `assignment_grant` proposal."""
    m = co.memberships[(who, ws)]
    await proposed(
        conn,
        co,
        proposer,
        actor,
        "assignment_grant",
        role_name,
        {"membership_id": str(m), "workspace_id": str(co.ws(ws)), "user_id": str(co.people[who])},
    )
    made = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO platform.role_assignments"
            " (id, tenant_id, workspace_id, membership_id, role_id, assigned_by)"
            " VALUES (:id, :t, :w, :m, :r, :by)"
        ),
        {
            "id": made,
            "t": co.t,
            "w": co.ws(ws),
            "m": m,
            "r": co.roles[role_name],
            "by": co.people[actor],
        },
    )
    co.assignments[(who, role_name, ws)] = made
    return made


async def revoke(
    conn: AsyncConnection, co: Company, actor: str, who: str, role_name: str, ws: str = "A"
) -> None:
    await bind(conn, co, actor)
    await conn.execute(
        sa.text("DELETE FROM platform.role_assignments WHERE id = :a"),
        {"a": co.assignments[(who, role_name, ws)]},
    )


def _cause(error: BaseException) -> Any:
    return getattr(getattr(error, "orig", None), "__cause__", None)


def _named(text: str | None, names: dict[uuid.UUID, str]) -> str | None:
    """A DETAIL or HINT with each id replaced by the person's name, a list sorted."""
    if text is None or not _UUID.search(text):
        return text
    parts = [part.strip() for part in text.split(",")]
    return ", ".join(sorted(names.get(uuid.UUID(p), p) if _UUID.fullmatch(p) else p for p in parts))


async def attempt(db: Db, co: Company, steps: Steps) -> Result:
    """`steps` in one `dw_app` transaction, committed: what it was answered."""
    try:
        async with db.app.begin() as conn:
            await steps(conn)
    except DBAPIError as error:
        cause = _cause(error)
        return (
            "refused",
            getattr(cause, "sqlstate", None),
            getattr(cause, "constraint_name", None),
            _named(getattr(cause, "detail", None), co.names),
            _named(getattr(cause, "hint", None), co.names),
        )
    return ACCEPTED


async def coverage(db: Db, co: Company) -> tuple[bool, int]:
    """Whether the company is marked below two, and its warning count, past RLS."""
    async with db.migrator.connect() as conn:
        since = await conn.scalar(
            sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
            {"t": co.t},
        )
        events = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.outbox_events"
                " WHERE tenant_id = :t AND event_type = :e"
            ),
            {"t": co.t, "e": COVERAGE_EVENT},
        )
    return since is not None, int(events or 0)


async def planted(db: Db, plant: Callable[[AsyncConnection], Awaitable[Company]]) -> Company:
    async with db.migrator.begin() as conn:
        return await plant(conn)


# ---- the hold rule: op add, raise, remove, lower -------------------------------------

# Where the actor holds the key (anchor, depth); every actor also holds
# `platform.roles.write` at `tenant` in A, which confirming a proposal needs.
CATALOGUE_ACTORS: dict[str, list[tuple[str, str]]] = {
    "ws_a": [("A", "workspace")],
    "ws_b": [("B", "workspace")],
    "ws_ab": [("A", "workspace"), ("B", "workspace")],
    "tenant": [("A", "tenant")],
    "none": [],
}
OBJECT_ACTORS: dict[str, list[tuple[str, str]]] = {
    "own_a": [("A", "own")],
    "tenant": [("A", "tenant")],
    "none": [],
}
FIELD_ACTORS: dict[str, list[tuple[str, str]]] = {"edit": [("A", "edit")], "none": []}
# Where the role is assigned (two holders at A, so an anchor repeats).
ROLE_HOLDERS: dict[str, list[str]] = {
    "unheld": [],
    "at_a": ["A", "A"],
    "at_b": ["B"],
    "at_ab": ["A", "A", "B"],
}
# The role's privilege before the write, and after it (None: no row).
CHANGES: dict[str, dict[str, tuple[str | None, str | None]]] = {
    "catalogue": {
        "add": (None, "workspace"),
        "raise": ("workspace", "tenant"),
        "remove": ("workspace", None),
        "lower": ("tenant", "workspace"),
    },
    "object": {
        "add": (None, "own"),
        "raise": ("own", "workspace"),
        "remove": ("own", None),
        "lower": ("workspace", "own"),
    },
    "field": {
        "add": (None, "read"),
        "raise": ("read", "edit"),
        "remove": ("read", None),
        "lower": ("edit", "read"),
    },
}
_TABLE = {
    "catalogue": ("platform.tenant_role_permissions", "permission_key", "depth"),
    "object": ("platform.tenant_role_object_privileges", "object_id", "depth"),
    "field": ("studio.field_permissions", "field_id", "access"),
}


async def _privilege(
    conn: AsyncConnection, co: Company, kind: str, role_name: str, level: str
) -> None:
    if kind == "catalogue":
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id,"
                " permission_key, depth) VALUES (:t, :r, :k, :d)"
            ),
            {"t": co.t, "r": co.roles[role_name], "k": KEY, "d": level},
        )
    elif kind == "object":
        await object_row(conn, co, role_name, level)
    else:
        await field_row(conn, co, role_name, level)


def _payload(co: Company, kind: str, level: str) -> dict[str, object]:
    if kind == "catalogue":
        return permissions(keys=[{"key": KEY, "depth": level}])
    assert co.lead is not None
    if kind == "object":
        return permissions(
            objects=[{"object_id": str(co.lead.object_id), "action": "read", "depth": level}]
        )
    return permissions(fields=[{"field_id": str(co.lead["phone"]), "access": level}])


def hold_case(kind: str, actor: str, holders: str, op: str) -> Callable[[Db], Awaitable[Result]]:
    actors = {"catalogue": CATALOGUE_ACTORS, "object": OBJECT_ACTORS, "field": FIELD_ACTORS}[kind]
    before, after = CHANGES[kind][op]

    async def plant(conn: AsyncConnection) -> Company:
        co = await company(conn, lead=kind != "catalogue")
        await role(conn, co, "admin", {"platform.roles.write": "tenant"})
        await person(conn, co, "actor", ("admin", "A"))
        if actors[actor]:
            await role(conn, co, "actor_keys", {})
            await _privilege(conn, co, kind, "actor_keys", actors[actor][0][1])
            for ws, _ in actors[actor]:
                await hold(conn, co, "actor", "actor_keys", ws)
        await role(conn, co, "target", {})
        if before is not None:
            await _privilege(conn, co, kind, "target", before)
        for n, ws in enumerate(ROLE_HOLDERS[holders], start=1):
            await person(conn, co, f"holder_{n}", ("target", ws))
        return co

    async def run(db: Db) -> Result:
        co = await planted(db, plant)
        table, column, level_column = _TABLE[kind]
        subject: object = KEY
        if kind != "catalogue":
            assert co.lead is not None
            subject = co.lead.object_id if kind == "object" else co.lead["phone"]

        async def steps(conn: AsyncConnection) -> None:
            values = {"t": co.t, "r": co.roles["target"], "s": subject, "l": after}
            if op == "add":
                await proposed(
                    conn,
                    co,
                    "owner_1",
                    "actor",
                    "role_permissions",
                    "target",
                    _payload(co, kind, str(after)),
                )
                extra = ", action" if kind == "object" else ""
                await conn.execute(
                    sa.text(
                        f"INSERT INTO {table} (tenant_id, role_id, {column}, {level_column}"
                        f"{extra}) VALUES (:t, :r, :s, :l{', :a' if extra else ''})"
                    ),
                    {**values, "a": "read"},
                )
                return
            if op == "raise":
                await proposed(
                    conn,
                    co,
                    "owner_1",
                    "actor",
                    "role_permissions",
                    "target",
                    _payload(co, kind, str(after)),
                )
            else:
                await bind(conn, co, "actor")
            if op == "remove":
                await conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE role_id = :r AND {column} = :s"), values
                )
            else:
                await conn.execute(
                    sa.text(
                        f"UPDATE {table} SET {level_column} = :l"
                        f" WHERE role_id = :r AND {column} = :s"
                    ),
                    values,
                )

        return await attempt(db, co, steps)

    return run


HOLD_CASES = {
    f"hold.{kind}.{actor}.{holders}.{op}": hold_case(kind, actor, holders, op)
    for kind, actors, holder_kinds in (
        ("catalogue", CATALOGUE_ACTORS, ("unheld", "at_a", "at_ab")),
        ("object", OBJECT_ACTORS, ("unheld", "at_a", "at_b")),
        ("field", FIELD_ACTORS, ("unheld", "at_a")),
    )
    for actor in actors
    for holders in holder_kinds
    for op in CHANGES[kind]
}


async def _closed_key(db: Db) -> Result:
    """A key no tenant may hold, refused before the hold rule is asked."""

    async def plant(conn: AsyncConnection) -> Company:
        co = await company(conn)
        await role(conn, co, "target", {})
        await person(conn, co, "holder_1", ("target", "A"))
        return co

    co = await planted(db, plant)
    return await attempt(
        db, co, lambda conn: add_key(conn, co, "owner_2", "target", CLOSED, "tenant")
    )


# ---- assignments: through platform.roles.bind and not ---------------------------------


def bind_case(
    role_keys: dict[str, str], actor: str, grantee: str
) -> Callable[[Db], Awaitable[Result]]:
    """`granted` assigned to `grantee` in A, confirmed by `actor`: a binder skips
    the hold rule for a role that is not critical (`platform.roles.write` makes
    one critical); the owner covers every key."""

    async def plant(conn: AsyncConnection) -> Company:
        co = await company(conn)
        await role(conn, co, "binder", {"platform.roles.bind": "tenant"})
        await person(conn, co, "binder_1", ("binder", "A"))
        await person(conn, co, "binder_2", ("binder", "A"))
        await person(conn, co, "grantee")
        await role(conn, co, "granted", role_keys)
        return co

    async def run(db: Db) -> Result:
        co = await planted(db, plant)
        proposer = "binder_1" if actor == "binder_2" else "binder_2"

        async def steps(conn: AsyncConnection) -> None:
            await grant_role(conn, co, proposer, actor, "granted", grantee)

        return await attempt(db, co, steps)

    return run


BIND_CASES = {
    "bind.plain_role_by_binder": bind_case({KEY: "workspace"}, "binder_1", "grantee"),
    "bind.critical_role_by_binder": bind_case(
        {KEY: "workspace", "platform.roles.write": "tenant"}, "binder_1", "grantee"
    ),
    "bind.critical_role_by_owner": bind_case(
        {KEY: "workspace", "platform.roles.write": "tenant"}, "owner_1", "grantee"
    ),
    "bind.to_oneself": bind_case({KEY: "workspace"}, "binder_1", "binder_1"),
}


# ---- separation of duties ------------------------------------------------------------


@dataclass(frozen=True)
class Sod:
    """`person` holds `holds` (role name, key) in A and `target` (carrying
    `target_keys`) in A; `breach` = (left, right) puts them in breach before
    the write through a restored role; `waived` rules carry a confirmed waiver;
    `clean` more holders of `target` breach nothing; the write adds `key` to
    `target` unless `write` says otherwise."""

    key: str = OUTSIDE
    holds: tuple[tuple[str, str], ...] = (("left", LEFT),)
    target_keys: tuple[tuple[str, str], ...] = ()
    breach: tuple[str, str] | None = None
    waived: tuple[str, ...] = ()
    clean: int = 0
    held: bool = True
    expired: bool = False
    write: str = "add"  # add | raise | lower | assign


def sod_case(case: Sod) -> Callable[[Db], Awaitable[Result]]:
    async def plant(conn: AsyncConnection) -> Company:
        co = await company(conn)
        await person(conn, co, "person")
        for name, key in case.holds:
            await role(conn, co, name, {key: "workspace"})
            await hold(conn, co, "person", name, "A")
        await role(conn, co, "target", dict(case.target_keys))
        if case.held:
            await hold(
                conn,
                co,
                "person",
                "target",
                "A",
                expired=case.expired,
            )
        for n in range(1, case.clean + 1):
            await person(conn, co, f"clean_{n}", ("target", "A"))
        if case.breach is not None:
            await restored_breach(conn, co, "person", *case.breach)
        for rule in case.waived:
            await waive(conn, co, rule)
        if case.write == "assign":
            await role(conn, co, "right_role", {case.key: "workspace"})
            await membership(conn, co, "person", "B")
        return co

    async def run(db: Db) -> Result:
        co = await planted(db, plant)

        async def steps(conn: AsyncConnection) -> None:
            if case.write == "add":
                await add_key(conn, co, "owner_2", "target", case.key, "workspace")
            elif case.write == "raise":
                await proposed(
                    conn,
                    co,
                    "owner_1",
                    "owner_2",
                    "role_permissions",
                    "target",
                    permissions(keys=[{"key": case.key, "depth": "tenant"}]),
                )
                await conn.execute(
                    sa.text(
                        "UPDATE platform.tenant_role_permissions SET depth = 'tenant'"
                        " WHERE role_id = :r AND permission_key = :k"
                    ),
                    {"r": co.roles["target"], "k": case.key},
                )
            elif case.write == "lower":
                await bind(conn, co, "owner_2")
                await conn.execute(
                    sa.text(
                        "UPDATE platform.tenant_role_permissions SET depth = 'workspace'"
                        " WHERE role_id = :r AND permission_key = :k"
                    ),
                    {"r": co.roles["target"], "k": case.key},
                )
            else:
                await grant_role(conn, co, "owner_1", "owner_2", "right_role", "person", "B")

        return await attempt(db, co, steps)

    return run


_BREACH = (LEFT, RIGHT)
_WBREACH = (WLEFT, WRIGHT)
SOD_CASES: dict[str, Sod] = {
    "sod.right_key_to_a_left_holder": Sod(key=RIGHT),
    "sod.left_key_to_a_left_holder": Sod(key=LEFT),
    "sod.outside_key_clean": Sod(clean=2),
    "sod.outside_key_unheld_role": Sod(held=False),
    "sod.outside_key_breached": Sod(breach=_BREACH, clean=1),
    "sod.outside_key_breached_waivable": Sod(holds=(("wleft", WLEFT),), breach=_WBREACH),
    "sod.outside_key_breached_waived": Sod(
        holds=(("wleft", WLEFT),), breach=_WBREACH, waived=(WAIVABLE_RULE,)
    ),
    "sod.outside_key_breached_expired_holder": Sod(breach=_BREACH, expired=True),
    "sod.wright_key_to_a_wleft_holder": Sod(key=WRIGHT, holds=(("wleft", WLEFT),)),
    "sod.wright_key_to_a_wleft_holder_waived": Sod(
        key=WRIGHT, holds=(("wleft", WLEFT),), waived=(WAIVABLE_RULE,)
    ),
    "sod.outside_key_raised_breached": Sod(
        breach=_BREACH, target_keys=((OUTSIDE, "workspace"),), write="raise"
    ),
    "sod.outside_key_lowered_breached": Sod(
        breach=_BREACH, target_keys=((OUTSIDE, "tenant"),), write="lower"
    ),
    "sod.right_role_assigned_to_a_left_holder": Sod(key=RIGHT, write="assign"),
}


# ---- the owner coverage warning ---------------------------------------------------------


async def owner_world(conn: AsyncConnection, owners: int = 2) -> Company:
    """`owners` holders of `tenant_owner` (the only holders of the owner keys),
    `maker` who proposes assignments, `member` with three spare roles, and
    `writer`, a role carrying every owner key the catalogue holds."""
    co = await company(conn, owners=owners)
    await role(conn, co, "maker", {"platform.roles.bind": "tenant"})
    await person(conn, co, "maker", ("maker", "A"))
    owner_keys = await conn.scalars(
        sa.text(
            "SELECT key FROM platform.permissions"
            " WHERE key = ANY (platform.owner_permission_keys()) AND status = 'active'"
        )
    )
    await role(conn, co, "writer", dict.fromkeys(owner_keys, "tenant"))
    await person(conn, co, "member")
    for n in range(1, 4):
        await role(conn, co, f"spare_{n}", {KEY: "workspace"})
        await hold(conn, co, "member", f"spare_{n}", "A")
    return co


async def fall(conn: AsyncConnection, co: Company) -> None:
    """owner_2 loses `tenant_owner`: one holder left."""
    await revoke(conn, co, "owner_1", "owner_2", "owner")


async def rise(conn: AsyncConnection, co: Company) -> None:
    """`member` is given `platform.roles.write`: one more holder."""
    await grant_role(conn, co, "maker", "owner_1", "writer", "member")


async def spare(conn: AsyncConnection, co: Company, n: int = 1) -> None:
    """A write that moves no holder: `member` loses a spare role."""
    await revoke(conn, co, "owner_1", "member", f"spare_{n}")


OwnerSteps = Callable[[AsyncConnection, Company], Awaitable[None]]


def owner_case(*steps: OwnerSteps, owners: int = 2) -> Callable[[Db], Awaitable[Result]]:
    """The steps in one transaction; the answer, whether the company is marked
    below two after the commit, and how many warnings the write caused."""

    async def run(db: Db) -> Result:
        co = await planted(db, lambda conn: owner_world(conn, owners))
        _, told = await coverage(db, co)

        async def body(conn: AsyncConnection) -> None:
            for step in steps:
                await step(conn, co)

        answer = await attempt(db, co, body)
        low, now_told = await coverage(db, co)
        return answer, low, now_told - told

    return run


async def _immediate(conn: AsyncConnection, co: Company) -> None:
    await conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))


def _savepoint(*steps: OwnerSteps) -> OwnerSteps:
    async def run(conn: AsyncConnection, co: Company) -> None:
        await conn.execute(sa.text("SAVEPOINT trbac08"))
        for step in steps:
            await step(conn, co)
        await conn.execute(sa.text("ROLLBACK TO SAVEPOINT trbac08"))

    return run


async def _spares(conn: AsyncConnection, co: Company) -> None:
    for n in range(1, 4):
        await spare(conn, co, n)


async def _up_then_down(conn: AsyncConnection, co: Company) -> None:
    await rise(conn, co)
    await fall(conn, co)
    await revoke(conn, co, "owner_1", "member", "writer")


async def _suspend(conn: AsyncConnection, co: Company) -> None:
    await bind(conn, co, "owner_1")
    await conn.execute(
        sa.text(
            "UPDATE platform.tenant_members SET status = 'suspended'"
            " WHERE tenant_id = :t AND user_id = :u"
        ),
        {"t": co.t, "u": co.people["owner_2"]},
    )


async def _two_tenants(db: Db) -> Result:
    """Two companies fall in one transaction."""
    first = await planted(db, owner_world)
    second = await planted(db, owner_world)
    told = [(await coverage(db, co))[1] for co in (first, second)]

    async def body(conn: AsyncConnection) -> None:
        await fall(conn, first)
        await fall(conn, second)

    answer = await attempt(db, first, body)
    after = [await coverage(db, co) for co in (first, second)]
    return answer, *((low, n - was) for (low, n), was in zip(after, told, strict=True))


OWNER_CASES: dict[str, Callable[[Db], Awaitable[Result]]] = {
    "owner.fall": owner_case(fall),
    "owner.fall_by_suspension": owner_case(_suspend),
    "owner.rise": owner_case(rise, owners=1),
    "owner.no_fall_three_statements": owner_case(_spares),
    "owner.two_tenants_in_one_transaction": _two_tenants,
    "owner.down_then_up_in_one_transaction": owner_case(fall, rise),
    "owner.up_then_down_in_one_transaction": owner_case(_up_then_down),
    "owner.fall_after_set_constraints_immediate": owner_case(_immediate, spare, fall),
    "owner.fall_after_rollback_to_savepoint": owner_case(_immediate, _savepoint(spare), fall),
    "owner.fall_rolled_back_to_savepoint": owner_case(_savepoint(fall)),
}

SCENARIOS: dict[str, Callable[[Db], Awaitable[Result]]] = {
    **HOLD_CASES,
    "hold.closed_key": _closed_key,
    **BIND_CASES,
    **{name: sod_case(case) for name, case in SOD_CASES.items()},
    **OWNER_CASES,
}
# The one answer step 1 changes on purpose: told before, not after.
CHANGED = {
    "owner.down_then_up_in_one_transaction": ((ACCEPTED, False, 1), (ACCEPTED, False, 0)),
}


# ---- step 5: every write of the set, on both databases ------------------------------------


async def test_every_write_is_answered_as_before_but_a_fall_the_transaction_undoes(
    dbs: tuple[Db, Db],
) -> None:
    before, after = dbs
    answers: dict[str, tuple[Result, Result]] = {}
    for name, scenario in SCENARIOS.items():
        one, other = await asyncio.gather(scenario(before), scenario(after))
        answers[name] = (one, other)
    differ = {name: pair for name, pair in answers.items() if pair[0] != pair[1]}
    assert differ == CHANGED
    # The harness wrote as the services do: no write failed for want of an
    # actor or a confirmed proposal, and the set reaches every answer it is for.
    first = [pair[0][0] if name.startswith("owner.") else pair[0] for name, pair in answers.items()]
    refusals = [row for row in first if row[0] == "refused"]
    reasons = {row[3] for row in refusals}
    assert not reasons & {"rbac_two_people", "rbac_actor_missing"}, reasons
    assert {"rbac_escalation", "rbac_not_grantable", "rbac_self_assignment"} <= reasons
    assert {
        "rbac_refusals_tenant_role_permissions",
        "rbac_refusals_tenant_role_object_privileges",
        "rbac_refusals_field_permissions",
        "rbac_refusals_role_assignments",
        "ck_roles_sod_memberships",
    } <= {row[2] for row in refusals}
    for kind in ("catalogue", "object", "field"):
        rows = [pair[0] for name, pair in answers.items() if name.startswith(f"hold.{kind}.")]
        assert ACCEPTED in rows and any(r[0] == "refused" for r in rows), kind
    for name, pair in answers.items():
        if name.startswith("owner.") and name != "owner.two_tenants_in_one_transaction":
            assert pair[1][0] == ACCEPTED, (name, pair)


# ---- K1: the warning, once per fall, in the same transaction -------------------------------


async def test_k1_a_fall_is_told_once_whether_alone_two_tenants_or_after_set_constraints(
    dbs: tuple[Db, Db],
) -> None:
    """R3.12, RB40 at head: one event per company that falls, the column set,
    two companies in one transaction each told, a fall after
    `SET CONSTRAINTS ALL IMMEDIATE` and an earlier write told, a fall after a
    write rolled back to a savepoint told, a fall rolled back not told."""
    _, after = dbs
    told_once = (ACCEPTED, True, 1)
    assert await OWNER_CASES["owner.fall"](after) == told_once
    assert await OWNER_CASES["owner.fall_by_suspension"](after) == told_once
    assert await _two_tenants(after) == (ACCEPTED, (True, 1), (True, 1))
    assert await OWNER_CASES["owner.fall_after_set_constraints_immediate"](after) == told_once
    assert await OWNER_CASES["owner.fall_after_rollback_to_savepoint"](after) == told_once
    assert await OWNER_CASES["owner.up_then_down_in_one_transaction"](after) == told_once
    assert await OWNER_CASES["owner.fall_rolled_back_to_savepoint"](after) == (ACCEPTED, False, 0)
    assert await OWNER_CASES["owner.rise"](after) == (ACCEPTED, False, 0)


async def test_k1_a_fall_after_a_committed_write_on_the_same_connection_is_told(
    dbs: tuple[Db, Db],
) -> None:
    """The mark of one transaction never silences the next on a pooled connection."""
    _, after = dbs
    co = await planted(after, owner_world)
    async with after.app.connect() as conn:
        async with conn.begin():
            await spare(conn, co)
        assert (await coverage(after, co))[0] is False
        async with conn.begin():
            await fall(conn, co)
    assert await coverage(after, co) == (True, 1)


async def test_k1_a_fall_undone_in_its_transaction_was_told_before_and_is_not_now(
    dbs: tuple[Db, Db],
) -> None:
    """The one answer step 1 changes, on purpose: nobody else ever saw the fall."""
    before, after = dbs
    case = OWNER_CASES["owner.down_then_up_in_one_transaction"]
    assert await case(before) == (ACCEPTED, False, 1)
    assert await case(after) == (ACCEPTED, False, 0)


# ---- what each write costs, counted ---------------------------------------------------------


async def calls(db: Db, steps: Steps) -> dict[str, int]:
    """The platform functions `steps` called, deferred triggers fired before the
    count is read; the transaction is rolled back."""
    async with db.app.connect() as conn:
        async with conn.begin() as tx:
            await steps(conn)
            await conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
            rows = await conn.execute(
                sa.text(
                    "SELECT funcname, calls FROM pg_stat_xact_user_functions"
                    " WHERE schemaname = 'platform'"
                )
            )
            counted = {row.funcname: int(row.calls) for row in rows}
            await tx.rollback()
    return counted


async def test_k1_the_coverage_check_runs_once_per_tenant_per_transaction(
    dbs: tuple[Db, Db],
) -> None:
    """Three statements in one transaction: three checks before, one at head."""
    for db, expected in zip(dbs, (3, 1), strict=True):
        co = await planted(db, owner_world)
        counted = await calls(db, partial(_spares, co=co))
        assert counted.get("check_owner_coverage", 0) == expected, (db.label, counted)


async def _held_role(conn: AsyncConnection, actor_holds: list[tuple[str, str]]) -> Company:
    """A role six people hold, four in A and two in B; the actor holds `KEY`
    as `actor_holds` (anchor, depth) and `platform.roles.write`."""
    co = await company(conn)
    await role(conn, co, "admin", {"platform.roles.write": "tenant"})
    await person(conn, co, "actor", ("admin", "A"))
    if actor_holds:
        await role(conn, co, "actor_keys", {KEY: actor_holds[0][1]})
        for ws, _ in actor_holds:
            await hold(conn, co, "actor", "actor_keys", ws)
    await role(conn, co, "target", {})
    for n, ws in enumerate("AAAABB", start=1):
        await person(conn, co, f"holder_{n}", ("target", ws))
    return co


@pytest.mark.parametrize(
    ("actor_holds", "before", "after"),
    [
        ([("A", "tenant")], 6, 1),
        ([("A", "workspace"), ("B", "workspace")], 6, 3),
    ],
    ids=["tenant", "workspace_at_a_and_b"],
)
async def test_k2_the_hold_rule_asks_once_per_anchor_and_once_at_tenant_depth(
    dbs: tuple[Db, Db], actor_holds: list[tuple[str, str]], before: int, after: int
) -> None:
    """A key added to a role with six assignments at two anchors: one
    `holder_covers_grant` per assignment before; at head one when the actor
    holds the key at `tenant`, else one more per distinct anchor."""
    for db, expected in zip(dbs, (before, after), strict=True):
        co = await planted(db, lambda conn: _held_role(conn, actor_holds))
        counted = await calls(
            db,
            partial(add_key, co=co, actor="actor", role_name="target", key=KEY, depth="workspace"),
        )
        assert counted.get("holder_covers_grant", 0) == expected, (db.label, counted)


# ---- K2: the hold rule per anchor refuses what it refused ---------------------------------


@pytest.mark.parametrize(
    ("case", "missing"),
    [
        ("hold.catalogue.ws_a.at_ab.add", f"{KEY}:workspace"),
        ("hold.catalogue.ws_b.at_ab.add", f"{KEY}:workspace"),
        ("hold.catalogue.none.unheld.add", f"{KEY}:workspace"),
        ("hold.object.own_a.at_b.add", "obj.lead.read:own"),
    ],
)
async def test_k2_an_anchor_the_actor_does_not_cover_is_refused_at_head_and_before(
    dbs: tuple[Db, Db], case: str, missing: str
) -> None:
    """R6.1, R9.5 (RB15): the actor holds the key at one of the role's two
    anchors (either one), or the role is held by nobody and the actor holds the
    key nowhere, or holds `own` at A for a role assigned at B."""
    table = "tenant_role_object_privileges" if ".object." in case else "tenant_role_permissions"
    refused = ("refused", "23514", f"rbac_refusals_{table}", "rbac_escalation", missing)
    for db in dbs:
        assert await HOLD_CASES[case](db) == refused, db.label


async def test_k2_an_actor_covering_every_anchor_or_at_tenant_passes(dbs: tuple[Db, Db]) -> None:
    _, after = dbs
    for case in (
        "hold.catalogue.ws_ab.at_ab.add",
        "hold.catalogue.tenant.at_ab.add",
        "hold.catalogue.ws_a.at_a.add",
        "hold.object.own_a.at_a.add",
    ):
        assert await HOLD_CASES[case](after) == ACCEPTED, case


# ---- K3: separation of duties refuses every write it refused -------------------------------


@pytest.mark.parametrize(
    "case",
    [
        "sod.right_key_to_a_left_holder",
        "sod.outside_key_breached",
        "sod.outside_key_breached_waivable",
        "sod.outside_key_breached_expired_holder",
    ],
)
async def test_k3_a_holder_left_or_already_in_breach_is_refused_at_head_and_before(
    dbs: tuple[Db, Db], case: str
) -> None:
    """R5.1 (RB14), ADR-0104 decision 9: a right key for a left holder, and a key
    in no rule for a role whose holder is already in breach (restored as the
    migrator), strict or waivable without a waiver, even through an assignment
    that has expired."""
    rule = WAIVABLE_RULE if "waivable" in case else STRICT_RULE
    refused = ("refused", "23514", "ck_roles_sod_memberships", "person", rule)
    for db in dbs:
        assert await sod_case(SOD_CASES[case])(db) == refused, db.label


async def _clean_holders(conn: AsyncConnection) -> Company:
    co = await company(conn)
    await role(conn, co, "target", {})
    for n in range(1, 4):
        await person(conn, co, f"holder_{n}", ("target", "A"))
    return co


@pytest.mark.parametrize(
    ("key", "before", "after"),
    [(OUTSIDE, 3, 0), (RIGHT, 3, 3), (WLEFT, 3, 3)],
    ids=["outside_every_rule", "right_side", "left_side_of_a_waivable_rule"],
)
async def test_k3_a_key_in_no_rule_asks_no_holder_and_a_key_in_one_still_does(
    dbs: tuple[Db, Db], key: str, before: int, after: int
) -> None:
    """Three clean holders: `sod_violation` per holder for a key on either side
    of a rule, strict or waivable, before and at head; none at head for a key
    in no rule."""
    for db, expected in zip(dbs, (before, after), strict=True):
        co = await planted(db, _clean_holders)
        counted = await calls(
            db,
            partial(
                add_key, co=co, actor="owner_2", role_name="target", key=key, depth="workspace"
            ),
        )
        assert counted.get("sod_violation", 0) == expected, (db.label, counted)


# ---- migrations on a populated database -------------------------------------------------


def _migration_constraints() -> str:
    """What `db/migrations/env.py` runs before the first revision, read from its
    source (importing it would run alembic), and only if `_run_migrations` runs
    it inside the transaction before the revisions."""
    tree = ast.parse((REPO_ROOT / "db" / "migrations" / "env.py").read_text(encoding="utf-8"))
    (value,) = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "MIGRATION_CONSTRAINTS" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    (run,) = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_migrations"
    ]
    calls = [ast.unparse(n.func) for n in ast.walk(run) if isinstance(n, ast.Call)]
    assert calls.index("connection.exec_driver_sql") < calls.index("context.run_migrations")
    return str(value)


async def test_a_revision_may_alter_a_role_table_a_backfill_wrote_on_a_populated_database(
    dbs: tuple[Db, Db],
) -> None:
    """Every revision runs in one transaction. A write of a covered table leaves
    its deferred coverage event pending, and an ALTER TABLE of that table later
    in the transaction is refused (55006) - on a deployed database only, since a
    test database is migrated empty. `env.py` makes constraints immediate first."""
    _, after = dbs
    co = await planted(after, owner_world)
    alter = sa.text(
        "ALTER TABLE platform.role_assignments DISABLE TRIGGER trg_role_assignments_complete_setup"
    )
    backfill = sa.text("DELETE FROM platform.role_assignments WHERE id = :a")
    spare_row = {"a": co.assignments[("member", "spare_1", "A")]}
    async with after.migrator.connect() as conn:
        async with conn.begin() as tx:
            await conn.execute(backfill, spare_row)
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(alter)
            await tx.rollback()
        assert getattr(_cause(caught.value), "sqlstate", None) == "55006"
        async with conn.begin() as tx:
            await conn.execute(sa.text(_migration_constraints()))
            await conn.execute(backfill, spare_row)
            await conn.execute(alter)
            await tx.rollback()
