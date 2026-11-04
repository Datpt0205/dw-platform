"""Each measurement of ticket 01 step 5, one function each, writing rows into the report."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta
from typing import Any

import asyncpg

from .cell import log, t1_partition_name
from .db import Endpoint, scoped
from .ddl import ACL_FUNCTIONS, TENANT, TENANT_PER_ROW, Variant, partitions, record_policies
from .model import ACCOUNT, LEAD, NAMES_OBJECT
from .report import Claim, Report, Row, percentile, series_limit
from .seed import Profile, SeedFacts
from .workload import (
    GET_SQL,
    LOCK_SQL,
    MixedLoad,
    Recorder,
    WritePath,
    Writer,
    page_sql,
    read_get,
    read_page,
    timed,
)

INDEX_NODE = re.compile(r"(?:Index (?:Only )?Scan(?: Backward)? using|Bitmap Index Scan on) (\S+)")
SORT_NODE = re.compile(r"^\s*(?:->\s+)?Sort\b", re.MULTILINE)

HotCounter = Callable[[asyncpg.Connection, str], Awaitable[tuple[int, int]]]


# ------------------------------------------------------------------ explain --
async def explain(
    conn: asyncpg.Connection, scope: tuple[uuid.UUID, uuid.UUID, str], sql: str, *args: Any
) -> str:
    async with scoped(conn, *scope):
        rows = await conn.fetch(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", *args)
    return "\n".join(r[0] for r in rows)


def claim_from(name: str, variant: str, modulus: int | None, sql: str, text: str) -> Claim:
    return Claim(
        name=name,
        variant=variant,
        modulus=modulus,
        sql=sql,
        explain=text,
        indexes=INDEX_NODE.findall(text),
        sort_over_match_set=bool(SORT_NODE.search(text)),
    )


# --------------------------------------------------------------------- R9.1 --
async def reads(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
    restart: Callable[[], Awaitable[None]] | None,
) -> None:
    """Warm under the mixed load, then cold after a restart, every profile."""
    scale = facts.scale
    rng = random.Random(42)
    t1 = facts.t1
    pools: dict[str, list[uuid.UUID]] = {}
    for profile in facts.profiles:
        pools[profile.name] = await _ids(endpoint, profile, facts, rng)
    update_pool = pools["service_account"] or pools["company"]
    for name, ids in pools.items():
        if not ids:
            # A profile that reads nothing here (W1's policy admits no agent) still
            # GETs: a record it may not read answers nothing, and that is timed too.
            pools[name] = update_pool
            report.info.append(
                f"{variant.name} m{modulus}: {name} đọc được 0 bản ghi; GET nhắm bản ghi"
                " nó không đọc được"
            )
    warm_pool = {name: ids[: max(1, len(ids) // 3)] for name, ids in pools.items()}
    load = MixedLoad(
        endpoint,
        facts,
        path,
        writer,
        facts.profiles,
        warm_pool,
        update_pool,
        read_target=scale.read_samples,
        recorder=Recorder(limit=_limits(report)),
    )
    log(f"{variant.name} m{modulus}: warm mixed load, {scale.sessions} sessions")
    rec = await load.until_sampled(scale.sessions, timeout_s=1800)
    for profile in facts.profiles:
        for kind, key in (("page", "page_p95_ms"), ("get", "get_p95_ms")):
            name = f"{kind}_warm:{profile.name}"
            report.add_p95(
                "R9.1",
                name,
                variant.name,
                modulus,
                rec.samples.get(name, []),
                key,
                _note(profile, rec, name),
            )
    report.add_p95(
        "record-access:R9.5",
        "write_update_p95",
        variant.name,
        modulus,
        rec.samples["write_update"],
        "write_p95_ms",
        _errors(rec, "write_update"),
    )
    report.add_p95(
        "record-access:R9.5",
        "write_create_p95",
        variant.name,
        modulus,
        rec.samples["write_create"],
        "write_p95_ms",
        _errors(rec, "write_create"),
    )
    # One plan per profile, carried by every "uses an index" claim.
    conn = await endpoint.connect("app")
    try:
        for profile in facts.profiles:
            sql = page_sql(profile.order, False)
            text = await explain(
                conn,
                (t1.tenant_id, profile.principal, profile.actor_kind),
                sql,
                t1.tenant_id,
                t1.object_id(profile.object_index),
            )
            report.claim(
                claim_from(f"R9.1 trang đầu {profile.name}", variant.name, modulus, sql, text)
            )
            get_id = (pools[profile.name] or update_pool)[0]
            text = await explain(
                conn,
                (t1.tenant_id, profile.principal, profile.actor_kind),
                GET_SQL,
                t1.tenant_id,
                get_id,
            )
            report.claim(
                claim_from(f"R9.1 GET {profile.name}", variant.name, modulus, GET_SQL, text)
            )
    finally:
        await conn.close()
    if restart is None:
        report.info.append(f"{variant.name} m{modulus}: không có container riêng, không chạy nguội")
        return
    from .workload import lead_cursors, run_queue

    cursors = await lead_cursors(endpoint, t1, scale.read_samples * len(facts.profiles) + 100)
    log(f"{variant.name} m{modulus}: cold run (restart + drop caches)")
    await restart()
    cold = Recorder(limit=_limits(report))
    jobs: list[tuple[str, Callable[[asyncpg.Connection], Awaitable[Any]]]] = []
    cursor_iter = iter(cursors)
    for profile in facts.profiles:
        cold_pool = pools[profile.name][len(warm_pool[profile.name]) :] or pools[profile.name]
        for i in range(scale.read_samples):
            cur = next(cursor_iter, cursors[i % len(cursors)])
            jobs.append((f"page_cold:{profile.name}", _page_job(profile, facts, cur)))
            jobs.append(
                (
                    f"get_cold:{profile.name}",
                    _get_job(profile, facts, cold_pool[i % len(cold_pool)]),
                )
            )
    rng.shuffle(jobs)
    await run_queue(endpoint, scale.sessions, jobs, cold)
    for profile in facts.profiles:
        pool_size = len(pools[profile.name]) - len(warm_pool[profile.name])
        for kind, key in (("page", "page_p95_ms"), ("get", "get_p95_ms")):
            name = f"{kind}_cold:{profile.name}"
            note = _note(profile, cold, name)
            if kind == "get" and pool_size < scale.read_samples:
                note += f" khóa chưa đọc: {pool_size}, phần còn lại đọc lại"
            report.add_p95(
                "R9.1", name, variant.name, modulus, cold.samples.get(name, []), key, note.strip()
            )


def _page_job(
    profile: Profile, facts: SeedFacts, cursor: Any
) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    return lambda conn: read_page(
        conn, profile, facts.t1, cursor if profile.order == "created" else None
    )


def _get_job(
    profile: Profile, facts: SeedFacts, rid: uuid.UUID
) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    return lambda conn: read_get(conn, profile, facts.t1, rid)


async def _ids(
    endpoint: Endpoint, profile: Profile, facts: SeedFacts, rng: random.Random
) -> list[uuid.UUID]:
    from .workload import readable_ids

    return await readable_ids(endpoint, profile, facts.t1, 3 * facts.scale.read_samples, rng)


def _limits(report: Report) -> Callable[[str], float | None]:
    return lambda series: series_limit(report.thresholds, series)


def _note(profile: Profile, rec: Recorder, name: str) -> str:
    return " ".join(x for x in (profile.note, _errors(rec, name)) if x)


def _errors(rec: Recorder, name: str) -> str:
    return f"{rec.errors[name]} lỗi, đầu: {rec.first_error[name]}" if rec.errors.get(name) else ""


# --------------------------------------------------------------------- R9.2 --
THREE_PREDICATES = (
    "SELECT * FROM studio.records WHERE tenant_id = $1 AND object_id = $2 AND t01 = $3 AND i01 >="
    " $4"
    " AND d01 < $5 AND deleted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 50"
)
THREE_PREDICATES_NO_TENANT = (
    "SELECT * FROM studio.records WHERE object_id = $1 AND t01 = $2 AND i01 >= $3"
    " AND d01 < $4 AND deleted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 50"
)


async def planning(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    samples: int,
) -> None:
    """Planning p95 of a three-predicate query on three slots of different families (t, i, d).

    Custom plan: `EXPLAIN (SUMMARY)` of the statement with literals. Generic plan:
    `PREPARE` then `EXPLAIN (SUMMARY) EXECUTE` under `plan_cache_mode =
    force_generic_plan`, a fresh PREPARE per sample so each one plans.
    """
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    conn = await endpoint.connect("app", statement_cache_size=0)
    rng = random.Random(3)
    scope = (t1.tenant_id, company.principal, "user")
    try:
        for with_tenant in (True, False):
            sql = THREE_PREDICATES if with_tenant else THREE_PREDICATES_NO_TENANT
            types = "uuid, uuid, text, bigint, date" if with_tenant else "uuid, text, bigint, date"
            label = "tenant" if with_tenant else "no_tenant"
            custom, generic = [], []
            for _ in range(samples):
                values = [
                    str(t1.object_id(LEAD)),
                    "Mới",
                    rng.randrange(1_000_000),
                    date(2022, 6, 1),
                ]
                if with_tenant:
                    values.insert(0, str(t1.tenant_id))
                literals = ", ".join(str(v) if isinstance(v, int) else f"'{v}'" for v in values)
                literal_sql = sql
                for i, v in reversed(list(enumerate(literals.split(", "), 1))):
                    literal_sql = literal_sql.replace(f"${i}", v)
                async with scoped(conn, *scope):
                    plan = await conn.fetchval(f"EXPLAIN (SUMMARY, FORMAT JSON) {literal_sql}")
                custom.append(float(json.loads(plan)[0]["Planning Time"]))
                async with scoped(conn, *scope):
                    await conn.execute("SET LOCAL plan_cache_mode = force_generic_plan")
                    await conn.execute(f"PREPARE q3 ({types}) AS {sql}")
                    plan = await conn.fetchval(
                        f"EXPLAIN (SUMMARY, FORMAT JSON) EXECUTE q3({literals})"
                    )
                    await conn.execute("DEALLOCATE q3")
                generic.append(float(json.loads(plan)[0]["Planning Time"]))
            report.add_p95(
                "R9.2",
                f"planning_custom_{label}",
                variant.name,
                modulus,
                custom,
                "planning_p95_ms",
                "EXPLAIN (SUMMARY) của câu literal",
            )
            report.add_p95(
                "R9.2",
                f"planning_generic_{label}",
                variant.name,
                modulus,
                generic,
                "planning_p95_ms",
                "PREPARE + EXPLAIN EXECUTE, force_generic_plan",
            )
            args: list[Any] = [t1.object_id(LEAD), "Mới", 500_000, date(2022, 6, 1)]
            if with_tenant:
                args.insert(0, t1.tenant_id)
            text = await explain(conn, scope, sql, *args)
            report.claim(claim_from(f"R9.2 ba vị từ ({label})", variant.name, modulus, sql, text))
    finally:
        await conn.close()


async def cache_memory(
    report: Report, endpoint: Endpoint, facts: SeedFacts, variant: Variant, modulus: int
) -> None:
    """CacheMemoryContext of one backend after touching every partition (gate MEDIUM (a))."""
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    conn = await endpoint.connect("admin")
    try:
        await conn.execute("SET ROLE dw_app")
        for tenant in [p.tenant_id for p in facts.plans]:
            async with scoped(conn, tenant, company.principal, "user"):
                await conn.fetch(page_sql("created", False), tenant, t1.object_id(LEAD))
                await conn.fetch(
                    THREE_PREDICATES, tenant, t1.object_id(LEAD), "Mới", 1, date(2022, 1, 1)
                )
        async with scoped(conn, t1.tenant_id, company.principal, "user"):
            # No tenant predicate: the planner opens every partition and its indexes.
            await conn.fetch(
                THREE_PREDICATES_NO_TENANT, t1.object_id(LEAD), "Mới", 1, date(2022, 1, 1)
            )
        await conn.execute("RESET ROLE")
        total = await conn.fetchval(
            "SELECT sum(total_bytes) FROM pg_backend_memory_contexts"
            " WHERE name = 'CacheMemoryContext' OR parent = 'CacheMemoryContext'"
        )
        own = await conn.fetchval(
            "SELECT total_bytes FROM pg_backend_memory_contexts WHERE name = 'CacheMemoryContext'"
        )
    finally:
        await conn.close()
    report.add(
        Row(
            "R9.2",
            "cache_memory_mb",
            variant.name,
            modulus,
            round(int(total) / 2**20, 2),
            "MB",
            "cache_memory_mb",
            note=f"CacheMemoryContext riêng {int(own) / 2**20:.1f} MB, cộng con trực tiếp;"
            " phiên superuser SET ROLE dw_app rồi RESET ROLE",
        )
    )
    report.info.append(await _locks_per_page(endpoint, facts, variant, modulus))


async def _locks_per_page(
    endpoint: Endpoint, facts: SeedFacts, variant: Variant, modulus: int
) -> str:
    """Relation locks one first-page transaction holds, custom plan against generic.

    The tiny run of 2/11 hit `out of shared memory` under the 50-session cold load:
    a plan that prunes partitions only at execution has locked every partition and
    every index of each by then, and the image's lock table is
    max_locks_per_transaction x max_connections. This says how many, per plan mode.
    """
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    counts: dict[str, int] = {}
    conn = await endpoint.connect("app")
    try:
        for mode in ("force_custom_plan", "force_generic_plan"):
            await conn.execute(f"SET plan_cache_mode = {mode}")
            async with scoped(conn, t1.tenant_id, company.principal, "user"):
                await conn.fetch(page_sql("created", False), t1.tenant_id, t1.object_id(LEAD))
                counts[mode] = int(
                    await conn.fetchval(
                        "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid()"
                        " AND locktype = 'relation'"
                    )
                )
        await conn.execute("RESET plan_cache_mode")
        slots = await conn.fetchval(
            "SELECT current_setting('max_locks_per_transaction')::int"
            " * (current_setting('max_connections')::int"
            " + current_setting('max_prepared_transactions')::int)"
        )
    finally:
        await conn.close()
    return (
        f"{variant.name} m{modulus}: khóa quan hệ một giao dịch trang đầu giữ: custom plan"
        f" {counts['force_custom_plan']}, generic plan {counts['force_generic_plan']}; bảng khóa"
        f" chung {slots} chỗ (max_locks_per_transaction x (max_connections +"
        " max_prepared_transactions)), 16 khóa fast-path mỗi backend"
    )


# --------------------------------------------------------------------- R9.8 --
async def qerror(
    report: Report, endpoint: Endpoint, facts: SeedFacts, variant: Variant, modulus: int, count: int
) -> None:
    """Three predicates on the shared slot t01 (a picklist on mkt_lead, e-mails on account)."""
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    rng = random.Random(8)
    mig = await endpoint.connect("migrator")
    try:
        emails = [
            r[0]
            for r in await mig.fetch(
                "SELECT t01 FROM studio.records TABLESAMPLE SYSTEM (5) REPEATABLE (3)"
                " WHERE tenant_id = $1 AND object_id = $2 AND t01 IS NOT NULL LIMIT 500",
                t1.tenant_id,
                t1.object_id(ACCOUNT),
            )
        ]
    finally:
        await mig.close()
    from .model import LEAD_STATUSES

    sql = (
        "SELECT id FROM studio.records WHERE tenant_id = $1 AND object_id = $2 AND t01 = $3 AND"
        " i01 >= $4"
        " AND d01 < $5 AND deleted_at IS NULL"
    )
    conn = await endpoint.connect("app")
    q_values: list[float] = []
    slowest: tuple[float, list[Any]] = (-1.0, [])
    try:
        for i in range(count):
            if i % 2 == 0:
                args = [t1.tenant_id, t1.object_id(LEAD), rng.choice(LEAD_STATUSES)]
            else:
                args = [t1.tenant_id, t1.object_id(ACCOUNT), rng.choice(emails or ["x"])]
            args += [
                rng.randrange(1_000_000),
                date(2018, 1, 1) + timedelta(days=rng.randrange(3000)),
            ]
            async with scoped(conn, t1.tenant_id, company.principal, "user"):
                plan = json.loads(
                    await conn.fetchval(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", *args)
                )[0]
            node = plan["Plan"]
            estimated = max(1.0, float(node["Plan Rows"]))
            actual = max(1.0, float(node["Actual Rows"]) * float(node.get("Actual Loops", 1)))
            q_values.append(max(estimated / actual, actual / estimated))
            took = float(plan["Execution Time"])
            if took > slowest[0]:
                slowest = (took, args)
        best = slowest[0]
        toggles = [
            "enable_seqscan",
            "enable_bitmapscan",
            "enable_indexscan",
            "enable_indexonlyscan",
        ]
        for off in toggles:
            async with scoped(conn, t1.tenant_id, company.principal, "user"):
                await conn.execute(f"SET LOCAL {off} = off")
                plan = json.loads(
                    await conn.fetchval(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", *slowest[1])
                )[0]
            best = min(best, float(plan["Execution Time"]))
    finally:
        await conn.close()
    report.add(
        Row(
            "R9.8",
            "qerror_p95",
            variant.name,
            modulus,
            round(percentile(q_values, 0.95), 2),
            "x",
            "qerror_p95",
            samples=len(q_values),
            note="nút gốc: ước lượng so với thực; nửa lead, nửa account",
        )
    )
    ratio = slowest[0] / best if best > 0 else 1.0
    report.add(
        Row(
            "R9.8",
            "slowest_vs_best",
            variant.name,
            modulus,
            round(ratio, 2),
            "x",
            "slowest_vs_best",
            note=f"chậm nhất {slowest[0]:.2f} ms, tốt nhất khi tắt từng kiểu quét {best:.2f} ms",
        )
    )


# ---------------------------------------------------------------------- HOT --
async def pg_hot_counter(conn: asyncpg.Connection, relation: str) -> tuple[int, int]:
    """(n_tup_upd, n_tup_hot_upd) of one relation, after the stats flush."""
    await conn.execute("SELECT pg_stat_clear_snapshot()")
    row = await conn.fetchrow(
        "SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relid = $1::regclass",
        relation,
    )
    return int(row["n_tup_upd"]), int(row["n_tup_hot_upd"])


def hot_ratio(before: tuple[int, int], after: tuple[int, int]) -> float | None:
    updates = after[0] - before[0]
    if updates <= 0:
        return None
    return (after[1] - before[1]) / updates


async def measure_hot(
    endpoint: Endpoint,
    facts: SeedFacts,
    path: WritePath,
    writer: Writer,
    count: int,
    counter: HotCounter = pg_hot_counter,
) -> tuple[float | None, int]:
    """HOT share of updates that touch only `data`, in steady state.

    A freshly loaded page is full, so a first update moves its row whatever the
    indexes; a page vacuumed after one of its rows moved has room. So: update a
    sample (prime), VACUUM T1's partition, then update rows that share pages
    with the primed ones and count only those (ADR-0107 decision 2's prediction:
    A1 ~ 0%, A2 > 0%).
    """
    t1 = facts.t1
    mig = await endpoint.connect("migrator")
    try:
        part = await t1_partition_name(mig, facts, "studio.records")
        primed = await mig.fetch(
            f"SELECT id, (ctid::text::point)[0]::int AS page FROM {part} TABLESAMPLE SYSTEM (10)"
            " REPEATABLE (5)"
            " WHERE tenant_id = $1 AND object_id = $2 LIMIT $3",
            t1.tenant_id,
            t1.object_id(LEAD),
            count,
        )
    finally:
        await mig.close()
    await _update_all(endpoint, path, writer, facts, [r["id"] for r in primed])
    mig = await endpoint.connect("migrator")
    try:
        await mig.execute(f"VACUUM {part}")
        neighbours = await mig.fetch(
            f"SELECT id FROM {part} WHERE ((ctid::text::point)[0])::int = ANY($1::int[])"
            " AND tenant_id = $2 AND NOT (id = ANY($3::uuid[])) LIMIT $4",
            sorted({r["page"] for r in primed}),
            t1.tenant_id,
            [r["id"] for r in primed],
            count,
        )
        await asyncio.sleep(1.2)
        before = await counter(mig, part)
        await _update_all(endpoint, path, writer, facts, [r["id"] for r in neighbours])
        await asyncio.sleep(1.2)  # backends flush their counters when they exit; let them
        after = await counter(mig, part)
    finally:
        await mig.close()
    return hot_ratio(before, after), len(neighbours)


async def _update_all(
    endpoint: Endpoint, path: WritePath, writer: Writer, facts: SeedFacts, ids: Sequence[uuid.UUID]
) -> None:
    chunks = [list(ids[i::8]) for i in range(8)]

    async def run(chunk: list[uuid.UUID]) -> None:
        conn = await endpoint.connect("app")
        try:
            for rid in chunk:
                # Object of the row is not known here; the lock key and schema read use mkt_lead's.
                await path.update_data(conn, writer, rid, facts.t1.object_id(LEAD), 7, None)
        finally:
            await conn.close()

    await asyncio.gather(*(run(c) for c in chunks if c))


# --------------------------------------------------------------------- R9.9 --
async def t2_busy(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
) -> None:
    """T2's first page and GET while T1 imports, vacuums and aggregates, same partition."""
    t1, t2, scale = facts.t1, facts.t2, facts.scale
    reader = Profile("t2_company", 1, facts.t2_reader, "user", LEAD)
    rng = random.Random(9)
    from .workload import readable_ids

    pool = await readable_ids(endpoint, reader, t2, scale.read_samples, rng)
    stop = asyncio.Event()
    busy_counts = {"import": 0, "vacuum": 0, "aggregate": 0}

    async def importer(no: int) -> None:
        conn = await endpoint.connect("app")
        r = random.Random(no)
        try:
            while not stop.is_set():
                await path.create(conn, writer, t1, LEAD, r)
                busy_counts["import"] += 1
        finally:
            await conn.close()

    async def vacuumer() -> None:
        conn = await endpoint.connect("migrator")
        try:
            part = await t1_partition_name(conn, facts, "studio.records")
            while not stop.is_set():
                await conn.execute(f"VACUUM {part}")
                busy_counts["vacuum"] += 1
        finally:
            await conn.close()

    company = next(p for p in facts.profiles if p.name == "company")

    async def aggregator() -> None:
        conn = await endpoint.connect("app")
        try:
            while not stop.is_set():
                async with scoped(conn, t1.tenant_id, company.principal, "user"):
                    await conn.fetch(
                        AGGREGATES[busy_counts["aggregate"] % 2], t1.tenant_id, t1.object_id(LEAD)
                    )
                busy_counts["aggregate"] += 1
        finally:
            await conn.close()

    background = [asyncio.create_task(importer(i)) for i in range(4)]
    background += [
        asyncio.create_task(vacuumer()),
        asyncio.create_task(aggregator()),
        asyncio.create_task(aggregator()),
    ]
    rec = Recorder(limit=_limits(report))
    from .workload import run_queue

    jobs: list[tuple[str, Callable[[asyncpg.Connection], Awaitable[Any]]]] = []
    for i in range(scale.read_samples):
        jobs.append(("t2_page_busy", lambda c: read_page(c, reader, t2, None)))
        rid = pool[i % len(pool)]
        jobs.append(("t2_get_busy", _t2_get(reader, t2, rid)))
    try:
        await run_queue(endpoint, 10, jobs, rec)
    finally:
        stop.set()
        await asyncio.gather(*background, return_exceptions=True)
    note = (
        f"trong lúc T1: {busy_counts['import']} lần tạo, {busy_counts['vacuum']} VACUUM,"
        f" {busy_counts['aggregate']} tổng hợp"
    )
    report.add_p95(
        "R9.9",
        "t2_page_busy",
        variant.name,
        modulus,
        rec.samples["t2_page_busy"],
        "page_p95_ms",
        note + (" " + _errors(rec, "t2_page_busy")).rstrip(),
    )
    report.add_p95(
        "R9.9",
        "t2_get_busy",
        variant.name,
        modulus,
        rec.samples["t2_get_busy"],
        "get_p95_ms",
        note + (" " + _errors(rec, "t2_get_busy")).rstrip(),
    )


