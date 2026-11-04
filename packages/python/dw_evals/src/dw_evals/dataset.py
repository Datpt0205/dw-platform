"""Versioned evaluation dataset schema.

Every worker ships normal/boundary/exception/failure cases plus security cases
(prompt injection, cross-tenant attack, missing evidence, ambiguous identity).
A case states its input and its expected outcome either as a file reference or
inline, each exactly one way (agent-lifecycle R3.3).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CaseCategory(StrEnum):
    NORMAL = "normal"
    BOUNDARY = "boundary"
    EXCEPTION = "exception"
    FAILURE = "failure"
    PROMPT_INJECTION = "prompt_injection"
    CROSS_TENANT_ATTACK = "cross_tenant_attack"
    MISSING_EVIDENCE = "missing_evidence"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    # A side effect taken without the approval its tool requires: a case of the
    # platform's security suite (agent-lifecycle ticket 06), not a CI coverage
    # requirement, so `SECURITY_CATEGORIES` does not change (G1).
    SIDE_EFFECT_WITHOUT_APPROVAL = "side_effect_without_approval"


SECURITY_CATEGORIES = frozenset(
    {
        CaseCategory.PROMPT_INJECTION,
        CaseCategory.CROSS_TENANT_ATTACK,
        CaseCategory.MISSING_EVIDENCE,
    }
)


def has_full_security_coverage(categories: Iterable[CaseCategory]) -> bool:
    """Whether cases of these categories cover every security category."""
    return frozenset(categories) >= SECURITY_CATEGORIES


class EvalCase(BaseModel):
    """One test case: its input and its expected outcome, each as a file
    reference (`*_ref`) or inline, never both and never neither (R3.3).

    `trials` is how often `run_cases` runs a case not tagged `consistency`; a
    `consistency` case runs the gate policy's `pass_k` times instead (R3.1).
    `run_dataset` grades once: the CI graders are deterministic."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(min_length=1)
    category: CaseCategory
    description: str
    input_ref: str | None = None
    expected_ref: str | None = None
    input: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    grader: str = Field(min_length=1)
    tags: frozenset[str] = frozenset()
    trials: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def _each_value_stated_exactly_once(self) -> EvalCase:
        for name, ref, inline in (
            ("input", self.input_ref, self.input),
            ("expected", self.expected_ref, self.expected),
        ):
            if (ref is None) == (inline is None):
                raise ValueError(f"{name}: state exactly one of {name}_ref and an inline {name}")
        return self


class EvalDataset(BaseModel):
    """Immutable, versioned dataset for one worker."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    worker_id: str
    cases: tuple[EvalCase, ...]

    @field_validator("cases")
    @classmethod
    def _case_ids_unique(cls, cases: tuple[EvalCase, ...]) -> tuple[EvalCase, ...]:
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id values must be unique within a dataset")
        return cases

    def security_coverage(self) -> frozenset[CaseCategory]:
        """Security categories present; the release gate requires all of them."""
        return frozenset(c.category for c in self.cases) & SECURITY_CATEGORIES

    def has_full_security_coverage(self) -> bool:
        return has_full_security_coverage(c.category for c in self.cases)
