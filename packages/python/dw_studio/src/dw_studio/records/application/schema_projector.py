"""`ObjectSchemaProjector`: JSON Schema 2020-12 for creating, changing and
querying an object's records, built from its stored definition (R3.6, R3.7).

The tenant comes from the caller's verified access context or run, never the
request (`CLAUDE.md`, Per-tenant artifacts), and it is part of the cache key:
an object's id travels to another tenant with a pack (ADR-0109 decision 1),
so `(object_id, schema_version)` alone would hand one company another's
schema (gate CRITICAL, 3/11/2026). The cache is a bounded LRU in the process,
never Valkey.

Every word a company wrote stays out of the schemas: no `title`, no
`description`, no label (gate MEDIUM (a)). `ai_description` comes back in its
own table beside them, for the consumer to wrap as untrusted data (YC48,
YC101). Which fields the caller may see or change is ticket 03's, with
field-security/01. The query schema is the JSON Schema of the filter tree
`dw_kernel.filters` exports for the caller's `QuerySchema` (`record_query`),
so a tool, a workflow step and the route parse one grammar (custom-objects
ticket 04, gate (h)).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from dw_kernel.filters import query_json_schema
from dw_studio.records.application.ports import AppliedObject, ObjectDefinitionReader
from dw_studio.records.application.record_query import SORTABLE, query_schema
from dw_studio.records.domain.document import NAME, OWNER, WORKSPACE, FieldDefinition

JSON_SCHEMA: Final = "https://json-schema.org/draft/2020-12/schema"
DEFAULT_CACHE_ENTRIES: Final = 1024
# An exact number and a currency travel as a decimal string at every door.
DECIMAL_PATTERN: Final = r"^-?[0-9]+(\.[0-9]+)?$"

_FORMATS: Final[Mapping[str, str]] = {
    "email": "email",
    "url": "uri",
    "date": "date",
    "datetime": "date-time",
}


@dataclass(frozen=True, slots=True)
class AiDescriptions:
    """The company's own words for an agent, apart from every schema."""

    object: str | None
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ObjectSchemas:
    object_id: uuid.UUID
    schema_version: int
    create: Mapping[str, Any]
    update: Mapping[str, Any]
    query: Mapping[str, Any]
    sortable: tuple[str, ...]
    ai_descriptions: AiDescriptions
    # What `narrowed` rebuilds the caller's query grammar from; `project`
    # always sets it. Without one the caller's grammar admits no filter.
    source: AppliedObject | None = field(default=None, repr=False, compare=False)


def value_schema(field: FieldDefinition) -> dict[str, Any]:
    """One value of the field: its JSON type and bounds, nothing it was called."""
    schema: dict[str, Any]
    if field.type == "currency" or (field.type == "number" and field.number_mode == "exact"):
        # A decimal string, never a JSON number (custom-objects/03, gate (e)).
        schema = {"type": "string", "pattern": DECIMAL_PATTERN}
    elif field.type == "number":
        schema = {"type": "number"}
    elif field.type == "boolean":
        schema = {"type": "boolean"}
    elif field.type == "picklist":
        active = sorted((o for o in field.options if o.active), key=lambda o: (o.position, o.key))
        schema = {"type": "string", "enum": [o.key for o in active]}
    else:
        schema = {"type": "string"}
    if field.type in _FORMATS:
        schema["format"] = _FORMATS[field.type]
    if field.max_length is not None:
        schema["maxLength"] = field.max_length
    return schema


def query_value(field: FieldDefinition) -> dict[str, Any]:
    """A filter's value of the field on the wire: as a write sends it, except
    that a picklist takes any of its keys, an inactive one finding the records
    that keep it (custom-objects ticket 04)."""
    if field.type == "picklist":
        keys = sorted(field.options, key=lambda o: (o.position, o.key))
        return {"type": "string", "enum": [o.key for o in keys]}
    return value_schema(field)


def query_grammar(applied: AppliedObject, readable: frozenset[str]) -> dict[str, Any]:
    """The filter tree a caller reading ``readable`` may send, as JSON Schema."""
    values: dict[str, Mapping[str, object]] = {
        NAME: {"type": "string", "minLength": 1, "maxLength": 255},
        OWNER: {"type": "string", "format": "uuid"},
        WORKSPACE: {"type": "string", "format": "uuid"},
    }
    for api_name, definition in applied.definition.fields.items():
        if api_name != NAME and applied.storage[api_name].storage_kind == "slot":
            values[api_name] = query_value(definition)
    return query_json_schema(query_schema(applied, readable), values=values)


