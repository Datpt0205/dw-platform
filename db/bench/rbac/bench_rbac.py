"""FOG-38 (discovery 08): what tenant roles cost at D12 scale, measured on head.

Five questions, on the schema `alembic upgrade head` builds (tenant-rbac 02-04):

1. `platform.effective_grants`, the access version read and the lookup behind
   every request, for a person in 10 workspaces holding 30 roles over 200
   catalogue keys and 200 generated object keys, an owner and a plain member;
   `GET /api/v1/me` through the real ASGI app, cache warm, right after a version
   bump and with no cache; the bytes of a cached `AccessContext`.
2. One transaction assigning a role to 1,000 people (each through its own
   confirmed proposal, as the triggers demand of `dw_app`), and edits of a role
   1,000 people hold: time, locks, a writer of the same tenant waiting behind
   it, `/me` P99 alongside; the separation-of-duties trigger per row against a
   statement-level prototype.
3. Two sessions racing a revocation against an assignment, 200 rounds each: the
   waiver `platform.sod_violation` locks, and the actor's own assignments
   `platform.rbac_refusals` locks; then the same with `FOR SHARE` taken out of
   the function in this database (never in a repository file), which must leak.
4. `session_user` over 1,000 borrows of the API's asyncpg pools, `SET LOCAL ROLE`
   included, and inside a SECURITY DEFINER function as a trigger sees it.
5. `_STANDING` and `_HOLDERS` (tenant-rbac 10): `platform.scopes_in` in the select
   list, frozen as it stood at `657ef4c6`, against the same call in FROM and the
   modules' own text, one member and a whole workspace (25 and 5,000 members).

Its own database, `dw_bench_rbac` plus `DW_TEST_DB_SUFFIX`, on the compose
PostgreSQL that `.env` names; tenants are planted as `dw_migrator`, measured as
`dw_app`. Not a test: nothing here is in `testpaths`.

    DW_TEST_DB_SUFFIX=_fog38 uv run python db/bench/rbac/bench_rbac.py setup
    DW_TEST_DB_SUFFIX=_fog38 uv run python db/bench/rbac/bench_rbac.py q1 q1gc q2 q3 q4 q5 --out DIR
    DW_TEST_DB_SUFFIX=_fog38 uv run python db/bench/rbac/bench_rbac.py drop
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import platform as host
import random
import secrets
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "support"))

from pg_test_db import (  # noqa: E402
    database_urls,
    load_env,
    provisioner_url,
    recreate_database,
    run_migrations,
    test_db_name,
)

from dw_api.bootstrap import ApiContainer  # noqa: E402
from dw_api.bootstrap.wiring import build_container  # noqa: E402
from dw_api.main import create_app  # noqa: E402
from dw_api.settings import ApiSettings  # noqa: E402
from dw_platform.adapters.identity.dev_token import DEV_ISSUER, DevTokenVerifier  # noqa: E402
from dw_platform.adapters.persistence.caching_lookup import _serialize  # noqa: E402
from dw_platform.adapters.persistence.digital_workers_repo import _STANDING  # noqa: E402
from dw_platform.adapters.persistence.membership_lookup import (  # noqa: E402
    _HELD,
    SqlMembershipLookup,
)
from dw_platform.adapters.persistence.scope_holders import _HOLDERS  # noqa: E402
from dw_platform.testing.rbac import plant_tenant  # noqa: E402
from dw_platform.testing.record_objects import plant_object  # noqa: E402

DB = "dw_bench_rbac"
# The dev-token signing key of this run only: the app and the harness share it in one process.
SECRET = secrets.token_urlsafe(32)
PEOPLE = 5_000
WORKSPACES = 200
KEYS = 200  # catalogue keys planted for the bench (`bench.k_000` ...)
OBJECTS = 40  # x 5 enforced actions = 200 generated object keys
FIELDS = 10  # per object
ROLES = 30  # the measured person holds all 30, three in each of 10 workspaces
BULK = 1_000
ROUNDS = 200
ME_REQUESTS = 300
SOD_RULE = "sod_bench_left_right"
# Inert rules over keys nobody holds, so `sod_violation` walks a realistic list.
INERT_RULES = 4

# The measured profiles of question 1 (index into `World.people`).
HEAVY, OWNER_1, OWNER_2, PLAIN = 0, 1, 2, 3
RACE_SOD_PERSON, RACE_GRANTEE = 3, 4  # in the race tenant
HELD_FROM, BULK_FROM = 1_000, 2_000  # 1,000 holders of `bench_held`; 1,000 bulk grantees


def _key(n: int) -> str:
    return f"bench.k_{n:03d}"


# -- the database -----------------------------------------------------------------


@dataclass(frozen=True)
class Urls:
    admin: str
    migrator: str
    app: str
    provisioner: str
    redis: str
    name: str


def urls() -> Urls:
    found = database_urls(DB)
    host_port = load_env().get("DW_VALKEY_HOST_PORT", "16379")
    return Urls(
        found.admin,
        found.migrator,
        found.app,
        provisioner_url(found.migrator),
        # Its own logical database: the keys carry random tenant ids anyway.
        f"redis://127.0.0.1:{host_port}/7",
        test_db_name(DB),
    )


def engine(url: str) -> AsyncEngine:
    return create_async_engine(url, poolclass=NullPool)


async def run(conn: AsyncConnection, statement: str, **values: object) -> Any:
    return await conn.execute(sa.text(statement), values)


async def bind(conn: AsyncConnection, tenant: uuid.UUID, user: uuid.UUID | None = None) -> None:
    """The settings `tenant_session` gives a transaction: tenant and actor, local."""
    await run(
        conn,
        "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)",
        t=str(tenant),
        u="" if user is None else str(user),
    )


@dataclass
class Person:
    user_id: str
    subject: str
    membership_id: str
    workspace_id: str


@dataclass
class RaceTenant:
    tenant_id: str
    main: str
    owner_1: str
    owner_2: str
    binder: str  # race b's actor, holding `platform.roles.bind` through one assignment
    binder_membership: str
    binder_role: str
    target_role: str
    sod_left_role: str
    sod_right_role: str
    people: list[Person] = field(default_factory=list)


@dataclass
class World:
    tenant_id: str
    workspaces: list[str]
    other_tenant_id: str
    people: list[Person]
    roles: list[str]
    held_role: str
    bulk_roles: list[str]
    objects: list[str]
    race: RaceTenant

    def person(self, n: int) -> Person:
        return self.people[n]


async def save_world(conn: AsyncConnection, world: World) -> None:
    await run(conn, "CREATE SCHEMA IF NOT EXISTS fog38")
    await run(conn, "CREATE TABLE IF NOT EXISTS fog38.world (id int PRIMARY KEY, body jsonb)")
    await run(
        conn,
        "INSERT INTO fog38.world VALUES (1, CAST(:b AS jsonb))"
        " ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body",
        b=json.dumps(asdict(world)),
    )


async def load_world(conn: AsyncConnection) -> World:
    body = (await run(conn, "SELECT body FROM fog38.world WHERE id = 1")).scalar_one()
    race = body.pop("race")
    people = [Person(**p) for p in body.pop("people")]
    race_people = [Person(**p) for p in race.pop("people")]
    return World(people=people, race=RaceTenant(people=race_people, **race), **body)


# -- planting (as the migrator) ---------------------------------------------------


async def _plant_people(
    conn: AsyncConnection, tenant: str, label: str, count: int, workspace_of: Sequence[str]
) -> list[Person]:
    """`count` active members, each with one membership, in bulk statements."""
    await run(
        conn,
        "CREATE TEMP TABLE IF NOT EXISTS seed_people"
        " (n int, user_id uuid, membership_id uuid, workspace_id uuid, subject text)"
        " ON COMMIT DROP",
    )
    await run(conn, "TRUNCATE seed_people")
    await run(
        conn,
        "INSERT INTO seed_people SELECT g, gen_random_uuid(), gen_random_uuid(),"
        " (CAST(:ws AS uuid[]))[1 + (g % :w)], :label || '-' || g"
        " FROM generate_series(0, :c - 1) g",
        ws=list(workspace_of),
        w=len(workspace_of),
        label=label,
        c=count,
    )
    await run(
        conn,
        "INSERT INTO platform.users (id, subject, display_name, kind)"
        " SELECT user_id, subject, 'Người đo ' || n, 'human' FROM seed_people ORDER BY n",
    )
    await run(
        conn,
        "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
        " SELECT CAST(:t AS uuid), user_id, 'active' FROM seed_people ORDER BY n",
        t=tenant,
    )
    await run(
        conn,
        "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
        " SELECT membership_id, CAST(:t AS uuid), workspace_id, user_id FROM seed_people"
        " ORDER BY n",
        t=tenant,
    )
    rows = await run(
        conn, "SELECT user_id, subject, membership_id, workspace_id FROM seed_people ORDER BY n"
    )
    return [Person(str(r[0]), r[1], str(r[2]), str(r[3])) for r in rows]


async def _assign(conn: AsyncConnection, tenant: str, people: Sequence[Person], role: str) -> None:
    """One assignment of `role` per person, at their membership, in one statement."""
    await run(
        conn,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id) SELECT gen_random_uuid(), CAST(:t AS uuid), w, m, CAST(:r AS uuid)"
        " FROM unnest(CAST(:ws AS uuid[]), CAST(:ms AS uuid[])) AS x(w, m)",
        t=tenant,
        r=role,
        ws=[p.workspace_id for p in people],
        ms=[p.membership_id for p in people],
    )


async def _role(conn: AsyncConnection, tenant: str, key: str, keys: dict[str, str]) -> str:
    role = str(uuid.uuid4())
    await run(
        conn,
        "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
        " VALUES (CAST(:r AS uuid), CAST(:t AS uuid), :k, :k, 'role')",
        r=role,
        t=tenant,
        k=key,
    )
    if keys:
        await run(
            conn,
            "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key,"
            " depth) SELECT CAST(:t AS uuid), CAST(:r AS uuid), k, d"
            " FROM unnest(CAST(:ks AS text[]), CAST(:ds AS text[])) AS x(k, d)",
            t=tenant,
            r=role,
            ks=list(keys),
            ds=list(keys.values()),
        )
    return role


async def _system_role(conn: AsyncConnection, tenant: str, key: str) -> str:
    found = await run(
        conn,
        "SELECT id FROM platform.tenant_roles WHERE tenant_id = CAST(:t AS uuid) AND key = :k",
        t=tenant,
        k=key,
    )
    return str(found.scalar_one())


async def _membership(conn: AsyncConnection, tenant: str, workspace: str, user: str) -> str:
    membership = str(uuid.uuid4())
    await run(
        conn,
        "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
        " VALUES (CAST(:m AS uuid), CAST(:t AS uuid), CAST(:w AS uuid), CAST(:u AS uuid))",
        m=membership,
        t=tenant,
        w=workspace,
        u=user,
    )
    return membership


async def _assign_one(
    conn: AsyncConnection, tenant: str, workspace: str, membership: str, role: str
) -> str:
    assignment = str(uuid.uuid4())
    await run(
        conn,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id) VALUES (CAST(:a AS uuid), CAST(:t AS uuid), CAST(:w AS uuid),"
        " CAST(:m AS uuid), CAST(:r AS uuid))",
        a=assignment,
        t=tenant,
        w=workspace,
        m=membership,
        r=role,
    )
    return assignment


async def plant_catalogue(conn: AsyncConnection) -> None:
    """200 bench keys, the separation-of-duties keys and rules; all removed by `cleanup`."""
    keys = [_key(n) for n in range(KEYS)] + ["bench.sod_left", "bench.sod_right"]
    keys += [f"bench.inert_{n}" for n in range(2 * INERT_RULES)]
    await run(
        conn,
        "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
        " owner_package, tenant_grantable) SELECT k, 'bench', 'Khóa đo FOG-38', 'workspace',"
        " 'standard', 'active', 'fog38', true FROM unnest(CAST(:ks AS text[])) k",
        ks=keys,
    )
    rules = [(SOD_RULE, "bench.sod_left", "bench.sod_right", True)] + [
        (f"sod_bench_inert_{n}", f"bench.inert_{2 * n}", f"bench.inert_{2 * n + 1}", False)
        for n in range(INERT_RULES)
    ]
    for key, left, right, waivable in rules:
        await run(
            conn,
            "INSERT INTO platform.sod_rules (key, description, left_scopes, right_scopes,"
            " waivable) VALUES (:k, 'Luật đo FOG-38', CAST(:l AS jsonb), CAST(:r AS jsonb), :w)",
            k=key,
            l=json.dumps([left]),
            r=json.dumps([right]),
            w=waivable,
        )


async def plant_company(conn: AsyncConnection) -> World:
    tenant = await plant_tenant(conn, workspaces=WORKSPACES)
    t = str(tenant.tenant_id)
    workspaces = [str(w) for w in tenant.workspaces]
    other = await plant_tenant(conn, workspaces=1)

    objects = []
    for n in range(OBJECTS):
        lead = await plant_object(
            conn, tenant, f"bench_obj_{n:02d}", {f"f{m:02d}": "basic" for m in range(FIELDS)}
        )
        objects.append((str(lead.object_id), [str(f) for f in lead.fields.values()]))

    # Roles before people: every statement on a role table runs
    # `platform.check_owner_coverage`, whose cost grows with the members (q2
    # measures it); planting them first keeps the seed to minutes.
    # 30 roles: each 20 catalogue keys (every key in three roles), 20 object
    # privileges over four objects (every object in three roles) and five field
    # permissions.
    depths = ("own", "workspace", "tenant")
    roles = []
    for r in range(ROLES):
        role = await _role(
            conn,
            t,
            f"bench_role_{r:02d}",
            {_key((r * 20 + j) % KEYS): "workspace" for j in range(20)},
        )
        await run(
            conn,
            "INSERT INTO platform.tenant_role_object_privileges (tenant_id, role_id, object_id,"
            " action, depth) SELECT CAST(:t AS uuid), CAST(:r AS uuid), o, a, d"
            " FROM unnest(CAST(:os AS uuid[]), CAST(:as AS text[]), CAST(:ds AS text[]))"
            " AS x(o, a, d)",
            t=t,
            r=role,
            os=[objects[(r * 4 + j // 5) % OBJECTS][0] for j in range(20)],
            **{"as": [("read", "create", "update", "delete", "assign")[j % 5] for j in range(20)]},
            ds=[depths[j % 3] for j in range(20)],
        )
        await run(
            conn,
            "INSERT INTO studio.field_permissions (tenant_id, role_id, field_id, access)"
            " SELECT CAST(:t AS uuid), CAST(:r AS uuid), f, 'read'"
            " FROM unnest(CAST(:fs AS uuid[])) f",
            t=t,
            r=role,
            fs=objects[(r * 4) % OBJECTS][1][:5],
        )
        roles.append(role)
    held = await _role(conn, t, "bench_held", {_key(n): "workspace" for n in range(3)})
    bulk_roles = [
        await _role(conn, t, f"bench_bulk_{n}", {_key(10 + n): "workspace"}) for n in range(6)
    ]

    people = await _plant_people(conn, t, "fog38", PEOPLE, workspaces)
    member = await _system_role(conn, t, "member")
    owner = await _system_role(conn, t, "tenant_owner")
    await _assign(conn, t, people, member)
    await _assign(conn, t, [people[OWNER_1], people[OWNER_2]], owner)
    await _assign(conn, t, people[HELD_FROM : HELD_FROM + BULK], held)

    heavy = people[HEAVY]
    # The measured person: memberships in ten workspaces, three roles in each.
    memberships = {heavy.workspace_id: heavy.membership_id}
    for ws in workspaces[:10]:
        if ws not in memberships:
            memberships[ws] = await _membership(conn, t, ws, heavy.user_id)
    rows = [
        (ws, memberships[ws], roles[w * 3 + r])
        for w, ws in enumerate(workspaces[:10])
        for r in range(3)
    ]
    await run(
        conn,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id) SELECT gen_random_uuid(), CAST(:t AS uuid), w, m, r"
        " FROM unnest(CAST(:ws AS uuid[]), CAST(:ms AS uuid[]), CAST(:rs AS uuid[]))"
        " AS x(w, m, r)",
        t=t,
        ws=[r[0] for r in rows],
        ms=[r[1] for r in rows],
        rs=[r[2] for r in rows],
    )
    race = await plant_race_tenant(conn)
    return World(
        tenant_id=t,
        workspaces=workspaces,
        other_tenant_id=str(other.tenant_id),
        people=people,
        roles=roles,
        held_role=held,
        bulk_roles=bulk_roles,
        objects=[o for o, _ in objects],
        race=race,
    )


async def plant_race_tenant(conn: AsyncConnection) -> RaceTenant:
    """A small company for question 3. The race does not depend on its size, and
    every write to a role table judges the whole company's owner coverage (q2),
    so five people: two owners, the binder, race a's person (holding the left
    side; each round gives and then takes back the right one) and race b's
    grantee (given the target role, taken back after each round)."""
    tenant = await plant_tenant(conn, workspaces=1)
    t, main = str(tenant.tenant_id), str(tenant.main)
    binder = await _role(conn, t, "bench_binder", {"platform.roles.bind": "tenant"})
    target = await _role(conn, t, "bench_target", {_key(0): "workspace"})
    left = await _role(conn, t, "bench_sod_left", {"bench.sod_left": "workspace"})
    right = await _role(conn, t, "bench_sod_right", {"bench.sod_right": "workspace"})
    people = await _plant_people(conn, t, "fog38race", 5, [main])
    owner = await _system_role(conn, t, "tenant_owner")
    await _assign(conn, t, people[:2], owner)
    await _assign(conn, t, [people[RACE_SOD_PERSON]], left)
    return RaceTenant(
        tenant_id=t,
        main=main,
        owner_1=people[0].user_id,
        owner_2=people[1].user_id,
        binder=people[2].user_id,
        binder_membership=people[2].membership_id,
        binder_role=binder,
        target_role=target,
        sod_left_role=left,
        sod_right_role=right,
        people=people,
    )


def setup() -> None:
    u = urls()
    asyncio.run(recreate_database(u.admin, DB))
    # It runs event loops of its own (the provisioner's password first).
    migrated = run_migrations(u.migrator)
    if migrated.returncode != 0:
        raise SystemExit(f"migrations failed:\n{migrated.stdout}\n{migrated.stderr}")
    asyncio.run(plant(u))


async def plant(u: Urls) -> None:
    admin = engine(u.admin.rsplit("/", 1)[0] + f"/{u.name}")
    async with admin.begin() as conn:
        # Per-function time inside a transaction (`pg_stat_xact_user_functions`)
        # attributes a write's cost to each trigger; a superuser setting.
        await run(conn, f"ALTER DATABASE {u.name} SET track_functions = 'all'")
    await admin.dispose()
    migrator = engine(u.migrator)
    started = time.perf_counter()
    async with migrator.begin() as conn:
        await plant_catalogue(conn)
        world = await plant_company(conn)
        await save_world(conn, world)
    await migrator.dispose()
    vacuum = create_async_engine(
        u.admin.rsplit("/", 1)[0] + f"/{u.name}", isolation_level="AUTOCOMMIT"
    )
    async with vacuum.connect() as conn:
        await run(conn, "VACUUM ANALYZE")
    await vacuum.dispose()
    print(f"planted in {time.perf_counter() - started:.1f} s: tenant {world.tenant_id}")


async def cleanup() -> None:
    """The planted catalogue rows first, as the ticket asks, then the database."""
    u = urls()
    migrator = engine(u.migrator)
    try:
        async with migrator.begin() as conn:
            await run(conn, "DELETE FROM platform.sod_waivers WHERE rule_key LIKE 'sod_bench_%'")
            await run(conn, "DELETE FROM platform.sod_rules WHERE key LIKE 'sod_bench_%'")
            await run(
                conn,
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key LIKE 'bench.%'",
            )
            await run(conn, "DELETE FROM platform.permissions WHERE key LIKE 'bench.%'")
            left = await run(
                conn, "SELECT count(*) FROM platform.permissions WHERE key LIKE 'bench.%'"
            )
            print(f"bench catalogue rows left: {left.scalar_one()}")
    finally:
        await migrator.dispose()
    admin = create_async_engine(u.admin, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await run(conn, f"DROP DATABASE IF EXISTS {u.name} WITH (FORCE)")
    await admin.dispose()
    print(f"dropped {u.name}")


# -- numbers --------------------------------------------------------------------


def pct(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    rank = max(1, min(len(ordered), round(p / 100 * len(ordered) + 0.4999)))
    return ordered[rank - 1]


def summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50": round(pct(values, 50), 2),
        "p95": round(pct(values, 95), 2),
        "p99": round(pct(values, 99), 2),
        "max": round(max(values), 2) if values else float("nan"),
    }


def ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


# -- the app ----------------------------------------------------------------------


@asynccontextmanager
async def api(u: Urls, *, cache: bool) -> AsyncIterator[tuple[httpx.AsyncClient, ApiContainer]]:
    """The real app over its real wiring: Valkey when `cache`, none otherwise."""
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=u.app,
            provisioner_database_url=u.provisioner,
            dev_secret=SECRET,
            # 240 a minute per caller would refuse the run itself; tests set 0 too.
            rate_limit_per_minute=0,
            redis_url=u.redis if cache else None,
        )
    )
    app = create_app(container)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
                yield client, container
    finally:
        if container.engine is not None:
            await container.engine.dispose()
        if container.provisioner_engine is not None:
            await container.provisioner_engine.dispose()


def me_call(
    client: httpx.AsyncClient, person: Person, tenant: str
) -> Callable[[], Awaitable[httpx.Response]]:
    headers = {
        "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
        "X-Tenant-Id": tenant,
        "X-Workspace-Id": person.workspace_id,
    }

    async def call() -> httpx.Response:
        return await client.get("/api/v1/me", headers=headers)

    return call


async def timed_me(call: Callable[[], Awaitable[httpx.Response]]) -> float:
    start = time.perf_counter()
    response = await call()
    took = ms(start)
    if response.status_code != 200:
        raise RuntimeError(f"/me answered {response.status_code}: {response.text[:300]}")
    return took


async def bump(migrator: AsyncEngine, tenant: str) -> None:
    """What every trigger on an authorization table does to the version row."""
    async with migrator.begin() as conn:
        await run(
            conn,
            "UPDATE platform.tenant_access_versions SET version = version + 1,"
            " changed_at = now() WHERE tenant_id = CAST(:t AS uuid)",
            t=tenant,
        )


# -- question 1 -------------------------------------------------------------------


async def explain_ms(conn: AsyncConnection, statement: str, **values: object) -> float:
    plan = (await run(conn, f"EXPLAIN (ANALYZE, FORMAT JSON) {statement}", **values)).scalar_one()
    return float(plan[0]["Execution Time"])


async def q1(u: Urls, world: World) -> dict[str, Any]:
    out: dict[str, Any] = {"functions": {}, "me": {}, "bytes": {}}
    app = engine(u.app)
    profiles = {"heavy": HEAVY, "owner": OWNER_1, "plain": PLAIN}
    t = world.tenant_id
    async with app.connect() as conn:
        await run(conn, "SELECT set_config('app.tenant_id', :t, false)", t=t)
        version = (
            "SELECT version FROM platform.tenant_access_versions WHERE tenant_id = CAST(:t AS uuid)"
        )
        statements: dict[str, tuple[str, dict[str, object]]] = {
            "access_version": (version, {"t": t}),
        }
        for name, n in profiles.items():
            p = world.person(n)
            statements[f"effective_grants:{name}"] = (
                "SELECT * FROM platform.effective_grants(CAST(:t AS uuid), CAST(:u AS uuid))",
                {"t": t, "u": p.user_id},
            )
            statements[f"lookup_held:{name}"] = (
                str(_HELD.text),
                {"t": t, "u": p.user_id, "w": p.workspace_id, "m": p.membership_id},
            )
        for name, (statement, values) in statements.items():
            rows = len((await run(conn, statement, **values)).all())
            for _ in range(20):  # warm
                await run(conn, statement, **values)
            trips = []
            for _ in range(1_000):
                start = time.perf_counter()
                (await run(conn, statement, **values)).all()
                trips.append(ms(start))
            server = [await explain_ms(conn, statement, **values) for _ in range(1_000)]
            out["functions"][name] = {
                "rows": rows,
                "round_trip_ms": summary(trips),
                "execution_ms": summary(server),
            }
            print(name, rows, out["functions"][name]["execution_ms"])
        grants = await run(
            conn,
            "SELECT count(*), count(DISTINCT permission_key),"
            " count(*) FILTER (WHERE permission_key LIKE 'obj.%'),"
            " count(*) FILTER (WHERE permission_key LIKE 'fld.%')"
            " FROM platform.effective_grants(CAST(:t AS uuid), CAST(:u AS uuid))",
            t=t,
            u=world.person(HEAVY).user_id,
        )
        out["heavy_grants"] = dict(
            zip(("rows", "distinct_keys", "object_rows", "field_rows"), grants.one(), strict=True)
        )
        plan = await run(
            conn,
            "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM platform.effective_grants("
            "CAST(:t AS uuid), CAST(:u AS uuid))",
            t=t,
            u=world.person(HEAVY).user_id,
        )
        out["heavy_plan"] = [r[0] for r in plan]
    await app.dispose()

    # The AccessContext as the cache stores it.
    lookup_engine = engine(u.app)
    lookup = SqlMembershipLookup(async_sessionmaker(lookup_engine, expire_on_commit=False))
    for name, n in profiles.items():
        p = world.person(n)
        access = await lookup.find_access(
            p.subject, DEV_ISSUER, uuid.UUID(t), uuid.UUID(p.workspace_id)
        )
        assert access is not None, name
        out["bytes"][name] = {
            "serialized": len(_serialize(access).encode()),
            "grants": len(access.grants),
            "scopes": len(access.scopes),
        }
    await lookup_engine.dispose()

    migrator = engine(u.migrator)
    for cached in (True, False):
        async with api(u, cache=cached) as (client, container):
            for name, n in profiles.items():
                call = me_call(client, world.person(n), t)
                for _ in range(20):
                    await timed_me(call)
                body = (await call()).content
                if cached:
                    warm = [await timed_me(call) for _ in range(ME_REQUESTS)]
                    after_bump = []
                    for _ in range(ME_REQUESTS):
                        await bump(migrator, t)
                        after_bump.append(await timed_me(call))
                    out["me"][f"{name}:warm"] = summary(warm)
                    out["me"][f"{name}:after_bump"] = summary(after_bump)
                    out["bytes"][name]["me_body"] = len(body)
                else:
                    out["me"][f"{name}:no_cache"] = summary(
                        [await timed_me(call) for _ in range(ME_REQUESTS)]
                    )
            if cached:
                redis = container.cache.client  # type: ignore[attr-defined]
                keys = [k async for k in redis.scan_iter(match=f"ml:{t}:*")]
                sizes = [await redis.memory_usage(k) for k in keys]
                out["bytes"]["valkey_memory_usage"] = sizes[:10]
        print(json.dumps(out["me"], indent=1))
    await migrator.dispose()
    return out


# -- question 2 -------------------------------------------------------------------


LOCKS = (
    "SELECT locktype, coalesce(relation::regclass::text, ''), mode, granted, count(*)"
    " FROM pg_locks WHERE pid = :pid GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC, 2"
)
WAITING = (
    "SELECT l.pid, l.locktype, coalesce(l.relation::regclass::text, ''), l.mode,"
    " left(a.query, 80) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
    " WHERE NOT l.granted"
)
FUNCTIONS = (
    "SELECT schemaname || '.' || funcname, calls, round(total_time::numeric, 1),"
    " round(self_time::numeric, 1) FROM pg_stat_xact_user_functions"
    " WHERE total_time > 1 ORDER BY total_time DESC LIMIT 15"
)


async def plant_proposals(
    migrator: AsyncEngine,
    tenant: str,
    proposer: str,
    kind: str,
    role: str,
    payloads: Sequence[dict[str, object]],
) -> list[str]:
    ids = [str(uuid.uuid4()) for _ in payloads]
    async with migrator.begin() as conn:
        await run(
            conn,
            "INSERT INTO platform.role_change_requests (id, tenant_id, kind, payload, role_id,"
            " required_permission, proposed_by, expires_at, status)"
            " SELECT i, CAST(:t AS uuid), :k, p, CAST(:r AS uuid),"
            " CASE WHEN :k = 'assignment_grant' THEN 'platform.roles.bind'"
            " ELSE 'platform.roles.write' END, CAST(:by AS uuid),"
            " now() + interval '7 days', 'proposed'"
            " FROM unnest(CAST(:ids AS uuid[]), CAST(:ps AS jsonb[])) AS x(i, p)",
            t=tenant,
            k=kind,
            r=role,
            by=proposer,
            ids=ids,
            ps=[json.dumps(p) for p in payloads],
        )
    return ids


async def confirm(conn: AsyncConnection, request: str, checker: str) -> None:
    """What `SqlRoleAdminRepository.confirm` writes before it applies the change."""
    await run(
        conn,
        "UPDATE platform.role_change_requests SET status = 'confirmed',"
        " confirmed_by = CAST(:u AS uuid), decided_at = now() WHERE id = CAST(:id AS uuid)",
        u=checker,
        id=request,
    )
    await run(conn, "SELECT set_config('app.role_change_id', :id, true)", id=request)


async def assign_confirmed(
    conn: AsyncConnection, tenant: str, request: str, checker: str, person: Person, role: str
) -> None:
    await confirm(conn, request, checker)
    await run(
        conn,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id, assigned_by) VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:w AS uuid),"
        " CAST(:m AS uuid), CAST(:r AS uuid), CAST(:u AS uuid))",
        t=tenant,
        w=person.workspace_id,
        m=person.membership_id,
        r=role,
        u=checker,
    )


@dataclass
class Alongside:
    """`/me` requests running beside a write, with when each one finished."""

    samples: list[tuple[float, float]] = field(default_factory=list)
    stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def drive(self, call: Callable[[], Awaitable[httpx.Response]]) -> None:
        while not self.stop.is_set():
            took = await timed_me(call)
            self.samples.append((time.perf_counter(), took))

    def within(self, start: float, end: float) -> list[float]:
        return [took for at, took in self.samples if start <= at - took / 1000 and at <= end]


async def probe_waiter(migrator: AsyncEngine, tenant: str) -> float:
    """A write to the tenant row from another session: its version bump waits."""
    start = time.perf_counter()
    async with migrator.begin() as conn:
        await run(conn, "SET LOCAL lock_timeout = '30min'")
        await run(
            conn,
            "UPDATE platform.tenants SET name = name WHERE id = CAST(:t AS uuid)",
            t=tenant,
        )
    return ms(start)


Body = Callable[[AsyncConnection, asyncio.Event], Awaitable[None]]


async def write_with_watch(
    u: Urls,
    world: World,
    label: str,
    body: Body,
    *,
    actor: str,
    clients: dict[str, httpx.AsyncClient],
) -> dict[str, Any]:
    """Run `body` in one `dw_app` transaction as `actor`, with `/me` driven beside
    it by each of `clients` (none: the write alone). Once the body says its first
    statement is in (`wrote`), a writer of the same tenant and one of another
    tenant try a write that bumps their access version, and `pg_locks` is read:
    the writer's own locks and every lock some session waits for."""
    app, migrator = engine(u.app), engine(u.migrator)
    monitor = engine(u.admin.rsplit("/", 1)[0] + f"/{u.name}")
    lanes = {name: Alongside() for name in clients}
    drivers = [
        asyncio.create_task(lanes[name].drive(me_call(c, world.person(HEAVY), world.tenant_id)))
        for name, c in clients.items()
    ]
    wrote = asyncio.Event()
    result: dict[str, Any] = {"label": label, "with_me": sorted(clients)}

    async def probe(tenant: str) -> float:
        await wrote.wait()
        return await probe_waiter(migrator, tenant)

    async def look(pid: int) -> None:
        await wrote.wait()
        await asyncio.sleep(0.5)
        async with monitor.connect() as m:
            result["writer_locks"] = [list(r) for r in await run(m, LOCKS, pid=pid)]
            result["waiting"] = [list(r) for r in await run(m, WAITING)]

    if clients:
        await asyncio.sleep(0.5)
    try:
        async with app.connect() as conn:
            tx = await conn.begin()
            pid = (await run(conn, "SELECT pg_backend_pid()")).scalar_one()
            await bind(conn, uuid.UUID(world.tenant_id), uuid.UUID(actor))
            looker = asyncio.create_task(look(pid))
            same = asyncio.create_task(probe(world.tenant_id))
            other = asyncio.create_task(probe(world.other_tenant_id))
            start = time.perf_counter()
            await body(conn, wrote)
            wrote.set()
            result["write_ms"] = round(ms(start), 1)
            result["functions"] = [list(r) for r in await run(conn, FUNCTIONS)]
            await looker
            commit_start = time.perf_counter()
            await tx.commit()
            end = time.perf_counter()
            result["commit_ms"] = round(ms(commit_start), 1)
            result["same_tenant_writer_waited_ms"] = round(await same, 1)
            result["other_tenant_writer_waited_ms"] = round(await other, 1)
            print(label, result["write_ms"], "ms", flush=True)
    finally:
        await asyncio.sleep(0.3)
        for lane in lanes.values():
            lane.stop.set()
        await asyncio.gather(*drivers)
        await app.dispose()
        await migrator.dispose()
        await monitor.dispose()
    for name, lane in lanes.items():
        during = lane.within(start, end)
        result[f"me_{name}_during"] = summary(during) if during else {"n": 0}
    return result


