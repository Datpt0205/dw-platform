"""FOG-32 (discovery 09): offboarding one company of 10^6 Studio records under the
worker's limits, and a table `dw_app` reads only by column, measured on head.

Two questions (ticket `.claude/plans/studio/discovery/issues/09-...`):

1. `run`: the real worker process (`python -m dw_worker.main`, the image's CMD)
   in its image, with the production overlay's limits (`--cpus 1.0 --memory 1g`,
   no swap), claims one offboarding request and exports then purges the company.
   The host polls the request row and the container's cgroup each second, then
   reads `memory.peak` and `memory.events`. When the request completes, the
   bundle is downloaded and every `studio.records` line is checked: exactly the
   company's rows, each once (count and md5 of the sorted ids against the seed).
   `--variant spool` runs the same process with a streaming bundle prototype
   (`worker_entry.py`), never a repository change.
2. `probe`: a scratch table in `studio` and one in `memory` that `dw_app` reads
   only by column, and `platform.feedback` regranted column by column, in the
   bench database only: the lane's catalog queries, `has_table_privilege` beside
   `has_any_column_privilege`, the coverage check of `test_offboarding_coverage.py`
   and the real `export_rows`.

The seed is planted once as `dw_migrator` (bulk SQL and COPY) into a template
database; every `run` and `probe` starts from a fresh copy of it, because the
purge deletes what it measured. Tenants: `big` 10^6 records, `mid` 250,000,
`small` 100,000 (the per-record cost), `other` 10,000 (never offboarded: the
export must not carry them and the purge must leave them).

    export DW_TEST_DB_SUFFIX=_fog32
    uv run python db/bench/offboarding/bench_offboarding.py setup
    uv run python db/bench/offboarding/bench_offboarding.py run --tenant big --out DIR
    uv run python db/bench/offboarding/bench_offboarding.py probe --out DIR
    uv run python db/bench/offboarding/bench_offboarding.py drop

Not a test: nothing here is in `testpaths`.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import time
import uuid
import zipfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "support"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "python" / "dw_platform" / "tests" / "integration"))

from pg_test_db import (  # noqa: E402
    database_urls,
    load_env,
    recreate_database,
    run_migrations,
    test_db_name,
)

DB = "dw_bench_offboarding"
SEED = "dw_bench_offboarding_seed"
TENANTS = {"big": 1_000_000, "mid": 250_000, "small": 100_000, "other": 10_000}
WORKSPACES = 20
MEMBERS = 200
OBJECTS = 5
COPY_CHUNK = 100_000
# Data fields of every object, stored in `data` under their field_no (1..5).
DATA_FIELDS = {"email": "basic", "dia_chi": "basic", "ghi_chu": "none", "nguon": "none"}
DATA_FIELDS["cong_ty"] = "none"
RECORD_COLUMNS = (
    "id",
    "tenant_id",
    "object_id",
    "workspace_id",
    "owner_kind",
    "owner_id",
    "name",
    "data",
    "t01",
    "i01",
    "d01",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
)

HO = ("Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ")
DEM = ("Văn", "Thị", "Hữu", "Minh", "Thanh", "Ngọc", "Quốc", "Thu", "Đức", "Hồng")
TEN = ("An", "Bình", "Châu", "Dũng", "Hà", "Hải", "Hạnh", "Hùng", "Lan", "Linh", "Nhung", "Phúc")
DUONG = (
    "Lê Lợi",
    "Nguyễn Huệ",
    "Trần Hưng Đạo",
    "Hai Bà Trưng",
    "Điện Biên Phủ",
    "Cách Mạng Tháng Tám",
)
QUAN = ("quận 1", "quận 3", "quận Bình Thạnh", "quận Hoàn Kiếm", "quận Cầu Giấy", "quận Hải Châu")
TINH = ("TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Cần Thơ", "Hải Phòng")
NGUON = ("Hội chợ triển lãm", "Giới thiệu", "Trang web", "Zalo OA", "Gọi điện")
GHI_CHU = (
    "Khách quan tâm gói dịch vụ doanh nghiệp, hẹn gọi lại vào tuần sau để báo giá chi tiết.",
    "Đã gửi tài liệu giới thiệu qua email; khách muốn so sánh với nhà cung cấp hiện tại.",
    "Cần xác nhận lại địa chỉ giao hàng và thời gian nhận hàng trước khi lên đơn.",
    "Khách hỏi về chính sách bảo hành và hỗ trợ kỹ thuật ngoài giờ hành chính.",
)


def _say(message: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {message}", flush=True)


def engine(url: str, **kw: Any) -> AsyncEngine:
    return create_async_engine(url, poolclass=NullPool, **kw)


async def run(conn: AsyncConnection, statement: str, **values: object) -> Any:
    return await conn.execute(sa.text(statement), values)


def run_db() -> str:
    return test_db_name(DB)


def seed_db() -> str:
    return test_db_name(SEED)


# -- planting (as the migrator) ---------------------------------------------------


async def _people(
    conn: AsyncConnection, tenant: uuid.UUID, workspaces: Sequence[uuid.UUID]
) -> list[str]:
    """`MEMBERS` active company members, each with a membership and the `member`
    system role at it."""
    await run(
        conn,
        "CREATE TEMP TABLE IF NOT EXISTS seed_people"
        " (n int, user_id uuid, membership_id uuid, workspace_id uuid) ON COMMIT DROP",
    )
    await run(conn, "TRUNCATE seed_people")
    await run(
        conn,
        "INSERT INTO seed_people SELECT g, gen_random_uuid(), gen_random_uuid(),"
        " (CAST(:ws AS uuid[]))[1 + (g % :w)] FROM generate_series(0, :c - 1) g",
        ws=list(workspaces),
        w=len(workspaces),
        c=MEMBERS,
    )
    await run(
        conn,
        "INSERT INTO platform.users (id, subject, display_name, kind)"
        " SELECT user_id, 'fog32-' || user_id, 'Người đo ' || n, 'human' FROM seed_people",
    )
    await run(
        conn,
        "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
        " SELECT CAST(:t AS uuid), user_id, 'active' FROM seed_people ORDER BY n",
        t=str(tenant),
    )
    await run(
        conn,
        "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
        " SELECT membership_id, CAST(:t AS uuid), workspace_id, user_id FROM seed_people",
        t=str(tenant),
    )
    await run(
        conn,
        "INSERT INTO platform.role_assignments"
        " (id, tenant_id, workspace_id, membership_id, role_id)"
        " SELECT gen_random_uuid(), CAST(:t AS uuid), workspace_id, membership_id,"
        " (SELECT id FROM platform.tenant_roles"
        "  WHERE tenant_id = CAST(:t AS uuid) AND key = 'member')"
        " FROM seed_people",
        t=str(tenant),
    )
    rows = await run(conn, "SELECT user_id FROM seed_people ORDER BY n")
    return [str(r[0]) for r in rows]


async def _slot_fields(conn: AsyncConnection, tenant: uuid.UUID, object_id: uuid.UUID) -> None:
    """Three filtering fields in typed slots: a phone (t01), a VND amount (i01), a date (d01)."""
    author = uuid.uuid4()
    for api_name, type_, slot, extra in (
        ("dien_thoai", "phone", "t01", {"max_length": 20, "pd": "basic", "sid": "phone"}),
        ("gia_tri", "currency", "i01", {"currency": "VND", "scale": 0}),
        ("ngay_lien_he", "date", "d01", {}),
    ):
        await run(
            conn,
            "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels, type,"
            " scale, currency_code, max_length, required, is_unique, indexed, pd_category,"
            " subject_identifier, storage_kind, slot, created_by, updated_by)"
            " VALUES (gen_random_uuid(), :t, :o, :n, CAST(:l AS jsonb), :ty, :sc, :cur, :ml,"
            " false, false, true, :pd, :sid, 'slot', :slot, :u, :u)",
            t=tenant,
            o=object_id,
            n=api_name,
            l=json.dumps({"vi": f"Trường {api_name}"}),
            ty=type_,
            sc=extra.get("scale"),
            cur=extra.get("currency"),
            ml=extra.get("max_length"),
            pd=extra.get("pd", "none"),
            sid=extra.get("sid"),
            slot=slot,
            u=author,
        )


def _record(
    rng: random.Random,
    tenant: uuid.UUID,
    objects: Sequence[uuid.UUID],
    workspaces: Sequence[uuid.UUID],
    people: Sequence[uuid.UUID],
    start: dt.datetime,
    n: int,
) -> tuple[Any, ...]:
    owner = people[n % len(people)]
    name = f"{rng.choice(HO)} {rng.choice(DEM)} {rng.choice(TEN)}"
    data = {
        "1": f"khach{n}@vi-du.vn",
        "2": f"Số {rng.randint(1, 300)} đường {rng.choice(DUONG)}, {rng.choice(QUAN)},"
        f" {rng.choice(TINH)}",
        "3": rng.choice(GHI_CHU),
        "4": rng.choice(NGUON),
        "5": f"Công ty TNHH {rng.choice(TEN)} {rng.choice(DEM)} số {n % 997}",
    }
    created = start + dt.timedelta(seconds=n * 47)
    return (
        uuid.uuid4(),
        tenant,
        objects[n % len(objects)],
        workspaces[n % len(workspaces)],
        "user",
        owner,
        name,
        json.dumps(data, ensure_ascii=False),
        f"09{rng.randint(0, 99_999_999):08d}",
        rng.randint(1, 500) * 100_000,
        (created + dt.timedelta(days=rng.randint(0, 60))).date(),
        created,
        owner,
        created + dt.timedelta(hours=rng.randint(0, 2_000)),
        owner,
    )


async def _copy_records(
    migrator: AsyncEngine,
    tenant: uuid.UUID,
    count: int,
    objects: Sequence[uuid.UUID],
    workspaces: Sequence[uuid.UUID],
    people: Sequence[uuid.UUID],
) -> None:
    """`count` records by COPY, `COPY_CHUNK` per transaction, under `app.tenant_id`
    (the owner trigger compares the row's tenant with it, the migrator too)."""
    rng = random.Random(f"fog32-{tenant}")
    start = dt.datetime(2024, 11, 1, tzinfo=dt.UTC)
    done = 0
    while done < count:
        size = min(COPY_CHUNK, count - done)
        rows = [
            _record(rng, tenant, objects, workspaces, people, start, done + i) for i in range(size)
        ]
        async with migrator.begin() as conn:
            await run(conn, "SELECT set_config('app.tenant_id', :t, true)", t=str(tenant))
            raw = await conn.get_raw_connection()
            await raw.driver_connection.copy_records_to_table(  # type: ignore[union-attr]
                "records", schema_name="studio", columns=RECORD_COLUMNS, records=rows
            )
        done += size
        _say(f"  {tenant}: {done:,}/{count:,} records")


async def _fingerprint(conn: AsyncConnection, tenant: str) -> dict[str, Any]:
    row = (
        await run(
            conn,
            "SELECT count(*), md5(string_agg(id::text, ',' ORDER BY id::text))"
            " FROM studio.records WHERE tenant_id = CAST(:t AS uuid)",
            t=tenant,
        )
    ).one()
    return {"count": int(row[0]), "md5": row[1]}


async def plant() -> None:
    from dw_platform.testing.rbac import plant_tenant
    from dw_platform.testing.record_objects import plant_object

    urls = database_urls(SEED)
    migrator = engine(urls.migrator)
    world: dict[str, Any] = {}
    try:
        for label, count in TENANTS.items():
            t0 = time.perf_counter()
            async with migrator.begin() as conn:
                tenant = await plant_tenant(conn, workspaces=WORKSPACES)
                people = await _people(conn, tenant.tenant_id, tenant.workspaces)
                objects = []
                for n in range(OBJECTS):
                    lead = await plant_object(conn, tenant, f"doi_tuong_{n}", dict(DATA_FIELDS))
                    await _slot_fields(conn, tenant.tenant_id, lead.object_id)
                    objects.append(lead.object_id)
            await _copy_records(
                migrator,
                tenant.tenant_id,
                count,
                objects,
                tenant.workspaces,
                [uuid.UUID(p) for p in people],
            )
            async with migrator.begin() as conn:
                # Every member's reach-ledger row, as each person's first request makes it.
                for person in people:
                    await run(
                        conn,
                        "SELECT set_config('app.tenant_id', :t, true),"
                        " set_config('app.user_id', :u, true)",
                        t=str(tenant.tenant_id),
                        u=person,
                    )
                    await run(conn, "SELECT studio.ensure_principal_scope()")
                print_ = await _fingerprint(conn, str(tenant.tenant_id))
            world[label] = {
                "tenant_id": str(tenant.tenant_id),
                "requester": people[0],
                "records": print_,
            }
            _say(f"{label}: {count:,} records in {time.perf_counter() - t0:.0f} s")
        async with migrator.begin() as conn:
            await run(conn, "CREATE SCHEMA IF NOT EXISTS fog32")
            await run(conn, "CREATE TABLE fog32.world (id int PRIMARY KEY, body jsonb)")
            await run(
                conn, "INSERT INTO fog32.world VALUES (1, CAST(:b AS jsonb))", b=json.dumps(world)
            )
        async with engine(urls.migrator, isolation_level="AUTOCOMMIT").connect() as conn:
            # Parallel vacuum asks for dynamic shared memory the compose /dev/shm (64 MB)
            # does not have (db/bench/record-access/RESULTS.md).
            await run(conn, "VACUUM (ANALYZE, PARALLEL 0)")
    finally:
        await migrator.dispose()


async def load_world(db: str) -> dict[str, Any]:
    migrator = engine(database_urls(db).migrator)
    try:
        async with migrator.connect() as conn:
            body = (await run(conn, "SELECT body FROM fog32.world WHERE id = 1")).scalar_one()
    finally:
        await migrator.dispose()
    return dict(body)


async def clone() -> None:
    """A fresh run database from the seed template (the purge consumes the seed)."""
    admin = engine(database_urls(DB).admin, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await run(conn, f"DROP DATABASE IF EXISTS {run_db()} WITH (FORCE)")
            await run(conn, f"CREATE DATABASE {run_db()} TEMPLATE {seed_db()} OWNER dw_migrator")
    finally:
        await admin.dispose()


# -- question 1: the lane in the worker container --------------------------------


def _docker(*args: str, check: bool = True, timeout: float = 60) -> str:
    done = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def _cgroup(container: str) -> dict[str, int]:
    out = _docker(
        "exec",
        container,
        "sh",
        "-c",
        "cd /sys/fs/cgroup && echo current $(cat memory.current) && echo peak $(cat memory.peak)"
        " && grep -E '^(anon|file) ' memory.stat && grep -E '^(oom|oom_kill) ' memory.events"
        " && echo pids_peak $(cat pids.peak 2>/dev/null || echo -1)"
        " && grep -E '^(usage_usec|nr_throttled|throttled_usec) ' cpu.stat",
        check=False,
        timeout=20,
    )
    values: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            values[parts[0]] = int(parts[1])
    return values


def _worker_env(env: dict[str, str]) -> list[str]:
    db = run_db()
    pairs = {
        "DW_API_PROFILE": "local",
        "DW_WORKER_DATABASE_URL": (
            f"postgresql+asyncpg://dw_app:{env['DW_DB_APP_PASSWORD']}@postgres:5432/{db}"
        ),
        # No Qdrant: the knowledge index's `delete_by_tenant` fails on a collection
        # nobody has created (the memory ranker's returns), which fails the request
        # after the SQL purge has committed; measured once, then the in-memory index.
        "S3_ENDPOINT_URL": "http://s3:8333",
        "MINIO_ROOT_USER": env["MINIO_ROOT_USER"],
        "MINIO_ROOT_PASSWORD": env["MINIO_ROOT_PASSWORD"],
        "S3_BUCKET_EXPORTS": env.get("S3_BUCKET_EXPORTS", "dw-exports"),
        "S3_BUCKET_ARTIFACTS": env.get("S3_BUCKET_ARTIFACTS", "dw-artifacts"),
        # The `feedback` bucket exists only once someone has uploaded an
        # attachment (the API makes it on its first put), and the lane's list
        # of a missing bucket fails the whole request: measured first, then
        # pointed at a bucket that exists, under the same `feedback/` prefix.
        "DW_WORKER_FEEDBACK_BUCKET": env.get("S3_BUCKET_ARTIFACTS", "dw-artifacts"),
        "DW_WORKER_EMBEDDING_PROVIDER": "hash",
        "DW_WORKER_MODEL_PROVIDER": "mock",
    }
    args: list[str] = []
    for key, value in pairs.items():
        args += ["-e", f"{key}={value}"]
    return args


def _minio(env: dict[str, str]) -> Any:
    from minio import Minio

    port = env.get("DW_MINIO_HOST_PORT", "9000")
    return Minio(
        f"127.0.0.1:{port}",
        access_key=env["MINIO_ROOT_USER"],
        secret_key=env["MINIO_ROOT_PASSWORD"],
        secure=False,
    )


def _check_bundle(path: Path, tenant: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Every line of the records entry: count, the md5 of the sorted ids (the
    seed's fingerprint), duplicates, rows of another tenant."""
    result: dict[str, Any] = {"zip_bytes": path.stat().st_size, "entries": {}}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            result["entries"][info.filename] = info.file_size
        ids: list[str] = []
        foreign = 0
        with zf.open("tables/studio.records.ndjson") as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8"):
                if not line.strip():
                    continue
                row = json.loads(line)
                ids.append(row["id"])
                if row["tenant_id"] != tenant:
                    foreign += 1
    ids.sort()
    result["records_lines"] = len(ids)
    result["records_distinct"] = len(set(ids))
    result["records_foreign_tenant"] = foreign
    result["records_md5"] = hashlib.md5(",".join(ids).encode(), usedforsecurity=False).hexdigest()
    result["matches_seed"] = (
        result["records_lines"] == expected["count"]
        and result["records_distinct"] == expected["count"]
        and result["records_md5"] == expected["md5"]
        and foreign == 0
    )
    return result


async def _request(tenant: str, requester: str) -> None:
    migrator = engine(database_urls(DB).migrator)
    try:
        async with migrator.begin() as conn:
            await run(
                conn,
                "UPDATE platform.tenants SET status = 'offboarding' WHERE id = CAST(:t AS uuid)",
                t=tenant,
            )
            await run(
                conn,
                "INSERT INTO platform.tenant_offboarding_requests (id, tenant_id, requested_by)"
                " VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:u AS uuid))",
                t=tenant,
                u=requester,
            )
    finally:
        await migrator.dispose()


async def _left(world: dict[str, Any]) -> dict[str, int]:
    migrator = engine(database_urls(DB).migrator)
    try:
        async with migrator.connect() as conn:
            rows = await run(
                conn, "SELECT tenant_id::text, count(*) FROM studio.records GROUP BY tenant_id"
            )
            by_id = {r[0]: int(r[1]) for r in rows}
    finally:
        await migrator.dispose()
    return {label: by_id.get(w["tenant_id"], 0) for label, w in world.items()}


async def measure_run(
    label: str, variant: str, image: str, memory: str, cpus: str, out: Path, idle_seconds: int
) -> dict[str, Any]:
    env = load_env()
    world = await load_world(SEED)
    await clone()
    target = world.get(label)
    if target is not None:
        await _request(target["tenant_id"], target["requester"])
    name = f"fog32-worker-{uuid.uuid4().hex[:8]}"
    network = f"{env.get('COMPOSE_PROJECT_NAME', 'dw')}_dw-internal"
    bench_dir = str(HERE).replace("\\", "/")
    started = time.time()
    _docker(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "--cpus",
        cpus,
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "-v",
        f"{bench_dir}:/bench:ro",
        "-e",
        "PYTHONPATH=/bench",
        *_worker_env(env),
        "--entrypoint",
        "sh",
        image,
        "-c",
        f'python /bench/worker_entry.py {variant}; echo "worker exit=$?"; sleep infinity',
    )
    samples: list[dict[str, Any]] = []
    status_seen: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "tenant": label,
        "variant": variant,
        "image": image,
        "memory_limit": memory,
        "cpus": cpus,
        "container": name,
    }
    migrator = engine(database_urls(DB).migrator)
    try:
        last_key: tuple[Any, ...] | None = None
        while True:
            elapsed = time.time() - started
            cg = _cgroup(name)
            samples.append({"t": round(elapsed, 1), **cg})
            row = None
            if target is not None:
                async with migrator.connect() as conn:
                    row = (
                        await run(
                            conn,
                            "SELECT status, export_key, error, updated_at"
                            " FROM platform.tenant_offboarding_requests"
                            " WHERE tenant_id = CAST(:t AS uuid)",
                            t=target["tenant_id"],
                        )
                    ).one()
                key = (row[0], row[1] is not None, row[3])
                if key != last_key:
                    status_seen.append(
                        {
                            "t": round(elapsed, 1),
                            "status": row[0],
                            "export_key": row[1],
                            "error": row[2],
                            "updated_at": row[3].isoformat(),
                        }
                    )
                    _say(f"{elapsed:7.1f}s {row[0]} key={row[1] is not None} {row[2] or ''}")
                    last_key = key
            logs = _docker("logs", "--tail", "5", name, check=False)
            exited = "worker exit=" in logs
            if cg.get("oom_kill", 0) > 0 or exited:
                _say(f"worker stopped: oom_kill={cg.get('oom_kill')} exited={exited}")
                break
            if target is not None and row is not None and row[0] in ("completed", "failed"):
                break
            if target is None and elapsed > idle_seconds:
                break
            if elapsed > 3 * 3600:
                raise TimeoutError("the lane ran past three hours")
            await asyncio.sleep(1.0)
        final = _cgroup(name)
        result["cgroup_final"] = final
        result["memory_peak_bytes"] = final.get("peak")
        result["anon_peak_sampled_bytes"] = max((s.get("anon", 0) for s in samples), default=0)
        result["oom_kill"] = final.get("oom_kill", 0)
        result["status"] = status_seen
        result["wall_seconds"] = round(time.time() - started, 1)
        (out / f"fog32-{label}-{variant}-{memory}-logs.txt").write_text(
            _docker("logs", name, check=False), encoding="utf-8"
        )
    finally:
        await migrator.dispose()
        _docker("rm", "-f", name, check=False)
    result["samples"] = samples
    keys = {seen["export_key"] for seen in status_seen if seen["export_key"]}
    if target is not None and keys:
        # Checked whenever a bundle was uploaded, and always removed from the store.
        (key,) = keys
        client = _minio(env)
        bucket = env.get("S3_BUCKET_EXPORTS", "dw-exports")
        local = out / f"fog32-{label}-{variant}-{memory}.zip"
        client.fget_object(bucket, key, str(local))
        try:
            result["bundle"] = _check_bundle(local, target["tenant_id"], target["records"])
        finally:
            client.remove_object(bucket, key)
            local.unlink()
        result["records_left"] = await _left(world)
    (out / f"fog32-{label}-{variant}-{memory}.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    _say(
        f"{label}/{variant}: peak {result.get('memory_peak_bytes')} B,"
        f" oom_kill {result.get('oom_kill')}, {result['wall_seconds']} s"
    )
    return result


# -- question 3 (column SELECT): the catalog filter and the coverage check --------

_TENANT = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _scratch(name: str) -> list[str]:
    short = name.split(".", 1)[1]
    return [
        f"CREATE TABLE {name} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, body text)",
        f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{short} ON {name}"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})",
        f"REVOKE ALL ON {name} FROM dw_app",
        f"GRANT SELECT (id, tenant_id, body), DELETE ON {name} TO dw_app",
    ]


PROBES = ("studio.fog32_probe", "memory.fog32_probe", "platform.feedback")


async def probe(out: Path) -> dict[str, Any]:
    from tenant_wide_scopes import OFFBOARDING_SCOPES
    from test_offboarding_coverage import _PLATFORM_PREDATING, offboarding_violations

    from dw_platform.adapters.persistence.offboarding import (
        _CATALOG_EXPORTABLE,
        _CATALOG_PURGEABLE,
        EXPORT_EXCLUSIONS,
        STUDIO_EXCLUSIONS,
        SqlTenantOffboarding,
    )
    from dw_platform.retention_policy import load_retention_policy

    world = await load_world(SEED)
    await clone()
    urls = database_urls(DB)
    tenant = world["other"]["tenant_id"]
    result: dict[str, Any] = {"tenant": "other", "tables": {}}
    admin = engine(urls.admin.rsplit("/", 1)[0] + f"/{run_db()}")
    app = engine(urls.app)
    try:
        async with admin.connect() as conn:
            result["coverage_before"] = await offboarding_violations(
                conn,
                STUDIO_EXCLUSIONS,
                EXPORT_EXCLUSIONS,
                _PLATFORM_PREDATING,
                load_retention_policy().term,
            )
        async with admin.begin() as conn:
            await run(conn, "SET LOCAL ROLE dw_migrator")
            for name in PROBES[:2]:
                for statement in _scratch(name):
                    await run(conn, statement)
                await run(
                    conn,
                    f"INSERT INTO {name}"
                    " VALUES (gen_random_uuid(), CAST(:t AS uuid), 'nội dung của khách')",
                    t=tenant,
                )
            # A predating table regranted column by column: every column, so the
            # application reads it exactly as before.
            columns = (
                await run(
                    conn,
                    "SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum)"
                    " FROM pg_attribute"
                    " WHERE attrelid = 'platform.feedback'::regclass AND attnum > 0"
                    " AND NOT attisdropped",
                )
            ).scalar_one()
            await run(conn, "REVOKE SELECT ON platform.feedback FROM dw_app")
            await run(conn, f"GRANT SELECT ({columns}) ON platform.feedback TO dw_app")
            workspace = (
                await run(
                    conn,
                    "SELECT id FROM platform.workspaces WHERE tenant_id = CAST(:t AS uuid) LIMIT 1",
                    t=tenant,
                )
            ).scalar_one()
            await run(
                conn,
                "INSERT INTO platform.feedback (id, tenant_id, workspace_id, author_id, category,"
                " message) VALUES (gen_random_uuid(), CAST(:t AS uuid), :w, CAST(:u AS uuid),"
                " 'bug', 'phản hồi của khách')",
                t=tenant,
                w=workspace,
                u=world["other"]["requester"],
            )
        async with admin.connect() as conn:
            exportable = {f"{r[0]}.{r[1]}" for r in await conn.execute(_CATALOG_EXPORTABLE)}
            purgeable = {f"{r[0]}.{r[1]}" for r in await conn.execute(_CATALOG_PURGEABLE)}
            for name in PROBES:
                privileges = (
                    await run(
                        conn,
                        "SELECT has_table_privilege('dw_app', CAST(:n AS regclass), 'SELECT'),"
                        " has_any_column_privilege('dw_app', CAST(:n AS regclass), 'SELECT'),"
                        " has_table_privilege('dw_app', CAST(:n AS regclass), 'DELETE')",
                        n=name,
                    )
                ).one()
                result["tables"][name] = {
                    "has_table_privilege_select": privileges[0],
                    "has_any_column_privilege_select": privileges[1],
                    "has_table_privilege_delete": privileges[2],
                    "in_catalog_exportable": name in exportable,
                    "in_catalog_purgeable": name in purgeable,
                }
            result["coverage_after"] = await offboarding_violations(
                conn,
                STUDIO_EXCLUSIONS,
                EXPORT_EXCLUSIONS,
                _PLATFORM_PREDATING,
                load_retention_policy().term,
            )
        # dw_app reads every probe row under the tenant: the data is there to export.
        async with app.begin() as conn:
            await run(conn, "SELECT set_config('app.tenant_id', :t, true)", t=tenant)
            for name in PROBES:
                cols = "id, tenant_id, body" if name != "platform.feedback" else "id, message"
                rows = (await run(conn, f"SELECT {cols} FROM {name}")).all()
                result["tables"][name]["dw_app_reads_rows"] = len(rows)
        # The real export, through the lane's own adapter as dw_app.
        exported: dict[str, int] = {}
        store = SqlTenantOffboarding(
            session_factory=async_sessionmaker(app, expire_on_commit=False),
            scopes=OFFBOARDING_SCOPES,
        )
        batches: AsyncIterator[Any] = store.export_rows(uuid.UUID(tenant))
        async for batch in batches:
            qualified = f"{batch.schema}.{batch.table}"
            exported[qualified] = exported.get(qualified, 0) + len(batch.rows)
        result["export_rows_tables"] = exported
        for name in PROBES:
            result["tables"][name]["rows_in_export"] = exported.get(name, 0)
    finally:
        await admin.dispose()
        await app.dispose()
    (out / "fog32-probe.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name, found in result["tables"].items():
        _say(f"{name}: {found}")
    _say(f"coverage before: {result['coverage_before']}")
    _say(f"coverage after: {result['coverage_after']}")
    return result


# -- setup and teardown -----------------------------------------------------------


def setup() -> None:
    urls = database_urls(SEED)
    asyncio.run(recreate_database(urls.admin, SEED))
    migrated = run_migrations(urls.migrator)
    if migrated.returncode != 0:
        raise SystemExit(migrated.stderr[-3000:])
    t0 = time.perf_counter()
    asyncio.run(plant())
    _say(f"seeded {sum(TENANTS.values()):,} records in {time.perf_counter() - t0:.0f} s")


async def drop() -> None:
    admin = engine(database_urls(DB).admin, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            for name in (run_db(), seed_db()):
                await run(conn, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
                _say(f"dropped {name}")
    finally:
        await admin.dispose()
    for line in _docker("ps", "-a", "--format", "{{.Names}}").splitlines():
        if line.startswith("fog32-worker-"):
            _docker("rm", "-f", line, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("step", choices=["setup", "run", "probe", "drop"])
    parser.add_argument("--tenant", default="big", choices=[*TENANTS, "none"])
    parser.add_argument("--variant", default="head", choices=["head", "spool"])
    parser.add_argument(
        "--image", default=os.environ.get("DW_BENCH_WORKER_IMAGE", "dw-worker:local")
    )
    parser.add_argument("--memory", default="1g")
    parser.add_argument("--cpus", default="1.0")
    parser.add_argument("--idle-seconds", type=int, default=90)
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("TMPDIR", ".")))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.step == "setup":
        setup()
    elif args.step == "run":
        asyncio.run(
            measure_run(
                args.tenant,
                args.variant,
                args.image,
                args.memory,
                args.cpus,
                args.out,
                args.idle_seconds,
            )
        )
    elif args.step == "probe":
        asyncio.run(probe(args.out))
    else:
        asyncio.run(drop())


if __name__ == "__main__":
    main()
