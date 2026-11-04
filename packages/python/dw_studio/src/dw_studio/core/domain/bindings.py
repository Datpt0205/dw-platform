"""Bindings: what a document names, and the values a Binding set gives them
(tenant-config R7, R8; ADR-0110 decisions 6-8; D11).

A document never carries a connection id, a person or a setting; it declares
`bindings[]`, one entry per name it needs, and the values live in the
artifact's approved Binding set (`platform.config_versions`, kind
`binding_set`), proposed by one person and approved by another.

One shape for every kind, read here and nowhere else:

- `{"name", "kind", "required", "description"}` on every entry: `name` matches
  `^[a-z][a-z0-9_]{0,62}$` and is declared once per document; `required` is
  stated, never defaulted;
- `connection`: `connector_key`, `connector_major` and `required_scopes`, which
  must be empty in W1 (a P1 connection has no scopes; OAuth scopes are W2), or
  the seal refuses `binding_scopes_unsupported`;
- `variable`: `schema`, one scalar JSON Schema inside `dw.tool-schema/v1`'s
  closed profile (no `pattern`, `$ref` or `format` outside the platform's
  list), and an optional `default`, the value's JSON text: a `required`
  variable with a `default` counts as set (gate 4/11/2026 (k));
- `principal`: an identity of the company, a service principal or a member.

`secret`, `webhook_endpoint` and `schedule` join with their readers (ADR-0110
decision 6), not before: a kind nothing reads would accept every value.

A Binding set's document is `{"values": {<name>: <value>}}`: a connection's
and a principal's value is the id as text, a variable's its JSON value.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from dw_kernel.canonical import CanonicalError, content_hash, ensure_hashable
from dw_studio.core.domain.artifacts import DocumentProblem, Reference, TargetKind, Usage

BINDING_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
CONNECTOR_KEY: Final = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
BINDINGS_KEY: Final = "bindings"
VALUES_KEY: Final = "values"
# 256 KiB, `ck_config_versions_document_size`.
MAX_BINDING_SET_BYTES: Final = 262144

# The scalar types a variable takes, and the keywords its schema may use: a
# closed subset of `dw.tool-schema/v1` (ADR-0116 decision 3), so no `pattern`
# and no `$ref` reach the validator.
VARIABLE_TYPES: Final = frozenset({"string", "integer", "number", "boolean"})
VARIABLE_KEYWORDS: Final = frozenset(
    {
        "type",
        "title",
        "description",
        "enum",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "format",
    }
)


class BindingKind(StrEnum):
    """The W1 kinds of a binding (ADR-0110 decision 6)."""

    CONNECTION = "connection"
    VARIABLE = "variable"
    PRINCIPAL = "principal"


_COMMON: Final = frozenset({"name", "kind", "required", "description"})
_FIELDS: Final[Mapping[BindingKind, frozenset[str]]] = {
    BindingKind.CONNECTION: _COMMON | {"connector_key", "connector_major", "required_scopes"},
    BindingKind.VARIABLE: _COMMON | {"schema", "default"},
    BindingKind.PRINCIPAL: _COMMON,
}


@dataclass(frozen=True, slots=True)
class BindingDecl:
    """One declared binding, as the seal accepted it."""

    name: str
    kind: BindingKind
    required: bool
    description: str = ""
    connector_key: str | None = None
    connector_major: int | None = None
    schema: Mapping[str, Any] | None = None
    # The parsed `default` of a variable; `has_default` says whether there is one
    # (a JSON `null` is a value).
    default: Any = None
    has_default: bool = False

    def as_json(self) -> dict[str, Any]:
        """The canonical form `bindings_hash` reads: what a value is checked
        against, never the description."""
        body: dict[str, Any] = {"name": self.name, "kind": self.kind.value}
        body["required"] = self.required
        if self.kind is BindingKind.CONNECTION:
            body["connector_key"] = self.connector_key
            body["connector_major"] = self.connector_major
        if self.kind is BindingKind.VARIABLE:
            body["schema"] = dict(self.schema or {})
            if self.has_default:
                body["default"] = self.default
        return body


@dataclass(frozen=True, slots=True)
class Declarations:
    """A document's bindings, or every problem with them."""

    items: tuple[BindingDecl, ...] = ()
    problems: tuple[DocumentProblem, ...] = ()

    def by_name(self) -> dict[str, BindingDecl]:
        return {decl.name: decl for decl in self.items}