async def statement_sod(u: Urls, on: bool) -> None:
    """Swap the privilege table's separation-of-duties trigger for a statement-level
    prototype over its transition table (`on`), or back to head's row trigger."""
    migrator = engine(u.migrator)
    async with migrator.begin() as conn:
        await run(
            conn,
            "DROP TRIGGER IF EXISTS trg_tenant_role_permissions_separation_of_duties"
            " ON platform.tenant_role_permissions",
        )
        await run(
            conn,
            "DROP TRIGGER IF EXISTS fog38_sod_statement ON platform.tenant_role_permissions",
        )
        if on:
            await run(
                conn,
                """
                CREATE OR REPLACE FUNCTION fog38.enforce_sod_statement() RETURNS trigger
                LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, platform
                AS $$
                DECLARE
                    v_rule text; v_count integer; v_listed text; v_reason text;
                BEGIN
                    WITH people AS (
                        SELECT DISTINCT n.tenant_id, m.user_id
                        FROM fog38_new n
                        JOIN platform.role_assignments a
                          ON a.tenant_id = n.tenant_id AND a.role_id = n.role_id
                        JOIN platform.memberships m ON m.id = a.membership_id
                    ), broken AS (
                        SELECT p.user_id, v.rule_key,
                               row_number() OVER (ORDER BY p.user_id) AS rn
                        FROM people p
                        CROSS JOIN LATERAL platform.sod_violation(p.tenant_id, p.user_id) v
                    )
                    SELECT min(rule_key), count(*),
                           string_agg(user_id::text, ', ' ORDER BY user_id) FILTER (WHERE rn <= 20)
                    INTO v_rule, v_count, v_listed FROM broken;
                    IF v_count > 0 THEN
                        SELECT description INTO v_reason FROM platform.sod_rules WHERE key = v_rule;
                        RAISE EXCEPTION '%', v_reason USING ERRCODE = 'check_violation',
                            CONSTRAINT = 'ck_roles_sod_memberships', HINT = v_rule,
                            DETAIL = v_listed;
                    END IF;
                    RETURN NULL;
                END
                $$
                """,
            )
            await run(
                conn,
                "CREATE TRIGGER fog38_sod_statement AFTER INSERT"
                " ON platform.tenant_role_permissions"
                " REFERENCING NEW TABLE AS fog38_new FOR EACH STATEMENT"
                " EXECUTE FUNCTION fog38.enforce_sod_statement()",
            )
        else:
            await run(
                conn,
                "CREATE TRIGGER trg_tenant_role_permissions_separation_of_duties"
                " AFTER INSERT OR UPDATE ON platform.tenant_role_permissions"
                " FOR EACH ROW EXECUTE FUNCTION platform.enforce_role_separation_of_duties()",
            )
    await migrator.dispose()


