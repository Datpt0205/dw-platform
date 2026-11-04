# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""The self-checks of record-access/01 step 7: each failure is a non-zero exit.

A session with no tenant, no actor kind, no ledger row or a stale epoch reads
nothing; T1's session never sees a row of T2, and every record table keeps A1's
RESTRICTIVE tenant policy; a share whose `grants_valid_until` has passed opens
nothing through the share arm; a cell's catalog differs from A1's only inside
its declared replacement; and the reach the door computes for each profile
principal equals the harness's arrays for every (action, arm) the harness sets.

Each behavioural probe first proves it can see: the same query with the right
settings returns a row, or the check reports itself blind (failure-modes #3).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from ..cell import create_cell_database
from ..db import BENCH_DB, TEMPLATE_DB, Endpoint, scoped
from ..ddl import VARIANTS, Variant, cell_ddl, partitions
from ..model import KIND_PERSON, PERSON_COMPANY, PERSON_SHARE, bench_uuid
from ..seed import SeedFacts, access_key
from .variants import (
    ACTIONS,
    HARNESS_AGENT,
    HARNESS_ARMS,
    PolicyVariant,
    declared,
    is_declared,
)

REF_DB = "dw_bench_ref"
PROBE = bench_uuid(KIND_PERSON, 0, 999_999)  # a principal with a grant and no ledger row
SCHEMAS = ("studio", "platform")

CatalogKey = tuple[str, ...]


# ------------------------------------------------------------------ catalog --
_CATALOG_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "table",
        "SELECT n.nspname || '.' || c.relname, NULL, c.relkind::text || ' rls='"
        " || c.relrowsecurity || ' force=' || c.relforcerowsecurity || ' acl='"
        " || coalesce(c.relacl::text, '')"
        " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = ANY ($1) AND c.relkind IN ('r', 'p')",
    ),
    (
        "column",
        "SELECT n.nspname || '.' || c.relname, a.attname,"
        " format_type(a.atttypid, a.atttypmod) || ' notnull=' || a.attnotnull"
        " || ' gen=' || a.attgenerated::text || ' default='"
        " || coalesce(pg_get_expr(d.adbin, d.adrelid), '')"
        " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum"
        " WHERE n.nspname = ANY ($1) AND c.relkind IN ('r', 'p') AND NOT c.relispartition"
        " AND a.attnum > 0 AND NOT a.attisdropped",
    ),
    (
        "index",
        "SELECT n.nspname || '.' || c.relname, ic.relname, pg_get_indexdef(i.indexrelid)"
        " FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid"
        " JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = ANY ($1) AND NOT c.relispartition",
    ),
    (
        "constraint",
        "SELECT n.nspname || '.' || c.relname, k.conname, pg_get_constraintdef(k.oid)"
        " FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = ANY ($1) AND NOT c.relispartition",
    ),
    (
        "policy",
        "SELECT schemaname || '.' || tablename, policyname, permissive || ' ' || cmd || ' '"
        " || roles::text || ' USING ' || coalesce(qual, '')"
        " || ' CHECK ' || coalesce(with_check, '')"
        " FROM pg_policies WHERE schemaname = ANY ($1)",
    ),
    (
        "function",
        "SELECT p.proname, NULL, string_agg(pg_get_functiondef(p.oid), E'\\n' ORDER BY p.oid)"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = ANY ($1) AND p.prokind = 'f' GROUP BY p.proname",
    ),
    (
        "trigger",
        "SELECT n.nspname || '.' || c.relname, t.tgname, pg_get_triggerdef(t.oid)"
        " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = ANY ($1) AND NOT t.tgisinternal AND t.tgparentid = 0",
    ),
)


async def catalog_signature(conn: asyncpg.Connection) -> dict[CatalogKey, str]:
    out: dict[CatalogKey, str] = {}
    for kind, sql in _CATALOG_QUERIES:
        for row in await conn.fetch(sql, list(SCHEMAS)):
            key: CatalogKey = (kind, row[0]) if row[1] is None else (kind, row[0], row[1])
            out[key] = str(row[2])
    return out


