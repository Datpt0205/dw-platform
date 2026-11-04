from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dw_evals.dataset import SECURITY_CATEGORIES, CaseCategory, EvalCase, EvalDataset
from dw_evals.graders import GraderContext, GradeResult
from dw_evals.runner import run_dataset

pytestmark = pytest.mark.unit


def make_case(case_id: str, category: CaseCategory) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        category=category,
        description="d",
        input_ref=f"evals/datasets/demo/{case_id}.json",
        expected_ref=f"evals/expected/demo/{case_id}.json",
        grader="deterministic.action_match",
    )


def make_dataset(cases: list[EvalCase]) -> EvalDataset:
    return EvalDataset(
        dataset_id="demo_golden",
        dataset_version="1.0.0",
        worker_id="demo",
        cases=tuple(cases),
    )


def test_dataset_version_must_be_semver() -> None:
    with pytest.raises(ValidationError):
        EvalDataset(dataset_id="x", dataset_version="v1", worker_id="demo", cases=())


def test_duplicate_case_ids_rejected() -> None:
    case = make_case("c1", CaseCategory.NORMAL)
    with pytest.raises(ValidationError):
        make_dataset([case, case])


def test_security_coverage_detection() -> None:
    partial = make_dataset(
        [
            make_case("c1", CaseCategory.NORMAL),
            make_case("c2", CaseCategory.PROMPT_INJECTION),
        ]
    )
    assert not partial.has_full_security_coverage()

    full = make_dataset(
        [
            make_case("c1", CaseCategory.PROMPT_INJECTION),
            make_case("c2", CaseCategory.CROSS_TENANT_ATTACK),
            make_case("c3", CaseCategory.MISSING_EVIDENCE),
        ]
    )
    assert full.has_full_security_coverage()


# ------------------------------------------- R3.3: a reference or inline --

REF = {"input_ref": "evals/fixtures/cases/pf_side_effect.json"}
EXP = {"expected_ref": "evals/expected/pf_side_effect.json"}


def _case(**values: Any) -> dict[str, Any]:
    return {"case_id": "c1", "category": "normal", "description": "d", "grader": "x.y", **values}


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({**REF, "input": {"a": 1}, **EXP}, id="input-both"),
        pytest.param({**EXP}, id="input-neither"),
        pytest.param({**REF, **EXP, "expected": {"b": 2}}, id="expected-both"),
        pytest.param({**REF}, id="expected-neither"),
        pytest.param({}, id="all-neither"),
    ],
)
def test_a_value_stated_both_ways_or_neither_is_refused(values: dict[str, Any]) -> None:
    """R3.3: refused when validated, so the case never reaches a runner."""
    with pytest.raises(ValidationError, match="state exactly one of"):
        EvalCase.model_validate(_case(**values))
    with pytest.raises(ValidationError):
        EvalDataset.model_validate(
            {
                "dataset_id": "d",
                "dataset_version": "1.0.0",
                "worker_id": "w",
                "cases": [_case(**values)],
            }
        )


def test_an_inline_case_runs_through_run_dataset_with_its_values() -> None:
    """R3.3: `run_dataset` hands the grader the inline values."""
    seen: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def grader(
        ctx: GraderContext, input_data: dict[str, Any], expected: dict[str, Any]
    ) -> GradeResult:
        seen.append((input_data, expected))
        return GradeResult.ok()

    dataset = EvalDataset.model_validate(
        {
            "dataset_id": "inline",
            "dataset_version": "1.0.0",
            "worker_id": "dw.test",
            "cases": [_case(input={"q": "hello"}, expected={"a": "world"}, grader="x.inline")],
        }
    )
    report = run_dataset(dataset, Path("/nonexistent"), {"x.inline": grader})
    assert seen == [({"q": "hello"}, {"a": "world"})]
    assert report.results[0].passed and report.results[0].trials_passed == 1


def test_trials_default_to_one_and_stay_within_one_to_ten() -> None:
    assert EvalCase.model_validate(_case(**REF, **EXP)).trials == 1
    for wrong in (0, 11):
        with pytest.raises(ValidationError):
            EvalCase.model_validate(_case(**REF, **EXP, trials=wrong))


def test_the_ci_security_categories_did_not_change() -> None:
    """G1: the new category is the gate suite's, not a CI coverage rule."""
    assert {
        CaseCategory.PROMPT_INJECTION,
        CaseCategory.CROSS_TENANT_ATTACK,
        CaseCategory.MISSING_EVIDENCE,
    } == SECURITY_CATEGORIES
    assert CaseCategory.SIDE_EFFECT_WITHOUT_APPROVAL.value == "side_effect_without_approval"