async def q2(u: Urls, world: World) -> dict[str, Any]:
    out: dict[str, Any] = {}
    t = world.tenant_id
    owner_1, owner_2 = world.person(OWNER_1).user_id, world.person(OWNER_2).user_id
    grantees = world.people[BULK_FROM : BULK_FROM + BULK]
    held = world.held_role
    migrator = engine(u.migrator)
    bulk_roles = iter(world.bulk_roles)

    async def bulk() -> Body:
        """1,000 assignments of a fresh role, each its own confirmed proposal."""
        role = next(bulk_roles)
        requests = await plant_proposals(
            migrator,
            t,
            owner_2,
            "assignment_grant",
            role,
            [{"membership_id": p.membership_id} for p in grantees],
        )

        async def body(conn: AsyncConnection, wrote: asyncio.Event) -> None:
            each = []
            for request, person in zip(requests, grantees, strict=True):
                start = time.perf_counter()
                await assign_confirmed(conn, t, request, owner_1, person, role)
                each.append(ms(start))
                wrote.set()
            out.setdefault("bulk_each_ms", []).append(summary(each))

        return body

    async def add_keys(keys: list[str], one_statement: bool) -> Body:
        """Privileges added to the role 1,000 people hold, as `_set_privileges` writes
        them (a statement each) or in one statement."""
        (request,) = await plant_proposals(
            migrator,
            t,
            owner_2,
            "role_permissions",
            held,
            [{"permissions": [{"key": k, "depth": "workspace"} for k in keys]}],
        )
        insert = (
            "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key,"
            " depth) SELECT CAST(:t AS uuid), CAST(:r AS uuid), k, 'workspace'"
            " FROM unnest(CAST(:ks AS text[])) k"
        )

        async def body(conn: AsyncConnection, wrote: asyncio.Event) -> None:
            await confirm(conn, request, owner_1)
            for batch in [keys] if one_statement else [[k] for k in keys]:
                await run(conn, insert, t=t, r=held, ks=batch)
                wrote.set()

        return body

    async def remove_keys(keys: list[str]) -> Body:
        async def body(conn: AsyncConnection, wrote: asyncio.Event) -> None:
            await run(
                conn,
                "DELETE FROM platform.tenant_role_permissions WHERE role_id = CAST(:r AS uuid)"
                " AND permission_key = ANY(CAST(:ks AS text[]))",
                r=held,
                ks=keys,
            )
            wrote.set()

        return body

    async def add_objects(objects: list[str]) -> Body:
        rows = [{"object_id": o, "action": "read", "depth": "workspace"} for o in objects]
        (request,) = await plant_proposals(
            migrator, t, owner_2, "role_permissions", held, [{"object_privileges": rows}]
        )

        async def body(conn: AsyncConnection, wrote: asyncio.Event) -> None:
            await confirm(conn, request, owner_1)
            for o in objects:
                await run(
                    conn,
                    "INSERT INTO platform.tenant_role_object_privileges (tenant_id, role_id,"
                    " object_id, action, depth) VALUES (CAST(:t AS uuid), CAST(:r AS uuid),"
                    " CAST(:o AS uuid), 'read', 'workspace')",
                    t=t,
                    r=held,
                    o=o,
                )
                wrote.set()

        return body

    ten = [_key(n) for n in range(110, 120)]
    async with api(u, cache=True) as (warm, _), api(u, cache=False) as (cold, _):
        lanes = {"warm": warm, "no_cache": cold}

        async def watch(label: str, body: Body, clients: dict[str, httpx.AsyncClient]) -> None:
            out.setdefault("writes", []).append(
                await write_with_watch(u, world, label, body, actor=owner_1, clients=clients)
            )

        await watch("bulk_1000_alone", await bulk(), {})
        await watch("bulk_1000", await bulk(), lanes)
        await watch("add_1_key", await add_keys([_key(100)], False), lanes)
        await watch("add_10_keys_10_statements", await add_keys(ten, False), lanes)
        await watch("remove_10_keys", await remove_keys(ten), lanes)
        await watch("add_10_keys_1_statement", await add_keys(ten, True), lanes)
        await watch("remove_10_keys", await remove_keys(ten), lanes)
        await statement_sod(u, on=True)
        try:
            await watch(
                "add_10_keys_1_statement_sod_per_statement", await add_keys(ten, True), lanes
            )
            await watch("remove_10_keys", await remove_keys(ten), lanes)
            await watch(
                "add_10_keys_10_statements_sod_per_statement", await add_keys(ten, False), lanes
            )
            await watch("remove_10_keys", await remove_keys(ten), lanes)
        finally:
            await statement_sod(u, on=False)
        await watch("add_5_object_privileges", await add_objects(world.objects[30:35]), lanes)
        # Last, since it cannot be undone in this process: the app's startup heap
        # frozen out of the collector (q1gc), the bulk again beside `/me`.
        gc.collect()
        gc.freeze()
        await watch("bulk_1000_gc_frozen", await bulk(), lanes)
    gc.unfreeze()
    await migrator.dispose()
    return out


