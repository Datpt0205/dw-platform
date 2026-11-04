"""One cell of the matrix: a fresh `dw_bench`, one variant's DDL at one modulus, the seed.

`dw_bench` is cloned per cell from `dw_bench_template`, which the harness
migrates once to the migration head with `dw_migrator`, and is dropped after
the cell and on exit (gate MEDIUM (g); failure-modes #6): the data is rebuilt
from `seed(scale)` each time.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from typing import Any

import asyncpg

from .db import BENCH_DB, REPO_ROOT, TEMPLATE_DB, Endpoint
from .ddl import Variant, cell_ddl
from .model import (
    KIND_RULE,
    LEAD,
    PERSON_SHARE,
    bench_uuid,
    depth_of,
    object_layouts,
    organisation,
)
from .scales import Scale
from .seed import (
    SeedFacts,
    TenantPlan,
    access_key,
    candidate_ids,
    field_id,
    field_rows,
    generated_columns,
    generator_sql,
    profiles_and_scopes,
    tenant_plans,
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


async def prepare_template(endpoint: Endpoint, revision: str) -> None:
    admin = await endpoint.on("postgres").connect("admin")
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {BENCH_DB} WITH (FORCE)")
        await admin.execute(f"DROP DATABASE IF EXISTS {TEMPLATE_DB} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {TEMPLATE_DB} OWNER dw_migrator")
    finally:
        await admin.close()
    migrated = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(REPO_ROOT / "db" / "alembic.ini"),
            "upgrade",
            revision,
        ],
        env={
            **os.environ,
            "DW_DATABASE_URL": endpoint.on(TEMPLATE_DB).url("migrator", "postgresql+asyncpg"),
        },
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if migrated.returncode != 0:
        raise RuntimeError(f"alembic upgrade {revision} failed:\n{migrated.stderr[-4000:]}")
    mig = await endpoint.on(TEMPLATE_DB).connect("migrator")
    try:
        # The partitions a deployment's `partitions` lane makes, so audit rows of
        # the write path land in this month's partition, not DEFAULT.
        await mig.execute("SELECT platform.ensure_time_partitions(2)")
    finally:
        await mig.close()


async def drop_databases(endpoint: Endpoint, template_too: bool) -> None:
    admin = await endpoint.on("postgres").connect("admin")
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {BENCH_DB} WITH (FORCE)")
        if template_too:
            await admin.execute(f"DROP DATABASE IF EXISTS {TEMPLATE_DB} WITH (FORCE)")
    finally:
        await admin.close()


async def create_cell_database(endpoint: Endpoint) -> None:
    mig = await endpoint.on("postgres").connect("migrator")
    try:
        await mig.execute(f"DROP DATABASE IF EXISTS {BENCH_DB} WITH (FORCE)")
        await mig.execute(f"CREATE DATABASE {BENCH_DB} TEMPLATE {TEMPLATE_DB} OWNER dw_migrator")
    finally:
        await mig.close()


async def _remainder(conn: asyncpg.Connection, tenant: uuid.UUID) -> int:
    for r in range(8):
        if await conn.fetchval(
            "SELECT satisfies_hash_partition('studio.records'::regclass, 8, $1, $2::uuid)",
            r,
            tenant,
        ):
            return r
    raise RuntimeError(f"no remainder for {tenant}")


async def _choose_tenants(
    conn: asyncpg.Connection, scale: Scale
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """T2 hashes into T1's partition; small tenant i into remainder i % 8."""
    t1 = bench_uuid(1, 0, 0)
    target = await _remainder(conn, t1)
    t2 = None
    for c in candidate_ids(1, 512):
        if await _remainder(conn, c) == target:
            t2 = c
            break
    if t2 is None:
        raise RuntimeError("no T2 candidate hashes into T1's partition")
    small: list[uuid.UUID] = []
    for i in range(scale.small_tenants):
        for c in candidate_ids(2 + i, 512):
            if await _remainder(conn, c) == i % 8:
                small.append(c)
                break
    return t2, small


