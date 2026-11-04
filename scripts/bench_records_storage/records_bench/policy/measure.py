# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""The measurements of record-access/01 step 5, each writing rows into the harness's report.

Every latency is the harness's: the client's wall time of the whole transaction,
settings and the door call included (`Endpoint.after_scope`), an upper bound of
the server's time. Every series is p95 on at least 1,000 samples, warm under the
harness's mixed load and cold after its restart, with p50 and p99 in the note.
"""

from __future__ import annotations

import asyncio
import math
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import asyncpg

from ..cell import log
from ..db import Endpoint, scope_sql, scoped
from ..measure import claim_from, explain
from ..model import ACCOUNT, LEAD, PERSON_COMPANY
from ..report import Report, Row, percentile, series_limit
from ..seed import Profile, SeedFacts
from ..workload import (
    GET_SQL,
    MixedLoad,
    Recorder,
    WritePath,
    Writer,
    lead_cursors,
    page_sql,
    readable_ids,
    run_queue,
    timed,
)
from .variants import PolicyVariant, own_filter

# First page with and without a filter on a typed slot, on mkt_lead (5% of its
# records carry grant keys) and on `account` (0.4%, like every other object);
# the next keyset page; GET; the capped count (ticket step 5).
KINDS = ("page_lead", "page_lead_f", "page_other", "page_other_f", "next", "get", "count")
OTHER = ACCOUNT
SLOT_FILTER = " AND i01 < 100000"
OWN_PROFILES = ("own", "own_sort_slot")
COUNT_SQL = (
    "SELECT count(*) FROM (SELECT 1 FROM studio.records WHERE tenant_id = $1 AND object_id = $2"
    " AND deleted_at IS NULL LIMIT 1001) c"
)
REQ_OF = {
    "page": ("record-access:R9.1", "page_p95_ms"),
    "next": ("record-access:R9.3", "next_page_p95_ms"),
    "get": ("record-access:R9.2", "get_p95_ms"),
    "count": ("record-access:R9.4", "count_p95_ms"),
}
# One principal per name: the agent profile runs as the Toàn công ty person.
SCOPE_PRINCIPALS = (
    "own",
    "team",
    "workspace_1",
    "workspace_40",
    "company",
    "public_read",
    "manager_50",
    "manager_500",
    "manager_5000",
    "share_recipient",
    "service_account",
)
WRITE_METRICS = (
    "assign_p95",
    "share_p95",
    "delete_p95",
    "door_valid_p95",
    "recompute_total_4",
    "recompute_total_1",
    "stale_reads_after_revoke",
)
SOAK_METRICS = ("write_create_soak", "write_update_slot_soak")
ASSIGN_OBJECT = 4
SHARE_OBJECT = 6
REVOKE_PERSON = 100  # no profile's principal
REVOKE_OBJECT = 5


def req_of(kind: str) -> tuple[str, str]:
    return REQ_OF["page"] if kind.startswith("page_") else REQ_OF[kind]


def cell_metrics(profiles: list[str], soak: bool) -> list[str]:
    """Every number one policy cell owes the matrix of steps 2 and 5."""
    out = [f"{k}_{t}:{p}" for p in profiles for k in KINDS for t in ("warm", "cold")]
    out += [f"scope_compute:{n}" for n in SCOPE_PRINCIPALS]
    out += list(WRITE_METRICS)
    if soak:
        out += list(SOAK_METRICS)
    return out


def policy_profiles(facts: SeedFacts) -> list[Profile]:
    """The harness's profiles; the agent runs as the Toàn công ty person (step 2)."""
    company = facts.t1.person(PERSON_COMPANY)
    return [
        replace(p, principal=company) if p.name == "agent_one_object" else p for p in facts.profiles
    ]


def spread(samples: list[float]) -> str:
    if not samples:
        return ""
    return f"p50 {percentile(samples, 0.5):.2f} ms, p99 {percentile(samples, 0.99):.2f} ms"


