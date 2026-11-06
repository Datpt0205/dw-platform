"""A record's values, coerced and normalized once (custom-objects R6; ADR-0107
decisions 3, 7).

Written for this platform against the test vectors of DO-03.2 (custom-objects
ticket 03, MEDIUM M2): no agreement to port si-platform's `si_metadata/values.py`
exists yet, so the rule's fallback applies and this module is not a port.

One function turns what a caller sent into what the store keeps
(`coerce_input`), and one turns a kept value back into what a caller reads
(`present`). Between them every value has one canonical form:

- text, `url` and `name`: NFC, surrounding white space removed, empty read as
  null;
- `email`: as text, then lower case, one `@` and a dot in the domain;
- `phone`: E.164 by `dw_kernel.phone`, the rule's one owner: "0901 234 567"
  is "+84901234567", a pre-2018 "0168 456 7890" is "+84384567890", and a
  Vietnamese number outside the current plan is `invalid_type` (ticket 10);
- an `exact` number and a currency: a JSON string `-?[0-9]+(.[0-9]+)?`, kept as
  the integer `value * 10^scale`, never a JSON number (gate (e)): a binary
  float cannot carry 0.1, and a string can. More decimals than `scale`, past
  trailing zeros, is `scale_exceeded` (R6.3);
- a `float` number: a JSON number; a `date`: `YYYY-MM-DD`; a `datetime`: ISO
  8601 with its offset, kept in UTC; a `boolean`: `true` or `false`;
- a picklist: an active option's key; an inactive one is `value_not_allowed`
  like an unknown one, though a record keeping it still reads it (gate (y)).

Every problem of one save comes back at once, each at its pointer, with a
fixed sentence per code: a detail never repeats the value it refused (gate
4/11/2026 (k)).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Final

from dw_kernel.phone import normalize_phone
from dw_studio.core.domain.artifacts import DocumentProblem
from dw_studio.records.domain.document import NAME, FieldDefinition

# The error codes of one value (R6.1, R6.3, R6.5).
REQUIRED: Final = "required"
INVALID_TYPE: Final = "invalid_type"
MAX_LENGTH: Final = "max_length"
VALUE_NOT_ALLOWED: Final = "value_not_allowed"
SCALE_EXCEEDED: Final = "scale_exceeded"
UNKNOWN_FIELD: Final = "unknown_field"

_DETAILS: Final[Mapping[str, str]] = {
    REQUIRED: "a value is required",
    INVALID_TYPE: "the value is not of the field's type",
    MAX_LENGTH: "the value is longer than the field allows",
    VALUE_NOT_ALLOWED: "the value is not one of the field's active options",
    SCALE_EXCEEDED: "the value has more decimal places than the field's scale",
    UNKNOWN_FIELD: "the object has no such field",
}

# What a `name` holds (`studio.records.name`, 1 to 255 characters).
NAME_MAX_LENGTH: Final = 255
# A bigint, the store of an exact number and a currency.
_BIGINT: Final = 2**63 - 1
_DECIMAL: Final = re.compile(r"^(-?)([0-9]+)(?:\.([0-9]+))?$")
_DATE: Final = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_EMAIL: Final = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s.][^@\s]*$")
_URL: Final = re.compile(r"^https?://\S+$", re.IGNORECASE)

Stored = str | int | float | bool | date | datetime


def pointer(api_name: str) -> str:
    """`/fields/<api_name>`, escaped as RFC 6901 asks; `/name` for the name."""
    if api_name == NAME:
        return "/name"
    return "/fields/" + api_name.replace("~", "~0").replace("/", "~1")


def problem(at: str, code: str) -> DocumentProblem:
    return DocumentProblem(at, code, _DETAILS[code])


class _Refused(Exception):  # noqa: N818 - one value's refusal, caught below
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _text(raw: Any) -> str | None:
    if not isinstance(raw, str):
        raise _Refused(INVALID_TYPE)
    text = unicodedata.normalize("NFC", raw).strip()
    return text or None


def _scaled(raw: Any, scale: int) -> int:
    if not isinstance(raw, str):
        raise _Refused(INVALID_TYPE)
    match = _DECIMAL.fullmatch(raw.strip())
    if match is None:
        raise _Refused(INVALID_TYPE)
    sign, whole, fraction = match.groups()
    fraction = (fraction or "").rstrip("0")
    if len(fraction) > scale:
        raise _Refused(SCALE_EXCEEDED)
    value: int = int(whole) * 10**scale + int(fraction.ljust(scale, "0") or "0")
    if value > _BIGINT:
        raise _Refused(INVALID_TYPE)
    return -value if sign else value


def _float(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise _Refused(INVALID_TYPE)
    value = float(raw)
    if not math.isfinite(value):
        raise _Refused(INVALID_TYPE)
    return value


def _date(raw: Any) -> date:
    if not isinstance(raw, str) or not _DATE.fullmatch(raw):
        raise _Refused(INVALID_TYPE)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _Refused(INVALID_TYPE) from None


def _datetime(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise _Refused(INVALID_TYPE)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise _Refused(INVALID_TYPE) from None
    if value.tzinfo is None:
        raise _Refused(INVALID_TYPE)
    return value.astimezone(UTC)


def _within(text: str | None, max_length: int | None) -> str | None:
    if text is not None and max_length is not None and len(text) > max_length:
        raise _Refused(MAX_LENGTH)
    return text


def _coerce(definition: FieldDefinition, raw: Any) -> Stored | None:
    if raw is None:
        return None
    kind = definition.type
    if kind in ("text", "url"):
        text = _within(_text(raw), definition.max_length)
        if kind == "url" and text is not None and not _URL.fullmatch(text):
            raise _Refused(INVALID_TYPE)
        return text
    if kind == "email":
        text = _text(raw)
        if text is None:
            return None
        if not _EMAIL.fullmatch(text):
            raise _Refused(INVALID_TYPE)
        return _within(text.lower(), definition.max_length)
    if kind == "phone":
        text = _text(raw)
        if text is None:
            return None
        phone = normalize_phone(text)
        if phone is None:
            raise _Refused(INVALID_TYPE)
        return _within(phone, definition.max_length)
    if kind == "currency" or (kind == "number" and definition.number_mode == "exact"):
        return _scaled(raw, definition.scale or 0)
    if kind == "number":
        return _float(raw)
    if kind == "boolean":
        if not isinstance(raw, bool):
            raise _Refused(INVALID_TYPE)
        return raw
    if kind == "date":
        return _date(raw)
    if kind == "datetime":
        return _datetime(raw)
    if kind == "picklist":
        if not isinstance(raw, str):
            raise _Refused(INVALID_TYPE)
        if not any(o.key == raw and o.active for o in definition.options):
            raise _Refused(VALUE_NOT_ALLOWED)
        return raw
    raise _Refused(INVALID_TYPE)


@dataclass(frozen=True, slots=True)
class Coerced:
    """What one save sent, in canonical form, by `api_name` (`name` among
    them when it was sent), and every problem found."""

    values: dict[str, Stored | None] = field(default_factory=dict)
    problems: list[DocumentProblem] = field(default_factory=list)


def coerce_input(
    fields: Mapping[str, FieldDefinition],
    sent: Mapping[str, Any],
    *,
    creating: bool,
) -> Coerced:
    """``sent``, by `api_name` (`name` for the name), against the object's
    ``fields`` (`name` among them): every problem at once, R6.1.

    On a create a required field that is absent or null is `required`; on a
    change only one set to null is, since an absent field keeps its value
    (JSON Merge Patch)."""
    out = Coerced()
    for api_name, raw in sent.items():
        definition = fields.get(api_name)
        if definition is None:
            out.problems.append(problem(pointer(api_name), UNKNOWN_FIELD))
            continue
        try:
            if api_name == NAME:
                value: Stored | None = _within(_text(raw), NAME_MAX_LENGTH)
            else:
                value = _coerce(definition, raw)
        except _Refused as refused:
            out.problems.append(problem(pointer(api_name), refused.code))
            continue
        if value is None and definition.required:
            out.problems.append(problem(pointer(api_name), REQUIRED))
            continue
        out.values[api_name] = value
    if creating:
        out.problems.extend(missing_required(fields, sent))
    return out


def missing_required(
    fields: Mapping[str, FieldDefinition], sent: Mapping[str, Any]
) -> list[DocumentProblem]:
    """`required` for each required field a create leaves out."""
    return [
        problem(pointer(api_name), REQUIRED)
        for api_name, definition in sorted(fields.items())
        if definition.required and api_name not in sent
    ]


def filter_value(definition: FieldDefinition, raw: Any) -> object:
    """A filter's value for the field, coerced and normalized as a write's is
    (custom-objects ticket 04, gate (f)), in the form `dw_kernel.filters`
    types: the kept value, a date or a time as ISO 8601 text. A phone is
    compared in E.164, an email in lower case, text in NFC, an exact number
    or a currency as its scaled integer from a decimal string.

    Raises ValueError, which the kernel answers as `invalid_type`, for what a
    write would refuse, a length or a scale past the field's included, and
    for a value that is empty once normalized. A picklist key is checked to
    exist, not to be active: a record keeping an inactive option is found."""
    try:
        if definition.type == "picklist":
            if not isinstance(raw, str) or not any(o.key == raw for o in definition.options):
                raise _Refused(INVALID_TYPE)
            value: Stored | None = raw
        elif definition.api_name == NAME:
            value = _within(_text(raw), NAME_MAX_LENGTH)
        else:
            value = _coerce(definition, raw)
    except _Refused:
        raise ValueError("not a value of the field") from None
    if value is None:
        raise ValueError("not a value of the field")
    if isinstance(value, date):  # a datetime too
        return value.isoformat()
    return value


def present(definition: FieldDefinition, stored: Stored | None) -> Any:
    """What a caller reads of a kept value: an exact number or a currency as
    a string with exactly `scale` decimals (R6.4), a date or a time in ISO
    8601, everything else as kept."""
    if stored is None:
        return None
    scaled = definition.type == "currency" or definition.number_mode == "exact"
    if scaled and isinstance(stored, int) and not isinstance(stored, bool):
        return decimal_text(stored, definition.scale or 0)
    if isinstance(stored, date | datetime):
        return stored.isoformat()
    return stored


def decimal_text(scaled: int, scale: int) -> str:
    """``scaled / 10^scale`` with exactly ``scale`` decimals: 10 at scale 2 is
    "0.10"."""
    whole, fraction = divmod(abs(scaled), 10**scale)
    sign = "-" if scaled < 0 else ""
    return f"{sign}{whole}" if scale == 0 else f"{sign}{whole}.{fraction:0{scale}d}"


def to_json(definition: FieldDefinition, stored: Stored | None) -> Any:
    """A kept value as `data` holds it: a date or a time as ISO 8601 text."""
    if isinstance(stored, date | datetime):
        return stored.isoformat()
    return stored


def from_json(definition: FieldDefinition, raw: Any) -> Stored | None:
    """A value of `data` back in its kept type: the inverse of `to_json`."""
    if raw is None:
        return None
    if definition.type == "date":
        return date.fromisoformat(raw)
    if definition.type == "datetime":
        return datetime.fromisoformat(raw)
    if definition.type == "number" and definition.number_mode != "exact":
        return float(raw)
    return raw  # type: ignore[no-any-return]
