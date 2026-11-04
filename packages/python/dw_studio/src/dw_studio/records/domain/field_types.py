"""The field types of an object and the slot families that store them.

One owner in code for both facts the database also holds (custom-objects
ticket 02 step 4): `FieldType` is `ck_field_defs_type`, read back from
`pg_constraint` by a test, and `SLOTS` is the set of slot columns of
`studio.records`, read back from `pg_attribute`. `SLOTS` is the provisional DDL
of the spec's Data section (A0 of custom-objects/01); ticket 07 changes both
in one revision when D12's measurement concludes.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, get_args

FieldType = Literal[
    "text",
    "number",
    "currency",
    "date",
    "datetime",
    "boolean",
    "picklist",
    "email",
    "phone",
    "url",
    "owner",
    "workspace",
]
FIELD_TYPES: Final[tuple[str, ...]] = get_args(FieldType)

SlotFamily = Literal["t", "u", "i", "f", "d", "z", "b"]

# The four types whose values are text a person types, and that may be unique
# (in the `u` family) as well as filtered (in `t`).
TEXT_LIKE: Final = frozenset({"text", "email", "phone", "url"})

_COUNTS: Final[tuple[tuple[str, int], ...]] = (
    ("t", 24),
    ("i", 12),
    ("f", 8),
    ("d", 8),
    ("z", 8),
    ("b", 8),
    ("u", 4),
)
SLOTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {family: tuple(f"{family}{n:02d}" for n in range(1, count + 1)) for family, count in _COUNTS}
)


def family_of(type_: str, *, number_mode: str | None, is_unique: bool) -> SlotFamily | None:
    """The slot family a filtering field of this type lives in; None for a type
    no slot holds (`owner`, `workspace`, whose values are system columns)."""
    if type_ in TEXT_LIKE:
        return "u" if is_unique else "t"
    match type_:
        case "picklist":
            return "t"
        case "currency":
            return "i"
        case "number":
            return "i" if number_mode == "exact" else "f"
        case "date":
            return "d"
        case "datetime":
            return "z"
        case "boolean":
            return "b"
    return None


def smallest_free_slot(family: SlotFamily, used: frozenset[str]) -> str | None:
    """The first slot of the family no field of the object holds (ADR-0107
    decision 5); None when the family is full."""
    return next((slot for slot in SLOTS[family] if slot not in used), None)