def _note(rec: Recorder, name: str) -> str:
    errors = rec.errors.get(name)
    tail = f"; {errors} lỗi, đầu: {rec.first_error[name]}" if errors else ""
    return spread(rec.samples.get(name, [])) + tail


def _limits(report: Report) -> Callable[[str], float | None]:
    return lambda series: series_limit(report.thresholds, series)


# ------------------------------------------------------------------ reads --
@dataclass
class Reader:
    """The read kinds of a policy cell, over the harness's page builder."""

    variant: PolicyVariant
    facts: SeedFacts
    cursors: list[tuple[datetime, uuid.UUID]]
    pools: dict[str, list[uuid.UUID]]

    def _own(self, profile: Profile, args: list[Any]) -> str:
        if profile.name not in OWN_PROFILES:
            return ""
        if self.variant.hint:
            return own_filter(self.variant, 0)
        args.append(profile.principal)
        return own_filter(self.variant, len(args))

    def query(self, profile: Profile, kind: str, rng: random.Random) -> tuple[str, list[Any]]:
        t1 = self.facts.t1
        if kind == "get":
            return GET_SQL, [t1.tenant_id, rng.choice(self.pools[profile.name])]
        if kind == "count":
            return COUNT_SQL, [t1.tenant_id, t1.object_id(LEAD)]
        if kind == "next":
            created, rid = rng.choice(self.cursors)
            args: list[Any] = [t1.tenant_id, t1.object_id(LEAD), created, rid]
            return page_sql("created", True, self._own(profile, args)), args
        obj = LEAD if kind.startswith("page_lead") else OTHER
        args = [t1.tenant_id, t1.object_id(obj)]
        predicate = (SLOT_FILTER if kind.endswith("_f") else "") + self._own(profile, args)
        return page_sql(profile.order, False, predicate), args

    async def op(
        self, conn: asyncpg.Connection, profile: Profile, kind: str, rng: random.Random
    ) -> int:
        sql, args = self.query(profile, kind, rng)
        async with scoped(conn, self.facts.t1.tenant_id, profile.principal, profile.actor_kind):
            rows = await conn.fetch(sql, *args)
        return len(rows)


