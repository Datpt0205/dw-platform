"""The matrix of ticket 01 step 5, cell by cell, and the command line around it."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import measure
from .cell import build_cell, drop_databases, log, prepare_template
from .container import Container
from .db import Endpoint
from .ddl import MODULI, VARIANTS, Variant, cell_ddl
from .report import Report, Row, parse_threshold_overrides, percentile
from .scales import SCALES
from .seed import SeedFacts, writer_actor_kind
from .workload import WritePath, Writer


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bench_records_storage", description=__doc__)
    p.add_argument("--scale", choices=sorted(SCALES), required=True)
    p.add_argument("--variants", default="all", help="all, or a comma list of A0,A1,A2,A3,C")
    p.add_argument(
        "--moduli",
        default="8,4",
        help="8,4 (default). Fewer leaves a variant at one modulus, which makes the run incomplete"
        " (exit 1).",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=25442)
    p.add_argument("--container", default="dwbench-postgres", help="the harness's own container")
    p.add_argument(
        "--no-container", action="store_true", help="use a running server; no cold run (exit 1)"
    )
    p.add_argument("--keep-container", action="store_true")
    p.add_argument(
        "--revision", default="head", help="alembic revision the template is migrated to"
    )
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--threshold", action="append", default=[], help="key=value, e.g. planning_p95_ms=0"
    )
    p.add_argument(
        "--skip-soak-unless-needed", action="store_true", default=True, help=argparse.SUPPRESS
    )
    return p.parse_args(argv)


def variants_of(arg: str) -> list[str]:
    if arg == "all":
        return list(VARIANTS)
    names = [v.strip() for v in arg.split(",") if v.strip()]
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variants: {', '.join(unknown)}")
    return names


async def _step(report: Report, label: str, fn: Callable[[], Awaitable[None]]) -> None:
    started = time.monotonic()
    try:
        await fn()
    except Exception as exc:  # a step that raised is a hole in the matrix, reported as such
        report.errors.append(f"{label}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    log(f"{label}: {time.monotonic() - started:.0f} s")


async def run_cell(
    report: Report,
    endpoint: Endpoint,
    container: Container | None,
    scale_name: str,
    variant: Variant,
    modulus: int,
    reads: bool,
    writes: bool,
    kept: bool,
) -> SeedFacts | None:
    scale = SCALES[scale_name]
    label = f"{variant.name} m{modulus}"
    try:
        facts = await build_cell(endpoint, scale, variant, modulus)
    except Exception as exc:
        report.errors.append(f"{label} dựng: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None
    report.shapes[label] = facts.shape
    writer = Writer(facts.t1.tenant_id, facts.writer, writer_actor_kind(variant))
    path = WritePath(variant, facts)
    restart = container.restart_cold if container else None
    if reads:
        await _step(
            report,
            f"{label} R9.1",
            lambda: measure.reads(report, endpoint, facts, variant, modulus, path, writer, restart),
        )
        await _step(
            report,
            f"{label} R9.2 planning",
            lambda: measure.planning(report, endpoint, facts, variant, modulus, scale.read_samples),
        )
        await _step(
            report,
            f"{label} R9.2 cache",
            lambda: measure.cache_memory(report, endpoint, facts, variant, modulus),
        )
        await _step(
            report,
            f"{label} R9.8",
            lambda: measure.qerror(report, endpoint, facts, variant, modulus, scale.qerror_queries),
        )
        await _step(
            report,
            f"{label} R9.9",
            lambda: measure.t2_busy(report, endpoint, facts, variant, modulus, path, writer),
        )

        async def hot() -> None:
            ratio, n = await measure.measure_hot(endpoint, facts, path, writer, scale.hot_updates)
            report.add(
                Row(
                    "R9.4",
                    "hot_ratio",
                    variant.name,
                    modulus,
                    ratio,
                    "",
                    None,
                    note=f"{n} lần sửa chỉ chạm data, trên trang đã vacuum",
                )
            )

        await _step(report, f"{label} HOT", hot)
        if variant.name == "A1":
            await _step(
                report,
                f"{label} PARALLEL SAFE",
                lambda: measure.parallel_aggregates(report, endpoint, facts, variant, modulus),
            )
    if writes:
        await _step(
            report,
            f"{label} R9.6 R9.7 soak",
            lambda: measure.soak(report, endpoint, facts, variant, modulus, path, writer),
        )
        await _step(
            report,
            f"{label} R9.10",
            lambda: measure.import_rows(report, endpoint, facts, variant, modulus, path, writer),
        )
        await _step(
            report,
            f"{label} R9.12",
            lambda: measure.campaign_children(
                report, endpoint, facts, variant, modulus, path, writer
            ),
        )
        await _step(
            report,
            f"{label} R9.11",
            lambda: measure.promote_purge(report, endpoint, facts, variant, modulus, writer),
        )
    if kept:
        await _step(
            report,
            f"{label} phép đo cũ",
            lambda: measure.kept_measurements(
                report, endpoint, facts, variant, modulus, path, writer
            ),
        )
    if variant.name == "A1":
        # Last: it drops an index of the cell.
        await _step(
            report,
            f"{label} tự kiểm CO27",
            lambda: measure.self_check(report, endpoint, facts, variant, modulus, path, writer),
        )
    return facts


async def config_lines(endpoint: Endpoint) -> list[str]:
    conn = await endpoint.on("postgres").connect("admin")
    try:
        version = await conn.fetchval("SELECT version()")
        rows = await conn.fetch(
            "SELECT name, setting, unit, source FROM pg_settings"
            " WHERE source NOT IN ('default', 'override', 'client', 'session') ORDER BY name"
        )
        trips = []
        for _ in range(500):
            started = time.perf_counter()
            await conn.fetchval("SELECT 1")
            trips.append((time.perf_counter() - started) * 1000)
        sb = await conn.fetchval("SHOW shared_buffers")
        wm = await conn.fetchval("SHOW work_mem")
    finally:
        await conn.close()
    lines = [
        f"máy: {platform.platform()}, {os.cpu_count()} luồng CPU ({platform.processor()})",
        f"PostgreSQL: {version}",
        f"shared_buffers {sb}, work_mem {wm}",
        f"một vòng khứ hồi SELECT 1 từ harness: p50 {percentile(trips, 0.5):.2f} ms, p95"
        f" {percentile(trips, 0.95):.2f} ms; mọi độ trễ là thời gian giao dịch phía harness, gồm"
        " các vòng khứ hồi (GET và trang đầu 3, ghi 7-8)",
        "postgresql.conf khác mặc định: "
        + "; ".join(f"{r['name']}={r['setting']}{r['unit'] or ''} ({r['source']})" for r in rows),
    ]
    free = shutil.disk_usage(Path.cwd().anchor).free / 2**30
    lines.append(f"chỗ trống trên ổ hệ thống trước lần chạy: {free:.0f} GiB")
    return lines


async def main_async(args: argparse.Namespace) -> int:
    scale = SCALES[args.scale]
    names = variants_of(args.variants)
    moduli = [int(m) for m in args.moduli.split(",")]
    report = Report(scale.name, names, moduli, thresholds=parse_threshold_overrides(args.threshold))
    endpoint = Endpoint.from_env(args.host, args.port)
    container = None if args.no_container else Container(args.container, args.port, endpoint)
    out = (
        args.out
        or Path(tempfile.gettempdir())
        / "dw_bench_records"
        / f"{scale.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    out.mkdir(parents=True, exist_ok=True)
    try:
        if container:
            container.start()
            await container.wait_ready()
            report.config += container.describe()
        report.config += await config_lines(endpoint)
        for line in scale.t1_partition_reloptions:
            report.config.append(
                f"chỉ ở --scale {scale.name}: {line[0]} = {line[1]} trên partition của T1 (soak"
                " rút ngắn, cùng hệ số)"
            )
        log(f"template at revision {args.revision}")
        await prepare_template(endpoint, args.revision)
        for name in names:
            variant = VARIANTS[name]
            ddl = cell_ddl(variant, 8)
            report.info.append(
                f"{name}: {len(ddl.indexes)} chỉ mục trên studio.records"
                + (" và các bảng pivot" if variant.pivot else "")
                + f" ({', '.join(ddl.indexes[:6])}, …)"
            )
        for modulus in moduli:
            for name in names:
                variant = VARIANTS[name]
                await run_cell(
                    report,
                    endpoint,
                    container,
                    scale.name,
                    variant,
                    modulus,
                    variant.reads,
                    variant.writes,
                    kept=(name == "A1" and modulus == moduli[0]),
                )
                await drop_databases(endpoint, template_too=False)
                _write(report, out)
        # Step 7: A2 and A3 are soaked only when only A1's write path misses.
        decision_needs = [
            m
            for m in moduli
            if report.passes("A1", m, ("R9.1", "R9.2", "R9.8", "R9.9"))
            and report.passes("A1", m, ("R9.6", "R9.7", "R9.10", "R9.11", "R9.12")) is False
        ]
        if decision_needs:
            for name in ("A2", "A3"):
                if name in names:
                    for modulus in moduli:
                        await run_cell(
                            report,
                            endpoint,
                            container,
                            scale.name,
                            VARIANTS[name],
                            modulus,
                            False,
                            True,
                            kept=False,
                        )
                        await drop_databases(endpoint, template_too=False)
    finally:
        try:
            await drop_databases(endpoint, template_too=True)
        except Exception as exc:  # the container may be gone already
            report.errors.append(f"dọn database: {exc}")
        if container and container.created_here and not args.keep_container:
            container.remove()
            log(f"removed {container.name} and its volume")
        _write(report, out)
    problems = report.problems()
    log(f"report: {out / 'report.md'}")
    for p in problems:
        log(f"  {p}")
    return report.exit_code()


def _write(report: Report, out: Path) -> None:
    (out / "report.md").write_text(report.markdown(), encoding="utf-8")
    (out / "report.json").write_text(report.to_json(), encoding="utf-8")


def main(argv: list[str]) -> int:
    # The log speaks Vietnamese; a Windows console or a redirected file is cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    return asyncio.run(main_async(parse(argv)))


__all__ = ["MODULI", "main"]