def _object(properties: Mapping[str, Any], required: list[str]) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA,
        "type": "object",
        "additionalProperties": False,
        "properties": dict(properties),
    }
    if required:
        schema["required"] = required
    return schema


def _nullable(field: FieldDefinition) -> dict[str, Any]:
    value = value_schema(field)
    return value if field.required else {"anyOf": [value, {"type": "null"}]}


def project(applied: AppliedObject) -> ObjectSchemas:
    fields = [
        f
        for name, f in sorted(applied.definition.fields.items())
        if applied.storage[name].storage_kind != "system"
    ]
    name = {"type": "string", "minLength": 1, "maxLength": 255}
    writable = {NAME: name, **{f.api_name: _nullable(f) for f in fields}}
    every = frozenset(applied.definition.fields)
    return ObjectSchemas(
        object_id=applied.object_id,
        schema_version=applied.schema_version,
        create=_object(writable, [NAME, *(f.api_name for f in fields if f.required)]),
        update=_object(writable, []),
        query=query_grammar(applied, every),
        sortable=SORTABLE,
        ai_descriptions=AiDescriptions(
            object=applied.definition.ai_description,
            fields={f.api_name: f.ai_description for f in fields if f.ai_description},
        ),
        source=applied,
    )


_Key = tuple[uuid.UUID, uuid.UUID, int]


def cache_key(tenant_id: uuid.UUID, object_id: uuid.UUID, schema_version: int) -> _Key:
    """The one cache key: the tenant first (gate CRITICAL, 3/11/2026)."""
    return (tenant_id, object_id, schema_version)


class ObjectSchemaProjector:
    def __init__(
        self, reader: ObjectDefinitionReader, *, max_entries: int = DEFAULT_CACHE_ENTRIES
    ) -> None:
        if max_entries < 1:
            raise ValueError("the cache holds at least one entry")
        self.reader = reader
        self.max_entries = max_entries
        self._cache: OrderedDict[_Key, ObjectSchemas] = OrderedDict()

    async def schemas(
        self, tenant_id: uuid.UUID, object_id: uuid.UUID, schema_version: int
    ) -> ObjectSchemas | None:
        """The schemas of that tenant's object at `schema_version`, the one the
        caller snapshot. A newer definition read on a miss is returned and kept
        under its own version; the caller compares `schema_version`."""
        key = cache_key(tenant_id, object_id, schema_version)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        applied = await self.reader.read(tenant_id, object_id)
        if applied is None:
            return None
        built = project(applied)
        self._remember(cache_key(tenant_id, object_id, built.schema_version), built)
        return built

    def _remember(self, key: _Key, schemas: ObjectSchemas) -> None:
        self._cache[key] = schemas
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)


def narrowed(
    schemas: ObjectSchemas,
    *,
    readable: frozenset[str],
    editable: frozenset[str],
    creatable: frozenset[str],
) -> ObjectSchemas:
    """``schemas`` as one caller may use them (R3.6, R3.7; custom-objects
    ticket 03 step 9): the create schema with the fields `create` lets it
    write, the update schema with those it edits, the query grammar of its
    own `QuerySchema` (custom-objects ticket 04), the sorts and the company's
    words without any field hidden from it. Applied to
    each call after the cache, never stored in it (gate M5), so a field
    secured without a new `schema_version` is out at the next call."""

    def keep(schema: Mapping[str, Any], names: frozenset[str]) -> dict[str, Any]:
        out = dict(schema)
        out["properties"] = {k: v for k, v in schema["properties"].items() if k in names}
        required = [k for k in schema.get("required", ()) if k in names]
        if required:
            out["required"] = required
        else:
            out.pop("required", None)
        return out

    return ObjectSchemas(
        object_id=schemas.object_id,
        schema_version=schemas.schema_version,
        create=keep(schemas.create, creatable),
        update=keep(schemas.update, editable),
        query={} if schemas.source is None else query_grammar(schemas.source, readable),
        sortable=tuple(s for s in schemas.sortable if s != NAME or NAME in readable),
        ai_descriptions=AiDescriptions(
            object=schemas.ai_descriptions.object,
            fields={k: v for k, v in schemas.ai_descriptions.fields.items() if k in readable},
        ),
        source=schemas.source,
    )
