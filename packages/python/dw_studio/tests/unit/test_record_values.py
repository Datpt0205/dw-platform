"""A record's values, coerced once (custom-objects R6.1-R6.5; ticket 03 step 1;
DO-03.2's test vectors, written here since no port agreement exists, M2)."""

from __future__ import annotations

import unicodedata
from datetime import UTC, date, datetime
from typing import Any

import pytest

from dw_kernel.phone import normalize_phone
from dw_studio.records.domain.document import FieldDefinition, OptionDefinition, definition_of
from dw_studio.records.domain.values import (
    coerce_input,
    decimal_text,
    from_json,
    present,
    to_json,
)
from dw_studio.testing.objects import object_document, object_field

pytestmark = pytest.mark.unit

FIELDS = definition_of(
    object_document(
        object_field("phone", "phone", pd_category="basic", is_unique=True),
        object_field("email", "email", pd_category="basic"),
        object_field("note", max_length=10),
        object_field("site", "url"),
        object_field("amount", "currency", scale=0),
        object_field("price", "number", number_mode="exact", scale=2),
        object_field("score", "number", number_mode="float"),
        object_field("met_on", "date"),
        object_field("seen_at", "datetime"),
        object_field("consent", "boolean"),
        object_field(
            "stage",
            "picklist",
            required=True,
            options=[
                {"key": "moi", "labels": {"vi": "Mới"}, "position": 0},
                {"key": "cu", "labels": {"vi": "Cũ"}, "position": 1, "active": False},
            ],
        ),
    )
).fields


def coerced(
    sent: dict[str, Any], *, creating: bool = False
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    out = coerce_input(FIELDS, sent, creating=creating)
    return out.values, {(p.pointer, p.code) for p in out.problems}


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        ("0901 234 567", "+84901234567"),
        ("0901.234.567", "+84901234567"),
        ("(090) 123-4567", "+84901234567"),
        ("+84901234567", "+84901234567"),
        ("84901234567", "+84901234567"),
        ("0084 901 234 567", "+84901234567"),
        ("024 3826 1234", "+842438261234"),
        ("+1 415 555 0100", "+14155550100"),
    ],
)
def test_r6_2_a_phone_is_kept_in_e164(raw: str, e164: str) -> None:
    assert normalize_phone(raw) == e164


@pytest.mark.parametrize(
    "raw", ["123", "0901", "+84 0901 234 567", "abc", "0901 234 567 890 12", "٠٩٠١٢٣٤٥٦٧"]
)
def test_r6_2_a_phone_that_is_no_number_is_refused(raw: str) -> None:
    assert normalize_phone(raw) is None
    assert coerced({"phone": raw})[1] == {("/fields/phone", "invalid_type")}


def test_r6_2_email_lower_case_and_text_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "Nguyễn Văn Á")
    values, problems = coerced({"email": " A@X.VN ", "name": nfd, "phone": "0901 234 567"})
    assert problems == set()
    assert values["email"] == "a@x.vn"
    assert values["phone"] == "+84901234567"
    assert values["name"].encode() == unicodedata.normalize("NFC", "Nguyễn Văn Á").encode()


def test_r6_3_r6_4_an_exact_number_is_a_scaled_integer_from_a_string() -> None:
    values, problems = coerced({"amount": "1000", "price": "0.1"})
    assert problems == set()
    assert values == {"amount": 1000, "price": 10}
    assert present(FIELDS["price"], 10) == "0.10"
    assert present(FIELDS["amount"], 1000) == "1000"
    assert present(FIELDS["price"], -5) == "-0.05"
    assert decimal_text(123456, 3) == "123.456"
    assert coerced({"price": "1.500"})[0] == {"price": 150}


@pytest.mark.parametrize(
    ("field", "raw", "code"),
    [
        ("amount", "1000.5", "scale_exceeded"),
        ("price", "0.001", "scale_exceeded"),
        ("amount", 1000.5, "invalid_type"),
        ("amount", 1000, "invalid_type"),
        ("amount", "1e3", "invalid_type"),
        ("amount", "9223372036854775808", "invalid_type"),
        ("score", "1.5", "invalid_type"),
        ("score", True, "invalid_type"),
        ("consent", "yes", "invalid_type"),
        ("met_on", "2026-13-01", "invalid_type"),
        ("met_on", "01/02/2026", "invalid_type"),
        ("seen_at", "2026-11-05T10:00:00", "invalid_type"),
        ("email", "not-an-email", "invalid_type"),
        ("site", "ftp://x.vn", "invalid_type"),
        ("note", "mười một ký", "max_length"),
        ("stage", "khong_co", "value_not_allowed"),
        ("stage", "cu", "value_not_allowed"),
        ("stage", None, "required"),
        ("khong_co", "x", "unknown_field"),
    ],
)
def test_r6_1_r6_3_r6_5_each_refusal_has_its_code(field: str, raw: Any, code: str) -> None:
    assert coerced({field: raw})[1] == {(f"/fields/{field}", code)}


def test_r6_1_every_problem_of_one_save_at_once_none_with_a_value() -> None:
    out = coerce_input(
        FIELDS, {"amount": 12.5, "stage": "khong_co", "email": "x@y.vn"}, creating=True
    )
    assert sorted((p.pointer, p.code) for p in out.problems) == [
        ("/fields/amount", "invalid_type"),
        ("/fields/stage", "value_not_allowed"),
        ("/name", "required"),
    ]
    assert all("12.5" not in p.detail and "khong_co" not in p.detail for p in out.problems)


def test_a_create_names_every_missing_required_field_a_change_does_not() -> None:
    assert coerced({}, creating=True)[1] == {("/name", "required"), ("/fields/stage", "required")}
    assert coerced({}, creating=False)[1] == set()
    assert coerced({"name": "  "})[1] == {("/name", "required")}


def test_values_of_every_type_and_their_json_form() -> None:
    values, problems = coerced(
        {
            "score": 2,
            "consent": False,
            "met_on": "2026-11-05",
            "seen_at": "2026-11-05T17:00:00+07:00",
            "site": "https://x.vn/a",
            "note": None,
        }
    )
    assert problems == set()
    assert values["score"] == 2.0
    assert values["met_on"] == date(2026, 11, 5)
    assert values["seen_at"] == datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    assert values["note"] is None
    for name in ("score", "consent", "met_on", "seen_at", "site"):
        definition = FIELDS[name]
        assert from_json(definition, to_json(definition, values[name])) == values[name]
    assert present(FIELDS["seen_at"], values["seen_at"]) == "2026-11-05T10:00:00+00:00"


def test_an_inactive_option_still_presents() -> None:
    stage: FieldDefinition = FIELDS["stage"]
    assert OptionDefinition("cu", {"vi": "Cũ"}, 1, False) in stage.options
    assert present(stage, "cu") == "cu"
