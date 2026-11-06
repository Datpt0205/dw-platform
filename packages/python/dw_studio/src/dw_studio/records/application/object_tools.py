"""`ObjectToolGenerator`: an agent's read tools over one company object, made
from the object version the run pinned (tools-and-skills ticket 03; R6.1-R6.8;
ADR-0116 decisions 1, 4, 5).

A toolset entry `{kind: object_crud, object, operations}` and the object
version its run manifest pinned give one `dw.tool/v1` tool per enabled
operation, `obj_<api_name>__search` and `obj_<api_name>__get`, never
registered: the run hands each to the executor itself (`pinned=`). The schemas
come from `project(...)` over the pinned version's own document, never the
projector's cache of the version in force, so a field added after the pin is
neither offered nor returned. `object_tools` is a pure function of that
version and of the object as `studio.field_defs` holds it now, which
agent-builder/05's boundary derivation calls too.

Three schemas per tool, on purpose:

- the executor's input schema, every filterable field of the pinned version,
  a field soft-deleted since included, so a call naming it reaches
  RecordService and is refused there with no row (R6.7);
- the model's view (`ObjectToolView`), without a soft-deleted field (R6.5) and,
  at every model call, without a field the run's actor cannot read (R6.3,
  `FieldSecurityToolSchemaMiddleware`): it only narrows;
- the output schema, a record as the records API shows it (one owner of that
  shape, `records.presentation.views`), with the pinned version's fields only.

A field "soft-deleted since the pin" is one the pinned version has and the
object's live definition no longer has: in W1 no field can leave a published
object (R2.4, `live_incompatible`), and field deletion (ADR-0107 decision 5)
is custom-objects W2, whose soft delete takes the field out of the live
definition `applied_object` reads. Every word a company wrote
(`ai_description`) reaches the description inside one escaped `<input>`
block, cut, never as an instruction (R6.8; ADR-0010).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

from pydantic import BaseModel

from dw_agent_runtime.contracts import DEFAULT_MAX_OUTPUT_CHARS, RunContext, ToolDefinition
from dw_agent_runtime.model.copy import CopyCodes
from dw_agent_runtime.model.prompts import TRUNCATED_MARK, contain_untrusted
from dw_agent_runtime.ports import ObjectDataPort, ObjectSearch, PinnedEntry, PinnedVersion
from dw_agent_runtime.studio_agent import LoadedToolKinds
from dw_agent_runtime.tool_kinds import CompiledTool, ToolBinding, ToolContract, ToolsetEntry
from dw_agent_runtime.tool_schema import json_schema_behaviour
from dw_agent_runtime.tools import FieldNarrowing, ModelView, ToolBehaviour
from dw_kernel.errors import ConfigError
from dw_kernel.filters import COMPARISONS
from dw_kernel.personal_data import PdCategory
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.core.domain.toolset import OBJECT_CRUD
from dw_studio.records.application.ports import (
    AppliedObject,
    FieldStorage,
    ObjectDefinitionReader,
)
from dw_studio.records.application.record_service import record_not_found
from dw_studio.records.application.schema_projector import project, value_schema
from dw_studio.records.domain.document import (
    NAME,
    OBJECT_DOCUMENT_SCHEMA,
    OWNER,
    WORKSPACE,
    definition_of,
)

SEARCH: Final = "search"
GET: Final = "get"
OPERATIONS: Final = (SEARCH, GET)
COPY_ID: Final = "studio.object_tools"
# R6.1 (gate, 4/11/2026): at most ten AND leaves; a page of 1 to 50, 20 unless asked.
MAX_FILTERS: Final = 10
MAX_LIMIT: Final = 50
DEFAULT_LIMIT: Final = 20
# The order a leaf's operators are listed in; the field's own family decides
# which of them it takes (`record_query`), at RecordService.
_OPERATORS: Final = tuple(sorted(COMPARISONS))
_DIRECTIONS: Final = ("asc", "desc")
_SCALARS: Final = ["string", "number", "boolean"]
# ADR-0116 decision 4's closed set, by the highest `pd_category` of the pinned
# fields (ADR-0106, amendment of 4/11/2026); never the category itself.
_CLASSIFICATION: Final[Mapping[str, str]] = {
    PdCategory.NONE.value: "none",
    PdCategory.BASIC.value: "personal",
    PdCategory.SENSITIVE.value: "sensitive",
}
_PD_RANK: Final[Mapping[str, int]] = {"none": 0, "basic": 1, "sensitive": 2}
_SYSTEM: Final = frozenset({NAME, OWNER, WORKSPACE})
_NO_STORAGE: Final = FieldStorage(uuid.UUID(int=0), "data", None, None)
# The block a company's words take in a description, and how much of them.
DESCRIPTION_BLOCK: Final = "object_description"
_COPY_CODES: Final = (
    "template",
    "data_note",
    *(f"{op}.{part}" for op in OPERATIONS for part in ("summary", "when", "when_not", "returns")),
)


def _refuse(message: str, reason: str, **details: object) -> ConfigError:
    return ConfigError(message, details={"reason": reason, **details})


# ---- the fixed words -------------------------------------------------------------

_PLACEHOLDER: Final = re.compile(r"\{([a-z_]+)\}")


def _fill(template: str, values: Mapping[str, str]) -> str:
    """``template``'s `{name}` placeholders replaced in one pass, never
    `str.format` (ADR-0114 decision 1): a value is put in as it is and never
    read as a template itself, and a placeholder with no value is a
    `ConfigError` naming it, as a copy code that does not exist is."""

    def value(found: re.Match[str]) -> str:
        name = found.group(1)
        if name not in values:
            raise ConfigError(f"copy placeholder {name!r} has no value")
        return values[name]

    return _PLACEHOLDER.sub(value, template)


@dataclass(frozen=True)
class ObjectToolCopy:
    """`configs/copy/studio_object_tools.yaml`, its codes checked on load."""

    codes: CopyCodes

    @classmethod
    def of(cls, codes: CopyCodes) -> ObjectToolCopy:
        if codes.copy_id != COPY_ID:
            raise ConfigError(f"copy {codes.copy_id} is not {COPY_ID}")
        for code in _COPY_CODES:
            codes.text(f"{COPY_ID}.{code}")
        return cls(codes)

    def _text(self, code: str) -> str:
        return self.codes.text(f"{COPY_ID}.{code}")

    def description(self, operation: str, api_name: str, block: str | None) -> str:
        text = _fill(
            self._text("template"),
            {
                "summary": _fill(self._text(f"{operation}.summary"), {"object": api_name}),
                "when": self._text(f"{operation}.when"),
                "when_not": self._text(f"{operation}.when_not"),
                "returns": self._text(f"{operation}.returns"),
            },
        )
        if block is None:
            return text
        return f"{text}\n{self._text('data_note')}\n{block}"


# ---- the model's view (R6.3, R6.5, R6.8) -----------------------------------------


def search_args(filterable: Sequence[str], sortable: Sequence[str]) -> dict[str, Any]:
    """`search`'s arguments: AND leaves over ``filterable``, an order on one of
    ``sortable``, a page. A value's type is RecordService's to coerce and
    refuse (custom-objects/04), so no branch per field here."""
    properties: dict[str, Any] = {}
    if filterable:
        properties["filters"] = {
            "type": "array",
            "maxItems": MAX_FILTERS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "op", "value"],
                "properties": {
                    "field": {"type": "string", "enum": list(filterable)},
                    "op": {"type": "string", "enum": list(_OPERATORS)},
                    "value": {"type": [*_SCALARS, "array"], "items": {"type": list(_SCALARS)}},
                },
            },
        }
    if sortable:
        properties["order_by"] = {
            "type": "string",
            "enum": [f"{name} {direction}" for name in sortable for direction in _DIRECTIONS],
        }
    properties["limit"] = {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}
    properties["cursor"] = {"type": "string", "minLength": 1}
    return {"type": "object", "additionalProperties": False, "properties": properties}


GET_ARGS: Final[Mapping[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id"],
    "properties": {"id": {"type": "string", "format": "uuid"}},
}


def _cut(text: str) -> str:
    if len(text) <= DEFAULT_MAX_OUTPUT_CHARS:
        return text
    return text[: DEFAULT_MAX_OUTPUT_CHARS - len(TRUNCATED_MARK)] + TRUNCATED_MARK


@dataclass(frozen=True)
class ObjectToolView:
    """What the model is shown of one object tool, for the fields it may see.

    ``visible`` is the pinned version's fields less those soft-deleted since
    (R6.5), `name` included; `view` intersects it with what the actor reads,
    so nothing outside it is ever shown (R6.3)."""

    api_name: str
    operation: str
    visible: frozenset[str]
    filterable: tuple[str, ...]
    sortable: tuple[str, ...]
    object_description: str | None
    field_descriptions: Mapping[str, str]
    copy: ObjectToolCopy

    def view(self, readable: frozenset[str]) -> ModelView:
        seen = self.visible & readable
        if self.operation == SEARCH:
            args = search_args(
                [name for name in self.filterable if name in seen],
                [name for name in self.sortable if name != NAME or NAME in seen],
            )
        else:
            args = dict(GET_ARGS)
        return ModelView(
            args, self.copy.description(self.operation, self.api_name, self._block(seen))
        )

    def _block(self, seen: frozenset[str]) -> str | None:
        lines = [] if self.object_description is None else [self.object_description]
        lines += [
            f"{name}: {text}"
            for name, text in sorted(self.field_descriptions.items())
            if name in seen
        ]
        if not lines:
            return None
        return contain_untrusted(DESCRIPTION_BLOCK, _cut("\n".join(lines)))


# ---- the output, one record as the records API shows it ---------------------------


def _nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


def _uuid() -> dict[str, Any]:
    return {"type": "string"}


def record_schema(field_types: Mapping[str, str]) -> dict[str, Any]:
    """A record of `records.presentation.views.RecordItem`, less
    `hidden_fields` (field-security R4.2): a hidden field is simply absent."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "object",
            "version",
            "etag",
            "owner",
            "workspace_id",
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
            "name",
            "fields",
        ],
        "properties": {
            "id": _uuid(),
            "object": {"type": "string"},
            "version": {"type": "integer"},
            "etag": {"type": "string"},
            "owner": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "id"],
                "properties": {"kind": {"type": "string"}, "id": _uuid()},
            },
            "workspace_id": _uuid(),
            "created_at": {"type": "string"},
            "created_by": _uuid(),
            "updated_at": {"type": "string"},
            "updated_by": _uuid(),
            "deleted_at": _nullable("string"),
            "deleted_by": _nullable("string"),
            "name": _nullable("string"),
            "fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": {name: _nullable(kind) for name, kind in sorted(field_types.items())},
            },
        },
    }