# -- question 3 -------------------------------------------------------------------


SOD_LOCK = "FOR SHARE;"
RBAC_LOCK = "FOR SHARE OF a;"
MUTATIONS = {
    "sod_violation": ("platform.sod_violation(uuid, uuid)", SOD_LOCK),
    "rbac_refusals": ("platform.rbac_refusals(uuid, uuid, jsonb, boolean)", RBAC_LOCK),
}


async def function_source(conn: AsyncConnection, signature: str) -> tuple[str, str]:
    row = (
        await run(
            conn,
            "SELECT pg_get_functiondef(CAST(:f AS regprocedure)),"
            " md5(prosrc) FROM pg_proc WHERE oid = CAST(:f AS regprocedure)",
            f=signature,
        )
    ).one()
    return row[0], row[1]


@asynccontextmanager
async def without_lock(u: Urls, name: str) -> AsyncIterator[dict[str, str]]:
    """The function with its `FOR SHARE` removed, in this database only; the saved
    definition is put back after, and checked byte for byte (failure-modes #3:
    a mutation that changes nothing proves nothing)."""
    signature, lock = MUTATIONS[name]
    migrator = engine(u.migrator)
    async with migrator.begin() as conn:
        original, digest = await function_source(conn, signature)
        if original.count(lock) != 1:
            raise RuntimeError(f"{name}: {lock!r} found {original.count(lock)} times, not once")
        await conn.exec_driver_sql(original.replace(lock, ";"))
        _, mutated_digest = await function_source(conn, signature)
    if mutated_digest == digest:
        raise RuntimeError(f"{name}: the mutation changed nothing")
    try:
        yield {
            "function": signature,
            "removed": lock,
            "md5_before": digest,
            "md5_mutated": mutated_digest,
        }
    finally:
        async with migrator.begin() as conn:
            await conn.exec_driver_sql(original)
            _, restored = await function_source(conn, signature)
        await migrator.dispose()
        if restored != digest:
            raise RuntimeError(f"{name}: restored definition differs from the original")