def _problem(at: str, code: str, detail: str) -> DocumentProblem:
    return DocumentProblem(at, code, detail)


def _variable_problems(schema: Any, at: str) -> list[DocumentProblem]:
    if not isinstance(schema, dict):
        return [_problem(at, "binding_schema_invalid", "a variable's schema is an object")]
    found = [
        _problem(f"{at}/{key}", "binding_schema_invalid", "outside the closed profile")
        for key in sorted(set(schema) - VARIABLE_KEYWORDS)
    ]
    if schema.get("type") not in VARIABLE_TYPES:
        found.append(
            _problem(f"{at}/type", "binding_schema_invalid", "string, integer, number or boolean")
        )
    return found


def _parse_one(raw: Any, at: str) -> tuple[BindingDecl | None, list[DocumentProblem]]:
    if not isinstance(raw, dict):
        return None, [_problem(at, "binding_invalid", "a binding is an object")]
    found: list[DocumentProblem] = []
    name, kind_raw, required = raw.get("name"), raw.get("kind"), raw.get("required")
    if not isinstance(name, str) or not BINDING_NAME.fullmatch(name):
        found.append(_problem(f"{at}/name", "binding_name_invalid", "^[a-z][a-z0-9_]{0,62}$"))
    try:
        kind = BindingKind(str(kind_raw))
    except ValueError:
        return None, [
            *found,
            _problem(f"{at}/kind", "binding_kind_unknown", "connection, variable or principal"),
        ]
    if not isinstance(required, bool):
        found.append(_problem(f"{at}/required", "binding_required_missing", "true or false"))
    description = raw.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        found.append(_problem(f"{at}/description", "binding_invalid", "at most 500 characters"))
    found += [
        _problem(f"{at}/{key}", "binding_field_unknown", f"not a field of a {kind.value}")
        for key in sorted(set(raw) - _FIELDS[kind])
    ]
    decl = BindingDecl(
        name=name if isinstance(name, str) else "",
        kind=kind,
        required=required is True,
        description=description if isinstance(description, str) else "",
    )
    if kind is BindingKind.CONNECTION:
        key, major = raw.get("connector_key"), raw.get("connector_major")
        if not isinstance(key, str) or not CONNECTOR_KEY.fullmatch(key):
            found.append(_problem(f"{at}/connector_key", "binding_invalid", "a connector key"))
        if not isinstance(major, int) or isinstance(major, bool) or major < 1:
            found.append(_problem(f"{at}/connector_major", "binding_invalid", "a major version"))
        scopes = raw.get("required_scopes", [])
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            found.append(_problem(f"{at}/required_scopes", "binding_invalid", "a list of names"))
        elif scopes:
            # Gate 4/11/2026 (j): nothing to compare in W1.
            found.append(
                _problem(
                    f"{at}/required_scopes",
                    "binding_scopes_unsupported",
                    "a W1 connection has no scopes; OAuth scopes are W2",
                )
            )
        decl = BindingDecl(
            name=decl.name,
            kind=kind,
            required=decl.required,
            description=decl.description,
            connector_key=key if isinstance(key, str) else None,
            connector_major=major if isinstance(major, int) else None,
        )
    elif kind is BindingKind.VARIABLE:
        schema = raw.get("schema")
        found += _variable_problems(schema, f"{at}/schema")
        default, has_default = None, "default" in raw
        if has_default:
            text = raw["default"]
            try:
                default = json.loads(text) if isinstance(text, str) else None
                if not isinstance(text, str):
                    raise ValueError("not text")
            except ValueError:
                found.append(
                    _problem(f"{at}/default", "binding_default_invalid", "the value's JSON text")
                )
        decl = BindingDecl(
            name=decl.name,
            kind=kind,
            required=decl.required,
            description=decl.description,
            schema=schema if isinstance(schema, dict) else None,
            default=default,
            has_default=has_default,
        )
    return decl, found


def parse_declarations(document: Any) -> Declarations:
    """The `bindings[]` of any kind's document; a document without one declares
    nothing."""
    if not isinstance(document, dict) or BINDINGS_KEY not in document:
        return Declarations()
    raw = document[BINDINGS_KEY]
    if not isinstance(raw, list):
        return Declarations(
            problems=(_problem(f"/{BINDINGS_KEY}", "binding_invalid", "bindings is a list"),)
        )
    items: list[BindingDecl] = []
    problems: list[DocumentProblem] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        at = f"/{BINDINGS_KEY}/{index}"
        decl, found = _parse_one(entry, at)
        problems += found
        if decl is None:
            continue
        if decl.name in seen:
            problems.append(_problem(f"{at}/name", "binding_name_repeated", "declared twice"))
            continue
        seen.add(decl.name)
        items.append(decl)
    return Declarations(tuple(items), tuple(problems))


