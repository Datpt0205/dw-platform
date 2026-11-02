"""Sample values that satisfy a JSON Schema, for a tool or a step that did not
run: the wf-ai dry run of a draft answers every tool and model step with one,
and the ToolExecutor answers an intercepted call outside `live` with one
(tenant-config R5.3). One generator for both, so a sample is the same shape
wherever it comes from.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

_SAMPLE_UUID = "00000000-0000-4000-8000-000000000000"


def sample_of(schema: Mapping[str, Any], defs: Mapping[str, Any] | None = None) -> Any:
    """A value that satisfies `schema`, for the shapes tools, prompts and kinds
    declare: an object's every property, an enum's first value, a number at
    its maximum (a `confidence` clears any floor), a string of its format."""
    defs = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        return sample_of(defs[str(schema["$ref"]).rsplit("/", 1)[-1]], defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"] or schema[key]
            return sample_of(options[0], defs)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        return {name: sample_of(prop, defs) for name, prop in props.items()}
    if kind == "array":
        count = int(schema.get("minItems", 0))
        return [sample_of(schema.get("items") or {}, defs) for _ in range(count)]
    if kind == "string":
        return _string(schema)
    if kind == "integer":
        return int(schema.get("minimum", schema.get("maximum", 0)))
    if kind == "number":
        return float(schema.get("maximum", schema.get("minimum", 1)))
    if kind == "boolean":
        return True
    return None


def _string(schema: Mapping[str, Any]) -> str:
    fmt = schema.get("format")
    if fmt == "email":
        return "mau@vi-du.vn"
    if fmt == "uuid":
        return _SAMPLE_UUID
    if fmt == "date-time":
        return datetime.now(UTC).isoformat()
    if fmt == "date":
        return datetime.now(UTC).date().isoformat()
    text = "mẫu"
    length = int(schema.get("minLength", 0))
    return (text * (length // len(text) + 1))[: max(length, len(text))][
        : int(schema.get("maxLength", 10_000))
    ]


class SampleOutput(BaseModel):
    """A sample a tool returns where it did not run: any fields, kept as
    given, so a simulated output may carry `simulated: true` beside the
    fields of the tool's own output model."""

    model_config = ConfigDict(extra="allow")


__all__ = ["SampleOutput", "sample_of"]
