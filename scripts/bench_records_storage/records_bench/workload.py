"""The simulated write path, the read queries, and the concurrent load that runs them.

RecordService and `RecordsPort` do not exist yet (custom-objects ticket 03 builds
them), so every write of the load, of the import (R9.10) and of R9.12 runs here:
one `dw_app` transaction holding exactly the write statements of ADR-0107
decision 3's pipeline, in its order (ticket 01 step 4) —
`pg_advisory_xact_lock_shared` on (tenant, object), read `schema_version`, write
`studio.records`, write `studio.record_write_keys` when the command is an update
with a `wf:` key, one `platform.outbox_events` row and one `platform.audit_events`
row. No COPY, no role that bypasses RLS, no statement left out. Ticket 04
measures R9.6 and R9.10 again through the real RecordService.

Latency is the client's wall time of the whole transaction, round trips
included: what the API's database driver would see, an upper bound of the
server's own time.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import asyncpg

from .db import Endpoint, scope_sql, scoped
from .ddl import Variant
from .model import ACCOUNT, CAMPAIGN, LEAD, ObjectLayout, slot_names
from .report import certain_miss
from .seed import (
    FAMILY_NAMES,
    GIVEN_NAMES,
    MIDDLE_NAMES,
    WORDS,
    Profile,
    SeedFacts,
    TenantPlan,
    field_id,
)

PAGE_ORDERS = {
    "created": ("", "created_at DESC, id DESC"),
    "updated": ("", "updated_at DESC, id DESC"),
    "name": ("", "name, id"),
    "slot": (" AND t02 IS NOT NULL", "t02, id"),
}


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    rand = random.getrandbits(74)
    value = (
        (ms << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)


def page_sql(order: str, cursor: bool) -> str:
    extra, order_by = PAGE_ORDERS[order]
    keyset = ""
    if cursor:
        # A keyset page at a cursor no sample has read since the restart: the
        # cold run's unread keys (gate MEDIUM (c)).
        keyset = " AND (created_at, id) < ($3, $4)" if order == "created" else ""
    return (
        "SELECT * FROM studio.records WHERE tenant_id = $1 AND object_id = $2 AND deleted_at IS"
        " NULL"
        f"{extra}{keyset} ORDER BY {order_by} LIMIT 50"
    )


GET_SQL = "SELECT * FROM studio.records WHERE tenant_id = $1 AND id = $2"
# Shared on (tenant, object): a field change takes it exclusively (ADR-0107 decisions 3 and 5).
LOCK_SQL = (
    "SELECT pg_advisory_xact_lock_shared("
    "hashtextextended($1::uuid::text || ':' || $2::uuid::text, 0))"
)


@dataclass
class Recorder:
    samples: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    first_error: dict[str, str] = field(default_factory=dict)
    # Series -> its ms limit, so a series whose miss is certain stops (report.certain_miss).
    limit: Callable[[str], float | None] = field(default=lambda _series: None)

    def add(self, series: str, ms: float) -> None:
        self.samples[series].append(ms)

    def settled(self, series: str, target: int) -> bool:
        if self.count(series) >= target:
            return True
        limit = self.limit(series)
        return limit is not None and certain_miss(self.samples.get(series, []), limit, target)

    def fail(self, series: str, exc: BaseException) -> None:
        self.errors[series] += 1
        self.first_error.setdefault(series, f"{type(exc).__name__}: {exc}")

    def count(self, series: str) -> int:
        return len(self.samples.get(series, []))


async def timed(recorder: Recorder, series: str, op: Awaitable[Any]) -> Any:
    """Await `op` (a coroutine not yet started) and record its wall time under `series`."""
    start = time.perf_counter()
    try:
        result = await op
    except asyncpg.PostgresError as exc:
        # A request the server refused (out of shared memory, statement_timeout,
        # a policy) met no latency bound: it is a sample at infinity, and named.
        recorder.fail(series, exc)
        recorder.add(series, math.inf)
        return None
    except asyncpg.InterfaceError as exc:
        recorder.fail(series, exc)
        return None
    recorder.add(series, (time.perf_counter() - start) * 1000)
    return result


# ---------------------------------------------------------------- the writes --
@dataclass(frozen=True)
class Writer:
    """Who writes, and how: the AI scoring flow, the import, a lane."""

    tenant: uuid.UUID
    user: uuid.UUID
    actor_kind: str


@dataclass
class WritePath:
    variant: Variant
    facts: SeedFacts
    with_lock: bool = True
    count_rows: bool = False  # the storage-quota counter row (legacy measurement)

    def __post_init__(self) -> None:
        self.layouts = {lay.index: lay for lay in self.facts.layouts}

    async def _head(
        self, conn: asyncpg.Connection, tenant: uuid.UUID, object_id: uuid.UUID
    ) -> None:
        if self.with_lock:
            await conn.execute(
                LOCK_SQL,
                tenant,
                object_id,
            )
        await conn.fetchval(
            "SELECT schema_version FROM studio.object_defs WHERE tenant_id = $1 AND id = $2",
            tenant,
            object_id,
        )

    async def _tail(
        self,
        conn: asyncpg.Connection,
        writer: Writer,
        record_id: uuid.UUID,
        object_id: uuid.UUID,
        workspace_id: uuid.UUID,
        version: int,
        action: str,
        fields: list[str],
    ) -> None:
        payload = json.dumps({"object_id": str(object_id), "version": version, "fields": fields})
        await conn.execute(
            "INSERT INTO platform.outbox_events (id, tenant_id, workspace_id, event_type,"
            " schema_version,"
            " aggregate_id, payload, actor_id, occurred_at) VALUES ($1, $2, $3, $4, '1', $5,"
            " $6::jsonb, $7, now())",
            uuid7(),
            writer.tenant,
            workspace_id,
            f"studio.record.{action}",
            record_id,
            payload,
            writer.user,
        )
        await conn.execute(
            "INSERT INTO platform.audit_events (id, tenant_id, workspace_id, actor_id, action,"
            " resource_type,"
            " resource_id, details, occurred_at) VALUES ($1, $2, $3, $4, $5, 'studio.record', $6,"
            " $7::jsonb, now())",
            uuid7(),
            writer.tenant,
            workspace_id,
            writer.user,
            f"studio.record.{action}",
            str(record_id),
            payload,
        )

    async def update_data(
        self,
        conn: asyncpg.Connection,
        writer: Writer,
        record_id: uuid.UUID,
        object_id: uuid.UUID,
        score: int,
        write_key: str | None,
    ) -> int | None:
        """The AI scoring flow: its field `diem_ai` lives in `data`, so only `data` changes."""
        async with scoped(conn, writer.tenant, writer.user, writer.actor_kind):
            await self._head(conn, writer.tenant, object_id)
            row = await conn.fetchrow(
                "UPDATE studio.records SET data = data || jsonb_build_object('diem_ai', $3::int),"
                " version = version + 1, updated_by = $4"
                " WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL RETURNING version,"
                " workspace_id",
                writer.tenant,
                record_id,
                score,
                writer.user,
            )
            if row is None:
                return None
            if write_key is not None:
                await conn.execute(
                    "INSERT INTO studio.record_write_keys (tenant_id, write_key, record_id, op,"
                    " version, actor_id)"
                    " VALUES ($1, $2, $3, 'update', $4, $5)",
                    writer.tenant,
                    write_key,
                    record_id,
                    row["version"],
                    writer.user,
                )
            await self._tail(
                conn,
                writer,
                record_id,
                object_id,
                row["workspace_id"],
                row["version"],
                "updated",
                ["diem_ai"],
            )
            return int(row["version"])

    def new_values(
        self, plan: TenantPlan, layout: ObjectLayout, rng: random.Random
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for slot in layout.used_slots(self.variant.families):
            fam = slot[0]
            if rng.random() < 0.1:
                continue
            if fam == "t":
                values[slot] = f"{rng.choice(WORDS)} {rng.randrange(500)}"
            elif fam == "u":
                values[slot] = f"{slot}-n-{uuid7().hex}"
            elif fam == "i":
                values[slot] = rng.randrange(1_000_000)
            elif fam == "f":
                values[slot] = rng.randrange(10_000_000) / 100
            elif fam == "d":
                values[slot] = datetime(
                    2018 + rng.randrange(8), 1 + rng.randrange(12), 1 + rng.randrange(28)
                ).date()
            elif fam == "z":
                values[slot] = datetime.now(UTC)
            elif fam == "b":
                values[slot] = rng.random() < 0.5
            elif fam == "l":
                k = rng.randrange(max(1, plan.records // (plan.objects - 1) - 2))
                n = k * (plan.objects - 1) + (ACCOUNT - 1)
                values[slot] = plan.record_id(n + (plan.objects - 1) if n % 5 == 0 else n)
            elif fam == "m":
                j = 2 + rng.randrange(plan.campaign_span)
                j += 1 if j % 5 == 0 else 0
                values[slot] = plan.record_id(j * (plan.objects - 1))
        return values

    async def create(
        self,
        conn: asyncpg.Connection,
        writer: Writer,
        plan: TenantPlan,
        object_index: int,
        rng: random.Random,
        overrides: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> uuid.UUID:
        layout = self.layouts[object_index]
        object_id = plan.object_id(object_index)
        values = self.new_values(plan, layout, rng)
        values.update(overrides or {})
        record_id = uuid7()
        workspace_id = plan.workspace(0)
        name = (
            name
            or f"{rng.choice(FAMILY_NAMES)} {rng.choice(MIDDLE_NAMES)} {rng.choice(GIVEN_NAMES)}"
        )
        data = json.dumps(
            {"f90": f"ghi chú {rng.choice(WORDS)}", "f91": rng.randrange(1000), "diem_ai": 0}
        )
        slot_values = {} if self.variant.pivot else values
        cols = [
            "id",
            "tenant_id",
            "object_id",
            "workspace_id",
            "owner_kind",
            "owner_id",
            "name",
            "data",
            *slot_values,
            "created_by",
            "updated_by",
        ]
        args = [
            record_id,
            writer.tenant,
            object_id,
            workspace_id,
            "user",
            writer.user,
            name,
            data,
            *slot_values.values(),
            writer.user,
            writer.user,
        ]
        placeholders = ", ".join(
            f"${i}" + ("::jsonb" if c == "data" else "") for i, c in enumerate(cols, 1)
        )
        async with scoped(conn, writer.tenant, writer.user, writer.actor_kind):
            await self._head(conn, writer.tenant, object_id)
            await conn.execute(
                f"INSERT INTO studio.records ({', '.join(cols)}) VALUES ({placeholders})", *args
            )
            if self.variant.pivot:
                await self._pivot_rows(
                    conn, writer, plan, object_index, record_id, workspace_id, values
                )
            if self.count_rows:
                await conn.execute(
                    "UPDATE studio.bench_record_counts SET n = n + 1 WHERE tenant_id = $1 AND"
                    " object_id = $2",
                    writer.tenant,
                    object_id,
                )
            await self._tail(
                conn, writer, record_id, object_id, workspace_id, 1, "created", sorted(values)
            )
        return record_id

    async def _pivot_rows(
        self,
        conn: asyncpg.Connection,
        writer: Writer,
        plan: TenantPlan,
        object_index: int,
        record_id: uuid.UUID,
        workspace_id: uuid.UUID,
        values: dict[str, Any],
    ) -> None:
        by_family: dict[str, list[tuple[uuid.UUID, Any]]] = defaultdict(list)
        for slot, value in values.items():
            by_family[slot[0]].append((field_id(plan, object_index, slot), value))
        types = {
            fam: sql_type.split(" ")[0] for fam, (sql_type, _c) in self.variant.families.items()
        }
        types["f"] = "float8"
        for fam, pairs in by_family.items():
            await conn.execute(
                f"INSERT INTO studio.record_values_{fam} (tenant_id, object_id, record_id,"
                " field_id, value,"
                " workspace_id, owner_kind, owner_id, access_key)"
                # Typed: an untyped `$2` in a SELECT list is text, and `$2::text` then
                # disagrees with the uuid it is (AmbiguousParameterError, tiny run 2/11).
                " SELECT $1::uuid, $2::uuid, $3::uuid, f, v, $4::uuid, 'user', $5::uuid,"
                " md5($2::uuid::text || '/' || $4::uuid::text)::uuid"
                f" FROM unnest($6::uuid[], $7::{types[fam]}[]) AS u(f, v)",
                writer.tenant,
                plan.object_id(object_index),
                record_id,
                workspace_id,
                writer.user,
                [p[0] for p in pairs],
                [p[1] for p in pairs],
            )


# ----------------------------------------------------------------- the reads --
async def read_page(
    conn: asyncpg.Connection,
    profile: Profile,
    plan: TenantPlan,
    cursor: tuple[datetime, uuid.UUID] | None,
) -> int:
    sql = page_sql(profile.order, cursor is not None)
    args: list[Any] = [plan.tenant_id, plan.object_id(profile.object_index)]
    if cursor is not None and profile.order == "created":
        args += list(cursor)
    async with scoped(conn, plan.tenant_id, profile.principal, profile.actor_kind):
        rows = await conn.fetch(sql, *args)
    return len(rows)


async def read_get(
    conn: asyncpg.Connection, profile: Profile, plan: TenantPlan, record_id: uuid.UUID
) -> int:
    async with scoped(conn, plan.tenant_id, profile.principal, profile.actor_kind):
        rows = await conn.fetch(GET_SQL, plan.tenant_id, record_id)
    return len(rows)


async def readable_ids(
    endpoint: Endpoint, profile: Profile, plan: TenantPlan, want: int, rng: random.Random
) -> list[uuid.UUID]:
    """Records this profile can read, as `dw_app` under its own settings."""
    conn = await endpoint.connect("app")
    try:
        async with scoped(conn, plan.tenant_id, profile.principal, profile.actor_kind):
            rows = await conn.fetch(
                "SELECT id FROM studio.records TABLESAMPLE SYSTEM (2) REPEATABLE (7) WHERE"
                " tenant_id = $1 LIMIT $2",
                plan.tenant_id,
                want * 2,
            )
            if len(rows) < want:
                rows = await conn.fetch(
                    "SELECT id FROM studio.records WHERE tenant_id = $1 LIMIT $2",
                    plan.tenant_id,
                    want * 2,
                )
    finally:
        await conn.close()
    ids = [r["id"] for r in rows]
    rng.shuffle(ids)
    return ids


async def lead_cursors(
    endpoint: Endpoint, plan: TenantPlan, count: int
) -> list[tuple[datetime, uuid.UUID]]:
    """Random keyset cursors over mkt_lead, read by the migrator (not measured)."""
    conn = await endpoint.connect("migrator")
    try:
        rows = await conn.fetch(
            "SELECT created_at, id FROM studio.records TABLESAMPLE SYSTEM (5) REPEATABLE (11)"
            " WHERE tenant_id = $1 AND object_id = $2 LIMIT $3",
            plan.tenant_id,
            plan.object_id(LEAD),
            count,
        )
    finally:
        await conn.close()
    return [(r["created_at"], r["id"]) for r in rows]


# ------------------------------------------------------------------ the load --
@dataclass
class MixedLoad:
    """50 sessions, 80% reads over every profile, 15% scoring updates, 5% creates."""

    endpoint: Endpoint
    facts: SeedFacts
    path: WritePath
    writer: Writer
    profiles: list[Profile]
    get_pools: dict[str, list[uuid.UUID]]
    update_pool: list[uuid.UUID]
    recorder: Recorder = field(default_factory=Recorder)
    read_target: int = 1_000
    seed: int = 1

    async def _worker(
        self, worker_no: int, stop: asyncio.Event, rate_per_worker: float | None, wf_prefix: str
    ) -> None:
        rng = random.Random(self.seed * 1000 + worker_no)
        plan = self.facts.t1
        conn = await self.endpoint.connect("app")
        series = [(p, kind) for p in self.profiles for kind in ("page", "get")]
        lead = plan.object_id(LEAD)
        step = 0
        next_at = time.perf_counter()
        try:
            while not stop.is_set():
                if rate_per_worker:
                    next_at += rng.expovariate(rate_per_worker)
                    delay = next_at - time.perf_counter()
                    if delay > 0:
                        await asyncio.sleep(delay)
                roll = rng.random()
                if roll < 0.80:
                    behind = [
                        s
                        for s in series
                        if not self.recorder.settled(f"{s[1]}_warm:{s[0].name}", self.read_target)
                    ]
                    profile, kind = rng.choice(behind or series)
                    name = f"{kind}_warm:{profile.name}"
                    if kind == "page":
                        await timed(self.recorder, name, read_page(conn, profile, plan, None))
                    else:
                        pool = self.get_pools[profile.name]
                        await timed(
                            self.recorder,
                            name,
                            read_get(conn, profile, plan, rng.choice(pool)),
                        )
                elif roll < 0.95:
                    step += 1
                    key = f"wf:{wf_prefix}:{worker_no}:{step}"
                    target = rng.choice(self.update_pool)
                    await timed(
                        self.recorder,
                        "write_update",
                        self.path.update_data(
                            conn, self.writer, target, lead, rng.randrange(100), key
                        ),
                    )
                else:
                    obj = LEAD if rng.random() < 0.2 else rng.randrange(1, plan.objects)
                    await timed(
                        self.recorder,
                        "write_create",
                        self.path.create(conn, self.writer, plan, obj, rng),
                    )
        finally:
            await conn.close()

    def _done(self) -> bool:
        reads_done = all(
            self.recorder.settled(f"{k}_warm:{p.name}", self.read_target)
            for p in self.profiles
            for k in ("page", "get")
        )
        return (
            reads_done
            and self.recorder.settled("write_update", self.read_target)
            and self.recorder.settled("write_create", self.read_target)
        )

    async def until_sampled(self, sessions: int, timeout_s: float) -> Recorder:
        stop = asyncio.Event()
        workers = [
            asyncio.create_task(self._worker(i, stop, None, f"warm{self.seed}"))
            for i in range(sessions)
        ]
        deadline = time.monotonic() + timeout_s
        while not self._done() and time.monotonic() < deadline:
            if any(w.done() for w in workers):
                break  # a worker raised: stop now and let gather say why
            await asyncio.sleep(0.5)
        stop.set()
        await asyncio.gather(*workers)
        return self.recorder

    async def for_duration(
        self, sessions: int, seconds: float, ops_per_second: float, tag: str
    ) -> Recorder:
        stop = asyncio.Event()
        per_worker = ops_per_second / sessions
        workers = [
            asyncio.create_task(self._worker(i, stop, per_worker, tag)) for i in range(sessions)
        ]
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.gather(*workers)
        return self.recorder


async def run_queue(
    endpoint: Endpoint,
    sessions: int,
    jobs: list[tuple[str, Callable[[asyncpg.Connection], Awaitable[Any]]]],
    recorder: Recorder,
) -> Recorder:
    """Run each job once, `sessions` at a time, each on its own `dw_app` connection."""
    queue: asyncio.Queue[tuple[str, Callable[[asyncpg.Connection], Awaitable[Any]]]] = (
        asyncio.Queue()
    )
    for job in jobs:
        queue.put_nowait(job)
    targets = Counter(name for name, _job in jobs)

    async def worker() -> None:
        conn = await endpoint.connect("app")
        try:
            while True:
                try:
                    name, job = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                if not recorder.settled(name, targets[name]):
                    await timed(recorder, name, job(conn))
        finally:
            await conn.close()

    await asyncio.gather(*(worker() for _ in range(sessions)))
    return recorder


__all__ = [
    "CAMPAIGN",
    "GET_SQL",
    "MixedLoad",
    "Recorder",
    "WritePath",
    "Writer",
    "lead_cursors",
    "page_sql",
    "read_get",
    "read_page",
    "readable_ids",
    "run_queue",
    "scope_sql",
    "slot_names",
    "timed",
    "uuid7",
]