def catalog_diff(
    reference: dict[CatalogKey, str], cell: dict[CatalogKey, str], allowed: set[CatalogKey]
) -> list[str]:
    """Every catalog difference outside the declared replacement, named."""
    out = []
    for key in sorted(set(reference) | set(cell)):
        if reference.get(key) == cell.get(key) or is_declared(key, allowed):
            continue
        if key not in cell:
            out.append(f"thiếu so với A1: {' '.join(key)}")
        elif key not in reference:
            out.append(f"thêm ngoài phần thay đã khai: {' '.join(key)}")
        else:
            out.append(f"khác A1 ngoài phần thay đã khai: {' '.join(key)}")
    return out


async def reference_signature(
    endpoint: Endpoint, base: Variant, modulus: int
) -> dict[CatalogKey, str]:
    """A1's catalog, schema only: the variant's DDL on an empty clone of the template."""
    admin = await endpoint.on("postgres").connect("admin")
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {REF_DB} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {REF_DB} TEMPLATE {TEMPLATE_DB} OWNER dw_migrator")
    finally:
        await admin.close()
    try:
        mig = await endpoint.on(REF_DB).connect("migrator")
        try:
            ddl = cell_ddl(base, modulus)
            for statement in ddl.schema + ddl.post_load:
                await mig.execute(statement)
            return await catalog_signature(mig)
        finally:
            await mig.close()
    finally:
        admin = await endpoint.on("postgres").connect("admin")
        try:
            await admin.execute(f"DROP DATABASE IF EXISTS {REF_DB} WITH (FORCE)")
        finally:
            await admin.close()


def restrictive_differs(
    reference: dict[CatalogKey, str], cell: dict[CatalogKey, str], modulus: int
) -> list[str]:
    """The cross-tenant check's structural half: A1's RESTRICTIVE tenant policy, unchanged."""
    out = []
    for table in ["studio.records", *partitions("studio.records", modulus)]:
        key = ("policy", table, f"tenant_isolation_{table.split('.')[1]}")
        if key not in cell or cell[key] != reference.get(key):
            out.append(f"policy RESTRICTIVE tenant của {table} khác A1: {cell.get(key)}")
    return out


# -------------------------------------------------------------- the arrays --
@dataclass
class ArrayComparison:
    failures: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)  # arms the harness does not set


def compare_arrays(
    expected: Iterable[tuple[str, str, str, list[str]]],
    computed: dict[tuple[str, str, str], list[str]],
    carried_grants: set[str],
) -> ArrayComparison:
    """The door's reach against the harness's, per (principal, action, arm) the harness sets.

    `expected` holds (principal, action, ledger arm, ids) from `profiles_and_scopes`
    and `computed` the door's arrays for the same principals. Equal as sets, with
    one tolerance on `grants`: ADR-0105 decision 3 gives a person their teams',
    home workspace's and sub-tree markers' keys too, which the harness leaves out;
    those may be extra only while no record of the seed carries them, so the reach
    is the same (gate HIGH 21).
    """
    out = ArrayComparison()
    set_by_harness: set[tuple[str, str, str]] = set()
    for principal, action, arm, ids in expected:
        key = (principal, action, arm)
        set_by_harness.add(key)
        want, got = set(ids), set(computed.get(key, []))
        if want == got:
            continue
        if arm == "grants" and want <= got and not (got - want) & carried_grants:
            out.extras.append(
                f"{principal} {action} grants: thêm {len(got - want)} khóa không bản ghi nào mang"
            )
            continue
        out.failures.append(
            f"mảng tính được khác harness: {principal} {action} {arm}: thiếu"
            f" {len(want - got)}, thừa {len(got - want)}"
        )
    principals = {p for p, _a, _r in set_by_harness}
    for (principal, action, arm), ids in sorted(computed.items()):
        if principal in principals and ids and (principal, action, arm) not in set_by_harness:
            out.extras.append(f"{principal} {action} {arm}: {len(ids)} (harness không đặt)")
    return out


