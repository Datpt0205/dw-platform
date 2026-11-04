"""`dw.toolset/v1`: the `toolset` an agent version embeds (ADR-0116 decision 6,
amended 2026-11-04; tools-and-skills ticket 02 step 1).

Not a kind of its own: a section of the `dw.agent/v1` document, `{tools:
[...]}`, whose W1 entries are an object's read operations (`object_crud`) or
one connector action (`connector_action`). The entries name what they use, not
a version: the envelope's seal pins each object's `live` version and hash as it
pins every `artifact` reference, and the run resolves only what was pinned.

Two pure functions, which the `agent` kind's validator and extractor call
(agent-builder/02), never a copy: `validate_toolset` returns every problem at
once, each at a pointer under `/toolset`; `extract_toolset` returns the
references the seal resolves. In core, not in a capability: the `agent` kind,
the object tools of tools-and-skills/03 and the action compiler of
connections-and-vault/05 each read these entries, and Studio's capabilities
never import one another (R5.2). The limits on what reaches a model, 64
characters a name and 40 tools, are the runtime's (`dw_agent_runtime.
contracts`), so the seal and the assembler read one number each.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from dw_agent_runtime.contracts import MAX_MODEL_TOOLS, MAX_TOOL_NAME_CHARS, model_facing_name
from dw_studio.core.domain.artifacts import (
    DocumentInvalidError,
    DocumentProblem,
    Reference,
    TargetKind,
    Usage,
)

TOOLSET_SCHEMA: Final = "dw.toolset/v1"
TOOLSET_POINTER: Final = "/toolset"

OBJECT_CRUD: Final = "object_crud"
CONNECTOR_ACTION: Final = "connector_action"
# The kinds a W1 toolset holds; `http`, `mcp`, `workflow` and `code` come with
# their own tickets (ADR-0116 decision 1).
W1_KINDS: Final = frozenset({OBJECT_CRUD, CONNECTOR_ACTION})

# A connector's manifest key (`configs/connectors/<key>@<semver>.yaml`), an
# action's namespaced name (connections-and-vault/05's load rule) and a binding
# name (tenant-config/05). An action's length is not capped here: its
# model-facing name is, as `tool_name_too_long`.
_CONNECTOR_KEY: Final = r"^[a-z][a-z0-9_]*@\d+\.\d+\.\d+$"
_ACTION_NAME: Final = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
_BINDING_NAME: Final = r"^[a-z][a-z0-9_]{0,62}$"

ObjectOperation = Literal["search", "get"]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObjectCrudEntry(_Entry):
    """An object's read tools, one per enabled operation (`obj_<api_name>__search`,
    `obj_<api_name>__get`); `object` is the object artifact's id."""

    kind: Literal["object_crud"]
    object: uuid.UUID
    operations: tuple[ObjectOperation, ...] = Field(min_length=1)

    def pin(self) -> tuple[str, str]:
        """The `(kind, key)` the run manifest pins this entry under."""
        return TargetKind.ARTIFACT.value, str(self.object)

    def tool_keys(self) -> list[tuple[str, ...]]:
        # The object's API name is the envelope's, not the document's, so a
        # tool is told apart by object and operation until the run builds it.
        return [(OBJECT_CRUD, str(self.object), operation) for operation in self.operations]

    def references(self, path: str) -> list[Reference]:
        kind, key = self.pin()
        return [Reference(TargetKind(kind), key, Usage.READ, path)]


class ConnectorActionEntry(_Entry):
    """One action of a platform connector, through the binding its run
    supplies (DO-06): the tool's name is the action's model-facing name."""

    kind: Literal["connector_action"]
    connector: StrictStr = Field(pattern=_CONNECTOR_KEY)
    action: StrictStr = Field(pattern=_ACTION_NAME)
    binding: StrictStr = Field(pattern=_BINDING_NAME)

    def pin(self) -> tuple[str, str]:
        """The `(kind, key)` the run manifest pins this entry under."""
        return TargetKind.CONNECTOR.value, self.connector

    def tool_name(self) -> str:
        return model_facing_name(self.action)

    def tool_keys(self) -> list[tuple[str, ...]]:
        return [(CONNECTOR_ACTION, self.tool_name())]

    def references(self, path: str) -> list[Reference]:
        kind, key = self.pin()
        return [
            Reference(TargetKind(kind), key, Usage.INVOKE, path),
            Reference(TargetKind.BINDING, self.binding, Usage.BIND, path),
        ]


ToolsetEntry = Annotated[ObjectCrudEntry | ConnectorActionEntry, Field(discriminator="kind")]


