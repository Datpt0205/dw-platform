"""A telephone number in E.164, one rule (custom-objects R6.2, ticket 10).

One owner for the readers that must agree: RecordService's coercion of a
`phone` field (`dw_studio.records.domain.values`) and the `phone_vn` format of a
tool's JSON Schema (`dw_platform.application.json_schema`). The dedupe oracle of
the marketing pilot keeps its own copy on purpose (marketing-pilot R1.2, MP17)
and a unit test runs one set of vectors through all of them.

Separators (white space, `.`, `-`, parentheses) are dropped. A leading `+` or
`00` is an international number; a leading `0` a Vietnamese national one; a
bare `84` followed by nine or ten digits is read as Vietnam's code. Another
country's number is kept as written, 8 to 15 digits.

A Vietnamese number is kept only in the current numbering plan, after the
mobile codes renumbered in 2018 are mapped to their new ones: decision
`798/QĐ-BTTTT` of 25/5/2018 (Ministry of Information and Communications, section
II.2.1) moved 21 three-digit codes to two-digit ones and kept the last seven
digits, so "0168 456 7890" is "+84384567890". What follows `84` must then be a
mobile (3, 5, 7, 8 or 9 and eight digits) or a landline (2 and nine digits).
A landline written with its area code from before the 2017 change is not
mapped: an old Hồ Chí Minh City "08 3825 1234" is, digit for digit, the
VinaPhone mobile "083 825 1234", so no table tells them apart; one outside the
current plan ("04 3825 1234") is refused rather than kept as a number that no
longer rings (custom-objects ticket 10, Comments).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = ["PRE_2018_MOBILE_CODES", "is_vietnamese_phone", "normalize_phone"]

# Decision `798/QĐ-BTTTT`, II.2.1: the old code after the leading 0, and its
# new one.
PRE_2018_MOBILE_CODES: Final[Mapping[str, str]] = MappingProxyType(
    {
        # MobiFone
        "120": "70",
        "121": "79",
        "122": "77",
        "126": "76",
        "128": "78",
        # VinaPhone
        "123": "83",
        "124": "84",
        "125": "85",
        "127": "81",
        "129": "82",
        # Viettel
        "162": "32",
        "163": "33",
        "164": "34",
        "165": "35",
        "166": "36",
        "167": "37",
        "168": "38",
        "169": "39",
        # Vietnamobile
        "186": "56",
        "188": "58",
        # Gmobile
        "199": "59",
    }
)

VIETNAM: Final = "84"
_SEPARATORS: Final = re.compile(r"[\s.\-()]")
_DIGITS: Final = re.compile(r"[0-9]+")
# The national number after `84` in the current plan: a mobile or a landline.
_NATIONAL: Final = re.compile(r"[35789][0-9]{8}|2[0-9]{9}")


def normalize_phone(raw: str) -> str | None:
    """E.164 of ``raw``, or None when it is no telephone number in use."""
    compact = _SEPARATORS.sub("", raw)
    if compact.startswith("+"):
        digits = compact[1:]
    elif compact.startswith("00"):
        digits = compact[2:]
    elif compact.startswith("0"):
        digits = VIETNAM + compact[1:]
    elif compact.startswith(VIETNAM) and len(compact) in (11, 12):
        digits = compact
    else:
        return None
    if not _DIGITS.fullmatch(digits) or not 8 <= len(digits) <= 15:
        return None
    if not digits.startswith(VIETNAM):
        return "+" + digits
    national = digits[len(VIETNAM) :]
    renumbered = PRE_2018_MOBILE_CODES.get(national[:3]) if len(national) == 10 else None
    if renumbered is not None:
        national = renumbered + national[3:]
    if _NATIONAL.fullmatch(national) is None:
        return None
    return "+" + VIETNAM + national


def is_vietnamese_phone(raw: str) -> bool:
    """Whether ``raw`` is a Vietnamese number in use: what `phone_vn` accepts."""
    e164 = normalize_phone(raw)
    return e164 is not None and e164.startswith("+" + VIETNAM)
