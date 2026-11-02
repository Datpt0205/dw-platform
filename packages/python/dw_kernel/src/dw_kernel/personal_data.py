"""The personal-data vocabulary every field carries: one owner (ADR-0106 decision 1).

A field-definition table anywhere in the platform (custom-object fields, Data
Hub schema fields, tool schema properties) carries three columns read from
here: ``pd_category``, ``sensitive_type`` and ``subject_identifier``. Each
owner's migration writes the CHECKs as literals, because no migration imports
a package; ``dw_platform.testing.personal_data.assert_field_tables_classified``
is the net that catches a CHECK drifting from these enums, and
``contracts/jsonschema/pd_classification.json`` is generated from them, so the
web's Vietnamese labels are tested against the same lists.

``SensitiveType`` is Decree 356/2025/ND-CP, Article 4, clause 1 ("Dữ liệu cá
nhân nhạy cảm bao gồm:"): one member per lettered point, each member carrying
its point's letter, and no catch-all ``other`` (point m is itself a category
the law names). Source: the Vietnamese text of Nghị định 356/2025/NĐ-CP, read
on 2026-11-02 from luatvietnam.vn's full text and cross-checked against the
Cần Thơ legal-dissemination portal (pbgdpl.cantho.gov.vn); the national legal
database (vbpl.moj.gov.vn) did not resolve from the machine that copied it, so
counsel (compliance-pdpl/02) confirms the list. Article 4, clause 1 has
12 lettered points.

The module is standard library only, like the rest of the kernel.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, Self

__all__ = [
    "SENSITIVE_TYPE_PAIRING_SQL",
    "SUBJECT_IDENTIFIER_PAIRING_SQL",
    "ClassificationCode",
    "ClassificationProblem",
    "ClassifiedField",
    "PdCategory",
    "SensitiveType",
    "SubjectIdentifierKind",
    "classification_problems",
]


class PdCategory(StrEnum):
    """Loại dữ liệu cá nhân: Không / Cơ bản / Nhạy cảm (`docs/platform/CONTEXT.md`)."""

    NONE = "none"
    BASIC = "basic"
    SENSITIVE = "sensitive"


class SensitiveType(StrEnum):
    """One member per lettered point of Decree 356/2025/ND-CP Art. 4.1, in order."""

    point: str

    def __new__(cls, value: str, point: str) -> Self:
        member = str.__new__(cls, value)
        member._value_ = value
        member.point = point
        return member

    # a) Dữ liệu tiết lộ nguồn gốc chủng tộc, nguồn gốc dân tộc
    RACIAL_ETHNIC_ORIGIN = "racial_ethnic_origin", "a"
    # b) Quan điểm về chính trị, tôn giáo, tín ngưỡng
    POLITICAL_RELIGIOUS_VIEWS = "political_religious_views", "b"
    # c) Thông tin về đời sống riêng tư, bí mật cá nhân, bí mật gia đình
    PRIVATE_LIFE = "private_life", "c"
    # d) Tình trạng sức khỏe
    HEALTH = "health", "d"
    # đ) Dữ liệu sinh trắc học, đặc điểm di truyền
    BIOMETRIC_GENETIC = "biometric_genetic", "đ"
    # e) Dữ liệu tiết lộ đời sống tình dục, xu hướng tình dục của cá nhân
    SEX_LIFE_ORIENTATION = "sex_life_orientation", "e"
    # g) Dữ liệu về tội phạm, vi phạm pháp luật được thu thập, lưu trữ bởi các
    #    cơ quan thực thi pháp luật
    CRIME_VIOLATION = "crime_violation", "g"
    # h) Vị trí của cá nhân được xác định qua dịch vụ định vị
    LOCATION = "location", "h"
    # i) Tên đăng nhập và mật khẩu tài khoản định danh điện tử; hình ảnh thẻ căn
    #    cước, thẻ căn cước công dân, chứng minh nhân dân
    IDENTITY_CREDENTIALS = "identity_credentials", "i"
    # k) Tên đăng nhập, mật khẩu tài khoản ngân hàng; thẻ ngân hàng, lịch sử giao
    #    dịch; thông tin tài chính, tín dụng, chứng khoán, bảo hiểm của khách hàng
    FINANCIAL = "financial", "k"
    # l) Dữ liệu theo dõi hành vi, hoạt động sử dụng dịch vụ viễn thông, mạng xã
    #    hội, dịch vụ truyền thông trực tuyến và các dịch vụ khác trên không gian mạng
    BEHAVIOUR_TRACKING = "behaviour_tracking", "l"
    # m) Dữ liệu cá nhân khác được pháp luật quy định cần giữ bí mật hoặc cần có
    #    biện pháp bảo mật chặt chẽ
    LEGALLY_CONFIDENTIAL = "legally_confidential", "m"


class SubjectIdentifierKind(StrEnum):
    """Trường định danh chủ thể: how a data-subject request finds a person (ADR-0106 decision 7)."""

    EMAIL = "email"
    PHONE = "phone"
    NATIONAL_ID = "national_id"
    ZALO_USER_ID = "zalo_user_id"
    FACEBOOK_PSID = "facebook_psid"
    TAX_CODE = "tax_code"
    BANK_ACCOUNT = "bank_account"


# The two row rules every field-definition table holds as CHECKs, in the form
# its migration writes them: `ck_<table>_pd_sensitive_type` and
# `ck_<table>_pd_subject_identifier`. The catalog helper compares a table's
# CHECK with what Postgres prints for these exact expressions.
SENSITIVE_TYPE_PAIRING_SQL: Final = "(pd_category = 'sensitive') = (sensitive_type IS NOT NULL)"
SUBJECT_IDENTIFIER_PAIRING_SQL: Final = "pd_category <> 'none' OR subject_identifier IS NULL"


class ClassificationCode(StrEnum):
    """An `errors[].code` of a 422 `validation_failed` (app-standards R1.3)."""

    PD_CATEGORY_REQUIRED = "pd_category_required"
    SENSITIVE_TYPE_REQUIRED = "sensitive_type_required"
    SENSITIVE_TYPE_NOT_ALLOWED = "sensitive_type_not_allowed"
    SUBJECT_IDENTIFIER_NOT_ALLOWED = "subject_identifier_not_allowed"


# One sentence per code, written here and nowhere else; never the value sent.
_DETAIL: Final[Mapping[ClassificationCode, str]] = {
    ClassificationCode.PD_CATEGORY_REQUIRED: "every field needs a personal-data category",
    ClassificationCode.SENSITIVE_TYPE_REQUIRED: "a sensitive field needs its sensitive type",
    ClassificationCode.SENSITIVE_TYPE_NOT_ALLOWED: (
        "only a sensitive field carries a sensitive type"
    ),
    ClassificationCode.SUBJECT_IDENTIFIER_NOT_ALLOWED: (
        "a field that identifies a data subject holds personal data"
    ),
}


@dataclass(frozen=True, slots=True)
class ClassificationProblem:
    """One thing wrong with a field's classification, at a JSON pointer."""

    code: ClassificationCode
    pointer: str

    @property
    def detail(self) -> str:
        return _DETAIL[self.code]


