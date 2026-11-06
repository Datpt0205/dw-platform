"""The harness's real-path mode (custom-objects ticket 04 step 7; R9.1, and the
paths of R9.6 and R9.10; lượt xác nhận (l)).

    uv run python scripts/bench_records_storage.py --scale smoke --real-path

Ticket 01's cells measure the harness's own SQL on a variant's DDL. This mode
measures the code that ships: the database is `db/migrations` at head (the
provisional A0 DDL of custom-objects/02, hash modulus 4, no variant of the
harness), and every measured read and write is a call of `RecordService`
(`query`, `get`, `create`, `update`) in this process, never a route. What is
seeded is not what is measured, so it is seeded the shortest legal way:
objects through the kind's publish hook with a fixture approval
(`dw_studio.testing.record_world.publish_object`), the company, its people,
roles and assignments as `dw_migrator` SQL into the real tables (`holder`);
the records themselves through `RecordService.create`, which is the import
of R9.10's path, timed.

Four reach profiles of record-access:R9.10, one person each: own records, my
workspace, the whole company, and an object whose default access is
`public_read`. Each takes the first page of 50, a `GET` of a record it reads,
a create and a one-field update. Then one soak of updates at the scale's
rate, its WAL read from `pg_current_wal_lsn()` (R9.6's path).

Every number is labelled "smoke, máy dev, không phải số D12" and is compared
with no threshold: R9's thresholds are ticket 09's, on the reference host.
Exit 0 means every series has its samples and the service counted a call
for each one (a measurement that never reached `RecordService` is not one).
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .cell import create_cell_database, drop_databases, log, prepare_template
from .db import BENCH_DB, Endpoint
from .report import percentile
from .scales import Scale

LABEL: Final = "smoke, máy dev, không phải số D12"
LEAD: Final = "bench_lead"
OPEN: Final = "bench_open"
SERIES: Final = ("page_first_50", "get", "create", "update_one_field")
PROFILES: Final = ("own", "workspace", "company", "public_read")


class CountedService:
    """`RecordService` with a count of the calls each series made, so a
    measurement that reached something else shows up as zero (failure-modes #3)."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self.calls: Counter[str] = Counter()

    async def call(self, series: str, method: str, *args: Any, **kwargs: Any) -> Any:
        self.calls[series] += 1
        return await getattr(self.service, method)(*args, **kwargs)


@dataclass
class RealPathReport:
    scale: str
    config: list[str] = field(default_factory=list)
    samples: dict[str, list[float]] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    minimum: int = 1

    def add(self, key: str, millis: float) -> None:
        self.samples.setdefault(key, []).append(millis)

    def problems(self) -> list[str]:
        found = list(self.errors)
        for profile in PROFILES:
            for series in SERIES:
                key = f"{profile}/{series}"
                if len(self.samples.get(key, ())) < self.minimum:
                    found.append(f"{key}: {len(self.samples.get(key, ()))} mẫu")
                if self.calls.get(key, 0) == 0:
                    found.append(f"{key}: RecordService không được gọi")
        for key in ("import", "soak"):
            if self.calls.get(key, 0) == 0:
                found.append(f"{key}: RecordService không được gọi")
        return found

    def exit_code(self) -> int:
        return 0 if not self.problems() else 1

    def markdown(self) -> str:
        lines = [
            f"# Đường thật của bản ghi, --scale {self.scale} ({LABEL})",
            "",
            "Mọi số đo qua `RecordService` trong tiến trình, không qua route, trên"
            " `db/migrations` ở head. Không số nào so với ngưỡng của R9 (ticket 09).",
            "",
            *[f"- {line}" for line in self.config],
            "",
            "| Hồ sơ | Phép đo | Mẫu | Lời gọi | p50 ms | p95 ms | p99 ms |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for profile in PROFILES:
            for series in SERIES:
                key = f"{profile}/{series}"
                got = self.samples.get(key, [])
                cells = (
                    [f"{percentile(got, q):.2f}" for q in (0.5, 0.95, 0.99)] if got else ["—"] * 3
                )
                lines.append(
                    f"| {profile} | {series} | {len(got)} | {self.calls.get(key, 0)} | "
                    + " | ".join(cells)
                    + " |"
                )
        lines += ["", "| Chỉ số | Giá trị |", "| --- | --- |"]
        lines += [f"| {key} | {value:.4g} |" for key, value in sorted(self.values.items())]
        lines += [
            "",
            f"Lời gọi của nhập và soak: {self.calls.get('import', 0)}, "
            f"{self.calls.get('soak', 0)}.",
        ]
        if self.problems():
            lines += ["", "## Vấn đề", *[f"- {p}" for p in self.problems()]]
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(
            {
                "label": LABEL,
                "scale": self.scale,
                "config": self.config,
                "percentiles": {
                    key: {f"p{int(q * 100)}": percentile(got, q) for q in (0.5, 0.95, 0.99)}
                    for key, got in self.samples.items()
                    if got
                },
                "samples": {key: len(got) for key, got in self.samples.items()},
                "calls": self.calls,
                "values": self.values,
                "problems": self.problems(),
            },
            ensure_ascii=False,
            indent=2,
        )


def _document(**over: Any) -> dict[str, Any]:
    from dw_studio.testing.objects import object_document, object_field

    return object_document(
        object_field("city", indexed=True),
        object_field("amount", "currency", scale=0, indexed=True),
        object_field("score", "number", number_mode="float", indexed=True),
        object_field("note"),
        **over,
    )


@dataclass
class World:
    service: CountedService
    doors: dict[str, Any]
    people: dict[str, Any]
    objects: dict[str, str]
    readable: dict[str, list[uuid.UUID]]
    own_records: dict[str, list[uuid.UUID]]


async def _seed(endpoint: Endpoint, scale: Scale, report: RealPathReport) -> tuple[World, Any]:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from dw_kernel.ports import SystemClock, Uuid7Generator
    from dw_platform.adapters.rate_limit import InProcessRateLimiter
    from dw_platform.testing.rbac import plant_tenant
    from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
    from dw_studio.core.application.field_access import FieldAccessService
    from dw_studio.records.adapters.definition_store import SqlObjectDefinitionReader
    from dw_studio.records.adapters.record_store import SqlRecordStore
    from dw_studio.records.application.record_service import RecordService
    from dw_studio.records.application.schema_projector import ObjectSchemaProjector
    from dw_studio.testing.objects import plant_manager
    from dw_studio.testing.record_world import holder, person_door, publish_object, sessions_of

    bench = endpoint.on(BENCH_DB)
    migrator = create_async_engine(bench.url("migrator", "postgresql+asyncpg"), poolclass=NullPool)
    app = create_async_engine(
        bench.url("app", "postgresql+asyncpg"), pool_size=scale.sessions, max_overflow=0
    )
    sessions = sessions_of(app)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        manager = await plant_manager(conn, tenant)
    lead = await publish_object(sessions, manager, LEAD, _document())
    opened = await publish_object(sessions, manager, OPEN, _document(default_access="public_read"))
    edit = dict.fromkeys(("name", "city", "amount", "score", "note"), "edit")
    writes = {"create": "own", "update": "own"}
    own_rw = {"read": "own", **writes}
    async with migrator.begin() as conn:
        people = {
            "own": await holder(conn, tenant, lead, {"read": "own", **writes}, edit),
            "workspace": await holder(conn, tenant, lead, {"read": "workspace", **writes}, edit),
            "company": await holder(conn, tenant, lead, {"read": "tenant", **writes}, edit),
            "public_read": await holder(conn, tenant, opened, {"read": "own", **writes}, edit),
            # Writers whose records the profiles read past their own.
            # Each reads its own, so the soak can change what it imported.
            "peer": await holder(conn, tenant, lead, own_rw, edit),
            "far": await holder(conn, tenant, lead, own_rw, edit, workspace=tenant.workspaces[1]),
            "open_writer": await holder(conn, tenant, opened, own_rw, edit),
        }
    await migrator.dispose()
    clock = SystemClock()
    service = CountedService(
        RecordService(
            SqlRecordStore(),
            FieldAccessService(SqlFieldSecurityInputs()),
            InProcessRateLimiter(1, clock),
            ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
            clock,
            Uuid7Generator(),
        )
    )
    doors = {name: person_door(sessions, person) for name, person in people.items()}
    objects = {name: OPEN if name in ("public_read", "open_writer") else LEAD for name in people}
    world = World(service, doors, people, objects, {}, {})
    report.config.append(
        f"công ty {tenant.tenant_id}, đối tượng {LEAD} ({lead}), {OPEN} ({opened})"
    )
    return world, app


def _fields(n: int) -> dict[str, Any]:
    return {"city": f"c{n % 50}", "amount": str(n * 100), "score": n * 1.5}


async def _import(world: World, scale: Scale, report: RealPathReport) -> None:
    """R9.10's path: `scale.import_rows` records through `RecordService.create`,
    `scale.import_sessions` at once, spread over the writers."""
    writers = ["own", "workspace", "company", "peer", "far", "open_writer", "public_read"]
    queue: asyncio.Queue[int] = asyncio.Queue()
    for n in range(scale.import_rows):
        queue.put_nowait(n)

    async def worker() -> None:
        while not queue.empty():
            n = queue.get_nowait()
            who = writers[n % len(writers)]
            made = await world.service.call(
                "import",
                "create",
                world.doors[who],
                world.objects[who],
                {"name": f"Nhập {n}", "fields": _fields(n)},
            )
            world.own_records.setdefault(who, []).append(made.record.id)

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(scale.import_sessions)))
    elapsed = time.perf_counter() - started
    report.values["import_rows_per_s"] = scale.import_rows / elapsed
    report.values["import_rows"] = scale.import_rows