def search_output(field_types: Mapping[str, str]) -> dict[str, Any]:
    """`next_cursor` first, so a page the wrapper cuts still says there is more."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["next_cursor", "items"],
        "properties": {
            "next_cursor": _nullable("string"),
            "items": {"type": "array", "items": record_schema(field_types)},
        },
    }


# ---- the pure function -------------------------------------------------------------


def _pinned_object(version: PinnedVersion, now: AppliedObject) -> AppliedObject:
    """The pinned version's document as `project` reads an object: what it
    decided, where each of its fields lives (a slot never moves while the
    field lives, ADR-0107 decision 5), at the version's own number."""
    if version.document_schema != OBJECT_DOCUMENT_SCHEMA:
        raise _refuse(
            "an object tool pins an object version",
            "pinned_not_object",
            document_schema=version.document_schema,
        )
    if version.version_no is None:
        raise _refuse("an object tool pins a published object version", "pinned_unnumbered")
    try:
        decided = definition_of(version.document)
    except DocumentInvalidError as exc:
        raise _refuse("the pinned object version is not valid", "pinned_invalid") from exc
    names = [*decided.fields, OWNER, WORKSPACE]
    return AppliedObject(
        object_id=version.artifact_id,
        api_name=now.api_name,
        applied_version_id=version.id,
        schema_version=version.version_no,
        definition=decided,
        storage={name: now.storage.get(name, _NO_STORAGE) for name in names},
    )