class ClassifiedField(Protocol):
    """What the check reads from a field, typed: an owner's input model, whose
    schema already refused a value outside the enums, satisfies it as it is."""

    @property
    def pd_category(self) -> PdCategory | None: ...

    @property
    def sensitive_type(self) -> SensitiveType | None: ...

    @property
    def subject_identifier(self) -> SubjectIdentifierKind | None: ...


def classification_problems(
    fields: Iterable[tuple[str, ClassifiedField]],
) -> list[ClassificationProblem]:
    """Every classification problem of every field, each pointer given with its field.

    Checks every field and does not stop at the first problem, so a 422 lists
    them all. A field without a category has one problem, at the field; the
    pairing rules then have nothing to compare against.
    """
    found: list[ClassificationProblem] = []
    for pointer, field in fields:
        category = field.pd_category
        if category is None:
            found.append(ClassificationProblem(ClassificationCode.PD_CATEGORY_REQUIRED, pointer))
            continue
        if category == PdCategory.SENSITIVE and field.sensitive_type is None:
            found.append(ClassificationProblem(ClassificationCode.SENSITIVE_TYPE_REQUIRED, pointer))
        if category != PdCategory.SENSITIVE and field.sensitive_type is not None:
            found.append(
                ClassificationProblem(
                    ClassificationCode.SENSITIVE_TYPE_NOT_ALLOWED, f"{pointer}/sensitive_type"
                )
            )
        if category == PdCategory.NONE and field.subject_identifier is not None:
            found.append(
                ClassificationProblem(
                    ClassificationCode.SUBJECT_IDENTIFIER_NOT_ALLOWED,
                    f"{pointer}/subject_identifier",
                )
            )
    return found
