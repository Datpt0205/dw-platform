"""`dw_kernel.personal_data`: the vocabulary and the pure check owners call (compliance-pdpl R1).

The HTTP half (422 `validation_failed`, nothing created) belongs to each table
owner (custom-objects R2.2, workflow-triggers R4.1); this proves the codes and
pointers those owners return.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

import dw_kernel.personal_data as personal_data
from dw_kernel.personal_data import (
    ClassificationCode,
    ClassificationProblem,
    PdCategory,
    SensitiveType,
    SubjectIdentifierKind,
    classification_problems,
)

pytestmark = pytest.mark.unit

# How Vietnamese legal texts letter the points of a clause: the Vietnamese
# alphabet without its accented vowels, f, j, w and z, with đ after d.
_POINT_LETTERS = list("abcdđeghiklmnopqrstuvxy")


@dataclass(frozen=True)
class _Field:
    pd_category: PdCategory | None
    sensitive_type: SensitiveType | None = None
    subject_identifier: SubjectIdentifierKind | None = None


def _documented_points() -> int:
    match = re.search(r"has\s+(\d+)\s+lettered\s+points", personal_data.__doc__ or "")
    assert match, "the module docstring states how many lettered points Art. 4.1 has"
    return int(match.group(1))


def test_sensitive_types_are_one_per_lettered_point_of_article_4_1() -> None:
    """R1.4: as many members as the docstring says the clause has, lettered in
    the clause's own order, so a point added or dropped goes red here."""
    count = _documented_points()
    assert len(SensitiveType) == count
    assert [member.point for member in SensitiveType] == _POINT_LETTERS[:count]


def test_sensitive_types_have_no_catch_all() -> None:
    values = [member.value for member in SensitiveType]
    assert "other" not in values
    assert len(set(values)) == len(values)
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", value) for value in values)


def test_the_category_and_identifier_lists_are_the_specs() -> None:
    """R1.2: the list every CHECK on `pd_category` must equal."""
    assert [m.value for m in PdCategory] == ["none", "basic", "sensitive"]
    assert [m.value for m in SubjectIdentifierKind] == [
        "email",
        "phone",
        "national_id",
        "zalo_user_id",
        "facebook_psid",
        "tax_code",
        "bank_account",
    ]


def test_a_field_without_a_category_is_one_problem_at_its_pointer() -> None:
    """R1.1 (CP1): the second of three fields has no category."""
    fields = [
        ("/fields/0", _Field(PdCategory.BASIC, subject_identifier=SubjectIdentifierKind.EMAIL)),
        ("/fields/1", _Field(None)),
        ("/fields/2", _Field(PdCategory.NONE)),
    ]
    assert classification_problems(fields) == [
        ClassificationProblem(ClassificationCode.PD_CATEGORY_REQUIRED, "/fields/1")
    ]
    assert classification_problems([fields[0], fields[2]]) == []


def test_sensitive_type_is_required_on_sensitive_and_refused_elsewhere() -> None:
    """R1.5: both refusals in one call, each at its own pointer, and every
    field is checked rather than the first problem ending the walk."""
    fields = [
        ("/fields/0", _Field(PdCategory.SENSITIVE)),
        ("/fields/1", _Field(PdCategory.BASIC, sensitive_type=SensitiveType.HEALTH)),
        ("/fields/2", _Field(PdCategory.NONE, sensitive_type=SensitiveType.LOCATION)),
        ("/fields/3", _Field(PdCategory.SENSITIVE, sensitive_type=SensitiveType.HEALTH)),
    ]
    assert classification_problems(fields) == [
        ClassificationProblem(ClassificationCode.SENSITIVE_TYPE_REQUIRED, "/fields/0"),
        ClassificationProblem(
            ClassificationCode.SENSITIVE_TYPE_NOT_ALLOWED, "/fields/1/sensitive_type"
        ),
        ClassificationProblem(
            ClassificationCode.SENSITIVE_TYPE_NOT_ALLOWED, "/fields/2/sensitive_type"
        ),
    ]


def test_a_subject_identifier_is_refused_on_a_field_with_no_personal_data() -> None:
    """A subject identifier is personal data, so `none` cannot carry one;
    `basic` and `sensitive` can."""
    fields = [
        ("/fields/0", _Field(PdCategory.NONE, subject_identifier=SubjectIdentifierKind.PHONE)),
        ("/fields/1", _Field(PdCategory.BASIC, subject_identifier=SubjectIdentifierKind.PHONE)),
        (
            "/fields/2",
            _Field(
                PdCategory.SENSITIVE,
                sensitive_type=SensitiveType.IDENTITY_CREDENTIALS,
                subject_identifier=SubjectIdentifierKind.NATIONAL_ID,
            ),
        ),
    ]
    assert classification_problems(fields) == [
        ClassificationProblem(
            ClassificationCode.SUBJECT_IDENTIFIER_NOT_ALLOWED, "/fields/0/subject_identifier"
        )
    ]


def test_every_code_has_one_sentence_that_never_carries_the_value() -> None:
    for code in ClassificationCode:
        detail = ClassificationProblem(code, "/fields/0").detail
        assert detail
        assert "/fields/0" not in detail


def test_the_pairing_expressions_are_the_ones_the_spec_states() -> None:
    """The text owners' migrations copy; the catalog helper compares their
    CHECKs with Postgres's printing of exactly these."""
    assert personal_data.SENSITIVE_TYPE_PAIRING_SQL == (
        "(pd_category = 'sensitive') = (sensitive_type IS NOT NULL)"
    )
    assert personal_data.SUBJECT_IDENTIFIER_PAIRING_SQL == (
        "pd_category <> 'none' OR subject_identifier IS NULL"
    )