async def reads(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    path: WritePath,
    writer: Writer,
    restart: Callable[[], Awaitable[None]] | None,
    profiles: list[Profile],
) -> None:
    """Warm under the harness's mixed load, then cold after its restart (step 5)."""
    scale, t1 = facts.scale, facts.t1
    rng = random.Random(42)
    writer_profile = Profile("writer", 0, writer.user, writer.actor_kind, LEAD)
    update_pool = await readable_ids(endpoint, writer_profile, t1, 2 * scale.read_samples, rng)
    pools: dict[str, list[uuid.UUID]] = {}
    for profile in profiles:
        ids = await readable_ids(endpoint, profile, t1, 3 * scale.read_samples, rng)
        if not ids:
            report.info.append(
                f"{variant.name} m{modulus}: {profile.name} đọc được 0 bản ghi; GET nhắm bản ghi"
                " nó không đọc được"
            )
            ids = update_pool
        pools[profile.name] = ids
    warm_pools = {n: ids[: max(1, len(ids) // 3)] for n, ids in pools.items()}
    cold_pools = {n: ids[len(warm_pools[n]) :] or ids for n, ids in pools.items()}
    cursors = await lead_cursors(endpoint, t1, 2 * scale.read_samples * len(profiles) + 100)
    half = len(cursors) // 2
    warm = Reader(variant, facts, cursors[:half], warm_pools)
    load = MixedLoad(
        endpoint,
        facts,
        path,
        writer,
        profiles,
        warm_pools,
        update_pool,
        recorder=Recorder(limit=_limits(report)),
        read_target=scale.read_samples,
        read_kinds=KINDS,
        read_op=warm.op,
    )
    names = ", ".join(p.name for p in profiles)
    log(f"{variant.name} m{modulus}: warm mixed load, {scale.sessions} sessions ({names})")
    rec = await load.until_sampled(scale.sessions, timeout_s=1800)
    _rows(report, variant, modulus, profiles, rec, "warm")
    if restart is None:
        report.info.append(f"{variant.name} m{modulus}: không có container riêng, không chạy nguội")
        return
    log(f"{variant.name} m{modulus}: cold run (restart + drop caches)")
    await restart()
    cold_reader = Reader(variant, facts, cursors[half:], cold_pools)
    cold = Recorder(limit=_limits(report))
    jobs: list[tuple[str, Callable[[asyncpg.Connection], Awaitable[Any]]]] = []
    for profile in profiles:
        for kind in KINDS:
            for i in range(scale.read_samples):
                jobs.append((f"{kind}_cold:{profile.name}", _job(cold_reader, profile, kind, i)))
    rng.shuffle(jobs)
    await run_queue(endpoint, scale.sessions, jobs, cold)
    _rows(report, variant, modulus, profiles, cold, "cold")


def _job(
    reader: Reader, profile: Profile, kind: str, i: int
) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    rng = random.Random(i * 7919 + len(kind))
    return lambda conn: reader.op(conn, profile, kind, rng)


def _rows(
    report: Report,
    variant: PolicyVariant,
    modulus: int,
    profiles: list[Profile],
    rec: Recorder,
    temp: str,
) -> None:
    for profile in profiles:
        for kind in KINDS:
            name = f"{kind}_{temp}:{profile.name}"
            req, key = req_of(kind)
            report.add_p95(
                req,
                name,
                variant.name,
                modulus,
                rec.samples.get(name, []),
                key,
                " ".join(x for x in (profile.note, _note(rec, name)) if x),
            )


async def explains(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    profiles: list[Profile],
) -> None:
    """One EXPLAIN (ANALYZE, BUFFERS) per profile and read kind, carried by its claim."""
    t1 = facts.t1
    rng = random.Random(5)
    cursors = await lead_cursors(endpoint, t1, 10)
    pools = {
        p.name: await readable_ids(endpoint, p, t1, 5, rng) or [t1.record_id(1)] for p in profiles
    }
    reader = Reader(variant, facts, cursors, pools)
    conn = await endpoint.connect("app")
    try:
        for profile in profiles:
            for kind in KINDS:
                sql, args = reader.query(profile, kind, rng)
                text = await explain(
                    conn, (t1.tenant_id, profile.principal, profile.actor_kind), sql, *args
                )
                report.claim(claim_from(f"{kind} {profile.name}", variant.name, modulus, sql, text))
    finally:
        await conn.close()


# ----------------------------------------------------------------- writes --
async def writes(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    path: WritePath,
    writer: Writer,
) -> None:
    """Assign and share through the definer stand-ins, and DELETE, in the pipeline's transaction."""
    scale, t1, org = facts.scale, facts.t1, facts.org
    n = scale.read_samples
    rng = random.Random(9)
    company = Writer(t1.tenant_id, t1.person(PERSON_COMPANY), "user")
    mig = await endpoint.connect("migrator")
    try:
        assign_ids = [
            r["id"]
            for r in await mig.fetch(
                "SELECT id FROM studio.records WHERE tenant_id = $1 AND object_id = $2"
                " ORDER BY id LIMIT $3",
                t1.tenant_id,
                t1.object_id(ASSIGN_OBJECT),
                n,
            )
        ]
        share_ids = [
            r["id"]
            for r in await mig.fetch(
                "SELECT id FROM studio.records WHERE tenant_id = $1 AND object_id = $2"
                " AND cardinality(read_grants) < 150 ORDER BY id LIMIT $3",
                t1.tenant_id,
                t1.object_id(SHARE_OBJECT),
                n,
            )
        ]
    finally:
        await mig.close()
    refused: dict[str, int] = {"assign_p95": 0, "share_p95": 0, "delete_p95": 0}

    def counted(name: str, op: Awaitable[Any]) -> Awaitable[Any]:
        async def run() -> Any:
            result = await op
            if result is None or result is False:
                refused[name] += 1
            return result

        return run()

    def assign(rid: uuid.UUID) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
        person = rng.randrange(org.people)
        owner, ws = t1.person(person), t1.workspace(org.home_workspace(person))
        return lambda conn: counted(
            "assign_p95",
            path.definer_write(
                conn,
                company,
                rid,
                t1.object_id(ASSIGN_OBJECT),
                "assigned",
                ["owner_id", "workspace_id"],
                "SELECT * FROM studio.assign_record($1, $2, $3)",
                rid,
                owner,
                ws,
            ),
        )

    def share(rid: uuid.UUID) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
        target = t1.person(rng.randrange(org.people))
        return lambda conn: counted(
            "share_p95",
            path.definer_write(
                conn,
                company,
                rid,
                t1.object_id(SHARE_OBJECT),
                "shared",
                ["read_grants"],
                "SELECT * FROM studio.share_record($1, $2, 'read', NULL)",
                rid,
                target,
            ),
        )

    rec = Recorder(limit=_limits(report))
    # The import's concurrency, not the load's 50: at 50 sessions every write meets
    # the 6,400-slot lock table (custom-objects/01's finding) and measures nothing else.
    sessions = scale.import_sessions
    await run_queue(endpoint, sessions, [("assign_p95", assign(r)) for r in assign_ids], rec)
    await run_queue(endpoint, sessions, [("share_p95", share(r)) for r in share_ids], rec)
    # DELETE: the writer's own new records, created first and not timed.
    created: list[uuid.UUID] = []
    conn = await endpoint.connect("app")
    try:
        for _ in range(n):
            created.append(await path.create(conn, writer, t1, ASSIGN_OBJECT, rng))
    finally:
        await conn.close()

    def delete(rid: uuid.UUID) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
        return lambda conn: counted(
            "delete_p95", path.delete(conn, writer, rid, t1.object_id(ASSIGN_OBJECT))
        )

    await run_queue(endpoint, sessions, [("delete_p95", delete(r)) for r in created], rec)
    for name, req, key in (
        ("assign_p95", "record-access:R9.6", "assign_p95_ms"),
        ("share_p95", "record-access:R9.6", None),
        ("delete_p95", "record-access:bước 5", None),
    ):
        note = _note(rec, name) + (f"; {refused[name]} lần không có tầm" if refused[name] else "")
        report.add_p95(req, name, variant.name, modulus, rec.samples.get(name, []), key, note)
        if refused[name]:
            report.check_failures.append(
                f"{variant.name} m{modulus}: {name}: {refused[name]} lần bị từ chối dù chủ thể"
                " có tầm: phép đo đi đường từ chối"
            )


# ------------------------------------------------------------ the ledger --
async def warm_ledger(endpoint: Endpoint, sessions: int = 8) -> int:
    """Every person of every tenant through the door once: the ledger rows (step 3)."""
    mig = await endpoint.connect("migrator")
    try:
        people = [
            (r["tenant_id"], r["id"])
            for r in await mig.fetch(
                "SELECT tenant_id, id FROM studio.bench_people ORDER BY tenant_id, id"
            )
        ]
    finally:
        await mig.close()
    queue = iter(people)

    async def worker() -> None:
        conn = await endpoint.connect("app")
        try:
            for tenant, person in queue:
                async with scoped(conn, tenant, person, "user"):
                    pass
        finally:
            await conn.close()

    await asyncio.gather(*(worker() for _ in range(sessions)))
    return len(people)


async def set_phase(endpoint: Endpoint, facts: SeedFacts, default_access: str) -> None:
    """mkt_lead's default_access, changed as a version publish does: one UPDATE, one epoch bump."""
    mig = await endpoint.connect("migrator")
    try:
        await mig.execute(
            "UPDATE studio.object_defs SET default_access = $3 WHERE tenant_id = $1 AND id = $2",
            facts.t1.tenant_id,
            facts.t1.object_id(LEAD),
            default_access,
        )
    finally:
        await mig.close()


def _principals(profiles: list[Profile]) -> list[tuple[str, uuid.UUID]]:
    seen: dict[uuid.UUID, str] = {}
    for p in profiles:
        if p.name in SCOPE_PRINCIPALS and p.principal not in seen:
            seen[p.principal] = p.name
    return [(name, principal) for principal, name in seen.items()]


async def scope_compute(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    profiles: list[Profile],
) -> None:
    """R9.7: the door on a stale row, in a transaction of its own, per profile principal."""
    t1, n = facts.t1, facts.scale.read_samples
    rec = Recorder()

    async def one(name: str, principal: uuid.UUID) -> None:
        mig = await endpoint.connect("migrator")
        app = await endpoint.connect("app")
        try:
            for _ in range(n):
                await mig.execute(
                    "UPDATE studio.principal_scopes SET state = 'stale', version = version + 1"
                    " WHERE tenant_id = $1 AND principal_id = $2",
                    t1.tenant_id,
                    principal,
                )
                await timed(rec, f"scope_compute:{name}", _door_txn(app, t1.tenant_id, principal))
        finally:
            await mig.close()
            await app.close()

    await asyncio.gather(*(one(name, p) for name, p in _principals(profiles)))
    for name in SCOPE_PRINCIPALS:
        series = f"scope_compute:{name}"
        report.add_p95(
            "record-access:R9.7",
            series,
            variant.name,
            modulus,
            rec.samples.get(series, []),
            "scope_compute_p95_ms",
            _note(rec, series),
        )


async def _door_txn(conn: asyncpg.Connection, tenant: uuid.UUID, principal: uuid.UUID) -> None:
    async with scoped(conn, tenant, principal, "user"):
        pass


async def door_valid(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    profiles: list[Profile],
) -> None:
    """R9.8: the door call alone on a valid row, timed inside a transaction already set."""
    t1, n = facts.t1, facts.scale.read_samples
    principals = [p for _n, p in _principals(profiles)]
    plain = replace(endpoint, after_scope="")
    conn = await plain.connect("app")
    samples: list[float] = []
    try:
        for i in range(n + len(principals)):
            principal = principals[i % len(principals)]
            await conn.execute(scope_sql(t1.tenant_id, principal, "user"))
            started = time.perf_counter()
            await conn.execute("SELECT studio.ensure_principal_scope()")
            if i >= len(principals):  # the first call of each makes its row valid
                samples.append((time.perf_counter() - started) * 1000)
            await conn.execute("COMMIT")
    finally:
        await conn.close()
    report.add_p95(
        "record-access:R9.8",
        "door_valid_p95",
        variant.name,
        modulus,
        samples,
        "door_p95_ms",
        spread(samples) + "; một vòng khứ hồi, trong giao dịch đã gắn setting",
    )


async def recompute(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    load: MixedLoad,
) -> None:
    """R9.9: after one epoch bump, every T1 person's door, four connections then one, under load."""
    t1, org, scale = facts.t1, facts.org, facts.scale
    people = [t1.person(p) for p in range(org.people)]
    for conns in (4, 1):
        mig = await endpoint.connect("migrator")
        try:
            await mig.execute(
                "UPDATE studio.access_epochs SET epoch = epoch + 1 WHERE tenant_id = $1",
                t1.tenant_id,
            )
            stop = asyncio.Event()
            background = asyncio.create_task(
                load.until_stopped(
                    scale.sessions, scale.soak_writes_per_second * 5, f"r99{conns}", stop
                )
            )
            queue = iter(people)
            refused: list[tuple[uuid.UUID, str]] = []
            started = time.monotonic()

            async def worker(
                todo: Iterator[uuid.UUID], failed: list[tuple[uuid.UUID, str]]
            ) -> None:
                conn = await endpoint.connect("app")
                try:
                    for person in todo:
                        try:
                            await _door_txn(conn, t1.tenant_id, person)
                        except asyncpg.PostgresError as exc:
                            # Under the load's lock pressure the server may refuse
                            # a door call (out of shared memory): counted, retried.
                            failed.append((person, f"{type(exc).__name__}: {exc}"))
                finally:
                    await conn.close()

            try:
                await asyncio.gather(*(worker(queue, refused) for _ in range(conns)))
                elapsed = time.monotonic() - started
            finally:
                stop.set()
                await background
            retry = await endpoint.connect("app")
            try:
                for person, _why in refused:
                    await _door_txn(retry, t1.tenant_id, person)
            finally:
                await retry.close()
            # Ledger-agnostic: a principal is valid when every row it has is.
            valid = await mig.fetchval(
                "SELECT count(*) FROM (SELECT s.principal_id FROM studio.principal_scopes s"
                " JOIN studio.access_epochs e ON e.tenant_id = s.tenant_id"
                " WHERE s.tenant_id = $1 AND s.principal_id = ANY ($2::uuid[])"
                " GROUP BY s.principal_id"
                " HAVING bool_and(s.state = 'valid' AND s.epoch = e.epoch)) v",
                t1.tenant_id,
                people,
            )
        finally:
            await mig.close()
        report.add(
            Row(
                "record-access:R9.9",
                f"recompute_total_{conns}",
                variant.name,
                modulus,
                round(elapsed, 2),
                "s",
                "recompute_total_s" if conns == 4 else None,
                note=f"{conns} kết nối, {len(people)} chủ thể, {valid} dòng valid ở epoch mới,"
                " dưới tải hỗn hợp"
                + (
                    f"; {len(refused)} lời gọi cửa bị máy chủ từ chối dưới tải, gọi lại sau tải"
                    f" (đầu: {refused[0][1]})"
                    if refused
                    else ""
                ),
            )
        )
        if valid != len(people):
            report.check_failures.append(
                f"{variant.name} m{modulus}: tính lại {conns} kết nối: {valid}/{len(people)} valid"
            )


async def revocation(
    report: Report, endpoint: Endpoint, facts: SeedFacts, variant: PolicyVariant, modulus: int
) -> None:
    """R9.9: a revocation committed between two statements is seen by the second, every time."""
    t1, org = facts.t1, facts.org
    n = facts.scale.read_samples
    person = t1.person(REVOKE_PERSON)
    obj = t1.object_id(REVOKE_OBJECT)
    key = f"obj.{facts.layouts[REVOKE_OBJECT].api_name}.read"
    home = t1.workspace(org.home_workspace(REVOKE_PERSON))
    probe = (
        "SELECT count(*) FROM (SELECT 1 FROM studio.records WHERE tenant_id = $1 AND object_id = $2"
        " AND owner_id <> $3 LIMIT 1) c"
    )
    grant = (
        "INSERT INTO studio.bench_effective_grants (tenant_id, principal_id, permission_key, depth,"
        " anchor_workspace_id) VALUES ($1, $2, $3, 'tenant', $4)"
    )
    revoke = (
        "DELETE FROM studio.bench_effective_grants WHERE tenant_id = $1 AND principal_id = $2"
        " AND permission_key = $3 AND depth = 'tenant'"
    )
    stale = blind = 0
    mig = await endpoint.connect("migrator")
    app = await endpoint.connect("app")
    try:
        for _ in range(n):
            await mig.execute(grant, t1.tenant_id, person, key, home)
            # The door recomputes in a transaction of its own first: a door that
            # writes the ledger row inside the reading transaction holds its lock,
            # and the revocation's stale mark would wait on it until commit.
            await _door_txn(app, t1.tenant_id, person)
            async with scoped(app, t1.tenant_id, person, "user"):
                before = await app.fetchval(probe, t1.tenant_id, obj, person)
                await mig.execute(revoke, t1.tenant_id, person, key)
                after = await app.fetchval(probe, t1.tenant_id, obj, person)
            blind += before == 0
            stale += after > 0
    finally:
        await mig.close()
        await app.close()
    report.add(
        Row(
            "record-access:R9.9",
            "stale_reads_after_revoke",
            variant.name,
            modulus,
            float(stale),
            "lần",
            "stale_reads_after_revoke",
            n,
            note=f"{n} lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm {n - blind} lần",
        )
    )
    if blind:
        report.check_failures.append(
            f"{variant.name} m{modulus}: kiểm thu hồi mù {blind}/{n} lần: trước thu hồi không thấy"
        )


async def pruning(
    report: Report, endpoint: Endpoint, facts: SeedFacts, variant: PolicyVariant, modulus: int
) -> None:
    """Partition pruning and InitPlans under RESTRICTIVE plus PERMISSIVE, custom and generic."""
    t1 = facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    sql = page_sql("created", False)
    conn = await endpoint.connect("app")
    parts: list[str] = []
    try:
        for mode in ("force_custom_plan", "force_generic_plan"):
            await conn.execute(f"SET plan_cache_mode = {mode}")
            text = await explain(
                conn,
                (t1.tenant_id, company.principal, "user"),
                sql,
                t1.tenant_id,
                t1.object_id(LEAD),
            )
            scanned = sorted(set(re.findall(r"on (records_p\d+)", text)))
            removed = re.findall(r"Subplans Removed: (\d+)", text)
            initplans = len(re.findall(r"InitPlan", text))
            parts.append(
                f"{mode}: partition quét {', '.join(scanned) or '—'}, Subplans Removed"
                f" {', '.join(removed) or '—'}, {initplans} InitPlan"
            )
            report.claim(claim_from(f"cắt partition {mode}", variant.name, modulus, sql, text))
        await conn.execute("RESET plan_cache_mode")
    finally:
        await conn.close()
    report.info.append(f"{variant.name} m{modulus}: " + "; ".join(parts))


async def soak(
    report: Report,
    endpoint: Endpoint,
    facts: SeedFacts,
    variant: PolicyVariant,
    modulus: int,
    path: WritePath,
    writer: Writer,
    reader: Reader,
) -> None:
    """R9.5 under WITH CHECK: the harness's paced soak, creates and one-slot updates (P0 and W)."""
    scale, t1 = facts.scale, facts.t1
    company = next(p for p in facts.profiles if p.name == "company")
    rng = random.Random(77)
    pool = await readable_ids(endpoint, company, t1, 2 * scale.read_samples, rng)
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
        read_kinds=("page_lead",),
        read_op=reader.op,
        slot_updates=True,
    )
    rate_goal = scale.soak_writes_per_second
    log(f"{variant.name} m{modulus}: soak {scale.soak_seconds} s, {rate_goal} w/s")
    started = time.monotonic()
    rec = await load.for_duration(
        scale.sessions, scale.soak_seconds, scale.soak_writes_per_second * 5, f"psoak{modulus}"
    )
    elapsed = time.monotonic() - started
    rate = (rec.count("write_update") + rec.count("write_create")) / max(elapsed, 1e-9)
    for metric, series in (
        ("write_create_soak", "write_create"),
        ("write_update_slot_soak", "write_update"),
    ):
        report.add_p95(
            "record-access:R9.5",
            metric,
            variant.name,
            modulus,
            rec.samples.get(series, []),
            "write_p95_ms",
            f"{_note(rec, series)}; soak {elapsed:.0f} s, {rate:.0f} lần ghi/s"
            f" (mục tiêu {scale.soak_writes_per_second})",
        )


def finite(value: float | None) -> bool:
    return value is not None and not math.isinf(value) and not math.isnan(value)