async def _seed_platform(conn: asyncpg.Connection, plans: list[TenantPlan]) -> None:
    await conn.copy_records_to_table(
        "tenants",
        schema_name="platform",
        columns=["id", "slug", "name"],
        records=[(p.tenant_id, f"bench-{p.idx}", f"Bench tenant {p.idx}") for p in plans],
    )
    await conn.copy_records_to_table(
        "workspaces",
        schema_name="platform",
        columns=["id", "tenant_id", "slug", "name"],
        records=[
            (p.workspace(w), p.tenant_id, f"ws-{w}", f"Workspace {w}")
            for p in plans
            for w in range(p.workspaces)
        ],
    )


async def _seed_org(conn: asyncpg.Connection, facts: SeedFacts) -> None:
    org, t1 = facts.org, facts.t1
    people: list[tuple[Any, ...]] = []
    for plan in facts.plans:
        for p in range(plan.people + 1):  # + the service account
            manager: uuid.UUID | None = None
            depth = 1
            if plan.idx == 0 and p in org.manager_of:
                manager = plan.person(org.manager_of[p])
                depth = depth_of(org.manager_of, p)
            people.append(
                (
                    plan.tenant_id,
                    plan.person(p),
                    p,
                    manager,
                    plan.workspace(p % plan.workspaces),
                    depth,
                )
            )
    await conn.copy_records_to_table(
        "bench_people",
        schema_name="studio",
        columns=["tenant_id", "id", "person_no", "manager_id", "home_workspace_id", "depth"],
        records=people,
    )
    tree = [
        (
            t1.tenant_id,
            t1.workspace(w),
            t1.workspace(org.workspace_parent[w]) if w in org.workspace_parent else None,
            depth_of(org.workspace_parent, w),
        )
        for w in range(t1.workspaces)
    ]
    await conn.copy_records_to_table(
        "bench_workspace_tree",
        schema_name="studio",
        columns=["tenant_id", "workspace_id", "parent_id", "depth"],
        records=tree,
    )
    teams, members = [], []
    for plan in facts.plans:
        for t in range(plan.teams):
            teams.append((plan.tenant_id, plan.team(t), plan.workspace(t % plan.workspaces)))
        for p in range(plan.people):
            members.append((plan.tenant_id, plan.team(p % plan.teams), plan.person(p)))
    await conn.copy_records_to_table(
        "bench_teams",
        schema_name="studio",
        columns=["tenant_id", "id", "workspace_id"],
        records=teams,
    )
    await conn.copy_records_to_table(
        "bench_team_members",
        schema_name="studio",
        columns=["tenant_id", "team_id", "person_id"],
        records=members,
    )


async def _seed_definitions(conn: asyncpg.Connection, facts: SeedFacts, variant: Variant) -> None:
    artifacts, objects, fields = [], [], []
    for plan in facts.plans:
        creator = plan.person(0)
        for lay in facts.layouts[: plan.objects]:
            oid = plan.object_id(lay.index)
            artifacts.append((oid, plan.tenant_id, "object", lay.api_name, plan.workspace(0), 1))
            default_access = "public_read" if (plan.idx == 0 and lay.index == LEAD) else "private"
            objects.append(
                (
                    plan.tenant_id,
                    oid,
                    lay.api_name,
                    f'{{"vi": "{lay.api_name}"}}',
                    default_access,
                    creator,
                    creator,
                )
            )
        fields += field_rows(plan, facts.layouts, variant)
    await conn.copy_records_to_table(
        "artifacts",
        schema_name="studio",
        columns=["id", "tenant_id", "kind", "api_name", "owning_workspace_id", "row_version"],
        records=artifacts,
    )
    await conn.copy_records_to_table(
        "object_defs",
        schema_name="studio",
        columns=[
            "tenant_id",
            "id",
            "api_name",
            "labels",
            "default_access",
            "created_by",
            "updated_by",
        ],
        records=objects,
    )
    await conn.copy_records_to_table(
        "field_defs",
        schema_name="studio",
        columns=[
            "tenant_id",
            "id",
            "object_id",
            "api_name",
            "type",
            "storage_kind",
            "slot",
            "field_no",
            "created_by",
            "updated_by",
        ],
        records=fields,
    )