def _first_page(schema: Any, person: Any, api_name: str) -> Any:
    from dw_kernel.filters import parse_query

    return parse_query(
        schema,
        route=f"/api/v1/studio/objects/{api_name}/records",
        tenant=person.tenant_id,
        workspace=person.workspace_id,
        limit=50,
    )


async def _timed(
    report: RealPathReport, service: CountedService, key: str, method: str, *args: Any
) -> Any:
    """One call of the service, its latency kept under ``key``."""
    started = time.perf_counter()
    result = await service.call(key, method, *args)
    report.add(key, (time.perf_counter() - started) * 1000)
    return result


async def _profile(world: World, profile: str, samples: int, report: RealPathReport) -> None:
    person, door, api_name = world.people[profile], world.doors[profile], world.objects[profile]
    service = world.service
    rng = random.Random(f"{profile}-{samples}")

    def first_page(schema: Any) -> Any:
        return _first_page(schema, person, api_name)

    page_key = f"{profile}/page_first_50"
    first = await service.call(page_key, "query", door, api_name, first_page)
    readable = [item.id for item in first.items]
    if not readable:
        report.errors.append(f"{profile}: trang đầu rỗng, không có bản ghi để GET")
        return
    mine = world.own_records.setdefault(profile, [])
    for n in range(samples):
        await _timed(report, service, page_key, "query", door, api_name, first_page)
        await _timed(report, service, f"{profile}/get", "get", door, api_name, rng.choice(readable))
        made = await _timed(
            report,
            service,
            f"{profile}/create",
            "create",
            door,
            api_name,
            {"name": f"Đo {profile} {n}", "fields": _fields(n)},
        )
        mine.append(made.record.id)
        await _timed(
            report,
            service,
            f"{profile}/update_one_field",
            "update",
            door,
            api_name,
            rng.choice(mine),
            {"fields": {"city": f"sửa {n}"}},
        )