class ToolsetSpec(BaseModel):
    """`dw.toolset/v1`: the tools an agent version pins."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tools: tuple[ToolsetEntry, ...] = ()


_CODES: Final[Mapping[str, str]] = {
    "missing": "required",
    "extra_forbidden": "not_allowed",
    "literal_error": "value_not_allowed",
    "string_pattern_mismatch": "value_not_allowed",
    "too_short": "too_short",
}


def _pointer(base: str, location: Sequence[int | str]) -> str:
    parts = (str(part).replace("~", "~0").replace("/", "~1") for part in location)
    return base + "".join(f"/{part}" for part in parts)


def _problems(error: ValidationError, at: str) -> list[DocumentProblem]:
    # A fixed sentence per code, never pydantic's message: it may echo the value.
    return [
        DocumentProblem(
            _pointer(at, tuple(item["loc"])),
            _CODES.get(item["type"], "wrong_type"),
            "the value is not one this toolset takes",
        )
        for item in error.errors()
    ]


_ENTRY_MODELS: Final[Mapping[str, type[ObjectCrudEntry] | type[ConnectorActionEntry]]] = {
    OBJECT_CRUD: ObjectCrudEntry,
    CONNECTOR_ACTION: ConnectorActionEntry,
}


def _entries(
    toolset: Any, at: str
) -> tuple[list[tuple[int, ObjectCrudEntry | ConnectorActionEntry]], list[DocumentProblem]]:
    """Each entry that parses, with its index, and a problem for each that
    does not: a kind outside W1 is `toolset.kind_unsupported` at its `kind`."""
    if isinstance(toolset, ToolsetSpec):
        return list(enumerate(toolset.tools)), []
    if not isinstance(toolset, Mapping):
        return [], [DocumentProblem(at, "wrong_type", "a toolset is an object")]
    extra = sorted(set(toolset) - {"tools"})
    problems = [
        DocumentProblem(f"{at}/{name}", "not_allowed", "a toolset holds only tools")
        for name in extra
    ]
    tools = toolset.get("tools", [])
    if not isinstance(tools, list):
        return [], [*problems, DocumentProblem(f"{at}/tools", "wrong_type", "tools is a list")]
    parsed: list[tuple[int, ObjectCrudEntry | ConnectorActionEntry]] = []
    for n, raw in enumerate(tools):
        where = f"{at}/tools/{n}"
        kind = raw.get("kind") if isinstance(raw, Mapping) else None
        model = _ENTRY_MODELS.get(kind) if isinstance(kind, str) else None
        if model is None:
            problems.append(
                DocumentProblem(
                    f"{where}/kind",
                    "toolset.kind_unsupported",
                    "a W1 toolset holds object_crud and connector_action entries",
                )
            )
            continue
        try:
            parsed.append((n, model.model_validate(raw)))
        except ValidationError as exc:
            problems.extend(_problems(exc, where))
    return parsed, problems


def validate_toolset(toolset: Any, *, at: str = TOOLSET_POINTER) -> list[DocumentProblem]:
    """Every problem of a toolset at once (R4.3, R4.5): its shape, a kind
    outside W1, two entries giving one tool, an action whose model-facing
    name is past 64 characters, and more than 40 tools reaching the model,
    an object entry counting one tool per enabled operation."""
    entries, problems = _entries(toolset, at)
    seen: set[tuple[str, ...]] = set()
    count = 0
    for n, entry in entries:
        where = f"{at}/tools/{n}"
        if isinstance(entry, ConnectorActionEntry) and len(entry.tool_name()) > MAX_TOOL_NAME_CHARS:
            problems.append(
                DocumentProblem(
                    f"{where}/action",
                    "tool_name_too_long",
                    f"the action's tool name is longer than {MAX_TOOL_NAME_CHARS} characters",
                )
            )
        for key in entry.tool_keys():
            count += 1
            if key in seen:
                problems.append(
                    DocumentProblem(
                        where, "toolset.duplicate_tool", "another entry already gives this tool"
                    )
                )
            seen.add(key)
    if count > MAX_MODEL_TOOLS:
        problems.append(
            DocumentProblem(
                f"{at}/tools",
                "too_many_tools",
                f"{count} tools would reach the model; at most {MAX_MODEL_TOOLS}",
            )
        )
    return problems


def extract_toolset(toolset: Any, *, at: str = TOOLSET_POINTER) -> list[Reference]:
    """What the seal resolves (tenant-config R2.7): an object entry reads its
    object (`artifact`, `read`), an action entry invokes its connector
    (`connector`, `invoke`) through its binding (`binding`, `bind`), each at
    the entry's pointer. An entry that does not parse gives none; the
    validator names it."""
    entries, _ = _entries(toolset, at)
    return [ref for n, entry in entries for ref in entry.references(f"{at}/tools/{n}")]


def parse_toolset(toolset: Any, *, at: str = TOOLSET_POINTER) -> ToolsetSpec:
    """The toolset of a sealed version, for the run that builds its tools;
    `DocumentInvalidError` with every problem otherwise."""
    problems = validate_toolset(toolset, at=at)
    if problems:
        raise DocumentInvalidError("the toolset is not valid", problems)
    entries, _ = _entries(toolset, at)
    return ToolsetSpec(tools=tuple(entry for _, entry in entries))