async def _seed_records(conn: asyncpg.Connection, facts: SeedFacts, variant: Variant) -> None:
    cols = generated_columns(variant)
    if not variant.pivot:
        target = f"studio.records ({', '.join(cols)})"
        for plan in facts.plans:
            await conn.execute(
                f"INSERT INTO {target}\n{generator_sql(plan, variant, facts.layouts)}"
            )
        return
    # C: the same generator into an unlogged staging table, then the narrow
    # records and one pivot row per non-NULL slot value.
    for i, plan in enumerate(facts.plans):
        sql = generator_sql(plan, variant, facts.layouts)
        if i == 0:
            await conn.execute(f"CREATE UNLOGGED TABLE studio.bench_staging AS {sql}")
        else:
            await conn.execute(f"INSERT INTO studio.bench_staging {sql}")
    system = [c for c in cols if not _is_slot(c)]
    await conn.execute(
        f"INSERT INTO studio.records ({', '.join(system)}) SELECT {', '.join(system)} FROM"
        " studio.bench_staging"
    )
    # One statement per slot, joined to the field each (tenant, object, slot)
    # maps to: one per (tenant, object, slot) scanned the unindexed staging
    # table ~10^4 times, minutes at tiny and many hours at smoke (3/11/2026).
    mapping = [
        (plan.tenant_id, plan.object_id(lay.index), slot, field_id(plan, lay.index, slot))
        for plan in facts.plans
        for lay in facts.layouts[: plan.objects]
        for slot in lay.used_slots(variant.families)
    ]
    await conn.execute(
        "CREATE UNLOGGED TABLE studio.bench_slot_fields (tenant_id uuid, object_id uuid,"
        " slot text, field_id uuid, PRIMARY KEY (tenant_id, object_id, slot))"
    )
    await conn.copy_records_to_table("bench_slot_fields", schema_name="studio", records=mapping)
    for slot in sorted({row[2] for row in mapping}):
        await conn.execute(
            f"INSERT INTO studio.record_values_{slot[0]} (tenant_id, object_id, record_id,"
            " field_id, value, workspace_id, owner_kind, owner_id, access_key, read_grants)"
            f" SELECT s.tenant_id, s.object_id, s.id, f.field_id, s.{slot}, s.workspace_id,"
            " s.owner_kind, s.owner_id,"
            " md5(s.object_id::text || '/' || s.workspace_id::text)::uuid, s.read_grants"
            " FROM studio.bench_staging s JOIN studio.bench_slot_fields f"
            " ON f.tenant_id = s.tenant_id AND f.object_id = s.object_id"
            f" AND f.slot = '{slot}' WHERE s.{slot} IS NOT NULL"
        )
    await conn.execute("DROP TABLE studio.bench_staging, studio.bench_slot_fields")


def _is_slot(column: str) -> bool:
    return len(column) == 3 and column[0] in "tuifdzblm" and column[1:].isdigit()


