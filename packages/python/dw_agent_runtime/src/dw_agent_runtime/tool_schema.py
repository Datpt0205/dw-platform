"""A tenant tool's JSON Schemas: the profile they must keep, and the behaviour
that checks a call against them (tools-and-skills R1; ADR-0116 decision 3).

LangChain checks nothing for a dict schema (measured on langchain 1.4.1,
2026-10-22), so a schema a tenant writes protects nothing unless the executor
checks it. The check itself is the platform's one validator
(`dw_platform.application.json_schema.tool_problems`); this module only holds
the profile `dw.tool-schema/v1` and builds the behaviour that calls it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from dw_agent_runtime.tools import (
    ApprovalPreview,
    SchemaViolation,
    ToolBehaviour,
    ToolHandler,
    ToolPayload,
)
from dw_kernel.errors import ConfigError
from dw_platform.application.json_schema import TOOL_FORMATS, tool_problems, tool_validator_for

TOOL_SCHEMA_PROFILE = "dw.tool-schema/v1"
MAX_DEPTH = 5
MAX_PROPERTIES = 100
_DRAFT = "https://json-schema.org/draft/2020-12/schema"
# Out of v1: a reference, a composition the model cannot be shown simply, a
# conditional, and a pattern (a regular expression a tenant writes is a
# backtracking cost the platform pays).
_FORBIDDEN = frozenset(
    {
        "$ref",
        "$dynamicRef",
        "allOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "dependentSchemas",
        "dependentRequired",
        "pattern",
        "patternProperties",
    }
)
# Keywords whose value is one subschema, and those whose value maps names to one.
_ONE_SCHEMA = ("items", "additionalProperties", "contains", "propertyNames")
_NAMED_SCHEMAS = ("properties", "$defs")


def _refuse(where: str, reason: str) -> ConfigError:
    return ConfigError(
        f"tool schema outside {TOOL_SCHEMA_PROFILE} at {where}: {reason}",
        details={"reason_code": "tool_schema_profile", "path": where, "rule": reason},
    )


def check_profile(schema: Mapping[str, Any]) -> None:
    """`ConfigError` unless `schema` keeps `dw.tool-schema/v1`: an object at
    the root, every object closed (`additionalProperties: false`), at most five
    levels deep and 100 properties in all, no `$ref`, `allOf`, `oneOf`, `not`,
    conditional or `pattern`, a `format` only from the closed list, and a valid
    Draft 2020-12 schema."""
    if schema.get("type") != "object":
        raise _refuse("(root)", "root_not_object")
    declared = schema.get("$schema")
    if declared is not None and declared != _DRAFT:
        raise _refuse("(root)", "draft_not_2020_12")
    count = _walk(schema, "(root)", 1)
    if count > MAX_PROPERTIES:
        raise _refuse("(root)", "too_many_properties")
    tool_validator_for(schema)


def _walk(node: object, where: str, depth: int) -> int:
    """The properties under `node`, refusing on the first rule it breaks."""
    if not isinstance(node, Mapping):
        return 0
    if depth > MAX_DEPTH:
        raise _refuse(where, "too_deep")
    for keyword in node:
        if keyword in _FORBIDDEN:
            raise _refuse(where, f"keyword:{keyword}")
    if "format" in node and node["format"] not in TOOL_FORMATS:
        raise _refuse(where, "format_unknown")
    is_object = node.get("type") == "object" or "properties" in node
    if is_object and node.get("additionalProperties") is not False:
        raise _refuse(where, "object_not_closed")
    count = 0
    for keyword in _NAMED_SCHEMAS:
        for name, child in (node.get(keyword) or {}).items():
            count += (keyword == "properties") + _walk(child, f"{where}/{name}", depth + 1)
    for keyword in _ONE_SCHEMA:
        if isinstance(node.get(keyword), Mapping):
            count += _walk(node[keyword], f"{where}/{keyword}", depth + 1)
    for child in node.get("anyOf") or ():
        count += _walk(child, f"{where}/anyOf", depth + 1)
    return count


def _checked(schema: Mapping[str, Any], value: object) -> BaseModel:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    found = tool_problems(schema, payload)
    if found:
        raise SchemaViolation([problem._asdict() for problem in found])
    if not isinstance(payload, Mapping):
        raise SchemaViolation([{"path": "(root)", "keyword": "type"}])
    return ToolPayload.model_validate(dict(payload))


def json_schema_behaviour(
    input_schema: Mapping[str, Any],
    output_schema: Mapping[str, Any],
    handler: ToolHandler,
    approval_preview: ApprovalPreview | None = None,
) -> ToolBehaviour:
    """A tenant tool, checked by its JSON Schemas; both are held to the
    profile here, so a schema outside it never reaches a call."""
    check_profile(input_schema)
    check_profile(output_schema)
    frozen_input = copy.deepcopy(dict(input_schema))
    frozen_output = copy.deepcopy(dict(output_schema))
    return ToolBehaviour(
        validate_input=lambda raw: _checked(frozen_input, raw),
        validate_output=lambda raw: _checked(frozen_output, raw),
        handler=handler,
        input_schema=lambda: copy.deepcopy(frozen_input),
        output_schema=lambda: copy.deepcopy(frozen_output),
        args_schema=copy.deepcopy(frozen_input),
        approval_preview=approval_preview,
    )