def expected_arrays(
    facts: SeedFacts,
    phase: str,
    public_principal: uuid.UUID,
    key_of: dict[str, str] | None = None,
) -> list[tuple[str, str, str, list[str]]]:
    """The harness's arrays for the profile principals compared in this phase (step 3).

    The public_read principal is compared in the `public_read` phase and every other
    in the `private` one, each where its object's `default_access` is the harness's.
    `key_of` turns the harness's uuid keys into the bigint keys of axis K.
    """
    out = []
    for tenant, principal, action, arm, ids in facts.scopes:
        del tenant
        is_public = principal == public_principal
        if (phase == "public_read") != is_public:
            continue
        ledger_arm = HARNESS_ARMS[arm]
        values = [str(i) for i in ids]
        if ledger_arm == "keys" and key_of is not None:
            values = [key_of[v] for v in values]
        out.append((str(principal), action, ledger_arm, values))
    return out


ARRAY_SQL = {
    "objects_tenant": "studio.acl_objects($1, 'tenant')",
    "objects_own": "studio.acl_objects($1, 'own')",
    "objects_team": "studio.acl_objects($1, 'team')",
    "keys": "studio.acl_keys($1)",
    "owners_team": "studio.acl_owners($1, 'team')",
    "owners_subordinate": "studio.acl_owners($1, 'subordinate')",
    "grants": "studio.acl_grant_keys($1)",
    "workspaces": "studio.acl_workspaces($1)",
}


async def door_arrays(
    endpoint: Endpoint, tenant: uuid.UUID, principal: uuid.UUID, actor_kind: str
) -> dict[tuple[str, str], list[str]]:
    """What the acl functions return to this principal after the door, every (action, arm)."""
    conn = await endpoint.connect("app")
    out: dict[tuple[str, str], list[str]] = {}
    try:
        async with scoped(conn, tenant, principal, actor_kind):
            boundary = [str(x) for x in await conn.fetchval("SELECT studio.acl_boundary()")]
            for action in ACTIONS:
                for arm, sql in ARRAY_SQL.items():
                    values = await conn.fetchval(f"SELECT {sql}", action)
                    out[(action, arm)] = sorted(str(v) for v in values or [])
            if actor_kind != "user":
                out[("boundary", "objects")] = boundary
    finally:
        await conn.close()
    return out


async def key_map(conn: asyncpg.Connection, facts: SeedFacts) -> dict[str, str]:
    """Harness uuid key -> bigint key, through the same per-tenant numbers (axis K)."""
    t1 = facts.t1
    objects = await conn.fetch(
        "SELECT id, object_no FROM studio.object_defs WHERE tenant_id = $1", t1.tenant_id
    )
    workspaces = await conn.fetch(
        "SELECT id, workspace_no FROM platform.workspaces WHERE tenant_id = $1", t1.tenant_id
    )
    return {
        str(access_key(o["id"], w["id"])): str((int(o["object_no"]) << 32) | int(w["workspace_no"]))
        for o in objects
        for w in workspaces
    }


async def array_check(
    endpoint: Endpoint,
    mig: asyncpg.Connection,
    facts: SeedFacts,
    variant: PolicyVariant,
    phase: str,
    public_principal: uuid.UUID,
) -> ArrayComparison:
    t1 = facts.t1
    key_of = await key_map(mig, facts) if variant.key == "bigint" else None
    expected = expected_arrays(facts, phase, public_principal, key_of)
    carried = {
        str(r[0])
        for r in await mig.fetch(
            "SELECT DISTINCT g FROM studio.records, unnest(read_grants) AS g WHERE tenant_id = $1",
            t1.tenant_id,
        )
    }
    computed: dict[tuple[str, str, str], list[str]] = {}
    tenant_of = {str(p): t for t, p, _a, _r, _i in facts.scopes}
    for principal in sorted({p for p, _a, _r, _i in expected}):
        tenant = uuid.UUID(str(tenant_of[principal]))
        if principal == str(HARNESS_AGENT):
            # The agent runs as the Toàn công ty person under its one-object boundary.
            arrays = await door_arrays(endpoint, tenant, t1.person(PERSON_COMPANY), "agent")
            bound = set(arrays.get(("boundary", "objects"), []))
            for (action, arm), ids in arrays.items():
                if arm.startswith("objects_"):
                    ids = sorted(set(ids) & bound)
                computed[(principal, action, arm)] = ids
            continue
        arrays = await door_arrays(endpoint, tenant, uuid.UUID(principal), "user")
        for (action, arm), ids in arrays.items():
            computed[(principal, action, arm)] = ids
    return compare_arrays(expected, computed, carried)