def _constraint(error: BaseException) -> str:
    orig = getattr(error, "orig", None)
    cause = getattr(orig, "__cause__", None) or orig
    name = getattr(cause, "constraint_name", None)
    detail = getattr(cause, "detail", None)
    return f"{name or type(cause).__name__}:{detail or ''}"


@dataclass
class Leg:
    ok: bool = False
    error: str = ""
    work_done: float = 0.0
    commit_sent: float = 0.0
    commit_done: float = 0.0


async def leg(
    conn: AsyncConnection,
    tenant: str,
    actor: str,
    delay_before: float,
    hold: float,
    work: Callable[[AsyncConnection], Awaitable[None]],
) -> Leg:
    found = Leg()
    await asyncio.sleep(delay_before)
    tx = await conn.begin()
    try:
        await bind(conn, uuid.UUID(tenant), uuid.UUID(actor))
        await work(conn)
        found.work_done = time.perf_counter()
        await asyncio.sleep(hold)
        found.commit_sent = time.perf_counter()
        await tx.commit()
        found.commit_done = time.perf_counter()
        found.ok = True
    except DBAPIError as error:
        await tx.rollback()
        found.error = _constraint(error)
    return found


def schedule(rng: random.Random, n: int) -> tuple[str, float, float, float, float]:
    """(plan, grant delay, grant hold, revoke delay, revoke hold), in seconds. Even
    rounds let the grant take its locks first and hold them open while the revoke
    arrives; odd rounds the reverse. Jitter inside each moves the window."""
    if n % 2 == 0:
        return (
            "grant_first",
            0.0,
            rng.uniform(0.15, 0.3),
            rng.uniform(0.08, 0.2),
            rng.uniform(0, 0.02),
        )
    return (
        "revoke_first",
        rng.uniform(0.02, 0.06),
        rng.uniform(0, 0.02),
        0.0,
        rng.uniform(0.1, 0.25),
    )


