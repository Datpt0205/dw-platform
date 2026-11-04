"""The table of numbers, what makes it complete, and what the exit code says.

The exit code says only whether the measurement saw what it measures and is
complete (ticket 01 step 6, CO27): every cell of the step-5 matrix at both
moduli, every p95 on at least 1,000 samples, every "uses an index" claim carrying
its `EXPLAIN (ANALYZE, BUFFERS)`, and the HOT self-check above zero. A missed
threshold is a row marked "trượt" for the decision rule of step 7, never a
non-zero exit.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Op = Literal["<=", "<", ">=", ">"]
MIN_SAMPLES = 1_000

# Every number with a threshold, named once (spec R9, record-access R9.5).
THRESHOLDS: dict[str, tuple[Op, float, str]] = {
    "page_p95_ms": ("<=", 50.0, "R9.1"),
    "get_p95_ms": ("<=", 5.0, "R9.1"),
    "write_p95_ms": ("<=", 10.0, "record-access:R9.5"),
    "planning_p95_ms": ("<=", 5.0, "R9.2"),
    "cache_memory_mb": ("<=", 64.0, "R9.2"),
    "wal_mb_per_s": ("<=", 20.0, "R9.6"),
    "autovacuum_cycle_min": ("<", 30.0, "R9.7"),
    "dead_tuple_growth": ("<=", 1.5, "R9.7"),
    "qerror_p95": ("<=", 10.0, "R9.8"),
    "slowest_vs_best": ("<=", 10.0, "R9.8"),
    "import_rows_per_s": (">=", 1000.0, "R9.10"),
    "maintenance_hours": ("<=", 2.0, "R9.11"),
    "background_p95_ratio": ("<=", 1.5, "R9.11"),
    "campaign_create_p95_ms": ("<=", 10.0, "R9.12"),
    "lock_wait_max_ms": ("<=", 100.0, "R9.12"),
}

READ_PROFILES = (
    "own",
    "own_sort_slot",
    "team",
    "team_sort_slot",
    "workspace_1",
    "workspace_40",
    "company",
    "company_updated",
    "company_name",
    "public_read",
    "manager_50",
    "manager_500",
    "manager_5000",
    "share_recipient",
    "agent_one_object",
    "service_account",
)


def percentile(samples: Sequence[float], q: float) -> float:
    """Nearest-rank percentile; a p95 of fewer than MIN_SAMPLES is not reported as met."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def certain_miss(samples: Sequence[float], limit: float, target: int = MIN_SAMPLES) -> bool:
    """More than 5% of a `target`-sample run above `limit`: its p95 misses whatever follows.

    The nearest-rank p95 of `target` samples is above `limit` exactly when more
    than `target - ceil(0.95 * target)` samples are (51 of 1,000), so a series
    may stop there without changing its verdict. This bounds a run in which a
    narrow-scope page takes seconds at D12.
    """
    over = sum(1 for s in samples if s > limit)
    return over > target - math.ceil(0.95 * target)


def series_limit(thresholds: dict[str, tuple[Op, float, str]], series: str) -> float | None:
    """The `<=` limit in ms a timed series is held to, read from the one threshold table."""
    for prefix, key in (
        ("page_", "page_p95_ms"),
        ("t2_page", "page_p95_ms"),
        ("get_", "get_p95_ms"),
        ("t2_get", "get_p95_ms"),
        ("write_", "write_p95_ms"),
        ("campaign", "campaign_create_p95_ms"),
    ):
        if series.startswith(prefix):
            return thresholds[key][1]
    return None


@dataclass
class Row:
    req: str
    metric: str  # key of the matrix, e.g. "page_warm:own"
    variant: str
    modulus: int | None
    value: float | None
    unit: str
    threshold_key: str | None = None
    samples: int | None = None
    note: str = ""
    verdict: str = "—"
    stopped_early: bool = False  # certain_miss: fewer samples, verdict already "trượt"

    @property
    def key(self) -> tuple[str, str, int | None]:
        return (self.metric, self.variant, self.modulus)


