"""Whether a gate run passes: one pure function of a report and a policy.

`evaluate_gate` is the one owner of "does this gate run pass" (ADR-0120
decision 4; agent-lifecycle R3.4): it reads its two arguments and nothing
else, no clock, no store, no setting. "Did this case pass over its k trials"
is `run_cases`'s (R3.1), and arrives here as `CaseResult.passed`.

In W1 the gate runs only the platform's security suite (agent-lifecycle R4.1),
so every case is a security case and `security_pass_rate` is 1.0: one case
failing, or unknown, fails the gate. The scenario cases and their rule are
agent-lifecycle ticket 06's.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dw_evals.runner import EvalReport


class GatePolicy(BaseModel):
    """The gate's versioned policy, only the fields something reads: `pass_k`
    by the caller of `run_cases`, `security_pass_rate` by `evaluate_gate`'s
    rules (1.0, so no case may fail; a policy stating less is refused)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    # Exactly 1.0: typing has no float Literal, so the field's bounds hold it.
    security_pass_rate: float = Field(ge=1.0, le=1.0)
    pass_k: int = Field(ge=1, le=10)


class GateVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    reasons: tuple[str, ...]


def evaluate_gate(report: EvalReport, policy: GatePolicy) -> GateVerdict:
    """Pass only with no reason against it: `no_cases` for an empty report,
    `case_unknown:<case_id>` for each unknown case and `case_failed:<case_id>`
    for each other failing one, ordered by case id so the order the cases ran
    in cannot change the verdict. With `policy.security_pass_rate` at 1.0,
    each case short of passing is a reason."""
    if not report.results:
        return GateVerdict(passed=False, reasons=("no_cases",))
    reasons: list[str] = []
    for result in sorted(report.results, key=lambda r: r.case_id):
        if result.passed:
            continue
        rule = "case_unknown" if result.unknown else "case_failed"
        reasons.append(f"{rule}:{result.case_id}")
    return GateVerdict(passed=not reasons, reasons=tuple(reasons))
