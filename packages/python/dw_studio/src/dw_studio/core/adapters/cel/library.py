"""The platform functions of `dw.cel/v1.0` (ADR-0114 decision 3; workflow-nodes
01 step 3), and the binding extensions that carry them.

Each function is plain Python over plain values and reports a failure by
raising. The binding turns any exception a Python function raises into an
`ERROR` value with `OUT_OF_RANGE` (measured, cel-expr-python 0.1.3), so every
failure here reaches a caller as `expression_error` (`OUT_OF_RANGE`) and the
exception's text, which may hold the value, never leaves the evaluator.

Time zones come from Python's `zoneinfo` with the `tzdata` package, never from
the binding's own table: the binding cannot find an IANA name on Windows.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from cel_expr_python import cel
from cel_expr_python.ext import ext_bindings, ext_encoders, ext_math, ext_optional, ext_strings

_VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")

MASK = "[đã che]"

# An email address, then a phone-like run: an optional `+`, then at least nine
# digits, which spaces, dots or dashes may separate. Emails go first, because
# an address can hold a run of digits.
_EMAIL = re.compile(r"[\w.%+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_PHONE = re.compile(r"\+?\d(?:[ .\-]*\d){8,}")
_PHONE_PUNCTUATION = re.compile(r"[ .\-()]")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def text_nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def text_unaccent(value: str) -> str:
    """NFD, drop the combining marks (Mn), then `đ` to `d` and `Đ` to `D`."""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn"
    )
    return unicodedata.normalize("NFC", stripped.replace("đ", "d").replace("Đ", "D"))


def text_mask_contacts(value: str) -> str:
    return _PHONE.sub(MASK, _EMAIL.sub(MASK, value))


def phone_e164(value: str) -> str:
    """A Vietnamese number in E.164, or a refusal; never an empty string."""
    digits = _PHONE_PUNCTUATION.sub("", value)
    if re.fullmatch(r"0\d{9}", digits):
        return "+84" + digits[1:]
    if re.fullmatch(r"\+840\d{9}", digits):
        return "+84" + digits[4:]
    if re.fullmatch(r"84\d{9}", digits):
        return "+" + digits
    if re.fullmatch(r"\+\d{8,15}", digits):
        return digits
    raise ValueError("phone.e164: not a phone number")


def email_normalize(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.count("@") != 1:
        raise ValueError("email.normalize: not one '@'")
    return normalized


def fmt_money_vnd(value: int) -> str:
    return f"{value:,}".replace(",", ".") + " ₫"


def fmt_datetime(value: datetime) -> str:
    return _aware(value).astimezone(_VIETNAM).strftime("%d/%m/%Y %H:%M")


def fmt_date_timestamp(value: datetime) -> str:
    return _aware(value).astimezone(_VIETNAM).strftime("%d/%m/%Y")


def fmt_date_string(value: str) -> str:
    """A date-only field (`YYYY-MM-DD`, ADR-0114 decision 4) as `dd/MM/yyyy`."""
    if not _ISO_DATE.fullmatch(value):
        raise ValueError("fmt.date: not YYYY-MM-DD")
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def _aware(value: datetime) -> datetime:
    # The binding hands a timestamp over as an aware UTC datetime (measured);
    # a naive one would be read in the host's zone, so it is refused.
    if value.tzinfo is None:
        raise ValueError("timestamp without a zone")
    return value


def _overload(
    overload_id: str, result: cel.Type, params: Sequence[cel.Type], impl: Callable[..., Any]
) -> cel.Overload:
    return cel.Overload(overload_id, result, list(params), impl=impl)


def _platform_functions() -> list[cel.FunctionDecl]:
    s, ts, i = cel.Type.STRING, cel.Type.TIMESTAMP, cel.Type.INT
    one: dict[str, tuple[str, cel.Type, Callable[..., Any]]] = {
        "text.nfc": ("dw_text_nfc_string", s, text_nfc),
        "text.unaccent": ("dw_text_unaccent_string", s, text_unaccent),
        "text.mask_contacts": ("dw_text_mask_contacts_string", s, text_mask_contacts),
        "phone.e164": ("dw_phone_e164_string", s, phone_e164),
        "email.normalize": ("dw_email_normalize_string", s, email_normalize),
        "fmt.money_vnd": ("dw_fmt_money_vnd_int", i, fmt_money_vnd),
        "fmt.datetime": ("dw_fmt_datetime_timestamp", ts, fmt_datetime),
    }
    decls = [
        cel.FunctionDecl(name, [_overload(oid, s, [param], impl)])
        for name, (oid, param, impl) in one.items()
    ]
    decls.append(
        cel.FunctionDecl(
            "fmt.date",
            [
                _overload("dw_fmt_date_timestamp", s, [ts], fmt_date_timestamp),
                _overload("dw_fmt_date_string", s, [s], fmt_date_string),
            ],
        )
    )
    return decls


# The function names `dw.cel/v1.0` adds to standard CEL; the contract suite
# holds a valid and an invalid case for each.
PLATFORM_FUNCTIONS: tuple[str, ...] = (
    "text.nfc",
    "text.unaccent",
    "text.mask_contacts",
    "phone.e164",
    "email.normalize",
    "fmt.money_vnd",
    "fmt.datetime",
    "fmt.date",
)


def library_extensions() -> list[cel.CelExtensionBase]:
    """Standard CEL plus `strings`, `math`, `optional`, `encoders`, `bindings`
    and the platform functions: the whole of `dw.cel/v1.0`."""
    return [
        ext_strings.ExtStrings(),
        ext_math.ExtMath(),
        ext_optional.ExtOptional(),
        ext_encoders.ExtEncoders(),
        ext_bindings.ExtBindings(),
        cel.CelExtension("dw.cel", _platform_functions()),
    ]
