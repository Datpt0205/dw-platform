"""Evaluation runner: cases → graded results → versioned report.

Two runners, one report. `run_dataset` grades a dataset's fixtures once with
the deterministic CI graders, as `make eval-smoke` does. `run_cases` runs each
case against an `EvalTargetPort`, once per trial, and grades every trial's
`Observation` (agent-lifecycle R3.1): a case passes only when all its trials
pass. Whether a whole run passes is not decided here but by
`dw_evals.gate.evaluate_gate`. Reports are plain JSON under evals/reports.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from dw_evals.dataset import (
    CaseCategory,
    EvalCase,
    EvalDataset,
    has_full_security_coverage,
)
from dw_evals.graders import (
    Grader,
    GraderContext,
    GradeResult,
    Observation,
    ObservationGrader,
)

# The tag of a case run `pass_k` times rather than its own `trials` (R3.1).
CONSISTENCY_TAG = "consistency"


class CaseResult(BaseModel):
    """One case's result over its trials. `unknown` when any trial was;
    `reason_code` is the reason of the first trial that failed, None when the
    case passed."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    category: CaseCategory
    grader: str
    passed: bool
    unknown: bool = False
    trials: int = 1
    trials_passed: int = 0
    reason_code: str | None = None
    details: dict[str, Any] = {}


class CategoryCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    passed: int
    failed: int
    unknown: int


class EvalReport(BaseModel):
    """A run's results. An unknown case counts in `failed` as well as in
    `unknown`. A report of `run_cases` names no dataset: its cases may come
    from several."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str | None
    dataset_version: str | None
    worker_id: str | None
    total: int
    passed: int
    failed: int
    unknown: int = 0
    by_category: dict[CaseCategory, CategoryCount] = {}
    security_coverage_ok: bool
    results: tuple[CaseResult, ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.security_coverage_ok


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _load_ref(repo_root: Path, ref: str) -> dict[str, Any]:
    resolved = (repo_root / ref).resolve()
    if not resolved.is_relative_to(repo_root.resolve()):
        raise ValueError(f"case ref escapes the repository: {ref}")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"case ref must contain a JSON object: {ref}")
    return data


def _value(repo_root: Path, inline: dict[str, Any] | None, ref: str | None) -> dict[str, Any]:
    """A case's inline value when it has one, its file reference's otherwise;
    `EvalCase` holds exactly one of the two."""
    if inline is not None:
        return inline
    if ref is None:
        raise ValueError("a case states neither a reference nor an inline value")
    return _load_ref(repo_root, ref)


def _reason(result: GradeResult) -> str:
    reason = result.details.get("reason")
    return "failed" if reason is None else str(reason)


def _grade(
    ctx: GraderContext, repo_root: Path, case: EvalCase, graders: Mapping[str, Grader]
) -> GradeResult:
    grader = graders.get(case.grader)
    if grader is None:
        return GradeResult.fail("unknown grader", grader=case.grader)
    try:
        input_data = _value(repo_root, case.input, case.input_ref)
        expected = _value(repo_root, case.expected, case.expected_ref)
        return grader(ctx, input_data, expected)
    except Exception as exc:  # a crashing grader is a failing case, not a crash
        return GradeResult.fail("grader raised", error=f"{type(exc).__name__}: {exc}")


def _report(
    results: tuple[CaseResult, ...],
    *,
    security_coverage_ok: bool,
    dataset: EvalDataset | None = None,
) -> EvalReport:
    by_category: dict[CaseCategory, CategoryCount] = {}
    for category in sorted({r.category for r in results}):
        own = [r for r in results if r.category == category]
        own_passed = sum(1 for r in own if r.passed)
        by_category[category] = CategoryCount(
            total=len(own),
            passed=own_passed,
            failed=len(own) - own_passed,
            unknown=sum(1 for r in own if r.unknown),
        )
    passed = sum(1 for r in results if r.passed)
    return EvalReport(
        dataset_id=dataset.dataset_id if dataset else None,
        dataset_version=dataset.dataset_version if dataset else None,
        worker_id=dataset.worker_id if dataset else None,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        unknown=sum(1 for r in results if r.unknown),
        by_category=by_category,
        security_coverage_ok=security_coverage_ok,
        results=results,
    )


def run_dataset(dataset: EvalDataset, repo_root: Path, graders: Mapping[str, Grader]) -> EvalReport:
    """Grade every case once with `graders`, the ONLY table consulted: the
    caller (the eval composition root) decides which graders exist. No
    default, so a caller that forgets the table is a type error, not an empty
    table. A case's `trials` is not read: the CI graders are deterministic."""
    ctx = GraderContext(repo_root=repo_root)
    results = tuple(
        CaseResult(
            case_id=case.case_id,
            category=case.category,
            grader=case.grader,
            passed=(result := _grade(ctx, repo_root, case, graders)).passed,
            unknown=result.unknown,
            trials=1,
            trials_passed=1 if result.passed else 0,
            reason_code=None if result.passed else _reason(result),
            details=result.details,
        )
        for case in dataset.cases
    )
    return _report(
        results, security_coverage_ok=dataset.has_full_security_coverage(), dataset=dataset
    )