async def _seed_shares(conn: asyncpg.Connection, facts: SeedFacts, variant: Variant) -> None:
    if not variant.w2:
        return
    t1 = facts.t1
    # Manual shares are the source of the person keys on read_grants (ADR-0105
    # decision 3); rule versions grant through their own key.
    await conn.execute(
        "INSERT INTO studio.record_shares (tenant_id, record_id, principal_id, access)"
        " SELECT tenant_id, id, g, 'read' FROM studio.records, unnest(read_grants) AS g"
        " WHERE substr(g::text, 1, 4) = '0004' ON CONFLICT DO NOTHING"
    )
    await conn.copy_records_to_table(
        "sharing_rule_versions",
        schema_name="studio",
        columns=["tenant_id", "id", "object_id", "condition", "target_id", "access"],
        records=[
            (
                t1.tenant_id,
                bench_uuid(KIND_RULE, 0, v),
                t1.object_id(LEAD),
                f"record.t02 == 'rule-{v}'",
                t1.team(v % t1.teams),
                "read",
            )
            for v in range(t1.rule_versions)
        ],
    )


async def build_cell(endpoint: Endpoint, scale: Scale, variant: Variant, modulus: int) -> SeedFacts:
    await create_cell_database(endpoint)
    ddl = cell_ddl(variant, modulus)
    conn = await endpoint.connect("migrator", command_timeout=None)
    try:
        started = time.monotonic()
        for statement in ddl.schema:
            await conn.execute(statement)
        t2, small = await _choose_tenants(conn, scale)
        facts = SeedFacts(
            scale=scale,
            plans=tenant_plans(scale, t2, small),
            layouts=object_layouts(scale.objects),
            org=organisation(scale),
        )
        profiles_and_scopes(facts, variant)
        await _seed_platform(conn, facts.plans)
        await _seed_org(conn, facts)
        await _seed_definitions(conn, facts, variant)
        log(f"{variant.name} m{modulus}: seeding records")
        await _seed_records(conn, facts, variant)
        await _seed_shares(conn, facts, variant)
        await conn.copy_records_to_table(
            "principal_scopes",
            schema_name="studio",
            columns=["tenant_id", "principal_id", "action", "arm", "ids"],
            records=facts.scopes,
        )
        log(f"{variant.name} m{modulus}: indexes and keys ({len(ddl.post_load)} statements)")
        for statement in ddl.post_load:
            await conn.execute(statement)
        t1_partition = await t1_partition_name(conn, facts, "studio.records")
        for option, value in scale.t1_partition_reloptions:
            await conn.execute(f"ALTER TABLE {t1_partition} SET ({option} = {value})")
        await conn.execute("VACUUM (ANALYZE)")
        facts.shape = await _shape(conn, facts, variant, modulus)
        facts.shape["build_seconds"] = round(time.monotonic() - started, 1)
        facts.shape["indexes_declared"] = len(ddl.indexes)
        log(f"{variant.name} m{modulus}: built in {facts.shape['build_seconds']} s")
        return facts
    finally:
        await conn.close()


async def t1_partition_name(conn: asyncpg.Connection, facts: SeedFacts, table: str) -> str:
    name = await conn.fetchval(
        f"SELECT tableoid::regclass::text FROM {table} WHERE tenant_id = $1 LIMIT 1",
        facts.t1.tenant_id,
    )
    if name is None:
        raise RuntimeError("T1 has no rows")
    return str(name)