# --------------------------------------------------------- the behaviours --
PROBE_SQL = "SELECT count(*) FROM (SELECT 1 FROM studio.records WHERE tenant_id = $1 LIMIT 1) x"


async def _rows(
    conn: asyncpg.Connection, settings: Sequence[tuple[str, str]], door: bool, sql: str, *args: Any
) -> int:
    """One transaction with exactly these settings, the door or not, then `sql`."""
    sets = ", ".join(f"set_config('{k}', '{v}', true)" for k, v in settings)
    await conn.execute("BEGIN" + (f"; SELECT {sets}" if sets else ""))
    try:
        if door:
            await conn.execute("SELECT studio.ensure_principal_scope()")
        return int(await conn.fetchval(sql, *args))
    finally:
        await conn.execute("ROLLBACK")


async def behaviour_checks(endpoint: Endpoint, facts: SeedFacts) -> list[str]:
    """Run in the `private` phase, after the ledger is warm."""
    t1, t2 = facts.t1, facts.t2
    company = str(t1.person(PERSON_COMPANY))
    tenant = ("app.tenant_id", str(t1.tenant_id))
    user = ("app.user_id", company)
    actor = ("app.actor_kind", "user")
    out: list[str] = []
    app = await endpoint.connect("app")
    mig = await endpoint.connect("migrator")
    try:
        seen = await _rows(app, [tenant, user, actor], True, PROBE_SQL, t1.tenant_id)
        if seen == 0:
            return ["phiên đủ setting của Toàn công ty không đọc được dòng nào: mọi kiểm mù"]
        if await _rows(app, [user, actor], True, PROBE_SQL, t1.tenant_id):
            out.append("phiên không gắn tenant vẫn đọc được dòng")
        if await _rows(app, [tenant, user], True, PROBE_SQL, t1.tenant_id):
            out.append("phiên không gắn loại actor vẫn đọc được dòng")
        # No ledger row: the probe holds tenant-wide read and never called the door.
        await mig.execute(
            "INSERT INTO studio.bench_effective_grants (tenant_id, principal_id, permission_key,"
            " depth, anchor_workspace_id)"
            " SELECT $1, $2, 'obj.' || api_name || '.read', 'tenant', $3"
            " FROM studio.object_defs WHERE tenant_id = $1",
            t1.tenant_id,
            PROBE,
            t1.workspace(0),
        )
        try:
            probe = ("app.user_id", str(PROBE))
            if await _rows(app, [tenant, probe, actor], False, PROBE_SQL, t1.tenant_id):
                out.append("phiên không có dòng sổ tầm vẫn đọc được dòng")
            if not await _rows(app, [tenant, probe, actor], True, PROBE_SQL, t1.tenant_id):
                out.append("kiểm không có dòng sổ tầm mù: có dòng rồi vẫn không đọc được")
        finally:
            await mig.execute(
                "DELETE FROM studio.bench_effective_grants WHERE tenant_id = $1 AND principal_id ="
                " $2",
                t1.tenant_id,
                PROBE,
            )
            await mig.execute(
                "DELETE FROM studio.principal_scopes WHERE tenant_id = $1 AND principal_id = $2",
                t1.tenant_id,
                PROBE,
            )
        # A stale epoch: the row is valid for an epoch the tenant has left.
        await _rows(app, [tenant, user, actor], True, "SELECT 1")
        await mig.execute(
            "UPDATE studio.access_epochs SET epoch = epoch + 1 WHERE tenant_id = $1", t1.tenant_id
        )
        if await _rows(app, [tenant, user, actor], False, PROBE_SQL, t1.tenant_id):
            out.append("phiên mang epoch cũ vẫn đọc được dòng")
        if not await _rows(app, [tenant, user, actor], True, PROBE_SQL, t1.tenant_id):
            out.append("kiểm epoch cũ mù: gọi cửa rồi vẫn không đọc được")
        # T2's rows in T1's session, even with the tenant-wide scope set.
        scope = ("app.workspace_scope", "tenant")
        if await _rows(app, [tenant, user, actor, scope], True, PROBE_SQL, t2.tenant_id):
            out.append("dòng của T2 xuất hiện trong phiên của T1")
        if not await _rows(app, [tenant, user, actor, scope], True, PROBE_SQL, t1.tenant_id):
            out.append("kiểm chéo tenant mù: phạm vi toàn tenant không đọc được T1")
        out += await _expiry_check(app, mig, facts)
    finally:
        await app.close()
        await mig.close()
    return out