def _t2_get(
    reader: Profile, plan: Any, rid: uuid.UUID
) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    return lambda c: read_get(c, reader, plan, rid)


AGGREGATES = (
    "SELECT t01, count(*) FROM studio.records WHERE tenant_id = $1 AND object_id = $2 AND"
    " deleted_at IS NULL"
    " GROUP BY t01",
    "SELECT date_trunc('month', z01) AS m, sum(i01) FROM studio.records WHERE tenant_id = $1 AND"
    " object_id = $2"
    " AND deleted_at IS NULL GROUP BY 1",
)


# --------------------------------------------------------- PARALLEL SAFE --
async def parallel_aggregates(
    report: Report, endpoint: Endpoint, facts: SeedFacts, variant: Variant, modulus: int
) -> None:
    """`studio.acl_*` PARALLEL SAFE against the default (report only).

    Whether the plan has a Gather and whether the results are equal.
    """
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    results: dict[str, list[Any]] = {}
    lines = []
    for mode in ("mặc định (PARALLEL UNSAFE)", "PARALLEL SAFE"):
        if mode == "PARALLEL SAFE":
            await _set_parallel(endpoint, "SAFE")
        conn = await endpoint.connect("app")
        try:
            for i, sql in enumerate(AGGREGATES):
                text = await explain(
                    conn,
                    (t1.tenant_id, company.principal, "user"),
                    sql,
                    t1.tenant_id,
                    t1.object_id(LEAD),
                )
                async with scoped(conn, t1.tenant_id, company.principal, "user"):
                    fetched = await conn.fetch(sql, t1.tenant_id, t1.object_id(LEAD))
                    rows = sorted((tuple(r) for r in fetched), key=repr)  # NULL groups sort too
                results.setdefault(str(i), []).append(rows)
                took = re.search(r"Execution Time: ([\d.]+)", text)
                lines.append(
                    f"{mode}, tổng hợp {i + 1}: Gather {'có' if 'Gather' in text else 'không'},"
                    f" {took.group(1) if took else '?'} ms"
                )
                report.claim(
                    claim_from(f"tổng hợp {i + 1} {mode}", variant.name, modulus, sql, text)
                )
        finally:
            await conn.close()
    await _set_parallel(endpoint, "UNSAFE")
    equal = all(v[0] == v[1] for v in results.values())
    report.info.append(
        f"{variant.name} m{modulus}: "
        + "; ".join(lines)
        + f"; kết quả bằng nhau: {'có' if equal else 'không'}"
    )


