"""The one JSON Schema validator: a work kind's payload and an edited proposal.

Draft 2020-12 with format checking, on `jsonschema` pinned exactly (ADR 0116).
In `dw_platform` rather than `dw_kernel`, whose contract is the standard library
only: the queue checks payloads here (digital-worker R3.3), the approval route
checks an edited proposal here (R5.4), and wf-lite reaches it through the
platform, which the runtime already depends on. Measured on 4.26.0: about
27 µs a call on a five-field object, so a validator is built per schema and
kept, keyed by the schema's canonical JSON.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from dw_kernel.errors import ConfigError
from dw_kernel.pagination import canonical_json

__all__ = ["problems", "validator_for"]


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