async def _expiry_check(
    app: asyncpg.Connection, mig: asyncpg.Connection, facts: SeedFacts
) -> list[str]:
    """A share past `grants_valid_until` opens nothing through the share arm (ADR-0105 d. 3)."""
    t1 = facts.t1
    recipient = t1.person(PERSON_SHARE)
    # In the private phase the recipient reaches a record it does not own only
    # through the share arm, so the arm alone decides these two reads.
    pick = (
        "SELECT id FROM studio.records WHERE tenant_id = $1 AND read_grants @> ARRAY[$2::uuid]"
        " AND owner_id <> $2 AND {expiry} ORDER BY id LIMIT 1"
    )
    expired = await mig.fetchval(
        pick.format(expiry="grants_valid_until < now()"), t1.tenant_id, recipient
    )
    shared = await mig.fetchval(
        pick.format(expiry="grants_valid_until IS NULL"), t1.tenant_id, recipient
    )
    if expired is None or shared is None:
        return ["kiểm hết hạn mù: không có bản ghi chia sẻ cho người nhận đã hết hạn và còn hạn"]
    settings = [
        ("app.tenant_id", str(t1.tenant_id)),
        ("app.user_id", str(recipient)),
        ("app.actor_kind", "user"),
    ]
    one = "SELECT count(*) FROM studio.records WHERE tenant_id = $1 AND id = $2"
    out = []
    if await _rows(app, settings, True, one, t1.tenant_id, expired):
        out.append(f"người nhận đọc được bản ghi {expired} có grants_valid_until ở quá khứ")
    if not await _rows(app, settings, True, one, t1.tenant_id, shared):
        out.append("kiểm hết hạn mù: người nhận không đọc được bản ghi chia sẻ còn hạn")
    return out


async def catalog_check(
    endpoint: Endpoint, variant: PolicyVariant, modulus: int
) -> tuple[list[str], dict[CatalogKey, str], dict[CatalogKey, str]]:
    """The cell's catalog against A1's, whatever the cell was built on (step 7)."""
    reference = await reference_signature(endpoint, VARIANTS["A1"], modulus)
    mig = await endpoint.on(BENCH_DB).connect("migrator")
    try:
        cell = await catalog_signature(mig)
    finally:
        await mig.close()
    return catalog_diff(reference, cell, declared(variant, modulus)), reference, cell


__all__ = [
    "PROBE",
    "ArrayComparison",
    "array_check",
    "behaviour_checks",
    "catalog_check",
    "catalog_diff",
    "catalog_signature",
    "compare_arrays",
    "create_cell_database",
    "expected_arrays",
    "restrictive_differs",
]