async def _set_parallel(endpoint: Endpoint, mode: str) -> None:
    mig = await endpoint.connect("migrator")
    try:
        for fn in ACL_FUNCTIONS:
            await mig.execute(f"ALTER FUNCTION {fn} PARALLEL {mode}")
    finally:
        await mig.close()


# ---------------------------------------------------- R9.6, R9.7: the soak --
async def soak(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
) -> None:
    """The mixed load paced to `soak_writes_per_second` writes for `soak_seconds`."""
    scale = facts.scale
    rng = random.Random(77)
    company = next(p for p in facts.profiles if p.name == "company")
    from .workload import readable_ids

    pool = await readable_ids(endpoint, company, facts.t1, 2 * scale.read_samples, rng)
    # The soak's reads are Toàn công ty's, which an index serves: a narrow profile's
    # page scans every lead under RLS (R9.1's rows say so) and would starve the
    # writes the soak exists to pace.
    load = MixedLoad(
        endpoint,
        facts,
        path,
        writer,
        [company],
        {company.name: pool},
        pool,
        read_target=0,
        seed=99,
    )
    mon = await endpoint.connect("admin")
    part = await t1_partition_name(mon, facts, "studio.records")
    samples: list[tuple[float, int, bool]] = []
    stop = asyncio.Event()

    async def monitor() -> None:
        while not stop.is_set():
            await mon.execute("SELECT pg_stat_clear_snapshot()")
            dead = await mon.fetchval(
                "SELECT n_dead_tup FROM pg_stat_user_tables WHERE relid = $1::regclass", part
            )
            running = await mon.fetchval(
                "SELECT count(*) > 0 FROM pg_stat_progress_vacuum WHERE relid = $1::regclass", part
            )
            samples.append((time.monotonic(), int(dead or 0), bool(running)))
            await asyncio.sleep(2)

    lsn0 = await mon.fetchval("SELECT pg_current_wal_lsn()")
    av0 = await mon.fetchval(
        "SELECT autovacuum_count FROM pg_stat_user_tables WHERE relid = $1::regclass", part
    )
    started = time.monotonic()
    watcher = asyncio.create_task(monitor())
    log(
        f"{variant.name} m{modulus}: soak {scale.soak_seconds} s at {scale.soak_writes_per_second}"
        " writes/s"
    )
    rec = await load.for_duration(
        scale.sessions, scale.soak_seconds, scale.soak_writes_per_second * 5, f"soak{modulus}"
    )
    elapsed = time.monotonic() - started
    stop.set()
    await watcher
    lsn1 = await mon.fetchval("SELECT pg_current_wal_lsn()")
    wal = await mon.fetchval("SELECT pg_wal_lsn_diff($1, $2)", lsn1, lsn0)
    await mon.execute("SELECT pg_stat_clear_snapshot()")
    av1 = await mon.fetchval(
        "SELECT autovacuum_count FROM pg_stat_user_tables WHERE relid = $1::regclass", part
    )
    await mon.close()
    writes = rec.count("write_update") + rec.count("write_create")
    report.add(
        Row(
            "R9.6",
            "wal_mb_per_s",
            variant.name,
            modulus,
            round(float(wal) / 1e6 / elapsed, 3),
            "MB/s",
            "wal_mb_per_s",
            note=f"pg_wal_lsn_diff qua {elapsed:.0f} s: bản ghi, write keys, outbox, audit"
            " và mọi WAL khác của cluster (autovacuum, checkpoint)",
        )
    )
    rate = writes / elapsed
    report.add(
        Row(
            "R9.6",
            "soak_writes_per_s",
            variant.name,
            modulus,
            round(rate, 1),
            "lần ghi/s",
            note=f"mục tiêu {scale.soak_writes_per_second}; {_errors(rec, 'write_update')}".strip(
                "; "
            ),
        )
    )
    cycles = _cycles(samples)
    durations = [c[1] - c[0] for c in cycles]
    dead_at_start = [c[2] for c in cycles]
    first_dead = samples[0][1] if samples else 0
    last_dead = samples[-1][1] if samples else 0
    if len(dead_at_start) >= 2:
        growth = dead_at_start[-1] / max(1, dead_at_start[0])
        how = f"dead tuple đầu mỗi vòng: {dead_at_start}"
    else:
        growth = last_dead / max(1, first_dead) if last_dead > first_dead else 1.0
        growth = max(growth, 1.51) if last_dead > first_dead else growth
        how = f"{len(cycles)} vòng trong soak; dead tuple {first_dead} → {last_dead}"
    report.add(
        Row(
            "R9.7",
            "dead_tuple_growth",
            variant.name,
            modulus,
            round(growth, 2),
            "x",
            "dead_tuple_growth",
            note=f"{how}; autovacuum_count {av0} → {av1}; {part}",
        )
    )
    longest = round(max(durations) / 60, 2) if durations else 0.0
    row = report.add(
        Row(
            "R9.7",
            "autovacuum_cycle_max_min",
            variant.name,
            modulus,
            longest,
            "phút",
            "autovacuum_cycle_min",
            note=f"{len(cycles)} vòng, dài nhất {longest:.2f} phút (lấy mẫu 2 s)"
            + ("" if cycles else "; không vòng nào trong soak"),
        )
    )
    if not cycles:
        row.verdict = "trượt"