def declaration_paths(document: Any) -> dict[str, str]:
    """Each declared name's pointer in `document`."""
    raw = document.get(BINDINGS_KEY) if isinstance(document, dict) else None
    if not isinstance(raw, list):
        return {}
    paths: dict[str, str] = {}
    for index, entry in enumerate(raw):
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name not in paths:
            paths[name] = f"/{BINDINGS_KEY}/{index}"
    return paths


def binding_references(document: Any) -> list[Reference]:
    """One `binding` row of `studio.dependencies` per declared name, `usage`
    `bind`, for every kind, through the seal's one extraction (R3.1)."""
    paths = declaration_paths(document)
    return [
        Reference(TargetKind.BINDING, decl.name, Usage.BIND, paths[decl.name])
        for decl in parse_declarations(document).items
    ]


def bindings_hash(declarations: Iterable[BindingDecl]) -> str:
    """`dw_kernel.canonical` over the declarations ordered by name: what a
    proposal was checked against (`base_bindings_hash`, gate 4/11/2026 (d))."""
    return content_hash(
        [decl.as_json() for decl in sorted(declarations, key=lambda decl: decl.name)]
    )


@dataclass(frozen=True, slots=True)
class Union:
    """The bindings a Binding set of one root may carry: every declaration of
    the latest sealed version's closure, plus the `live` version's where it
    declares a name the candidate does not (gate 4/11/2026 (n), (o))."""

    items: Mapping[str, BindingDecl] = field(default_factory=dict)
    conflicts: tuple[str, ...] = ()


def merge(groups: Sequence[Sequence[BindingDecl]]) -> Union:
    """One name, one kind: the first group's declaration wins a repeated name
    of the same kind; a name declared with two kinds is a conflict."""
    items: dict[str, BindingDecl] = {}
    conflicts: list[str] = []
    for group in groups:
        for decl in group:
            known = items.get(decl.name)
            if known is None:
                items[decl.name] = decl
            elif known.kind is not decl.kind and decl.name not in conflicts:
                conflicts.append(decl.name)
    return Union(items, tuple(conflicts))


def connection_strings(document: Any, *, at: str = "") -> list[tuple[str, uuid.UUID]]:
    """Every string of `document` that reads as a UUID, with its pointer: what
    the seal asks the tenant's connections about (R7.1, TC23)."""
    found: list[tuple[str, uuid.UUID]] = []
    if isinstance(document, str):
        value = as_uuid(document)
        if value is not None:
            found.append((at, value))
    elif isinstance(document, dict):
        for key, value in document.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            found += connection_strings(value, at=f"{at}/{escaped}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found += connection_strings(value, at=f"{at}/{index}")
    return found


# ---- a Binding set's document ------------------------------------------------


def binding_set_values(document: Any) -> dict[str, Any]:
    """`values` of a Binding set's document; anything else holds no value."""
    if not isinstance(document, dict):
        return {}
    values = document.get(VALUES_KEY)
    return dict(values) if isinstance(values, dict) else {}


def document_problems(document: Any) -> list[DocumentProblem]:
    """The shape a Binding set's document keeps before any value is checked:
    one object with `values`, hashable by `dw_kernel.canonical`."""
    if not isinstance(document, dict) or set(document) != {VALUES_KEY}:
        return [_problem("", "binding_set_invalid", 'a Binding set is {"values": {...}}')]
    if not isinstance(document[VALUES_KEY], dict):
        return [_problem(f"/{VALUES_KEY}", "binding_set_invalid", "values is an object")]
    try:
        ensure_hashable(document)
    except CanonicalError as exc:
        return [_problem(str(exc.details.get("pointer", "")), "binding_set_invalid", exc.message)]
    if len(json.dumps(document, ensure_ascii=False).encode()) > MAX_BINDING_SET_BYTES:
        return [_problem("", "binding_set_too_large", "at most 256 KiB")]
    return []


def unset_required(declarations: Iterable[BindingDecl], values: Mapping[str, Any]) -> list[str]:
    """The required names with no value and no default, in name order."""
    return sorted(
        decl.name
        for decl in declarations
        if decl.required and decl.name not in values and not decl.has_default
    )


def as_uuid(value: Any) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