async def _shape(
    conn: asyncpg.Connection, facts: SeedFacts, variant: Variant, modulus: int
) -> dict[str, Any]:
    """What the seed actually holds, so a report states the shape it measured."""
    t1, t2 = facts.t1, facts.t2
    part_of = {
        str(r["tenant_id"]): r["p"]
        for r in await conn.fetch(
            "SELECT DISTINCT ON (tenant_id) tenant_id, tableoid::regclass::text AS p FROM"
            " studio.records"
        )
    }
    small_parts = {
        part_of[str(p.tenant_id)] for p in facts.plans[2:] if str(p.tenant_id) in part_of
    }
    shape: dict[str, Any] = {
        "t1_records": await conn.fetchval(
            "SELECT count(*) FROM studio.records WHERE tenant_id = $1", t1.tenant_id
        ),
        "t1_leads": await conn.fetchval(
            "SELECT count(*) FROM studio.records WHERE tenant_id = $1 AND object_id = $2",
            t1.tenant_id,
            t1.object_id(LEAD),
        ),
        "t2_records": await conn.fetchval(
            "SELECT count(*) FROM studio.records WHERE tenant_id = $1", t2.tenant_id
        ),
        "all_records": await conn.fetchval("SELECT count(*) FROM studio.records"),
        "t1_partition": part_of.get(str(t1.tenant_id)),
        "t2_partition": part_of.get(str(t2.tenant_id)),
        "t2_shares_t1_partition": part_of.get(str(t1.tenant_id)) == part_of.get(str(t2.tenant_id)),
        "small_tenants": len(facts.plans) - 2,
        "small_tenant_partitions": len(small_parts),
        "partitions": modulus,
        "people": facts.org.people,
        "workspaces": facts.org.workspaces,
        "workspace_depth": facts.org.max_workspace_depth,
        "manager_depth": facts.org.max_manager_depth,
        "teams": facts.org.teams,
        "objects": t1.objects,
        "pg_indexes_on_t1_partition": await conn.fetchval(
            "SELECT count(*) FROM pg_index WHERE indrelid = $1::regclass",
            part_of.get(str(t1.tenant_id)),
        ),
        "t1_partition_size_mb": round(
            await conn.fetchval(
                "SELECT pg_total_relation_size($1::regclass)", part_of.get(str(t1.tenant_id))
            )
            / 2**20,
            1,
        ),
    }
    if not variant.pivot:
        shape["campaign_children"] = (
            await conn.fetchval(
                "SELECT count(*) FROM studio.records WHERE tenant_id = $1 AND m01 = $2",
                t1.tenant_id,
                facts.campaign_id(),
            )
            if variant.w2
            else None
        )
        shape["service_account_leads"] = await conn.fetchval(
            "SELECT count(*) FROM studio.records WHERE tenant_id = $1 AND owner_id = $2 AND"
            " object_id = $3",
            t1.tenant_id,
            facts.writer,
            t1.object_id(LEAD),
        )
        shape["t01_lead_distinct"] = await conn.fetchval(
            "SELECT count(DISTINCT t01) FROM studio.records WHERE tenant_id = $1 AND object_id ="
            " $2",
            t1.tenant_id,
            t1.object_id(LEAD),
        )
        shape["t01_account_distinct"] = await conn.fetchval(
            "SELECT count(DISTINCT t01) FROM studio.records WHERE tenant_id = $1 AND object_id ="
            " $2",
            t1.tenant_id,
            t1.object_id(2),
        )
    else:
        shape["pivot_rows"] = {
            fam: await conn.fetchval(f"SELECT count(*) FROM studio.record_values_{fam}")
            for fam in variant.families
        }
    if variant.w2:
        shape["share_recipient_records"] = await conn.fetchval(
            "SELECT count(*) FROM studio.records WHERE tenant_id = $1 AND read_grants @>"
            " ARRAY[$2::uuid]",
            t1.tenant_id,
            t1.person(PERSON_SHARE),
        )
        shape["records_with_grants_pct"] = await conn.fetchval(
            "SELECT round(100.0 * count(*) FILTER (WHERE cardinality(read_grants) > 0) / count(*),"
            " 2)"
            " FROM studio.records WHERE tenant_id = $1",
            t1.tenant_id,
        )
    row = await conn.fetchrow(
        "SELECT workspace_id, access_key FROM studio.records WHERE tenant_id = $1 AND object_id ="
        " $2 LIMIT 1",
        t1.tenant_id,
        t1.object_id(LEAD),
    )
    shape["access_key_matches_python"] = row["access_key"] == access_key(
        t1.object_id(LEAD), row["workspace_id"]
    )
    shape["record_id_matches_python"] = bool(
        await conn.fetchval(
            "SELECT count(*) FROM studio.records WHERE tenant_id = $1 AND id = $2",
            t1.tenant_id,
            t1.record_id(12345),
        )
    )
    return shape
