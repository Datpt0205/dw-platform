# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""The real-path report's own rules (custom-objects ticket 04 step 7, R9.1).

Exit 0 only when every series of every profile has its samples and counted
a `RecordService` call, and the import and the soak did too: a measurement
that never reached the service is a hole (failure-modes #3). Every number is
labelled smoke and none is judged against a threshold.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from ..real_path import (
    LABEL,
    PROFILES,
    SERIES,
    CountedService,
    RealPathReport,
)

pytestmark = pytest.mark.unit


def full(minimum: int = 2) -> RealPathReport:
    report = RealPathReport("tiny", minimum=minimum)
    for profile in PROFILES:
        for series in SERIES:
            key = f"{profile}/{series}"
            for millis in range(minimum):
                report.add(key, float(millis + 1))
            report.calls[key] = minimum + 1
    report.calls["import"] = 10
    report.calls["soak"] = 10
    return report


def test_a_complete_report_exits_zero_and_says_smoke() -> None:
    report = full()
    assert report.exit_code() == 0 and report.problems() == []
    text = report.markdown()
    assert LABEL in text and LABEL in json.loads(report.to_json())["label"]
    # Nothing is judged against R9's thresholds.
    assert "đạt" not in text and "trượt" not in text


def test_a_series_the_service_never_saw_exits_one() -> None:
    report = full()
    report.calls["own/get"] = 0
    assert report.exit_code() == 1
    assert report.problems() == ["own/get: RecordService không được gọi"]


def test_a_series_short_of_samples_or_a_silent_import_exits_one() -> None:
    report = full()
    report.samples["company/create"].pop()
    report.calls.pop("soak")
    assert report.exit_code() == 1
    assert report.problems() == [
        "company/create: 1 mẫu",
        "soak: RecordService không được gọi",
    ]


def test_the_counted_service_counts_what_it_forwards() -> None:
    class Fake:
        async def get(self, *args: object) -> tuple[object, ...]:
            return args

    counted = CountedService(Fake())
    assert asyncio.run(counted.call("own/get", "get", 1, 2)) == (1, 2)
    assert counted.calls == {"own/get": 1}
