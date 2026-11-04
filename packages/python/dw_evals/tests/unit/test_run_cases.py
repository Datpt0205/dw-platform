"""`run_cases`: k trials of a case against a target, every trial graded, a
case passing only when all of them pass (agent-lifecycle ticket 02: R3.1,
R3.2)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from dw_evals.dataset import CaseCategory, EvalCase
from dw_evals.graders import GradeResult, Observation
from dw_evals.runner import run_cases

pytestmark = pytest.mark.unit


def make_case(case_id: str, *, tags: frozenset[str] = frozenset(), **values: Any) -> EvalCase:
    return EvalCase.model_validate(
        {
            "case_id": case_id,
            "category": "prompt_injection",
            "description": "d",
            "input": {"q": case_id},
            "expected": {},
            "grader": "fake.grade",
            "tags": tags,
            **values,
        }
    )


CONSISTENT = frozenset({"consistency"})


def observation(**values: Any) -> Observation:
    return Observation.model_validate(
        {"final_output": {}, "cost_usd": "0", "latency_ms": 0, **values}
    )


@dataclass
class CountingTarget:
    """`EvalTargetPort`: one observation per trial, every call recorded."""

    fail_on: set[tuple[str, int]] = field(default_factory=set)
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def run(self, case: EvalCase, trial: int) -> Observation:
        self.calls.append((case.case_id, trial))
        if (case.case_id, trial) in self.fail_on:
            raise RuntimeError("target down")
        return observation(latency_ms=trial)


def scripted(*grades: GradeResult) -> Any:
    """An `ObservationGrader` answering with `grades`, one per call."""
    answers: Iterator[GradeResult] = iter(grades)

    async def grade(case: EvalCase, observation: Observation) -> GradeResult:
        return next(answers)

    return grade


PASS, FAIL = GradeResult.ok(), GradeResult.fail("wrong")


async def test_a_consistency_case_fails_when_one_of_its_k_trials_fails() -> None:
    """R3.1: pass, fail, pass → the case fails, 3 trials, 2 passed, 3 calls."""
    target = CountingTarget()
    report = await run_cases(
        [make_case("c1", tags=CONSISTENT)],
        target,
        {"fake.grade": scripted(PASS, FAIL, PASS)},
        pass_k=3,
    )
    [result] = report.results
    assert (result.passed, result.trials, result.trials_passed) == (False, 3, 2)
    assert result.reason_code == "wrong" and not result.unknown
    assert target.calls == [("c1", 1), ("c1", 2), ("c1", 3)]


async def test_a_consistency_case_passes_when_all_k_trials_pass() -> None:
    """R3.1."""
    target = CountingTarget()
    report = await run_cases(
        [make_case("c1", tags=CONSISTENT)],
        target,
        {"fake.grade": scripted(PASS, PASS, PASS)},
        pass_k=3,
    )
    [result] = report.results
    assert (result.passed, result.trials, result.trials_passed) == (True, 3, 3)
    assert result.reason_code is None
    assert len(target.calls) == 3
    assert (report.passed, report.failed, report.unknown) == (1, 0, 0)


async def test_a_case_without_the_tag_runs_its_own_trials_whatever_pass_k() -> None:
    """R3.1: `trials = 1` → one call though `pass_k = 3`; `trials = 2` → two."""
    target = CountingTarget()
    report = await run_cases(
        [make_case("one"), make_case("two", trials=2)],
        target,
        {"fake.grade": scripted(PASS, PASS, PASS)},
        pass_k=3,
    )
    assert target.calls == [("one", 1), ("two", 1), ("two", 2)]
    assert [r.trials for r in report.results] == [1, 2]


async def test_one_unknown_trial_makes_the_case_unknown_and_failing() -> None:
    """R3.2: an abstaining grader is never a pass, in the case and the report."""
    report = await run_cases(
        [make_case("c1", tags=CONSISTENT)],
        CountingTarget(),
        {"fake.grade": scripted(PASS, GradeResult.abstain("judge_abstained"), PASS)},
        pass_k=3,
    )
    [result] = report.results
    assert result.unknown and not result.passed
    assert result.reason_code == "judge_abstained"
    assert (report.failed, report.unknown, report.passed) == (1, 1, 0)
    assert not report.ok


async def test_an_unknown_grader_fails_the_case_and_runs_no_trial() -> None:
    target = CountingTarget()
    report = await run_cases([make_case("c1")], target, {}, pass_k=3)
    [result] = report.results
    assert not result.passed and result.trials == 0
    assert result.reason_code == "unknown grader"
    assert target.calls == []


async def test_a_grader_that_raises_fails_its_trial() -> None:
    async def broken(case: EvalCase, observation: Observation) -> GradeResult:
        raise KeyError("verdict")

    report = await run_cases([make_case("c1")], CountingTarget(), {"fake.grade": broken}, pass_k=1)
    [result] = report.results
    assert not result.passed and not result.unknown
    assert result.reason_code == "grader raised"


async def test_a_target_that_raises_fails_its_trial_and_the_rest_still_run() -> None:
    target = CountingTarget(fail_on={("c1", 2)})
    report = await run_cases(
        [make_case("c1", tags=CONSISTENT)],
        target,
        {"fake.grade": scripted(PASS, PASS)},
        pass_k=3,
    )
    [result] = report.results
    assert (result.passed, result.trials_passed) == (False, 2)
    assert result.reason_code == "target_error"
    assert len(target.calls) == 3


async def test_the_report_counts_each_category() -> None:
    report = await run_cases(
        [
            make_case("a"),
            make_case("b", category="side_effect_without_approval"),
            make_case("c", category="side_effect_without_approval"),
        ],
        CountingTarget(),
        {"fake.grade": scripted(PASS, FAIL, GradeResult.abstain("x"))},
        pass_k=1,
    )
    injection = report.by_category[CaseCategory.PROMPT_INJECTION]
    side_effect = report.by_category[CaseCategory.SIDE_EFFECT_WITHOUT_APPROVAL]
    assert (injection.total, injection.passed, injection.failed, injection.unknown) == (1, 1, 0, 0)
    assert (side_effect.total, side_effect.passed, side_effect.failed, side_effect.unknown) == (
        2,
        0,
        2,
        1,
    )
    assert report.dataset_id is None and not report.security_coverage_ok


@pytest.mark.parametrize("pass_k", [0, 11])
async def test_pass_k_outside_one_to_ten_is_refused(pass_k: int) -> None:
    with pytest.raises(ValueError, match="pass_k"):
        await run_cases([make_case("c1")], CountingTarget(), {}, pass_k=pass_k)


async def test_two_cases_with_one_id_are_refused() -> None:
    target = CountingTarget()
    with pytest.raises(ValueError, match="unique"):
        await run_cases([make_case("c1"), make_case("c1")], target, {}, pass_k=1)
    assert target.calls == []
