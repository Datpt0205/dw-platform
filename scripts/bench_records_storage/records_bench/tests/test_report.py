# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""The exit code says whether the measurement saw what it measures, never whether a threshold held.

Ticket 01 step 6 and its CO27 criteria: a complete table exits 0 even with a
missed threshold; a missing cell, a variant at one modulus, a p95 under 1,000
samples, an index claim without its EXPLAIN (ANALYZE, BUFFERS), or a HOT
self-check at zero exits 1.
"""

from __future__ import annotations

import pytest

from ..ddl import VARIANTS
from ..measure import hot_ratio
from ..report import (
    MIN_SAMPLES,
    THRESHOLDS,
    Claim,
    Report,
    Row,
    certain_miss,
    judge,
    parse_threshold_overrides,
    percentile,
    read_cell_metrics,
    write_cell_metrics,
)

pytestmark = pytest.mark.unit

ANALYZED = (
    "Limit  (cost=0.56..10.2 rows=50 width=900) (actual time=0.031..0.210 rows=50 loops=1)\n"
    "  Buffers: shared hit=57\n"
    "  ->  Index Scan using ix_records_tenant_id_object_id_created_at_p0 on records_p0"
    "  (actual time=0.030..0.200 rows=50 loops=1)\n"
    "        Buffers: shared hit=57"
)

THRESHOLD_OF = {
    "page_": "page_p95_ms",
    "get_": "get_p95_ms",
    "write_": "write_p95_ms",
    "planning_": "planning_p95_ms",
    "cache_memory_mb": "cache_memory_mb",
    "qerror_p95": "qerror_p95",
    "slowest_vs_best": "slowest_vs_best",
    "t2_page": "page_p95_ms",
    "t2_get": "get_p95_ms",
    "wal_mb_per_s": "wal_mb_per_s",
    "dead_tuple_growth": "dead_tuple_growth",
    "autovacuum_cycle_max_min": "autovacuum_cycle_min",
    "import_rows_per_s": "import_rows_per_s",
    "promote_hours": "maintenance_hours",
    "purge_hours": "maintenance_hours",
    "promote_background_ratio": "background_p95_ratio",
    "purge_background_ratio": "background_p95_ratio",
    "campaign_create_p95": "campaign_create_p95_ms",
    "lock_wait_max_ms": "lock_wait_max_ms",
}


def _threshold(metric: str) -> str | None:
    return next((key for prefix, key in THRESHOLD_OF.items() if metric.startswith(prefix)), None)


def _passing_value(key: str | None) -> float:
    if key is None:
        return 0.5
    op, limit, _req = THRESHOLDS[key]
    return limit * 2 if op in (">=", ">") else limit / 2


def _req(key: str | None) -> str:
    return THRESHOLDS[key][2] if key else "R9.4"


def complete(variants: list[str] | None = None) -> Report:
    """A report holding every cell of the matrix, every number passing."""
    names = variants or list(VARIANTS)
    report = Report("tiny", names, [8, 4])
    for name in names:
        variant = VARIANTS[name]
        metrics = (read_cell_metrics() if variant.reads else []) + (
            write_cell_metrics() if variant.writes else []
        )
        for modulus in (8, 4):
            for metric in metrics:
                key = _threshold(metric)
                timed = metric.startswith(
                    ("page_", "get_", "write_", "planning_", "t2_", "campaign")
                )
                report.add(
                    Row(
                        _req(key),
                        metric,
                        name,
                        modulus,
                        _passing_value(key),
                        "ms" if timed else "",
                        key,
                        samples=MIN_SAMPLES if timed else None,
                    )
                )
            if name == "A1":
                report.selfchecks.append(
                    Row("CO27", "hot_ratio_without_updated_at_btree", name, modulus, 0.4, "")
                )
            report.claim(
                Claim("R9.1 trang đầu own", name, modulus, "SELECT 1", ANALYZED, ["ix_records_x"])
            )
    return report


def test_a_complete_table_exits_zero() -> None:
    report = complete()
    assert report.problems() == []
    assert report.exit_code() == 0


def test_a_missed_threshold_is_a_row_marked_missed_and_still_exits_zero() -> None:
    """CO27: planning threshold set to 0 ms -> the row reads "trượt", the exit stays 0."""
    report = Report(
        "tiny", ["A1"], [8, 4], thresholds=parse_threshold_overrides(["planning_p95_ms=0"])
    )
    filled = complete(["A1"])
    for row in filled.rows:
        row.verdict = "—"
        report.add(row)
    report.selfchecks = filled.selfchecks
    report.claims = filled.claims
    planning = [r for r in report.rows if r.metric.startswith("planning_")]
    assert planning and all(r.verdict == "trượt" for r in planning)
    assert report.exit_code() == 0


def test_a_missing_cell_exits_non_zero_and_names_it() -> None:
    report = complete()
    report.rows = [r for r in report.rows if r.key != ("qerror_p95", "A2", 4)]
    assert report.exit_code() == 1
    assert any("qerror_p95 của A2 modulus 4" in p for p in report.problems())


def test_a_variant_measured_at_one_modulus_exits_non_zero() -> None:
    report = complete()
    report.rows = [r for r in report.rows if not (r.variant == "A3" and r.modulus == 4)]
    assert report.exit_code() == 1


def test_a_cell_whose_value_is_none_counts_as_missing() -> None:
    report = complete()
    next(r for r in report.rows if r.key == ("wal_mb_per_s", "C", 8)).value = None
    assert report.exit_code() == 1


def test_a_p95_under_a_thousand_samples_exits_non_zero() -> None:
    report = complete()
    next(r for r in report.rows if r.key == ("get_cold:own", "A0", 8)).samples = MIN_SAMPLES - 1
    assert report.exit_code() == 1
    assert any("999 mẫu" in p for p in report.problems())


def test_an_index_claim_without_its_analyzed_plan_exits_non_zero() -> None:
    """CO27: removing the EXPLAIN (ANALYZE, BUFFERS) of a "uses an index" claim -> exit 1."""
    report = complete()
    report.claims[0].explain = ""
    assert report.exit_code() == 1
    report.claims[
        0
    ].explain = "Index Scan using ix_records_x on records_p0  (cost=0.56..10.2 rows=50)"
    assert report.exit_code() == 1, "a bare EXPLAIN is not EXPLAIN (ANALYZE, BUFFERS)"


def test_a_claim_of_no_index_needs_no_plan_to_exit_zero() -> None:
    report = complete()
    report.claims.append(Claim("seq", "A1", 8, "SELECT 1", "", []))
    assert report.exit_code() == 0


def test_a_blind_hot_counter_exits_non_zero() -> None:
    """CO27: a HOT counter that always returns 0 -> the self-check fails the run."""

    def blind(updates: int) -> tuple[int, int]:
        return (updates, 0)

    ratio = hot_ratio(blind(100), blind(2_100))
    assert ratio == 0.0
    report = complete()
    report.selfchecks[0].value = ratio
    assert report.exit_code() == 1
    assert any("bộ đếm HOT mù" in p for p in report.problems())


def test_a_hot_counter_that_saw_no_update_reads_as_none_and_fails() -> None:
    assert hot_ratio((5, 1), (5, 1)) is None
    report = complete()
    report.selfchecks[1].value = None
    assert report.exit_code() == 1


def test_a1_without_its_self_check_exits_non_zero() -> None:
    report = complete()
    report.selfchecks = []
    assert any("không chạy" in p for p in report.problems())


def test_a_step_that_raised_exits_non_zero() -> None:
    report = complete()
    report.errors.append("A1 m8 R9.11: RuntimeError: boom")
    assert report.exit_code() == 1


def test_percentile_is_nearest_rank() -> None:
    samples = [float(i) for i in range(1, 1001)]
    assert percentile(samples, 0.95) == 950.0
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    with pytest.raises(ValueError):
        percentile([], 0.95)


def test_an_unknown_threshold_override_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown threshold"):
        parse_threshold_overrides(["planing_p95_ms=0"])


def _set(report: Report, metric: str, variant: str, modulus: int, value: float) -> None:
    row = next(r for r in report.rows if r.key == (metric, variant, modulus))
    row.value = value
    if row.threshold_key:
        op, limit, _ = report.thresholds[row.threshold_key]
        row.verdict = "đạt" if judge(value, op, limit) else "trượt"


def test_the_decision_picks_modulus_8_only_with_a_measured_maintenance_gain() -> None:
    report = complete()
    for metric in ("autovacuum_cycle_max_min", "promote_hours", "purge_hours"):
        _set(report, metric, "A1", 8, 0.5)
        _set(report, metric, "A1", 4, 1.0)
    assert any(line.startswith("modulus: 8") for line in report.decide())
    for metric in ("autovacuum_cycle_max_min", "promote_hours", "purge_hours"):
        _set(report, metric, "A1", 8, 1.0)
    assert any(line.startswith("modulus: 4") for line in report.decide())


def test_the_decision_returns_to_the_requester_when_a1_misses_reads_at_both_moduli() -> None:
    report = complete()
    for modulus in (8, 4):
        _set(report, "page_warm:own", "A1", modulus, 500.0)
    assert any("DO-15" in line for line in report.decide())


def test_the_decision_tries_a2_and_a3_when_only_the_write_path_misses() -> None:
    report = complete()
    _set(report, "wal_mb_per_s", "A1", 8, 50.0)
    lines = report.decide()
    assert any("thử A2" in line for line in lines) and any("thử A3" in line for line in lines)


def test_a_series_stops_early_only_once_its_miss_is_certain() -> None:
    """51 of 1,000 above the limit decides the nearest-rank p95; 50 does not."""
    assert certain_miss([60.0] * 51, 50.0)
    assert not certain_miss([60.0] * 50 + [1.0] * 900, 50.0)
    report = complete()
    report.rows = [r for r in report.rows if r.key != ("page_cold:own", "A1", 8)]
    row = report.add_p95("R9.1", "page_cold:own", "A1", 8, [900.0] * 51, "page_p95_ms")
    assert row.stopped_early and row.verdict == "trượt"
    assert report.exit_code() == 0
    report.rows.remove(row)
    report.add_p95("R9.1", "page_cold:own", "A1", 8, [900.0] * 50, "page_p95_ms")
    assert report.exit_code() == 1, "50 slow samples settle nothing"


def test_asking_for_one_modulus_does_not_make_one_modulus_complete() -> None:
    """`--moduli 8` measures half a variant; the run is incomplete, whatever was asked."""
    report = complete()
    report.moduli = [8]
    report.rows = [r for r in report.rows if r.modulus != 4]
    assert report.exit_code() == 1
