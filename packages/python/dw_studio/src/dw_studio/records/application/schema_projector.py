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
field-security/01; the query schema names what filters and sorts and the
type of each value, and its grammar is ticket 04's.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from dw_studio.records.application.ports import AppliedObject, ObjectDefinitionReader
from dw_studio.records.domain.document import NAME, FieldDefinition

JSON_SCHEMA: Final = "https://json-schema.org/draft/2020-12/schema"
DEFAULT_CACHE_ENTRIES: Final = 1024
# Sortable beside the slot fields: the indexes of `studio.records` carry them.
SYSTEM_SORTS: Final = ("name", "created_at", "updated_at")

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


def value_schema(field: FieldDefinition) -> dict[str, Any]:
    """One value of the field: its JSON type and bounds, nothing it was called."""
    schema: dict[str, Any]
    if field.type in ("number", "currency"):
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
    filterable = [f for f in fields if applied.storage[f.api_name].storage_kind == "slot"]
    return ObjectSchemas(
        object_id=applied.object_id,
        schema_version=applied.schema_version,
        create=_object(writable, [NAME, *(f.api_name for f in fields if f.required)]),
        update=_object(writable, []),
        query=_object({f.api_name: value_schema(f) for f in filterable}, []),
        sortable=(*SYSTEM_SORTS, *(f.api_name for f in filterable)),
        ai_descriptions=AiDescriptions(
            object=applied.definition.ai_description,
            fields={f.api_name: f.ai_description for f in fields if f.ai_description},
        ),
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
