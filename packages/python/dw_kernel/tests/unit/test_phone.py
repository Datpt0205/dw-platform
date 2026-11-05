"""One rule for a telephone number (custom-objects R6.2, ticket 10): the 21
mobile codes of decision `798/QĐ-BTTTT` in every writing, the current plan,
and what is refused."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from dw_kernel.phone import PRE_2018_MOBILE_CODES, is_vietnamese_phone, normalize_phone

pytestmark = pytest.mark.unit

# Written out from the decision's section II.2.1, not read from the module: a
# row removed from the table turns its own code's case red.
RENUMBERED = [
    ("120", "70"),
    ("121", "79"),
    ("122", "77"),
    ("126", "76"),
    ("128", "78"),
    ("123", "83"),
    ("124", "84"),
    ("125", "85"),
    ("127", "81"),
    ("129", "82"),
    ("162", "32"),
    ("163", "33"),
    ("164", "34"),
    ("165", "35"),
    ("166", "36"),
    ("167", "37"),
    ("168", "38"),
    ("169", "39"),
    ("186", "56"),
    ("188", "58"),
    ("199", "59"),
]

# Every writing a number was accepted in before ticket 10, as a function of
# the old code and the last seven digits.
WRITINGS: dict[str, Callable[[str, str], str]] = {
    "spaced": lambda old, tail: f"0{old} {tail[:3]} {tail[3:]}",
    "plain": lambda old, tail: f"0{old}{tail}",
    "plus": lambda old, tail: f"+84{old}{tail}",
    "plus_spaced": lambda old, tail: f"+84 {old} {tail[:3]} {tail[3:]}",
    "country": lambda old, tail: f"84{old}{tail}",
    "double_zero": lambda old, tail: f"0084 {old} {tail}",
    "dotted": lambda old, tail: f"0{old}.{tail[:3]}.{tail[3:]}",
    "dashed": lambda old, tail: f"0{old}-{tail[:3]}-{tail[3:]}",
    "brackets": lambda old, tail: f"(0{old}) {tail}",
}


@pytest.mark.parametrize(("old", "new"), RENUMBERED, ids=[old for old, _ in RENUMBERED])
@pytest.mark.parametrize("writing", sorted(WRITINGS))
def test_r6_2_every_pre_2018_mobile_code_is_its_new_one(old: str, new: str, writing: str) -> None:
    raw = WRITINGS[writing](old, "4567890")
    assert normalize_phone(raw) == f"+84{new}4567890"
    assert is_vietnamese_phone(raw)


def test_the_table_is_the_decision_s_21_codes() -> None:
    assert dict(PRE_2018_MOBILE_CODES) == dict(RENUMBERED)


@pytest.mark.parametrize(
    "raw", ["0168 456 7890", "+84 168 456 7890", "841684567890", "01684567890"]
)
def test_r6_2_the_ticket_s_four_writings_of_one_old_number(raw: str) -> None:
    assert normalize_phone(raw) == "+84384567890"


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        # A new code is kept as it is, its last seven digits too.
        ("038 456 7890", "+84384567890"),
        ("0384567890", "+84384567890"),
        ("0901 234 567", "+84901234567"),
        ("84900000101", "+84900000101"),
        ("0084 900 000 101", "+84900000101"),
        ("0559 123 456", "+84559123456"),
        ("024 3826 1234", "+842438261234"),
        ("0236 382 1234", "+842363821234"),
        # Another country's number is kept as written.
        ("+1 415 555 0100", "+14155550100"),
        ("0044 20 7946 0958", "+442079460958"),
    ],
)
def test_r6_2_a_number_in_use_is_kept(raw: str, e164: str) -> None:
    assert normalize_phone(raw) == e164


@pytest.mark.parametrize(
    "raw",
    [
        # A three-digit code no decision maps.
        "+84 130 123 4567",
        "0189 123 4567",
        # A landline with its area code from before the 2017 change, outside
        # the current plan.
        "04 3825 1234",
        "0511 382 1234",
        # A national number of the wrong length, or one that starts with 0.
        "+84 0901 234 567",
        "+84 90 123 45678",
        "0901 234 56",
        # No number at all.
        "123",
        "abc",
        "+84 (0)901 234 567",
        "0901/234/567",
        "٠٩٠١٢٣٤٥٦٧",
    ],
)
def test_r6_2_a_number_not_in_use_is_refused(raw: str) -> None:
    assert normalize_phone(raw) is None
    assert not is_vietnamese_phone(raw)


def test_another_country_s_number_is_not_vietnamese() -> None:
    assert normalize_phone("+1 415 555 0100") is not None
    assert not is_vietnamese_phone("+1 415 555 0100")