@dataclass
class Claim:
    """A statement that a plan uses an index, with the plan that shows it."""

    name: str
    variant: str
    modulus: int | None
    sql: str
    explain: str
    indexes: list[str] = field(default_factory=list)
    sort_over_match_set: bool = False

    @property
    def statement(self) -> str:
        if self.indexes:
            return "dùng chỉ mục " + ", ".join(sorted(set(self.indexes)))
        return "không dùng chỉ mục"


def explain_is_analyzed(text: str) -> bool:
    """`EXPLAIN (ANALYZE, BUFFERS)` text, not a bare EXPLAIN or nothing."""
    return "actual time=" in text and "Buffers:" in text


def judge(value: float, op: Op, limit: float) -> bool:
    return {
        "<=": value <= limit,
        "<": value < limit,
        ">=": value >= limit,
        ">": value > limit,
    }[op]


@dataclass
class Report:
    scale: str
    variants: list[str]
    moduli: list[int]
    thresholds: dict[str, tuple[Op, float, str]] = field(default_factory=lambda: dict(THRESHOLDS))
    rows: list[Row] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    selfchecks: list[Row] = field(default_factory=list)
    config: list[str] = field(default_factory=list)
    shapes: dict[str, dict[str, Any]] = field(default_factory=dict)
    info: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # a step that raised

    # ------------------------------------------------------------- adding --
    def add(self, row: Row) -> Row:
        if row.threshold_key is not None and row.value is not None:
            op, limit, _req = self.thresholds[row.threshold_key]
            row.verdict = "đạt" if judge(row.value, op, limit) else "trượt"
        self.rows.append(row)
        return row

    def add_p95(
        self,
        req: str,
        metric: str,
        variant: str,
        modulus: int | None,
        samples: Sequence[float],
        threshold_key: str | None,
        note: str = "",
    ) -> Row:
        value = percentile(samples, 0.95) if samples else None
        row = self.add(
            Row(req, metric, variant, modulus, value, "ms", threshold_key, len(samples), note)
        )
        if threshold_key and len(samples) < MIN_SAMPLES:
            limit = self.thresholds[threshold_key][1]
            if certain_miss(samples, limit):
                row.stopped_early = True
                row.verdict = "trượt"
                row.note = (row.note + " dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng").strip()
        return row

    def claim(self, claim: Claim) -> Claim:
        self.claims.append(claim)
        return claim

    # --------------------------------------------------------- completeness --
    def expected(self) -> list[tuple[str, str, int]]:
        """Every (metric, variant, modulus) the step-5 matrix asks for."""
        from .ddl import VARIANTS

        keys: list[tuple[str, str, int]] = []
        for name in self.variants:
            variant = VARIANTS[name]
            for modulus in (8, 4):  # both, whatever was asked: one modulus is incomplete
                if variant.reads:
                    keys += [(m, name, modulus) for m in read_cell_metrics()]
                if variant.writes:
                    keys += [(m, name, modulus) for m in write_cell_metrics()]
        return keys

    def problems(self) -> list[str]:
        found = {row.key: row for row in self.rows}
        out: list[str] = []
        for key in self.expected():
            row = found.get(key)
            if row is None or row.value is None:
                out.append(f"ô thiếu số: {key[0]} của {key[1]} modulus {key[2]}")
            elif (
                row.unit == "ms"
                and row.samples is not None
                and row.samples < MIN_SAMPLES
                and not row.stopped_early
            ):
                out.append(
                    f"p95 trên {row.samples} mẫu (< {MIN_SAMPLES}): {key[0]} của {key[1]} modulus"
                    f" {key[2]}"
                )
        for claim in self.claims:
            if claim.indexes and not explain_is_analyzed(claim.explain):
                out.append(
                    f"khẳng định '{claim.statement}' ({claim.name}) không kèm EXPLAIN (ANALYZE,"
                    " BUFFERS)"
                )
        for check in self.selfchecks:
            if check.value is None or check.value <= 0:
                out.append(
                    f"tự kiểm CO27: tỉ lệ HOT {check.value} khi bỏ btree updated_at của "
                    f"{check.variant} modulus {check.modulus}: bộ đếm HOT mù"
                )
        if any(v in self.variants for v in ("A1",)) and not self.selfchecks:
            out.append("tự kiểm CO27 không chạy")
        out += [f"bước lỗi: {e}" for e in self.errors]
        return out

    def exit_code(self) -> int:
        return 1 if self.problems() else 0

    # ------------------------------------------------------------ decision --
    def _rows_of(self, variant: str, modulus: int, reqs: Iterable[str]) -> list[Row]:
        wanted = set(reqs)
        return [
            r
            for r in self.rows
            if r.variant == variant and r.modulus == modulus and r.req in wanted and r.threshold_key
        ]

    def passes(self, variant: str, modulus: int, reqs: Iterable[str]) -> bool | None:
        rows = self._rows_of(variant, modulus, reqs)
        if not rows:
            return None
        return all(r.verdict == "đạt" for r in rows)

    def value(self, metric: str, variant: str, modulus: int | None) -> float | None:
        for r in self.rows:
            if r.key == (metric, variant, modulus):
                return r.value
        return None

    def decide(self) -> list[str]:
        """Step 7, read off the table. Lines for the ticket's Comments."""
        reads = ("R9.1", "R9.2", "R9.8", "R9.9", "record-access:R9.5")
        writes = ("R9.6", "R9.7", "R9.10", "R9.11", "R9.12")
        lines: list[str] = []
        a1 = {m: (self.passes("A1", m, reads), self.passes("A1", m, writes)) for m in (8, 4)}
        lines.append(
            "A1: "
            + "; ".join(
                f"modulus {m} đọc {_word(r)}, ghi và bảo trì {_word(w)}" for m, (r, w) in a1.items()
            )
        )
        gains = self.maintenance_gain()
        lines.append(
            "lợi ích bảo trì của modulus 8 so với 4: "
            + (", ".join(f"{k} {v:+.0%}" for k, v in gains.items()) if gains else "chưa có số")
        )
        gain = any(v <= -0.10 for v in gains.values())
        r8, w8 = a1[8]
        r4, _w4 = a1[4]
        if r8 and w8 and gain:
            lines.append("modulus: 8 (A1 đạt mọi ngưỡng và có lợi ích bảo trì đo được)")
        elif r4:
            lines.append(
                "modulus: 4 (A1 modulus 8 không đạt điều kiện R9.2, hoặc không có lợi ích bảo trì"
                " đo được)"
            )
        elif r8 is False and r4 is False:
            lines.append("A1 trượt ngưỡng đọc ở cả hai modulus: quay lại người đặt yêu cầu (DO-15)")
        else:
            lines.append("modulus: chưa quyết được (thiếu số)")
        if (r8 and w8 is False) or (r4 and a1[4][1] is False):
            for candidate in ("A2", "A3"):
                verdicts = [self.passes(candidate, m, writes) for m in (8, 4)]
                lines.append(
                    f"chỉ đường ghi trượt: thử {candidate}: {', '.join(_word(v) for v in verdicts)}"
                )
            lines.append(
                "sau A2, A3: giảm số slot mỗi họ, `wal_compression`, rồi mới pivot cho trường tràn"
            )
        for m in (8, 4):
            hot = self.value("hot_ratio", "A2", m)
            page = self.value("page_warm:company_updated", "A2", m)
            if hot is not None and page is not None:
                pick = hot > 0 and page <= self.thresholds["page_p95_ms"][1]
                lines.append(
                    f"BRIN (A2) modulus {m}: HOT {hot:.1%}, trang mới cập nhật p95 {page:.1f} ms → "
                    + ("chọn BRIN" if pick else "giữ btree")
                )
        return lines

    def maintenance_gain(self) -> dict[str, float]:
        """Relative change of each maintenance number, modulus 8 against 4 (negative = 8 better)."""
        out: dict[str, float] = {}
        for metric in (
            "autovacuum_cycle_max_min",
            "promote_hours",
            "purge_hours",
            "vacuum_t1_partition_s",
        ):
            m8, m4 = self.value(metric, "A1", 8), self.value(metric, "A1", 4)
            if m8 is not None and m4 is not None and m4 > 0:
                out[metric] = (m8 - m4) / m4
        return out

    # ------------------------------------------------------------- output --
    def markdown(self) -> str:
        lines = [f"# Đo nền lưu trữ bản ghi — `--scale {self.scale}`", ""]
        if self.config:
            lines += ["## Máy và cấu hình", "", *[f"- {c}" for c in self.config], ""]
        if self.shapes:
            lines += ["## Hình dạng seed mỗi ô", ""]
            lines += [
                f"- {cell}: {json.dumps(shape, default=str, ensure_ascii=False)}"
                for cell, shape in self.shapes.items()
            ]
            lines.append("")
        lines += [
            "## Bảng số",
            "",
            "| Mã | Chỉ số | Biến thể | Modulus | Giá trị | Mẫu | Ngưỡng | Kết luận | Ghi chú |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in sorted(self.rows, key=lambda r: (r.req, r.metric, r.variant, -(r.modulus or 0))):
            threshold = ""
            if r.threshold_key:
                op, limit, _ = self.thresholds[r.threshold_key]
                threshold = f"{op} {limit:g}"
            value = "—" if r.value is None else f"{r.value:.4g} {r.unit}"
            lines.append(
                f"| {r.req} | {r.metric} | {r.variant} | {r.modulus or ''} | {value} |"
                f" {r.samples or ''}"
                f" | {threshold} | {r.verdict} | {r.note} |"
            )
        lines += ["", "## Tự kiểm CO27", ""]
        lines += [
            f"- {c.variant} m{c.modulus}: {c.metric} = {c.value} ({c.note})"
            for c in self.selfchecks
        ]
        lines += ["", "## Luật quyết (bước 7)", "", *[f"- {d}" for d in self.decide()], ""]
        if self.info:
            lines += ["## Kết quả không có ngưỡng", "", *[f"- {i}" for i in self.info], ""]
        lines += ["## Kế hoạch đi kèm mỗi khẳng định", ""]
        for c in self.claims:
            lines += [
                f"### {c.name} ({c.variant} m{c.modulus}): {c.statement}",
                "",
                "```sql",
                c.sql,
                "```",
                "```",
                c.explain,
                "```",
                "",
            ]
        problems = self.problems()
        lines += ["## Mã thoát", "", f"{1 if problems else 0}", *[f"- {p}" for p in problems]]
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        data = {
            "scale": self.scale,
            "variants": self.variants,
            "moduli": self.moduli,
            "rows": [asdict(r) for r in self.rows],
            "claims": [asdict(c) | {"statement": c.statement} for c in self.claims],
            "selfchecks": [asdict(c) for c in self.selfchecks],
            "config": self.config,
            "shapes": self.shapes,
            "info": self.info,
            "errors": self.errors,
            "decision": self.decide(),
            "problems": self.problems(),
        }
        return json.dumps(data, default=str, ensure_ascii=False, indent=2)


def _word(value: bool | None) -> str:
    return {True: "đạt", False: "trượt", None: "chưa đo"}[value]


def read_cell_metrics() -> list[str]:
    metrics: list[str] = []
    for profile in READ_PROFILES:
        metrics += [
            f"page_warm:{profile}",
            f"page_cold:{profile}",
            f"get_warm:{profile}",
            f"get_cold:{profile}",
        ]
    metrics += [
        "write_update_p95",
        "write_create_p95",
        "planning_custom_tenant",
        "planning_custom_no_tenant",
        "planning_generic_tenant",
        "planning_generic_no_tenant",
        "cache_memory_mb",
        "qerror_p95",
        "slowest_vs_best",
        "t2_page_busy",
        "t2_get_busy",
        "hot_ratio",
    ]
    return metrics


def write_cell_metrics() -> list[str]:
    return [
        "wal_mb_per_s",
        "soak_writes_per_s",
        "dead_tuple_growth",
        "autovacuum_cycle_max_min",
        "import_rows_per_s",
        "promote_hours",
        "purge_hours",
        "promote_background_ratio",
        "purge_background_ratio",
        "campaign_create_p95",
        "lock_wait_max_ms",
    ]


def parse_threshold_overrides(pairs: Iterable[str]) -> dict[str, tuple[Op, float, str]]:
    out = dict(THRESHOLDS)
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if key not in out:
            raise ValueError(f"unknown threshold {key!r}; known: {', '.join(sorted(out))}")
        op, _limit, req = out[key]
        out[key] = (op, float(raw), req)
    return out