def _classification(pinned: AppliedObject) -> str:
    highest = max(
        (f.pd_category for f in pinned.definition.fields.values()),
        key=lambda category: _PD_RANK[category],
        default=PdCategory.NONE.value,
    )
    return _CLASSIFICATION[highest]


def object_tools(
    operations: Sequence[str],
    version: PinnedVersion,
    now: AppliedObject,
    copy: ObjectToolCopy,
) -> list[CompiledTool]:
    """One tool per operation over ``version``, the object version a run
    pinned, ``now`` the object as its live definition stands (its API name,
    its slots, and which of the pinned fields it still has)."""
    pinned = _pinned_object(version, now)
    schemas = project(pinned)
    fields = pinned.definition.fields
    custom = sorted(name for name in fields if name not in _SYSTEM)
    deleted = frozenset(fields) - frozenset(now.definition.fields)
    # A field filters when its version put it in a slot (ADR-0107 decision 1):
    # the document says so, wherever the slot is.
    filterable = tuple(name for name in custom if fields[name].indexed or fields[name].is_unique)
    types = {name: str(value_schema(fields[name])["type"]) for name in custom}
    returned = frozenset(custom) - deleted
    tools: list[CompiledTool] = []
    for operation in dict.fromkeys(operations):
        if operation not in OPERATIONS:
            raise _refuse("an object tool reads only", "operation_unknown", operation=operation)
        view = ObjectToolView(
            api_name=pinned.api_name,
            operation=operation,
            visible=frozenset(fields) - deleted,
            filterable=filterable,
            sortable=schemas.sortable,
            object_description=schemas.ai_descriptions.object,
            field_descriptions=schemas.ai_descriptions.fields,
            copy=copy,
        )
        built = view.view(view.visible)
        name = f"obj_{pinned.api_name}.{operation}"
        definition = ToolDefinition(
            name=name,
            version=f"{pinned.schema_version}.0.0",
            description=built.description,
            input_schema_ref=f"studio/objects/{version.artifact_id}/{version.id}/{operation}.input",
            output_schema_ref=f"studio/objects/{version.artifact_id}/{version.id}/{operation}.output",
            required_scopes=frozenset(),
            side_effect_level="none",
            approval_policy="never",
            timeout_seconds=30,
            max_retries=1,
            idempotent=True,
            data_classification=frozenset({_classification(pinned)}),
            simulate_safe=True,
        )
        output = search_output(types) if operation == SEARCH else record_schema(types)
        executor_input = (
            search_args(filterable, schemas.sortable) if operation == SEARCH else dict(GET_ARGS)
        )
        tools.append(
            CompiledTool(
                ToolBinding(
                    OBJECT_CRUD,
                    {"object": pinned.api_name, "fields": returned, "view": view},
                    operation="read",
                ),
                ToolContract(definition, executor_input, output),
            )
        )
    return tools


