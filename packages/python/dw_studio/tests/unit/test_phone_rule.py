"""One phone rule, read four ways (custom-objects R6.2, ticket 10;
failure-modes #2).

`dw_kernel.phone` owns the rule. RecordService reads it through
`coerce_input`, a tool's `phone_vn` format through `tool_problems`, and the
marketing pilot's dedupe oracle keeps its own copy on purpose (marketing-pilot
R1.2, MP17: the harness imports nothing of the platform's). One set of vectors
goes through all four, so the day one changes the rule alone this test is red.
"""

from __future__ import annotations

import pytest
from marketing_pilot import measure
from marketing_pilot.generator import PHONE_FORMATS, TEST_RANGE

from dw_kernel.phone import normalize_phone
from dw_platform.application.json_schema import tool_problems
from dw_studio.records.domain.document import definition_of
from dw_studio.records.domain.values import INVALID_TYPE, coerce_input
from dw_studio.testing.objects import object_document, object_field

pytestmark = pytest.mark.unit

FIELDS = definition_of(
    object_document(object_field("phone", "phone", pd_category="basic", is_unique=True))
).fields
PHONE_VN = {"type": "string", "format": "phone_vn"}

# The 21 codes of decision `798/QĐ-BTTTT`, II.2.1, by network.
OLD_CODES = (
    *("120", "121", "122", "126", "128"),
    *("123", "124", "125", "127", "129"),
    *(f"16{d}" for d in "23456789"),
    *("186", "188", "199"),
)


def _vectors() -> list[str]:
    """The generator's seven writings of a slice of the test range, every old
    mobile code in five writings, and the edges either side of the rule."""
    found = [
        write("0" + str(number)[2:])
        for number in TEST_RANGE[::97]
        for write in PHONE_FORMATS.values()
    ]
    for old in OLD_CODES:
        found += [
            f"0{old} 456 7890",
            f"+84{old}4567890",
            f"84{old}4567890",
            f"0084 {old} 456 7890",
            f"0{old}.456.7890",
        ]
    found += [
        "038 456 7890",
        "0084 900 000 101",
        "024 3826 1234",
        "+84 130 123 4567",
        "04 3825 1234",
        "0511 382 1234",
        "+84 0901 234 567",
        "+84 (0)901 234 567",
        "0901/234/567",
        "+1 415 555 0100",
        "123",
        "abc",
    ]
    return found


VECTORS = _vectors()


def _vietnamese(raw: str) -> str | None:
    e164 = normalize_phone(raw)
    return e164 if e164 is not None and e164.startswith("+84") else None


def _record(raw: str) -> str | None:
    out = coerce_input(FIELDS, {"phone": raw}, creating=False)
    if out.problems:
        assert [(p.pointer, p.code) for p in out.problems] == [("/fields/phone", INVALID_TYPE)]
        return None
    value = out.values["phone"]
    assert isinstance(value, str)
    return value


def _oracle(raw: str) -> str | None:
    try:
        return measure.normalize_phone(raw)
    except ValueError:
        return None


@pytest.mark.parametrize("raw", VECTORS)
def test_r6_2_record_service_phone_vn_and_the_oracle_read_one_rule(raw: str) -> None:
    owner = normalize_phone(raw)
    vietnamese = _vietnamese(raw)
    assert _record(raw) == owner
    assert (tool_problems(PHONE_VN, raw) == []) == (vietnamese is not None)
    assert _oracle(raw) == vietnamese


def test_the_vectors_reach_every_side_of_the_rule() -> None:
    """A vector set that only ever agreed on one answer would prove nothing."""
    answers = [_vietnamese(raw) for raw in VECTORS]
    assert "+84384567890" in answers
    assert "+84900000101" in answers
    assert None in answers
    assert normalize_phone("+1 415 555 0100") == "+14155550100"
    assert len(VECTORS) == len(set(VECTORS))


@pytest.mark.parametrize("raw", ["84900000101", "0084 900 000 101", "0168 456 7890"])
def test_r6_2_phone_vn_takes_what_record_service_stores(raw: str) -> None:
    assert tool_problems(PHONE_VN, raw) == []