async def _wal_lsn(endpoint: Endpoint) -> int:
    conn = await endpoint.on("postgres").connect("admin")
    try:
        return int(await conn.fetchval("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')"))
    finally:
        await conn.close()


async def _soak(world: World, endpoint: Endpoint, scale: Scale, report: RealPathReport) -> None:
    """R9.6's path: one-field updates through `RecordService.update` at the
    scale's rate for its soak seconds, `scale.sessions` at once."""
    writers = [
        w for w in ("own", "workspace", "company", "peer", "far") if world.own_records.get(w)
    ]
    deadline = time.monotonic() + scale.soak_seconds
    interval = scale.sessions / scale.soak_writes_per_second
    done = Counter[str]()
    failed = Counter[str]()

    async def session(index: int) -> None:
        rng = random.Random(index)
        while time.monotonic() < deadline:
            tick = time.monotonic()
            who = writers[index % len(writers)]
            target = rng.choice(world.own_records[who])
            try:
                await world.service.call(
                    "soak",
                    "update",
                    world.doors[who],
                    world.objects[who],
                    target,
                    {"fields": {"city": f"soak {rng.random():.6f}"}},
                )
                done["writes"] += 1
            except Exception as exc:  # a concurrent If-Match-free write still may conflict
                failed[type(exc).__name__] += 1
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - tick)))

    before, started = await _wal_lsn(endpoint), time.perf_counter()
    await asyncio.gather(*(session(i) for i in range(scale.sessions)))
    elapsed = time.perf_counter() - started
    after = await _wal_lsn(endpoint)
    report.values["soak_seconds"] = elapsed
    report.values["soak_writes_per_s"] = done["writes"] / elapsed
    report.values["soak_wal_mb_per_s"] = (after - before) / elapsed / 2**20
    if failed:
        report.config.append(f"soak: lần ghi lỗi theo loại {dict(failed)}")


async def run_real_path(
    endpoint: Endpoint, scale: Scale, revision: str, out: Path, report: RealPathReport
) -> int:
    report.minimum = scale.read_samples
    log(f"real path: template at revision {revision}")
    await prepare_template(endpoint, revision)
    await create_cell_database(endpoint)
    app = None
    try:
        world, app = await _seed(endpoint, scale, report)
        log(f"real path: import {scale.import_rows} records through RecordService")
        await _import(world, scale, report)
        report.calls["import"] = world.service.calls["import"]
        for profile in PROFILES:
            log(f"real path: profile {profile}, {scale.read_samples} samples per series")
            await _profile(world, profile, scale.read_samples, report)
        log(f"real path: soak {scale.soak_seconds} s")
        await _soak(world, endpoint, scale, report)
        report.calls.update(world.service.calls)
    except Exception as exc:  # a step that raised is a hole, reported as one
        report.errors.append(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if app is not None:
            await app.dispose()
        await drop_databases(endpoint, template_too=True)
        (out / "real_path.md").write_text(report.markdown(), encoding="utf-8")
        (out / "real_path.json").write_text(report.to_json(), encoding="utf-8")
    return report.exit_code()