async def race_sod(u: Urls, world: World, rounds: int, seed: int) -> dict[str, Any]:
    """Race a: assigning the right side of a waived rule against revoking the waiver.
    A leak is a person holding both sides with no open confirmed waiver."""
    race = world.race
    rng = random.Random(seed)
    app, migrator = engine(u.app), engine(u.migrator)
    tally: dict[str, int] = {}
    leaks = 0
    async with app.connect() as c1, app.connect() as c2:
        for n in range(rounds):
            person = race.people[RACE_SOD_PERSON]
            waiver = str(uuid.uuid4())
            async with migrator.begin() as conn:
                await run(
                    conn,
                    "INSERT INTO platform.sod_waivers (id, tenant_id, rule_key, reason, granted_by)"
                    " VALUES (CAST(:w AS uuid), CAST(:t AS uuid), :k, 'đo FOG-38',"
                    " CAST(:u AS uuid))",
                    w=waiver,
                    t=race.tenant_id,
                    k=SOD_RULE,
                    u=race.owner_1,
                )
                await run(
                    conn,
                    "UPDATE platform.sod_waivers SET confirmed_at = now(),"
                    " confirmed_by = CAST(:u AS uuid), confirm_reason = 'đo FOG-38'"
                    " WHERE id = CAST(:w AS uuid)",
                    w=waiver,
                    u=race.owner_2,
                )
            (request,) = await plant_proposals(
                migrator,
                race.tenant_id,
                race.owner_2,
                "assignment_grant",
                race.sod_right_role,
                [{"membership_id": person.membership_id}],
            )

            async def grant(
                conn: AsyncConnection, request: str = request, person: Person = person
            ) -> None:
                await assign_confirmed(
                    conn, race.tenant_id, request, race.owner_1, person, race.sod_right_role
                )

            async def revoke(conn: AsyncConnection, waiver: str = waiver) -> None:
                await run(
                    conn,
                    "UPDATE platform.sod_waivers SET revoked_at = now(),"
                    " revoked_by = CAST(:u AS uuid), revoke_reason = 'đo FOG-38'"
                    " WHERE id = CAST(:w AS uuid)",
                    u=race.owner_2,
                    w=waiver,
                )

            plan, grant_delay, grant_hold, revoke_delay, revoke_hold = schedule(rng, n)
            a, b = await asyncio.gather(
                leg(c1, race.tenant_id, race.owner_1, grant_delay, grant_hold, grant),
                leg(c2, race.tenant_id, race.owner_2, revoke_delay, revoke_hold, revoke),
            )
            outcome = (
                f"{plan}: grant={'ok' if a.ok else a.error} revoke={'ok' if b.ok else b.error}"
            )
            tally[outcome] = tally.get(outcome, 0) + 1
            async with migrator.begin() as conn:
                broken = (
                    await run(
                        conn,
                        "SELECT platform.sod_rule_broken(:k, platform.sod_held_keys("
                        "CAST(:t AS uuid), CAST(:u AS uuid))) AND NOT EXISTS ("
                        " SELECT 1 FROM platform.sod_waivers w WHERE w.tenant_id = CAST(:t AS uuid)"
                        " AND w.rule_key = :k AND w.revoked_at IS NULL"
                        " AND w.confirmed_at IS NOT NULL)",
                        k=SOD_RULE,
                        t=race.tenant_id,
                        u=person.user_id,
                    )
                ).scalar_one()
                leaks += int(bool(broken))
                # Back to one open waiver at most: the right side goes, then the waiver.
                await run(
                    conn,
                    "DELETE FROM platform.role_assignments WHERE membership_id = CAST(:m AS uuid)"
                    " AND role_id = CAST(:r AS uuid)",
                    m=person.membership_id,
                    r=race.sod_right_role,
                )
                await run(
                    conn,
                    "UPDATE platform.sod_waivers SET revoked_at = now(),"
                    " revoked_by = CAST(:u AS uuid), revoke_reason = 'đo FOG-38, dọn'"
                    " WHERE id = CAST(:w AS uuid) AND revoked_at IS NULL",
                    u=race.owner_1,
                    w=waiver,
                )
    await app.dispose()
    await migrator.dispose()
    return {"rounds": rounds, "leaks": leaks, "outcomes": tally}


async def race_rbac(u: Urls, world: World, rounds: int, seed: int) -> dict[str, Any]:
    """Race b: the binder assigning a role while an owner revokes the binder's own
    `platform.roles.bind`. A leak is an assignment that commits after the
    revocation of the authority it was judged by has committed."""
    race = world.race
    rng = random.Random(seed)
    app, migrator = engine(u.app), engine(u.migrator)
    tally: dict[str, int] = {}
    leaks = 0
    async with app.connect() as c1, app.connect() as c2:
        for n in range(rounds):
            grantee = race.people[RACE_GRANTEE]
            async with migrator.begin() as conn:
                authority = await _assign_one(
                    conn, race.tenant_id, race.main, race.binder_membership, race.binder_role
                )
            (request,) = await plant_proposals(
                migrator,
                race.tenant_id,
                race.owner_2,
                "assignment_grant",
                race.target_role,
                [{"membership_id": grantee.membership_id}],
            )

            async def grant(
                conn: AsyncConnection, request: str = request, grantee: Person = grantee
            ) -> None:
                await assign_confirmed(
                    conn, race.tenant_id, request, race.binder, grantee, race.target_role
                )

            async def revoke(conn: AsyncConnection, authority: str = authority) -> None:
                await run(
                    conn,
                    "DELETE FROM platform.role_assignments WHERE id = CAST(:a AS uuid)",
                    a=authority,
                )

            plan, grant_delay, grant_hold, revoke_delay, revoke_hold = schedule(rng, n)
            a, b = await asyncio.gather(
                leg(c1, race.tenant_id, race.binder, grant_delay, grant_hold, grant),
                leg(c2, race.tenant_id, race.owner_1, revoke_delay, revoke_hold, revoke),
            )
            leaked = a.ok and b.ok and b.commit_done < a.commit_sent
            leaks += int(leaked)
            outcome = (
                f"{plan}: grant={'ok' if a.ok else a.error} revoke={'ok' if b.ok else b.error}"
            )
            if a.ok and b.ok:
                outcome += " order=" + (
                    "revoke_first" if b.commit_done < a.commit_sent else "grant_first"
                )
            tally[outcome] = tally.get(outcome, 0) + 1
            async with migrator.begin() as conn:
                # The authority if it survived, and the grant if it landed.
                await run(
                    conn,
                    "DELETE FROM platform.role_assignments WHERE id = CAST(:a AS uuid)"
                    " OR (membership_id = CAST(:m AS uuid) AND role_id = CAST(:r AS uuid))",
                    a=authority,
                    m=grantee.membership_id,
                    r=race.target_role,
                )
    await app.dispose()
    await migrator.dispose()
    return {"rounds": rounds, "leaks": leaks, "outcomes": tally}


async def q3(u: Urls, world: World) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["sod_head"] = await race_sod(u, world, ROUNDS, seed=0)
    print("sod head", out["sod_head"])
    async with without_lock(u, "sod_violation") as how:
        out["sod_without_for_share"] = {**await race_sod(u, world, ROUNDS, seed=1), **how}
    print("sod mutated", out["sod_without_for_share"])
    out["rbac_head"] = await race_rbac(u, world, ROUNDS, seed=0)
    print("rbac head", out["rbac_head"])
    async with without_lock(u, "rbac_refusals") as how:
        out["rbac_without_for_share"] = {**await race_rbac(u, world, ROUNDS, seed=1), **how}
    print("rbac mutated", out["rbac_without_for_share"])
    out["verdict"] = {
        "head_leaks": out["sod_head"]["leaks"] + out["rbac_head"]["leaks"],
        "sod_mutation_red": out["sod_without_for_share"]["leaks"] > 0,
        "rbac_mutation_red": out["rbac_without_for_share"]["leaks"] > 0,
    }
    return out


# -- question 4 -------------------------------------------------------------------