def _cycles(samples: list[tuple[float, int, bool]]) -> list[tuple[float, float, int]]:
    """(start, end, dead tuples just before) of each vacuum seen running on the partition."""
    out: list[tuple[float, float, int]] = []
    start: float | None = None
    before = 0
    prev_dead = 0
    for ts, dead, running in samples:
        if running and start is None:
            start, before = ts, prev_dead
        elif not running and start is not None:
            out.append((start, ts, before))
            start = None
        prev_dead = dead
    return out


# -------------------------------------------------------------------- R9.10 --
async def import_rows(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
) -> None:
    scale = facts.scale
    per = scale.import_rows // scale.import_sessions
    rec = Recorder(limit=_limits(report))

    async def run(no: int) -> None:
        conn = await endpoint.connect("app")
        rng = random.Random(500 + no)
        try:
            for _ in range(per):
                await timed(rec, "import", path.create(conn, writer, facts.t1, LEAD, rng))
        finally:
            await conn.close()

    started = time.monotonic()
    await asyncio.gather(*(run(i) for i in range(scale.import_sessions)))
    elapsed = time.monotonic() - started
    done = sum(1 for ms in rec.samples["import"] if ms != float("inf"))
    report.add(
        Row(
            "R9.10",
            "import_rows_per_s",
            variant.name,
            modulus,
            round(done / elapsed, 1),
            "hàng/s",
            "import_rows_per_s",
            samples=done,
            note=f"{done} bản ghi trong {elapsed:.1f} s, {scale.import_sessions} phiên, đường ghi"
            " mô phỏng" + (f"; {_errors(rec, 'import')}" if rec.errors else ""),
        )
    )


