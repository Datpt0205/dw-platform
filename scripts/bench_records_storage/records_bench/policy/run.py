# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""record-access/01's run: P0, one cell per axis, the winners, and their combination W.

Only policy cells are built (A1 plus each variant's replacement) at the one
modulus the command names; custom-objects/01's cells and its storage
measurements do not run. The run is complete when every cell of steps 2 and 5
has its numbers at that modulus (P0, K, L, E, H, and W when the winners differ
from P0) and every self-check of step 7 holds; a missed threshold is a "trượt"
row, never a non-zero exit (step 7).
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import replace

from ..cell import build_cell, drop_databases, log
from ..container import Container
from ..db import Endpoint
from ..ddl import VARIANTS
from ..report import READ_PROFILES, Report
from ..run import step
from ..scales import SCALES
from ..seed import writer_actor_kind
from ..workload import MixedLoad, Recorder, WritePath, Writer
from . import checks, measure
from .inputs import PolicyCell
from .variants import AXES, P0, POLICY_VARIANTS, PolicyVariant, combination, door_sql

POLICY_ORDER = ("P0", *AXES)
WIN_MARGIN = 0.10  # under 10% apart, P0 is kept (step 2)


def expected_cells(name: str, modulus: int, soak: bool) -> list[tuple[str, str, int]]:
    return [(m, name, modulus) for m in measure.cell_metrics(list(READ_PROFILES), soak)]


# ----------------------------------------------------------------- winners --
def worst_page_p95(report: Report, variant: str, modulus: int) -> float | None:
    """R9.1's worst first page: every profile, warm and cold, both objects, filter or not."""
    values = [
        r.value
        for r in report.rows
        if r.variant == variant
        and r.modulus == modulus
        and r.metric.startswith("page_")
        and r.value is not None
    ]
    return max(values) if values else None


def cell_passes(report: Report, variant: str, modulus: int) -> bool:
    rows = [r for r in report.rows if r.variant == variant and r.modulus == modulus]
    judged = [r for r in rows if r.threshold_key]
    return bool(judged) and all(r.verdict == "đạt" for r in judged)


def choose_winner(report: Report, axis: str, modulus: int) -> tuple[str, str]:
    """The winner of one axis against P0 and why (ticket step 2's rule)."""
    worst = {c: worst_page_p95(report, c, modulus) for c in ("P0", axis)}
    if any(w is None for w in worst.values()):
        return "P0", "thiếu số, giữ P0"
    passing = [c for c in ("P0", axis) if cell_passes(report, c, modulus)]
    pool = passing or ["P0", axis]
    best = min(pool, key=lambda c: _order(worst[c]))
    p0, other = worst["P0"], worst[axis]
    assert p0 is not None and other is not None
    verdict = "đạt mọi ngưỡng" if passing else "không phương án nào đạt, trượt"
    if best == axis and "P0" in pool and _closer_than(p0, other, WIN_MARGIN):
        return "P0", f"{verdict}; chênh dưới 10% ({p0:.1f} so với {other:.1f} ms), giữ P0"
    return best, f"{verdict}; p95 tệ nhất P0 {p0:.1f} ms, {axis} {other:.1f} ms"


def _order(value: float | None) -> float:
    return math.inf if value is None or math.isnan(value) else value


def _closer_than(p0: float, other: float, margin: float) -> bool:
    if math.isinf(p0) or p0 <= 0:
        return False
    return (p0 - other) / p0 < margin


# -------------------------------------------------------------------- cells --
async def run_cell(
    report: Report,
    endpoint: Endpoint,
    container: Container | None,
    scale_name: str,
    variant: PolicyVariant,
    modulus: int,
    soak: bool,
) -> None:
    scale = SCALES[scale_name]
    base = VARIANTS[variant.base]
    label = f"{variant.name} m{modulus}"
    try:
        facts = await build_cell(endpoint, scale, base, modulus, PolicyCell(variant, base))
    except Exception as exc:  # a cell that did not build is a hole in the matrix
        report.errors.append(f"{label} dựng: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return
    report.shapes[label] = facts.shape
    door = replace(endpoint, after_scope=door_sql())
    writer = Writer(facts.t1.tenant_id, facts.writer, writer_actor_kind(base))
    path = WritePath(base, facts)
    restart = container.restart_cold if container else None
    profiles = measure.policy_profiles(facts)
    private = [p for p in profiles if p.name != "public_read"]
    public = [p for p in profiles if p.name == "public_read"]
    public_principal = public[0].principal

    async def private_phase() -> None:
        await measure.set_phase(endpoint, facts, "private")
        log(f"{label}: {await measure.warm_ledger(door)} dòng sổ tầm")

    async def catalog() -> None:
        failures, reference, cell = await checks.catalog_check(endpoint, variant, modulus)
        crossing = checks.restrictive_differs(reference, cell, modulus)
        report.check_failures += [f"{label} danh mục: {f}" for f in failures]
        report.check_failures += [f"{label} chéo tenant: {f}" for f in crossing]

    async def arrays(phase: str) -> None:
        mig = await endpoint.connect("migrator")
        try:
            result = await checks.array_check(door, mig, facts, variant, phase, public_principal)
        finally:
            await mig.close()
        report.check_failures += [f"{label} {phase}: {f}" for f in result.failures]
        if result.extras:
            report.info.append(
                f"{label} tầm tính được ngoài harness ({phase}): " + "; ".join(result.extras[:40])
            )

    async def behaviour() -> None:
        report.check_failures += [
            f"{label}: {f}" for f in await checks.behaviour_checks(door, facts)
        ]

    async def public_phase() -> None:
        await measure.set_phase(endpoint, facts, "public_read")
        try:
            await arrays("public_read")
            await measure.reads(
                report, door, facts, variant, modulus, path, writer, restart, public
            )
            await measure.explains(report, door, facts, variant, modulus, public)
        finally:
            await measure.set_phase(endpoint, facts, "private")

    async def recompute() -> None:
        reader = measure.Reader(variant, facts, [], {})
        rng_pool = [facts.t1.record_id(n) for n in range(1, 50)]
        load = MixedLoad(
            door,
            facts,
            path,
            writer,
            [p for p in private if p.name == "company"],
            {"company": rng_pool},
            rng_pool,
            recorder=Recorder(),
            read_target=0,
            read_kinds=("page_lead",),
            read_op=reader.op,
        )
        await measure.recompute(report, door, facts, variant, modulus, load)

    async def soaked() -> None:
        reader = measure.Reader(variant, facts, [], {})
        await measure.soak(report, door, facts, variant, modulus, path, writer, reader)

    steps: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("pha private, sổ tầm", private_phase),
        ("tự kiểm danh mục", catalog),
        ("tự kiểm mảng (private)", lambda: arrays("private")),
        ("tự kiểm hành vi", behaviour),
        (
            "đọc (private)",
            lambda: measure.reads(
                report, door, facts, variant, modulus, path, writer, restart, private
            ),
        ),
        ("đọc (public_read)", public_phase),
        ("kế hoạch", lambda: measure.explains(report, door, facts, variant, modulus, private)),
        (
            "giao, chia sẻ, xóa",
            lambda: measure.writes(report, door, facts, variant, modulus, path, writer),
        ),
        (
            "R9.7",
            lambda: measure.scope_compute(report, door, facts, variant, modulus, profiles),
        ),
        ("R9.8", lambda: measure.door_valid(report, door, facts, variant, modulus, profiles)),
        ("R9.9 tính lại", recompute),
        ("R9.9 thu hồi", lambda: measure.revocation(report, door, facts, variant, modulus)),
        ("cắt partition", lambda: measure.pruning(report, door, facts, variant, modulus)),
    ]
    if soak:
        steps.append(("R9.5 soak", soaked))
    for name, fn in steps:
        before = len(report.check_failures)
        await step(report, f"{label} {name}", fn)
        for failure in report.check_failures[before:]:
            log(f"  tự kiểm: {failure}")


async def run_policy(
    report: Report,
    endpoint: Endpoint,
    container: Container | None,
    scale_name: str,
    names: list[str],
    modulus: int,
    checkpoint: Callable[[], None] = lambda: None,
) -> None:
    """Every axis cell, then W if it differs from P0 (step 2), each dropped after it ran.

    `checkpoint` writes the report after each cell, so a run cut short keeps its cells.
    """
    for name in POLICY_ORDER:
        report.policy_cells += expected_cells(name, modulus, soak=name == "P0")
    for name in names:
        await run_cell(
            report, endpoint, container, scale_name, POLICY_VARIANTS[name], modulus, name == "P0"
        )
        await drop_databases(endpoint, template_too=False)
        checkpoint()
    winners: dict[str, str] = {}
    lines = []
    for axis in AXES:
        winner, why = choose_winner(report, axis, modulus)
        winners[axis] = winner
        lines.append(f"- trục {axis} ({_axis_option(axis)}): thắng {winner}; {why}")
    combo = combination(winners)
    if combo.options() == P0.options():
        lines.append("- tổ hợp thắng là P0: số của P0 là số của nó, không đo lại")
    else:
        lines.append(f"- tổ hợp thắng W: {combo.options()}")
        report.policy_cells += expected_cells("W", modulus, soak=True)
        await run_cell(report, endpoint, container, scale_name, combo, modulus, True)
        await drop_databases(endpoint, template_too=False)
    report.sections.append(("Biến thể chính sách: luật chọn (bước 2)", lines))
    report.sections.append(("Biến thể chính sách: trang đầu p95 (ms)", page_table(report, modulus)))


def _axis_option(axis: str) -> str:
    return {
        "K": "khóa bigint",
        "L": "sổ tầm một dòng mỗi hành động",
        "E": "nhánh EXISTS thay mảng",
        "H": "câu gợi ý cho planner",
    }[axis]


def page_table(report: Report, modulus: int) -> list[str]:
    """Worst first page per profile and variant: the table step 6 adds to the report."""
    variants = [v for v in (*POLICY_ORDER, "W") if any(r.variant == v for r in report.rows)]
    out = [
        "| Hồ sơ | " + " | ".join(variants) + " |",
        "| --- | " + " | ".join("---" for _ in variants) + " |",
    ]
    for profile in READ_PROFILES:
        cells = []
        for v in variants:
            values = [
                r.value
                for r in report.rows
                if r.variant == v
                and r.modulus == modulus
                and r.metric.startswith("page_")
                and r.metric.endswith(f":{profile}")
                and r.value is not None
            ]
            cells.append(f"{max(values):.1f}" if values else "—")
        out.append(f"| {profile} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("Mỗi ô là p95 lớn nhất qua trang đầu trên hai object, có và không có bộ lọc,")
    out.append("nóng và nguội; số đủ ở Bảng số.")
    return out


def results_markdown(report: Report, modulus: int, chosen_modulus: str) -> str:
    """`db/bench/record-access/RESULTS.md`'s smoke section (step 6): never a D12 number."""
    lines = [
        "## smoke, máy dev, không phải số D12",
        "",
        f"Modulus {modulus} ({chosen_modulus}).",
        "Mỗi độ trễ là thời gian cả giao dịch đo từ harness, gồm gắn setting và lời gọi",
        "`studio.ensure_principal_scope()`; ngưỡng là của R9, xét lại ở D12 bởi ticket 06.",
        "Ở smoke, kết quả chỉ chọn phương án cho ticket 02 và 03 đọc.",
        "",
        "### Máy và cấu hình",
        "",
        *[f"- {c}" for c in report.config],
        "",
    ]
    for title, body in report.sections:
        lines += [f"### {title}", "", *body, ""]
    lines += [
        "### Bảng số",
        "",
        "| Mã | Chỉ số | Biến thể | Giá trị | Mẫu | Ngưỡng | Kết luận | Ghi chú |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(report.rows, key=lambda r: (r.variant, r.req, r.metric)):
        threshold = ""
        if r.threshold_key:
            op, limit, _ = report.thresholds[r.threshold_key]
            threshold = f"{op} {limit:g}"
        value = "—" if r.value is None else f"{r.value:.4g} {r.unit}"
        lines.append(
            f"| {r.req} | {r.metric} | {r.variant} | {value} | {r.samples or ''} | {threshold}"
            f" | {r.verdict} | {r.note} |"
        )
    lines += ["", "### Tự kiểm (bước 7)", ""]
    problems = report.problems()
    lines += [f"- {p}" for p in problems] or ["- đủ ô, mọi tự kiểm đạt"]
    lines += ["", "### Kế hoạch trang đầu trên mkt_lead (P0 và W)", ""]
    for c in report.claims:
        if c.variant in ("P0", "W") and c.name.startswith("page_lead "):
            lines += [
                f"#### {c.name} ({c.variant}): {c.statement}",
                "",
                "```",
                c.explain,
                "```",
                "",
            ]
    return "\n".join(lines) + "\n"


__all__ = [
    "POLICY_ORDER",
    "choose_winner",
    "expected_cells",
    "page_table",
    "results_markdown",
    "run_policy",
    "worst_page_p95",
]
