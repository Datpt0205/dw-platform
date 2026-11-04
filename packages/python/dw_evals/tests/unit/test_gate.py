"""`evaluate_gate`, the one pure function deciding whether a gate run passes,
and its policy (agent-lifecycle ticket 02: R3.2, R3.4, R3.5)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dw_evals.dataset import CaseCategory
from dw_evals.gate import GatePolicy, GateVerdict, evaluate_gate
from dw_evals.runner import CaseResult, EvalReport

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
POLICY = GatePolicy(policy_id="studio_gate", version="1.0.0", security_pass_rate=1.0, pass_k=3)


def result(case_id: str, *, passed: bool = True, unknown: bool = False) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        category=CaseCategory.PROMPT_INJECTION,
        grader="eval.judge",
        passed=passed,
        unknown=unknown,
        trials=1,
        trials_passed=1 if passed else 0,
        reason_code=None if passed else "x",
    )


def report(*results: CaseResult) -> EvalReport:
    passed = sum(1 for r in results if r.passed)
    return EvalReport(
        dataset_id=None,
        dataset_version=None,
        worker_id=None,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        unknown=sum(1 for r in results if r.unknown),
        security_coverage_ok=True,
        results=results,
    )


def test_every_case_passing_passes_the_gate() -> None:
    assert evaluate_gate(report(result("a"), result("b")), POLICY) == GateVerdict(
        passed=True, reasons=()
    )


def test_an_empty_report_fails_with_no_cases() -> None:
    """R3.4: nothing run is never a pass."""
    assert evaluate_gate(report(), POLICY) == GateVerdict(passed=False, reasons=("no_cases",))


def test_an_unknown_case_fails_the_gate_naming_it() -> None:
    """R3.2: unknown blocks as failing does, under its own reason."""
    verdict = evaluate_gate(report(result("a"), result("b", passed=False, unknown=True)), POLICY)
    assert verdict == GateVerdict(passed=False, reasons=("case_unknown:b",))


def test_a_failing_case_fails_the_gate_naming_it() -> None:
    verdict = evaluate_gate(report(result("a", passed=False), result("b")), POLICY)
    assert verdict == GateVerdict(passed=False, reasons=("case_failed:a",))


def test_the_verdict_does_not_depend_on_the_order_the_cases_ran_in() -> None:
    """R3.4: the same report in another order, the same verdict."""
    cases = [
        result("c", passed=False),
        result("a", passed=False, unknown=True),
        result("b"),
        result("d", passed=False),
    ]
    forward = evaluate_gate(report(*cases), POLICY)
    backward = evaluate_gate(report(*reversed(cases)), POLICY)
    assert forward == backward
    assert forward.reasons == ("case_unknown:a", "case_failed:c", "case_failed:d")


def _policy(**values: Any) -> dict[str, Any]:
    return {**POLICY.model_dump(), **values}


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({"security_pass_rate": 0.99}, id="rate-below-one"),
        pytest.param({"security_pass_rate": 1.5}, id="rate-above-one"),
        pytest.param({"min_cases_total": 5}, id="field-nobody-reads"),
        pytest.param({"pass_k": 0}, id="pass-k-zero"),
        pytest.param({"pass_k": 11}, id="pass-k-eleven"),
        pytest.param({"version": "v1"}, id="version-not-semver"),
    ],
)
def test_a_policy_is_refused_unless_it_is_well_formed(values: dict[str, Any]) -> None:
    """R3.4: an unknown field or a security rate other than 1.0 is refused."""
    with pytest.raises(ValidationError):
        GatePolicy.model_validate(_policy(**values))


def test_a_policy_must_state_its_security_rate() -> None:
    values = _policy()
    del values["security_pass_rate"]
    with pytest.raises(ValidationError):
        GatePolicy.model_validate(values)


def test_the_platform_core_contract_keeps_studio_out_of_dw_evals() -> None:
    """R3.5: the contract is studio-skeleton R5.1's, not a second copy; this
    only fails if `dw_evals` leaves it. That `lint-imports` reports a planted
    `import dw_studio` was seen by hand (ticket 02's Comments)."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        contracts = tomllib.load(handle)["tool"]["importlinter"]["contracts"]
    [core] = [c for c in contracts if c["name"] == "Platform core does not import Studio"]
    assert core["type"] == "forbidden"
    assert "dw_evals" in core["source_modules"]
    assert core["forbidden_modules"] == ["dw_studio"]