# -------------------------------------------------------------------- R9.11 --
async def promote_purge(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    writer: Writer,
) -> None:
    """Promote `nguon` from `data` to a slot, then purge it, on every mkt_lead row.

    The background p95 is measured before and while each runs.
    """
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    rng = random.Random(13)
    from .workload import readable_ids

    pool = await readable_ids(endpoint, company, t1, 2000, rng)

    async def background(seconds: float | None, stop: asyncio.Event | None, name: str) -> Recorder:
        rec = Recorder(limit=_limits(report))

        async def worker(no: int) -> None:
            conn = await endpoint.connect("app")
            r = random.Random(no)
            try:
                deadline = time.monotonic() + (seconds or 1e9)
                while time.monotonic() < deadline and not (stop and stop.is_set()):
                    if r.random() < 0.5:
                        await timed(rec, name, read_page(conn, company, t1, None))
                    else:
                        await timed(rec, name, read_get(conn, company, t1, r.choice(pool)))
            finally:
                await conn.close()

        await asyncio.gather(*(worker(i) for i in range(4)))
        return rec

    normal = await background(20, None, "normal")
    normal_p95 = percentile(normal.samples["normal"], 0.95)
    for step in ("promote", "purge"):
        stop = asyncio.Event()
        bg = asyncio.create_task(background(None, stop, step))
        started = time.monotonic()
        batches = await (_promote if step == "promote" else _purge)(
            endpoint, facts, variant, writer
        )
        hours = (time.monotonic() - started) / 3600
        stop.set()
        rec = await bg
        during = percentile(rec.samples[step], 0.95) if rec.samples[step] else float("inf")
        rows = t1.leads
        report.add(
            Row(
                "R9.11",
                f"{step}_hours",
                variant.name,
                modulus,
                round(hours, 4),
                "giờ",
                "maintenance_hours",
                note=f"{rows} lead, {batches} lô 2.000 hàng; quy về 10^7 hàng ≈"
                f" {hours * 1e7 / max(1, rows):.2f} giờ",
            )
        )
        report.add(
            Row(
                "R9.11",
                f"{step}_background_ratio",
                variant.name,
                modulus,
                round(during / normal_p95, 2),
                "x",
                "background_p95_ratio",
                samples=len(rec.samples[step]),
                note=f"p95 nền {during:.2f} ms trong lúc chạy so với {normal_p95:.2f} ms bình"
                " thường",
            )
        )


async def _batches(endpoint: Endpoint, facts: SeedFacts, writer: Writer, statement: str) -> int:
    """Run `statement` (keyset over created_at, id of mkt_lead) in batches as a W2 lane."""
    t1 = facts.t1
    conn = await endpoint.connect("app", command_timeout=None)
    cursor: tuple[Any, Any] | None = None
    batches = 0
    try:
        while True:
            async with scoped(
                conn, t1.tenant_id, writer.user, writer.actor_kind, workspace_scope="tenant"
            ):
                row = await conn.fetchrow(
                    statement,
                    t1.tenant_id,
                    t1.object_id(LEAD),
                    cursor[0] if cursor else None,
                    cursor[1] if cursor else None,
                )
            batches += 1
            if row is None or row[0] is None:
                return batches
            cursor = (row[0], row[1])
    finally:
        await conn.close()


_BATCH = (
    "WITH b AS (SELECT id, created_at FROM studio.records WHERE tenant_id = $1 AND object_id = $2"
    " AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4::uuid))"
    " ORDER BY created_at DESC, id DESC LIMIT 2000)"
)