# ------------------------------------------------------------------ trials --
class EvalTargetPort(Protocol):
    """Runs one trial of a case and reports what it did; trials count from 1.
    The real target, a Studio run in simulate mode, is wired at the worker's
    composition root (agent-lifecycle ticket 06);
    `dw_evals.testing.RecordedTarget` replays recorded observations."""

    async def run(self, case: EvalCase, trial: int) -> Observation: ...


async def _trial(
    case: EvalCase, trial: int, target: EvalTargetPort, grader: ObservationGrader
) -> GradeResult:
    try:
        observation = await target.run(case, trial)
    except Exception as exc:  # a target that crashed is a failing trial
        return GradeResult.fail("target_error", error=f"{type(exc).__name__}: {exc}")
    try:
        return await grader(case, observation)
    except Exception as exc:  # a crashing grader is a failing trial, not a crash
        return GradeResult.fail("grader raised", error=f"{type(exc).__name__}: {exc}")


async def _run_case(
    case: EvalCase,
    target: EvalTargetPort,
    graders: Mapping[str, ObservationGrader],
    pass_k: int,
) -> CaseResult:
    grader = graders.get(case.grader)
    if grader is None:  # nothing could grade it, so no trial is run
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            grader=case.grader,
            passed=False,
            trials=0,
            reason_code="unknown grader",
            details={"reason": "unknown grader", "grader": case.grader},
        )
    count = pass_k if CONSISTENCY_TAG in case.tags else case.trials
    grades = [await _trial(case, n, target, grader) for n in range(1, count + 1)]
    first_failed = next((g for g in grades if not g.passed), None)
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        grader=case.grader,
        passed=first_failed is None,
        unknown=any(g.unknown for g in grades),
        trials=count,
        trials_passed=sum(1 for g in grades if g.passed),
        reason_code=None if first_failed is None else _reason(first_failed),
        details={"trials": [g.model_dump(mode="json") for g in grades]},
    )


async def run_cases(
    cases: Sequence[EvalCase],
    target: EvalTargetPort,
    graders: Mapping[str, ObservationGrader],
    *,
    pass_k: int,
) -> EvalReport:
    """Run and grade every case, one trial after another: a case tagged
    `consistency` `pass_k` times, any other its own `trials` times, passing
    only if every trial passes (R3.1). `pass_k` is the gate policy's
    (`GatePolicy.pass_k`), its one owner; `graders` is the only table
    consulted, as for `run_dataset`."""
    if not 1 <= pass_k <= 10:
        raise ValueError(f"pass_k must be between 1 and 10, not {pass_k}")
    twice = sorted(i for i, n in Counter(c.case_id for c in cases).items() if n > 1)
    if twice:
        raise ValueError(f"case_id values must be unique: {twice}")
    results = tuple([await _run_case(case, target, graders, pass_k) for case in cases])
    return _report(
        results, security_coverage_ok=has_full_security_coverage(c.category for c in cases)
    )


def write_report(report: EvalReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report.dataset_id}@{report.dataset_version}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