# ---- the source and the factory -----------------------------------------------------


class ObjectToolGenerator:
    """The `object_crud` source and factory of a Studio run's assembler
    (`studio_tools`): `compile` makes an entry's tools from its pinned
    version, `build` their behaviour over `ObjectDataPort`. Built for one run
    by `load`, which reads each pinned object as it stands now under the run's
    company, once; afterwards nothing here reads the database."""

    def __init__(
        self,
        data: ObjectDataPort,
        copy: ObjectToolCopy,
        objects: Mapping[uuid.UUID, AppliedObject],
    ) -> None:
        self.data = data
        self.copy = copy
        self.objects = objects

    @classmethod
    async def load(
        cls,
        reader: ObjectDefinitionReader,
        tenant_id: uuid.UUID,
        entries: Sequence[ToolsetEntry],
        *,
        data: ObjectDataPort,
        copy: ObjectToolCopy,
    ) -> ObjectToolGenerator:
        """The generator for a run of ``tenant_id``, the company the run says,
        never a request: each `object_crud` entry's object as defined now."""
        objects: dict[uuid.UUID, AppliedObject] = {}
        for entry in entries:
            if entry.kind != OBJECT_CRUD:
                continue
            object_id = uuid.UUID(entry.pin()[1])
            found = await reader.read(tenant_id, object_id)
            if found is not None:
                objects[object_id] = found
        return cls(data, copy, objects)

    def compile(self, entry: ToolsetEntry, pinned: PinnedEntry) -> Sequence[CompiledTool]:
        object_id = uuid.UUID(entry.pin()[1])
        version = pinned.artifact
        now = self.objects.get(object_id)
        if version is None or version.artifact_id != object_id or now is None:
            raise _refuse("the pinned object is not this company's", "object_unavailable")
        return object_tools(tuple(getattr(entry, "operations", ())), version, now, self.copy)

    def build(self, binding: ToolBinding, contract: ToolContract) -> ToolBehaviour:
        view: ObjectToolView = binding.config["view"]
        api_name = str(binding.config["object"])
        fields = frozenset(binding.config["fields"])
        handler = (
            self._search(api_name, fields)
            if view.operation == SEARCH
            else self._get(api_name, fields)
        )
        behaviour = json_schema_behaviour(contract.input_schema, contract.output_schema, handler)
        return replace(
            behaviour,
            args_schema=view.view(view.visible).args_schema,
            narrowing=FieldNarrowing(api_name, view.view),
        )

    def _search(self, api_name: str, fields: frozenset[str]) -> Any:
        async def handler(payload: BaseModel, run: RunContext) -> Mapping[str, Any]:
            args = payload.model_dump()
            leaves = [
                {leaf["field"]: {leaf["op"]: leaf["value"]}} for leaf in args.get("filters") or ()
            ]
            request = ObjectSearch(
                filter={"$and": leaves} if leaves else None,
                order_by=args.get("order_by"),
                limit=int(args.get("limit") or DEFAULT_LIMIT),
                cursor=args.get("cursor"),
                fields=fields,
            )
            return await self.data.search(run, api_name, request)

        return handler

    def _get(self, api_name: str, fields: frozenset[str]) -> Any:
        async def handler(payload: BaseModel, run: RunContext) -> Mapping[str, Any]:
            try:
                record_id = uuid.UUID(str(payload.model_dump()["id"]))
            except ValueError:
                raise record_not_found() from None
            return await self.data.get(run, api_name, record_id, fields)

        return handler


@dataclass(frozen=True)
class ObjectToolKinds:
    """`ToolKindsLoaderPort` for `object_crud` (agent-builder/03): a Studio
    agent run's object tools, the generator loaded for the run's company and
    standing as the kind's source and its factory. Built once at the worker's
    composition root, where ``data`` is `RecordObjectData` over the one
    `RecordService` with each call's door in `agent_record_session`."""

    reader: ObjectDefinitionReader
    data: ObjectDataPort
    copy: ObjectToolCopy

    async def load(self, tenant_id: uuid.UUID, entries: Sequence[ToolsetEntry]) -> LoadedToolKinds:
        generator = await ObjectToolGenerator.load(
            self.reader, tenant_id, entries, data=self.data, copy=self.copy
        )
        return LoadedToolKinds(sources={OBJECT_CRUD: generator}, factories={OBJECT_CRUD: generator})