async def _promote(endpoint: Endpoint, facts: SeedFacts, variant: Variant, writer: Writer) -> int:
    if variant.pivot:
        from .seed import field_id

        fid = field_id(facts.t1, LEAD, "t24")
        sql = (
            f"{_BATCH}, w AS (INSERT INTO studio.record_values_t (tenant_id, object_id, record_id,"
            " field_id, value,"
            " workspace_id, owner_kind, owner_id, access_key, read_grants)"
            f" SELECT r.tenant_id, r.object_id, r.id, '{fid}'::uuid, r.data ->> 'nguon',"
            " r.workspace_id, r.owner_kind,"
            " r.owner_id, r.access_key, r.read_grants FROM studio.records r JOIN b ON r.tenant_id"
            " = $1 AND r.id = b.id"
            " WHERE r.data ? 'nguon' ON CONFLICT DO NOTHING)"
            " SELECT created_at, id FROM b ORDER BY created_at, id LIMIT 1"
        )
    else:
        sql = (
            f"{_BATCH}, u AS (UPDATE studio.records r SET t24 = r.data ->> 'nguon' FROM b"
            " WHERE r.tenant_id = $1 AND r.id = b.id)"
            " SELECT created_at, id FROM b ORDER BY created_at, id LIMIT 1"
        )
    return await _batches(endpoint, facts, writer, sql)


async def _purge(endpoint: Endpoint, facts: SeedFacts, variant: Variant, writer: Writer) -> int:
    if variant.pivot:
        from .seed import field_id

        fid = field_id(facts.t1, LEAD, "t24")
        sql = (
            f"{_BATCH}, d AS (DELETE FROM studio.record_values_t v USING b WHERE v.tenant_id = $1"
            f" AND v.record_id = b.id AND v.field_id = '{fid}'::uuid)"
            " SELECT created_at, id FROM b ORDER BY created_at, id LIMIT 1"
        )
    else:
        sql = (
            f"{_BATCH}, u AS (UPDATE studio.records r SET t24 = NULL FROM b"
            " WHERE r.tenant_id = $1 AND r.id = b.id AND r.t24 IS NOT NULL)"
            " SELECT created_at, id FROM b ORDER BY created_at, id LIMIT 1"
        )
    batches = await _batches(endpoint, facts, writer, sql)
    # The verified probe of ADR-0107 decision 5: no value remains (index-backed).
    conn = await endpoint.connect("app")
    try:
        async with scoped(
            conn, facts.t1.tenant_id, writer.user, writer.actor_kind, workspace_scope="tenant"
        ):
            probe = (
                "SELECT 1 FROM studio.records WHERE tenant_id = $1 AND object_id = $2 AND t24 IS"
                " NOT NULL"
                " AND deleted_at IS NULL LIMIT 1"
                if not variant.pivot
                else "SELECT 1 FROM studio.record_values_t WHERE tenant_id = $1 AND object_id = $2"
                " LIMIT 1"
            )
            left = await conn.fetchval(probe, facts.t1.tenant_id, facts.t1.object_id(LEAD))
    finally:
        await conn.close()
    if left is not None and not variant.pivot:
        raise RuntimeError("purge left a value in t24")
    return batches