async def q4(u: Urls, world: World) -> dict[str, Any]:
    migrator = engine(u.migrator)
    async with migrator.begin() as conn:
        await run(
            conn,
            "CREATE OR REPLACE FUNCTION fog38.whoami() RETURNS text[] LANGUAGE sql"
            " SECURITY DEFINER SET search_path = pg_catalog"
            " AS $$ SELECT ARRAY[session_user::text, current_user::text] $$",
        )
        await run(conn, "GRANT USAGE ON SCHEMA fog38 TO dw_app, dw_provisioner")
        await run(conn, "GRANT EXECUTE ON FUNCTION fog38.whoami() TO dw_app, dw_provisioner")
    await migrator.dispose()
    out: dict[str, Any] = {}
    async with api(u, cache=True) as (_, container):
        pools = {"api_engine": container.engine, "provisioner_engine": container.provisioner_engine}
        for name, pool in pools.items():
            assert pool is not None
            login = "dw_app" if name == "api_engine" else "dw_provisioner"
            seen: dict[str, int] = {}
            refused: dict[str, int] = {}

            async def borrow(
                n: int,
                pool: AsyncEngine = pool,
                login: str = login,
                seen: dict[str, int] = seen,
                refused: dict[str, int] = refused,
            ) -> None:
                async with pool.connect() as conn:
                    kind = n % 5
                    try:
                        async with conn.begin():
                            if kind == 1:
                                await run(conn, f"SET LOCAL ROLE {login}")
                            elif kind == 2:
                                await run(conn, "SET LOCAL ROLE dw_migrator")
                            elif kind == 3:
                                await run(conn, "SET SESSION AUTHORIZATION dw_migrator")
                            elif kind == 4:
                                # Session-level, left on the pooled connection on purpose.
                                await run(conn, f"SET ROLE {login}")
                            row = (
                                await run(conn, "SELECT session_user, current_user, fog38.whoami()")
                            ).one()
                            key = f"session={row[0]} current={row[1]} definer_sees={row[2][0]}"
                            key += f" definer_current={row[2][1]}"
                            seen[key] = seen.get(key, 0) + 1
                    except DBAPIError as error:
                        reason = f"kind{kind}:{str(getattr(error, 'orig', error))[-70:]}"
                        refused[reason] = refused.get(reason, 0) + 1
                        async with conn.begin():
                            row = (
                                await run(conn, "SELECT session_user, current_user, fog38.whoami()")
                            ).one()
                            key = f"session={row[0]} current={row[1]} definer_sees={row[2][0]}"
                            key += f" definer_current={row[2][1]}"
                            seen[key] = seen.get(key, 0) + 1

            for start in range(0, 1_000, 25):
                await asyncio.gather(*(borrow(n) for n in range(start, start + 25)))
            total = sum(seen.values())
            as_login = sum(v for k, v in seen.items() if k.startswith(f"session={login} "))
            definer = sum(v for k, v in seen.items() if f"definer_sees={login} " in k)
            out[name] = {
                "borrows": total,
                "session_user_is_login": as_login,
                "definer_function_sees_login": definer,
                "seen": seen,
                "refused": refused,
                "pool": pool.pool.status(),
            }
            print(name, out[name])
    return out


# -- the run ----------------------------------------------------------------------


async def machine(u: Urls) -> dict[str, Any]:
    admin = engine(u.admin.rsplit("/", 1)[0] + f"/{u.name}")
    async with admin.connect() as conn:
        found = {
            "postgres": (await run(conn, "SELECT version()")).scalar_one(),
            "settings": {
                r[0]: r[1]
                for r in await run(
                    conn,
                    "SELECT name, setting FROM pg_settings WHERE name IN ('shared_buffers',"
                    " 'work_mem', 'max_connections', 'synchronous_commit', 'jit',"
                    " 'default_transaction_isolation', 'track_functions')",
                )
            },
        }
        trips = []
        for _ in range(200):
            start = time.perf_counter()
            await run(conn, "SELECT 1")
            trips.append(ms(start))
        found["select_1_ms"] = summary(trips)
    await admin.dispose()
    found["host"] = f"{host.platform()}, {os.cpu_count()} threads, Python {host.python_version()}"
    return found


