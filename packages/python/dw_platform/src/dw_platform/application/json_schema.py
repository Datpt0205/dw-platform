"""The one JSON Schema validator: a work kind's payload and an edited proposal.

Draft 2020-12 with format checking, on `jsonschema` pinned exactly (ADR 0116).
In `dw_platform` rather than `dw_kernel`, whose contract is the standard library
only: the queue checks payloads here (digital-worker R3.3), the approval route
checks an edited proposal here (R5.4), and wf-lite reaches it through the
platform, which the runtime already depends on. Measured on 4.26.0: about
27 µs a call on a five-field object, so a validator is built per schema and
kept, keyed by the schema's canonical JSON.

A tool's input and output are checked here too (`tool_problems`, ADR-0116
decision 3, amended 2026-11-02): the same Draft 2020-12, but a closed format
list (`TOOL_FORMATS`) and an empty `referencing.Registry()`, so no `$ref`
reaches beyond the schema, and a problem names its path and the keyword that
refused it, never the value: a tool's input is what a model wrote, and a value
in an error would carry a lead's phone number into the record and the trace.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from typing import Any, NamedTuple

from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from referencing import Registry

from dw_kernel.errors import ConfigError
from dw_kernel.pagination import canonical_json
from dw_kernel.phone import is_vietnamese_phone

__all__ = [
    "TOOL_FORMATS",
    "SchemaProblem",
    "problems",
    "tool_problems",
    "tool_validator_for",
    "validator_for",
]


@lru_cache(maxsize=256)
def _cached(schema_json: str) -> Draft202012Validator:
    import json

    schema = json.loads(schema_json)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ConfigError(f"not a valid JSON Schema: {exc.message}") from exc
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validator_for(schema: Mapping[str, Any]) -> Draft202012Validator:
    """A checked validator for `schema`; `ConfigError` when it is no schema."""
    return _cached(canonical_json(dict(schema)))


def problems(schema: Mapping[str, Any], value: object) -> list[str]:
    """What is wrong with `value` under `schema`, as `path: message`, at most
    ten; empty when it is valid."""
    found: list[str] = []
    for error in validator_for(schema).iter_errors(value):
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        found.append(f"{where}: {error.message}")
        if len(found) == 10:
            break
    return found


# --------------------------------------------------------------- a tool's check --

# A mã số thuế: ten digits, ten and a three-digit branch suffix, or the twelve
# of a personal code (the citizen id). The check digit is not verified.
_TAX_CODE_VN = re.compile(r"\d{10}(?:-\d{3})?|\d{12}")


def _phone_vn(value: object) -> bool:
    """A Vietnamese number in use, by the rule RecordService stores a `phone`
    field with (`dw_kernel.phone`, custom-objects ticket 10): every writing it
    reads as a `+84` number, a pre-2018 mobile code included."""
    return not isinstance(value, str) or is_vietnamese_phone(value)


def _tax_code_vn(value: object) -> bool:
    return not isinstance(value, str) or _TAX_CODE_VN.fullmatch(value) is not None


def _date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if "T" not in value.upper():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return False
    # RFC 3339 needs the offset.
    return parsed.tzinfo is not None


def _tool_format_checker() -> FormatChecker:
    """Only these formats, each one really checked: `date-time` is not in the
    library's set without an extra package (measured on 4.26.0), so it is
    checked here rather than passed silently."""
    checker = FormatChecker(formats=("email", "uuid", "date"))
    checker.checks("date-time")(_date_time)
    checker.checks("phone_vn")(_phone_vn)
    checker.checks("tax_code_vn")(_tax_code_vn)
    return checker


_TOOL_FORMAT_CHECKER = _tool_format_checker()
# The closed list a tool schema may name: a `format` outside it would be an
# annotation the check ignores, so the profile refuses it instead.
TOOL_FORMATS = frozenset(_TOOL_FORMAT_CHECKER.checkers)


class SchemaProblem(NamedTuple):
    """Where a value failed a tool's schema and which keyword refused it."""

    path: str
    keyword: str


@lru_cache(maxsize=256)
def _cached_tool(schema_json: str) -> Draft202012Validator:
    import json

    schema = json.loads(schema_json)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ConfigError(f"not a valid JSON Schema: {exc.message}") from exc
    return Draft202012Validator(schema, format_checker=_TOOL_FORMAT_CHECKER, registry=Registry())


def tool_validator_for(schema: Mapping[str, Any]) -> Draft202012Validator:
    """A tool schema's checked validator; `ConfigError` when it is no schema."""
    return _cached_tool(canonical_json(dict(schema)))


def tool_problems(schema: Mapping[str, Any], value: object) -> list[SchemaProblem]:
    """What is wrong with a tool's input or output, as path and keyword, at
    most ten, never a value; empty when it is valid."""
    found: list[SchemaProblem] = []
    for error in tool_validator_for(schema).iter_errors(value):
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        found.append(SchemaProblem(path=where, keyword=str(error.validator)))
        if len(found) == 10:
            break
    return found