# -------------------------------------------------------------------- R9.12 --
async def campaign_children(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
) -> None:
    """32 writers create children of the Campaign that already has `campaign_children` of them."""
    scale = facts.scale
    campaign = facts.campaign_id()
    rec = Recorder(limit=_limits(report))
    stop = asyncio.Event()
    longest = 0.0
    mon = await endpoint.connect("admin")

    async def sampler() -> None:
        nonlocal longest
        while not stop.is_set():
            waited = await mon.fetchval(
                "SELECT max(extract(epoch FROM clock_timestamp() - query_start)) * 1000 FROM"
                " pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
            if waited is not None:
                longest = max(longest, float(waited))
            await asyncio.sleep(0.005)

    async def writer_task(no: int) -> None:
        conn = await endpoint.connect("app")
        rng = random.Random(900 + no)
        try:
            for _ in range(scale.campaign_creates_per_writer):
                await timed(
                    rec,
                    "campaign",
                    path.create(conn, writer, facts.t1, LEAD, rng, {"m01": campaign}),
                )
        finally:
            await conn.close()

    watch = asyncio.create_task(sampler())
    await asyncio.gather(*(writer_task(i) for i in range(scale.campaign_writers)))
    stop.set()
    await watch
    await mon.close()
    report.add_p95(
        "R9.12",
        "campaign_create_p95",
        variant.name,
        modulus,
        rec.samples["campaign"],
        "campaign_create_p95_ms",
        f"{scale.campaign_writers} người ghi, Campaign có {scale.campaign_children} con"
        + (f"; {_errors(rec, 'campaign')}" if rec.errors else ""),
    )
    report.add(
        Row(
            "R9.12",
            "lock_wait_max_ms",
            variant.name,
            modulus,
            round(longest, 2),
            "ms",
            "lock_wait_max_ms",
            note="lớn nhất của now() - query_start ở backend đang chờ Lock, lấy mẫu 5 ms (cận"
            " trên)",
        )
    )


# ----------------------------------------------------- the kept measurements --
async def kept_measurements(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
) -> None:
    """Step 5's "giữ các phép đo cũ", once, on A1 at modulus 8."""
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    rng = random.Random(21)
    app = await endpoint.connect("app")
    mig = await endpoint.connect("migrator")
    try:
        # 1. Vietnamese order under RLS, and the index the name page uses.
        names = ["Đạt", "Bình", "Ân", "Ánh", "An"]
        for n in names:
            await path.create(app, writer, t1, NAMES_OBJECT, rng, name=n)
        async with scoped(app, t1.tenant_id, company.principal, "user"):
            got = [
                r[0]
                for r in await app.fetch(
                    "SELECT name FROM studio.records WHERE tenant_id = $1 AND object_id = $2 AND"
                    " name = ANY($3::text[])"
                    " ORDER BY name, id",
                    t1.tenant_id,
                    t1.object_id(NAMES_OBJECT),
                    names,
                )
            ]
        report.info.append(
            f"ORDER BY name dưới RLS trả: {', '.join(got)}"
            f" ({'đúng' if got == ['An', 'Ánh', 'Ân', 'Bình', 'Đạt'] else 'SAI'} thứ tự)"
        )
        sql = page_sql("name", False)
        text = await explain(
            app, (t1.tenant_id, company.principal, "user"), sql, t1.tenant_id, t1.object_id(LEAD)
        )
        claim = report.claim(
            claim_from("R9.1 ORDER BY name dưới RLS", variant.name, modulus, sql, text)
        )
        report.info.append(
            f"ORDER BY name: {claim.statement}; Sort trên cả tập khớp: "
            f"{'có' if claim.sort_over_match_set else 'không'}"
        )
        # 2. InitPlan against the per-row setting read of the 0001 baseline.
        for form, tenant_expr in (
            ("InitPlan", TENANT),
            ("đọc setting theo từng dòng", TENANT_PER_ROW),
        ):
            if tenant_expr != TENANT:
                await _replace_policies(mig, variant, modulus, tenant_expr)
            rec = Recorder(limit=_limits(report))
            pool = (await _ids(endpoint, company, facts, rng))[:1000]
            for i in range(facts.scale.read_samples):
                await timed(rec, "page", read_page(app, company, t1, None))
                await timed(rec, "get", read_get(app, company, t1, pool[i % len(pool)]))
            text = await explain(
                app,
                (t1.tenant_id, company.principal, "user"),
                page_sql("created", False),
                t1.tenant_id,
                t1.object_id(LEAD),
            )
            report.claim(
                claim_from(
                    f"policy {form}: trang đầu company",
                    variant.name,
                    modulus,
                    page_sql("created", False),
                    text,
                )
            )
            report.info.append(
                f"policy {form}: trang đầu p95 {percentile(rec.samples['page'], 0.95):.2f} ms, GET"
                " p95"
                f" {percentile(rec.samples['get'], 0.95):.2f} ms ({facts.scale.read_samples} mẫu"
                " mỗi loại, một phiên)"
            )
        await _replace_policies(mig, variant, modulus, TENANT)
        # 3. The advisory lock per write.
        rec = Recorder(limit=_limits(report))
        for _ in range(facts.scale.read_samples):

            async def locked() -> None:
                async with scoped(app, t1.tenant_id, writer.user, writer.actor_kind):
                    await app.execute(
                        LOCK_SQL,
                        t1.tenant_id,
                        t1.object_id(LEAD),
                    )

            async def bare() -> None:
                async with scoped(app, t1.tenant_id, writer.user, writer.actor_kind):
                    await app.execute("SELECT 1")

            await timed(rec, "lock", locked())
            await timed(rec, "bare", bare())
        no_lock = WritePath(variant, facts, with_lock=False)
        for _ in range(facts.scale.read_samples):
            await timed(rec, "create_lock", path.create(app, writer, t1, LEAD, rng))
            await timed(rec, "create_no_lock", no_lock.create(app, writer, t1, LEAD, rng))
        report.info.append(
            "pg_advisory_xact_lock_shared trên (công ty, đối tượng): giao dịch có khóa p50/p95"
            f" {_p50_p95(rec.samples['lock'])} ms, không khóa"
            f" {_p50_p95(rec.samples['bare'])} ms; tạo bản ghi"
            f" có khóa p95 {percentile(rec.samples['create_lock'], 0.95):.2f} ms, không khóa"
            f" {percentile(rec.samples['create_no_lock'], 0.95):.2f} ms"
        )
        # 4. INSERT ... ON CONFLICT on a partial UNIQUE under per-command policies.
        report.info += await _upsert(app, facts, writer)
        # 5. The updated_at trigger on the parent, for a partition's row.
        report.info.append(await _trigger(app, mig, facts, writer))
        # 6. unaccent and the generated COLLATE "C" column.
        report.info += await _unaccent(mig, variant)
        # 7. Counting records for the storage quota.
        report.info += await _counting(endpoint, mig, facts, variant, writer)
        # 8. JSONB: one EXPLAIN under dw_app and why it is rejected.
        report.info += await _jsonb(app, mig, report, facts, variant, modulus)
    finally:
        await app.close()
        await mig.close()


def _p50_p95(samples: list[float]) -> str:
    return f"{percentile(samples, 0.5):.3f}/{percentile(samples, 0.95):.3f}"


async def _replace_policies(
    mig: asyncpg.Connection, variant: Variant, modulus: int, tenant_expr: str
) -> None:
    for table in ["studio.records", *partitions("studio.records", modulus)]:
        short = table.split(".")[1]
        for suffix in ("", "_select", "_insert", "_update", "_delete"):
            name = f"tenant_isolation_{short}" if suffix == "" else f"record_access_{short}{suffix}"
            await mig.execute(f"DROP POLICY IF EXISTS {name} ON {table}")
        for statement in record_policies(table, short, variant.w2):
            if statement.startswith("CREATE POLICY"):
                await mig.execute(statement.replace(TENANT, tenant_expr))


async def _upsert(app: asyncpg.Connection, facts: SeedFacts, writer: Writer) -> list[str]:
    t1 = facts.t1
    sql = (
        "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind, owner_id,"
        " name, data, u01,"
        " created_by, updated_by) VALUES ($1, $2, $3, $4, 'user', $5, 'Upsert', '{}'::jsonb, $6,"
        " $5, $5)"
        " ON CONFLICT (tenant_id, object_id, u01) WHERE u01 IS NOT NULL AND deleted_at IS NULL"
        " DO UPDATE SET data = studio.records.data || jsonb_build_object('lan', 2),"
        " version = studio.records.version + 1 RETURNING version, version = 1 AS inserted"
    )
    out = []
    from .workload import uuid7

    # The common `(xmax = 0) AS inserted` idiom, once: on a partitioned table
    # PostgreSQL 16 refuses it, which RecordService has to know (tiny run 2/11).
    try:
        async with scoped(app, t1.tenant_id, writer.user, writer.actor_kind):
            await app.fetchrow(
                sql.replace("version = 1 AS inserted", "(xmax = 0) AS inserted"),
                uuid7(),
                t1.tenant_id,
                t1.object_id(LEAD),
                t1.workspace(0),
                writer.user,
                "upsert-bench-xmax",
            )
        out.append("ON CONFLICT với RETURNING (xmax = 0): chạy được")
    except asyncpg.PostgresError as exc:
        out.append(
            "ON CONFLICT với RETURNING (xmax = 0) trên bảng partition: lỗi nguyên văn:"
            f" {exc}; thêm hay sửa đọc từ `version = 1`"
        )
    for attempt in (1, 2):
        try:
            async with scoped(app, t1.tenant_id, writer.user, writer.actor_kind):
                row = await app.fetchrow(
                    sql,
                    uuid7(),
                    t1.tenant_id,
                    t1.object_id(LEAD),
                    t1.workspace(0),
                    writer.user,
                    "upsert-bench-1",
                )
            out.append(
                f"ON CONFLICT ... DO UPDATE lần {attempt} dưới policy theo lệnh: chạy được,"
                f" version {row['version']}, {'thêm mới' if row['inserted'] else 'cập nhật'}"
            )
        except asyncpg.PostgresError as exc:
            out.append(f"ON CONFLICT lần {attempt}: lỗi nguyên văn: {exc}")
    return out


async def _trigger(
    app: asyncpg.Connection, mig: asyncpg.Connection, facts: SeedFacts, writer: Writer
) -> str:
    t1 = facts.t1
    rid = t1.record_id(10)  # a mkt_lead (10 % 5 == 0)
    before = await mig.fetchval(
        "SELECT updated_at FROM studio.records WHERE tenant_id = $1 AND id = $2", t1.tenant_id, rid
    )
    async with scoped(app, t1.tenant_id, writer.user, writer.actor_kind):
        await app.execute(
            "UPDATE studio.records SET data = data || '{\"x\": 1}' WHERE tenant_id = $1 AND id ="
            " $2",
            t1.tenant_id,
            rid,
        )
    touched = await mig.fetchval(
        "SELECT updated_at FROM studio.records WHERE tenant_id = $1 AND id = $2", t1.tenant_id, rid
    )
    async with scoped(app, t1.tenant_id, writer.user, writer.actor_kind):
        await app.execute(
            "UPDATE studio.records SET updated_at = '2001-02-03 04:05:06+00' WHERE tenant_id = $1"
            " AND id = $2",
            t1.tenant_id,
            rid,
        )
    stated = await mig.fetchval(
        "SELECT updated_at FROM studio.records WHERE tenant_id = $1 AND id = $2", t1.tenant_id, rid
    )
    part = await mig.fetchval(
        "SELECT tableoid::regclass::text FROM studio.records WHERE tenant_id = $1 AND id = $2",
        t1.tenant_id,
        rid,
    )
    return (
        f"trigger platform.touch_updated_at() trên bảng cha, dòng ở {part}: không nêu updated_at → "
        f"{'đổi' if touched != before else 'KHÔNG đổi'} ({before} → {touched}); nêu 2001-02-03 → "
        f"{'giữ giá trị câu lệnh' if stated.year == 2001 else 'KHÔNG giữ: ' + str(stated)}"
    )


async def _unaccent(mig: asyncpg.Connection, variant: Variant) -> list[str]:
    out = []
    try:
        version = await mig.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'unaccent'"
        )
        out.append(
            f"CREATE EXTENSION unaccent bằng dw_migrator: chạy được trong DDL của {variant.name}"
            f" (unaccent {version}); CI: không chạy ở đây, cùng image và cùng tệp compose"
            " (.github/workflows/ci.yml:254)"
        )
        key = await mig.fetchval("SELECT studio.search_key('Đạt Ánh Nguyễn')")
        collation = await mig.fetchval(
            "SELECT collname FROM pg_attribute a JOIN pg_collation c ON c.oid = a.attcollation"
            " WHERE attrelid = 'studio.records'::regclass AND attname = 'name_key'"
        )
        gen = await mig.fetchval(
            "SELECT attgenerated FROM pg_attribute WHERE attrelid = 'studio.records'::regclass AND"
            " attname = 'name_key'"
        )
        out.append(
            f'cột sinh name_key STORED từ hàm IMMUTABLE studio.search_key, COLLATE "{collation}",'
            f" attgenerated '{gen}': chạy được; search_key('Đạt Ánh Nguyễn') = '{key}'"
        )
    except asyncpg.PostgresError as exc:
        out.append(f"unaccent / cột sinh: lỗi nguyên văn: {exc}")
    return out