async def q1gc(u: Urls, world: World) -> dict[str, Any]:
    """Where q1's warm tail comes from: the same warm `/me` with every garbage
    collection timed, then with the startup heap frozen (`gc.freeze`) so a full
    collection no longer walks the app's own imports."""
    out: dict[str, Any] = {}
    pauses: list[tuple[int, float]] = []
    started: dict[str, float] = {}

    def watch(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            started["at"] = time.perf_counter()
        else:
            pauses.append((info["generation"], ms(started["at"])))

    gc.callbacks.append(watch)
    try:
        async with api(u, cache=True) as (client, _):
            for frozen in (False, True):
                if frozen:
                    gc.collect()
                    gc.freeze()
                for name, n in {"heavy": HEAVY, "plain": PLAIN}.items():
                    call = me_call(client, world.person(n), world.tenant_id)
                    for _ in range(20):
                        await timed_me(call)
                    pauses.clear()
                    took = [await timed_me(call) for _ in range(ME_REQUESTS)]
                    full = [p for g, p in pauses if g == 2]
                    out[f"{name}:warm:{'frozen' if frozen else 'default'}"] = {
                        **summary(took),
                        "gen2_collections": len(full),
                        "gen2_pause_ms": summary(full) if full else {},
                    }
                    print(name, frozen, out[f"{name}:warm:{'frozen' if frozen else 'default'}"])
    finally:
        gc.callbacks.remove(watch)
        gc.unfreeze()
    return out


# -- question 5 (tenant-rbac 10) ----------------------------------------------------

# `_STANDING` and `_HOLDERS` as they stood at `657ef4c6`, `platform.scopes_in` in
# the select list, copied verbatim and frozen here: the baseline every later run
# compares against, whatever the modules hold by then.
_STANDING_SELECT_LIST = """
    SELECT u.kind,
           ARRAY(SELECT platform.scopes_in(CAST(:t AS uuid), u.id, CAST(:w AS uuid))) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    JOIN platform.tenant_members tm
      ON tm.tenant_id = m.tenant_id AND tm.user_id = m.user_id AND tm.status = 'active'
    WHERE m.workspace_id = CAST(:w AS uuid) AND m.user_id = CAST(:u AS uuid)
    """
_HOLDERS_SELECT_LIST = """
    SELECT m.user_id,
           ARRAY(SELECT platform.scopes_in(m.tenant_id, m.user_id, m.workspace_id)) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    WHERE m.tenant_id = CAST(:t AS uuid) AND m.workspace_id = CAST(:w AS uuid)
      AND (CAST(:u AS uuid) IS NULL OR m.user_id = CAST(:u AS uuid))
      AND (NOT CAST(:people AS boolean) OR u.kind = 'human')
    ORDER BY m.user_id
    """
# The same two with the call in FROM, as `_HELD` makes it (tenant-rbac/07): same
# three arguments in the same order, nothing else changed.
_STANDING_FROM = """
    SELECT u.kind,
           ARRAY(
               SELECT s.key
               FROM platform.scopes_in(CAST(:t AS uuid), u.id, CAST(:w AS uuid)) AS s(key)
           ) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    JOIN platform.tenant_members tm
      ON tm.tenant_id = m.tenant_id AND tm.user_id = m.user_id AND tm.status = 'active'
    WHERE m.workspace_id = CAST(:w AS uuid) AND m.user_id = CAST(:u AS uuid)
    """
_HOLDERS_FROM = """
    SELECT m.user_id,
           ARRAY(
               SELECT s.key
               FROM platform.scopes_in(m.tenant_id, m.user_id, m.workspace_id) AS s(key)
           ) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    WHERE m.tenant_id = CAST(:t AS uuid) AND m.workspace_id = CAST(:w AS uuid)
      AND (CAST(:u AS uuid) IS NULL OR m.user_id = CAST(:u AS uuid))
      AND (NOT CAST(:people AS boolean) OR u.kind = 'human')
    ORDER BY m.user_id
    """
Q5_TRIPS = 200
Q5_WARM = 20


async def _plant_q5_workspace(migrator: AsyncEngine, world: World) -> str:
    """A workspace every one of the 5,000 people is a member of, each holding
    `member` there, as the seed assigns it."""
    workspace = str(uuid.uuid4())
    async with migrator.begin() as conn:
        await run(
            conn,
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
            " VALUES (CAST(:w AS uuid), CAST(:t AS uuid), 'q5', 'q5')",
            w=workspace,
            t=world.tenant_id,
        )
        await run(
            conn,
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
            " SELECT gen_random_uuid(), CAST(:t AS uuid), CAST(:w AS uuid), u"
            " FROM unnest(CAST(:us AS uuid[])) u",
            t=world.tenant_id,
            w=workspace,
            us=[p.user_id for p in world.people],
        )
        member = await _system_role(conn, world.tenant_id, "member")
        await run(
            conn,
            "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
            " role_id) SELECT gen_random_uuid(), m.tenant_id, m.workspace_id, m.id,"
            " CAST(:r AS uuid) FROM platform.memberships m WHERE m.workspace_id = CAST(:w AS uuid)",
            r=member,
            w=workspace,
        )
    return workspace


async def _remove_q5_workspace(migrator: AsyncEngine, workspace: str) -> None:
    async with migrator.begin() as conn:
        await run(
            conn,
            "DELETE FROM platform.role_assignments WHERE workspace_id = CAST(:w AS uuid)",
            w=workspace,
        )
        await run(
            conn,
            "DELETE FROM platform.memberships WHERE workspace_id = CAST(:w AS uuid)",
            w=workspace,
        )
        await run(conn, "DELETE FROM platform.workspaces WHERE id = CAST(:w AS uuid)", w=workspace)


async def _analyze(u: Urls) -> None:
    admin = create_async_engine(
        u.admin.rsplit("/", 1)[0] + f"/{u.name}", isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as conn:
        await run(
            conn, "ANALYZE platform.workspaces, platform.memberships, platform.role_assignments"
        )
    await admin.dispose()


async def _explain(
    conn: AsyncConnection, statement: str, values: dict[str, object]
) -> dict[str, Any]:
    plan = (await run(conn, f"EXPLAIN (ANALYZE, FORMAT JSON) {statement}", **values)).scalar_one()
    return {
        "execution": float(plan[0]["Execution Time"]),
        "planning": float(plan[0]["Planning Time"]),
    }


def _answer(rows: Sequence[Any]) -> list[tuple[str, frozenset[str]]]:
    return [(str(r[0]), frozenset(r[1])) for r in rows]


async def q5(u: Urls, world: World) -> dict[str, Any]:
    """`_STANDING` and `_HOLDERS`, `platform.scopes_in` in the select list (the
    frozen baseline) against FROM, beside the modules' own text, one run, one
    database, under `dw_app` bound as `tenant_session` binds it."""
    out: dict[str, Any] = {"cells": {}, "plans": {}, "equal": {}}
    forms = {
        "standing": {
            "select_list": _STANDING_SELECT_LIST,
            "from": _STANDING_FROM,
            "module": str(_STANDING.text),
        },
        "holders": {
            "select_list": _HOLDERS_SELECT_LIST,
            "from": _HOLDERS_FROM,
            "module": str(_HOLDERS.text),
        },
    }
    for query, texts in forms.items():
        out[f"module_is_{query}"] = [
            name
            for name in ("select_list", "from")
            if " ".join(texts[name].split()) == " ".join(texts["module"].split())
        ]
    t = world.tenant_id
    migrator = engine(u.migrator)
    workspace = await _plant_q5_workspace(migrator, world)
    try:
        await _analyze(u)
        cells: dict[str, tuple[str, str, dict[str, object]]] = {}
        for name, n in {"heavy": HEAVY, "owner": OWNER_1, "plain": PLAIN}.items():
            p = world.person(n)
            cells[f"standing:{name}"] = (
                "standing",
                p.workspace_id,
                {"t": t, "w": p.workspace_id, "u": p.user_id},
            )
            cells[f"holders_one:{name}"] = (
                "holders",
                p.workspace_id,
                {"t": t, "w": p.workspace_id, "u": p.user_id, "people": False},
            )
        heavy_ws = world.person(HEAVY).workspace_id
        cells["holders_all:heavy_ws"] = (
            "holders",
            heavy_ws,
            {"t": t, "w": heavy_ws, "u": None, "people": True},
        )
        cells["holders_all:q5_ws"] = (
            "holders",
            workspace,
            {"t": t, "w": workspace, "u": None, "people": True},
        )
        app = engine(u.app)
        async with app.connect() as conn:
            await run(conn, "SELECT set_config('app.tenant_id', :t, false)", t=t)
            for cell, (query, ws, values) in cells.items():
                await run(conn, "SELECT set_config('app.workspace_id', :w, false)", w=ws)
                texts = forms[query]
                answers = {
                    form: _answer((await run(conn, text, **values)).all())
                    for form, text in texts.items()
                }
                if len({tuple(a) for a in answers.values()}) != 1 or not answers["select_list"]:
                    raise RuntimeError(f"{cell}: forms disagree or answer nothing")
                for text in texts.values():
                    for _ in range(Q5_WARM):
                        (await run(conn, text, **values)).all()
                trips: dict[str, list[float]] = {form: [] for form in texts}
                server: dict[str, list[dict[str, Any]]] = {form: [] for form in texts}
                order = list(texts)
                for i in range(Q5_TRIPS):
                    # Rotated so no form always runs first after another's cache.
                    for form in order[i % 3 :] + order[: i % 3]:
                        start = time.perf_counter()
                        (await run(conn, texts[form], **values)).all()
                        trips[form].append(ms(start))
                for i in range(Q5_TRIPS):
                    for form in order[i % 3 :] + order[: i % 3]:
                        server[form].append(await _explain(conn, texts[form], values))
                out["cells"][cell] = {
                    "rows": len(answers["select_list"]),
                    "scopes": sum(len(s) for _, s in answers["select_list"]),
                    **{
                        form: {
                            "round_trip_ms": summary(trips[form]),
                            "execution_ms": summary([s["execution"] for s in server[form]]),
                            "planning_ms": summary([s["planning"] for s in server[form]]),
                        }
                        for form in texts
                    },
                }
                print(
                    cell,
                    {f: out["cells"][cell][f]["round_trip_ms"]["p50"] for f in texts},
                    {f: out["cells"][cell][f]["round_trip_ms"]["p95"] for f in texts},
                )
            # The plans, the heavy person at their first workspace.
            for cell in ("standing:heavy", "holders_one:heavy", "holders_all:heavy_ws"):
                query, ws, values = cells[cell]
                await run(conn, "SELECT set_config('app.workspace_id', :w, false)", w=ws)
                for form, text in forms[query].items():
                    plan = await run(conn, f"EXPLAIN (ANALYZE, VERBOSE) {text}", **values)
                    lines = [r[0] for r in plan]
                    body = "\n".join(lines)
                    out["plans"][f"{cell}:{form}"] = {
                        "project_set": "ProjectSet" in body,
                        "function_scan_scopes_in": any(
                            "Function Scan" in line and "scopes_in" in line for line in lines
                        ),
                        "calls_scopes_in": "platform.scopes_in" in body,
                        "lines": lines,
                    }
            # Every membership of the company: `_STANDING` per membership, `_HOLDERS`
            # per workspace (all members, people and not), the two forms equal.
            memberships = (
                await run(
                    conn,
                    "SELECT workspace_id, user_id FROM platform.memberships"
                    " WHERE tenant_id = CAST(:t AS uuid) ORDER BY workspace_id, user_id",
                    t=t,
                )
            ).all()
            standing_diff = holders_diff = 0
            for ws_id, user_id in memberships:
                await run(conn, "SELECT set_config('app.workspace_id', :w, false)", w=str(ws_id))
                values = {"t": t, "w": str(ws_id), "u": str(user_id)}
                old = _answer((await run(conn, _STANDING_SELECT_LIST, **values)).all())
                new = _answer((await run(conn, _STANDING_FROM, **values)).all())
                standing_diff += old != new
            for ws_id in sorted({ws for ws, _ in memberships}):
                await run(conn, "SELECT set_config('app.workspace_id', :w, false)", w=str(ws_id))
                values = {"t": t, "w": str(ws_id), "u": None, "people": False}
                old = _answer((await run(conn, _HOLDERS_SELECT_LIST, **values)).all())
                new = _answer((await run(conn, _HOLDERS_FROM, **values)).all())
                holders_diff += old != new
            out["equal"] = {
                "memberships": len(memberships),
                "standing_differ": standing_diff,
                "workspaces": len({ws for ws, _ in memberships}),
                "holders_differ": holders_diff,
            }
            print("equal", out["equal"])
        await app.dispose()
    finally:
        await _remove_q5_workspace(migrator, workspace)
        await migrator.dispose()
        await _analyze(u)
    return out


QUESTIONS = {"q1": q1, "q1gc": q1gc, "q2": q2, "q3": q3, "q4": q4, "q5": q5}


async def measure(questions: list[str], out_dir: Path) -> None:
    u = urls()
    out_dir.mkdir(parents=True, exist_ok=True)
    migrator = engine(u.migrator)
    async with migrator.connect() as conn:
        world = await load_world(conn)
    await migrator.dispose()
    (out_dir / "machine.json").write_text(json.dumps(await machine(u), indent=1), encoding="utf-8")
    for name in questions:
        started = time.perf_counter()
        result = await QUESTIONS[name](u, world)
        result["took_s"] = round(time.perf_counter() - started, 1)
        (out_dir / f"{name}.json").write_text(
            json.dumps(result, indent=1, default=str, ensure_ascii=False), encoding="utf-8"
        )
        print(f"{name} done in {result['took_s']} s -> {out_dir / f'{name}.json'}")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("steps", nargs="+", choices=["setup", *QUESTIONS, "drop"])
    parser.add_argument(
        "--out", type=Path, default=Path(tempfile.gettempdir()) / "fog38-rbac", help="JSON results"
    )
    args = parser.parse_args()
    if "setup" in args.steps:
        setup()
    questions = [s for s in args.steps if s in QUESTIONS]
    if questions:
        asyncio.run(measure(questions, args.out))
    if "drop" in args.steps:
        asyncio.run(cleanup())


if __name__ == "__main__":
    main()
