"""Grades of a trial's observation, the judge behind its port, and one table
of graders of either kind (agent-lifecycle ticket 02: R3.2)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from dw_evals.dataset import EvalCase
from dw_evals.graders import (
    GRADERS,
    GradeResult,
    JudgeVerdict,
    Observation,
    ObservationGrader,
    ObservedToolCall,
    judge_grader,
    merge_graders,
)
from dw_evals.testing import ScriptedJudge

pytestmark = pytest.mark.unit

SHA = "a" * 64


def make_case(case_id: str = "c1", **values: Any) -> EvalCase:
    stated: dict[str, Any] = {
        "input": {"case_id": case_id, "message": "xin báo giá"},
        "expected": {"reply_mentions": "báo giá"},
        **values,
    }
    return EvalCase.model_validate(
        {
            "case_id": case_id,
            "category": "prompt_injection",
            "description": "d",
            "grader": "eval.judge",
            **stated,
        }
    )


def observe(**values: Any) -> Observation:
    return Observation.model_validate(
        {"final_output": {"reply": "ok"}, "cost_usd": "0.01", "latency_ms": 5, **values}
    )


# ----------------------------------------------------------- GradeResult --


def test_a_grade_cannot_both_pass_and_be_unknown() -> None:
    """R3.2: refused when built, so no door can count it as a pass."""
    with pytest.raises(ValidationError, match="both pass and be unknown"):
        GradeResult(passed=True, unknown=True)


def test_abstain_is_an_unknown_failing_grade_with_its_reason() -> None:
    grade = GradeResult.abstain("judge_abstained", reasons=["unsure"])
    assert (grade.passed, grade.unknown) == (False, True)
    assert grade.details == {"reason": "judge_abstained", "reasons": ["unsure"]}
    assert GradeResult.ok().unknown is False and GradeResult.ok().score is None


# ----------------------------------------------------------- Observation --


def test_an_observation_carries_what_a_trial_did() -> None:
    observation = observe(
        tool_calls=[
            {
                "tool": "email.send@1.0.0",
                "side_effect_level": "external",
                "simulated": True,
                "args_sha256": SHA,
            }
        ],
        approval_requests=["studio.publish.agent"],
        evidence_refs=["ev-1"],
        error_code=None,
    )
    assert observation.tool_calls[0].simulated is True
    assert observation.cost_usd == Decimal("0.01")


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({"tool": "email.send"}, id="tool-without-version"),
        pytest.param({"tool": "a@b@c"}, id="tool-two-ats"),
        pytest.param({"side_effect_level": "loud"}, id="unknown-level"),
        pytest.param({"args_sha256": "A" * 64}, id="hash-uppercase"),
        pytest.param({"args_sha256": "a" * 63}, id="hash-short"),
        pytest.param({"args": {"to": "x"}}, id="raw-arguments"),
    ],
)
def test_a_tool_call_is_refused_unless_it_is_well_formed(values: dict[str, Any]) -> None:
    call = {
        "tool": "email.send@1.0.0",
        "side_effect_level": "external",
        "simulated": False,
        "args_sha256": SHA,
        **values,
    }
    with pytest.raises(ValidationError):
        ObservedToolCall.model_validate(call)


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({"cost_usd": "-0.01"}, id="negative-cost"),
        pytest.param({"latency_ms": -1}, id="negative-latency"),
        pytest.param({"simulated_effects": []}, id="unknown-field"),
    ],
)
def test_an_observation_is_refused_unless_it_is_well_formed(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        observe(**values)


def test_an_observation_cannot_be_changed() -> None:
    observation = observe()
    with pytest.raises(ValidationError):
        observation.latency_ms = 1  # type: ignore[misc]


# ----------------------------------------------------------------- judge --


async def test_the_judge_is_asked_about_the_output_with_the_case() -> None:
    judge = ScriptedJudge({"c1": JudgeVerdict(verdict="pass", reasons=("fine",), score=0.9)})
    asked: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    real = judge.judge

    async def spy(
        rubric: str, case_input: dict[str, Any], output: dict[str, Any], reference: dict[str, Any]
    ) -> JudgeVerdict:
        asked.append((rubric, case_input, output, reference))
        return await real(rubric, case_input, output, reference)

    judge.judge = spy  # type: ignore[method-assign]
    grade = await judge_grader(judge, "rubric-v1")(make_case(), observe())
    assert grade.passed and grade.score == 0.9 and grade.details == {"reasons": ["fine"]}
    case = make_case()
    assert asked == [("rubric-v1", case.input, {"reply": "ok"}, case.expected)]


@pytest.mark.parametrize(
    ("verdict", "passed", "unknown", "reason"),
    [
        ("pass", True, False, None),
        ("fail", False, False, "judge_failed"),
        ("abstain", False, True, "judge_abstained"),
    ],
)
async def test_each_verdict_becomes_its_grade(
    verdict: str, passed: bool, unknown: bool, reason: str | None
) -> None:
    """R3.2: `abstain` is unknown, `fail` fails with the judge's reasons."""
    judge = ScriptedJudge(
        {"c1": JudgeVerdict.model_validate({"verdict": verdict, "reasons": ["r"]})}
    )
    grade = await judge_grader(judge, "rubric")(make_case(), observe())
    assert (grade.passed, grade.unknown) == (passed, unknown)
    assert grade.details.get("reason") == reason
    assert grade.details["reasons"] == ["r"]
    assert judge.calls == ["c1"]


async def test_a_trial_with_no_output_fails_without_asking_the_judge() -> None:
    judge = ScriptedJudge({})
    grade = await judge_grader(judge, "rubric")(
        make_case(), observe(final_output=None, error_code="timeout")
    )
    assert not grade.passed and not grade.unknown
    assert grade.details == {"reason": "no_final_output", "error_code": "timeout"}
    assert judge.calls == []


async def test_a_case_stated_by_reference_is_unknown_without_asking_the_judge() -> None:
    """A file reference is nothing the judge can read: unknown, never a pass."""
    judge = ScriptedJudge({})
    case = make_case(input=None, input_ref="evals/fixtures/cases/pf_side_effect.json")
    grade = await judge_grader(judge, "rubric")(case, observe())
    assert grade.unknown and grade.details["reason"] == "judge_needs_inline_case"
    assert judge.calls == []


def test_a_verdict_outside_the_three_is_refused() -> None:
    with pytest.raises(ValidationError):
        JudgeVerdict.model_validate({"verdict": "maybe"})


# ------------------------------------------------------- one table, two kinds --


def test_merge_graders_merges_observation_graders_and_refuses_a_name_twice() -> None:
    """The same function, generic over the kind of grader."""
    grader: ObservationGrader = judge_grader(ScriptedJudge({}), "rubric")
    merged = merge_graders({"studio.a": grader}, {"studio.b": grader})
    assert set(merged) == {"studio.a", "studio.b"}
    with pytest.raises(ValueError, match=r"studio\.a"):
        merge_graders({"studio.a": grader}, {"studio.a": grader})
    assert set(merge_graders(GRADERS)) == set(GRADERS)