async def _counting(
    endpoint: Endpoint, mig: asyncpg.Connection, facts: SeedFacts, variant: Variant, writer: Writer
) -> list[str]:
    t1 = facts.t1
    part = await t1_partition_name(mig, facts, "studio.records")
    reltuples = await mig.fetchval(
        "SELECT reltuples::bigint FROM pg_class WHERE oid = $1::regclass", part
    )
    exact = await mig.fetchval(
        "SELECT count(*) FROM studio.records WHERE tenant_id = $1", t1.tenant_id
    )
    tenants_in = await mig.fetchval(f"SELECT count(DISTINCT tenant_id) FROM {part}")
    await mig.execute(
        "CREATE TABLE IF NOT EXISTS studio.bench_record_counts (tenant_id uuid NOT NULL, object_id"
        " uuid NOT NULL,"
        " n bigint NOT NULL, PRIMARY KEY (tenant_id, object_id))"
    )
    await mig.execute("ALTER TABLE studio.bench_record_counts ENABLE ROW LEVEL SECURITY")
    await mig.execute("ALTER TABLE studio.bench_record_counts FORCE ROW LEVEL SECURITY")
    await mig.execute("DROP POLICY IF EXISTS t ON studio.bench_record_counts")
    await mig.execute(
        f"CREATE POLICY t ON studio.bench_record_counts USING ({TENANT}) WITH CHECK ({TENANT})"
    )
    await mig.execute("GRANT SELECT, UPDATE ON studio.bench_record_counts TO dw_app")
    await mig.execute(
        "INSERT INTO studio.bench_record_counts SELECT tenant_id, object_id, count(*) FROM"
        " studio.records"
        " GROUP BY 1, 2 ON CONFLICT DO NOTHING"
    )
    counted = WritePath(variant, facts, count_rows=True)
    plain = WritePath(variant, facts)
    rec = Recorder()

    async def writers(path: WritePath, name: str) -> None:
        async def one(no: int) -> None:
            conn = await endpoint.connect("app")
            rng = random.Random(no)
            try:
                for _ in range(20):
                    await timed(rec, name, path.create(conn, writer, t1, LEAD, rng))
            finally:
                await conn.close()

        await asyncio.gather(*(one(i) for i in range(32)))

    await writers(plain, "plain")
    await writers(counted, "counted")
    return [
        f"đếm bản ghi cho hạn mức: reltuples của {part} = {reltuples}, đếm đúng của T1 = {exact};"
        f" partition chứa {tenants_in} tenant nên reltuples không tách được T1 (sai"
        f" {abs(reltuples - exact) / max(1, exact):.1%})",
        f"dòng bộ đếm (UPDATE một dòng mỗi lần tạo, 32 người ghi trên một đối tượng): tạo p95"
        f" {percentile(rec.samples['counted'], 0.95):.2f} ms, max"
        f" {max(rec.samples['counted']):.2f} ms; không bộ đếm"
        f" p95 {percentile(rec.samples['plain'], 0.95):.2f} ms, max"
        f" {max(rec.samples['plain']):.2f} ms"
        f" ({len(rec.samples['counted'])} mẫu mỗi loại)",
    ]


async def _jsonb(
    app: asyncpg.Connection,
    mig: asyncpg.Connection,
    report: Report,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
) -> list[str]:
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    await mig.execute(
        "CREATE INDEX ix_records_data_gin ON studio.records USING gin (data jsonb_path_ops)"
    )
    await mig.execute("ANALYZE studio.records")
    try:
        sql = (
            "SELECT * FROM studio.records WHERE tenant_id = $1 AND object_id = $2"
            ' AND data @> \'{"nguon": "Zalo"}\'::jsonb AND deleted_at IS NULL'
            " ORDER BY created_at DESC, id DESC LIMIT 50"
        )
        text = await explain(
            app, (t1.tenant_id, company.principal, "user"), sql, t1.tenant_id, t1.object_id(LEAD)
        )
        claim = report.claim(
            claim_from("JSONB lọc trên data dưới dw_app", variant.name, modulus, sql, text)
        )
        leak = await mig.fetch(
            "SELECT proname, proleakproof FROM pg_proc WHERE proname IN ('jsonb_contains',"
            " 'jsonb_object_field_text')"
        )
        uses_gin = "ix_records_data_gin" in claim.indexes
        return [
            f"JSONB: GIN jsonb_path_ops trên data, kế hoạch {'CÓ' if uses_gin else 'không'} dùng nó"
            f" ({claim.statement}); "
            + ", ".join(f"{r[0]} LEAKPROOF={r[1]}" for r in leak)
            + "; lý do loại: hàm so sánh của jsonb không LEAKPROOF nên không chạy trước policy"
        ]
    finally:
        await mig.execute("DROP INDEX studio.ix_records_data_gin")


# ----------------------------------------------------------------- self-check --
async def self_check(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: Variant,
    modulus: int,
    path: WritePath,
    writer: Writer,
    counter: HotCounter = pg_hot_counter,
) -> None:
    """CO27: without A1's btree on updated_at, a data-only update must be HOT sometimes."""
    mig = await endpoint.connect("migrator")
    try:
        await mig.execute("DROP INDEX studio.ix_records_tenant_id_object_id_updated_at")
    finally:
        await mig.close()
    ratio, n = await measure_hot(endpoint, facts, path, writer, facts.scale.hot_updates, counter)
    report.selfchecks.append(
        Row(
            "CO27",
            "hot_ratio_without_updated_at_btree",
            variant.name,
            modulus,
            ratio,
            "",
            note=f"{n} lần sửa chỉ chạm data trên trang đã vacuum",
        )
    )
