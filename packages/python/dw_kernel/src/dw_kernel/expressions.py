"""The expression port: one language for tenant text that decides or renders
(ADR-0114 decisions 2-4; workflow-nodes R3).

`ExpressionEngine` is the one door. `check` type-checks a source against an
environment of typed variables and returns its result type or its issues;
`evaluate` runs a checked expression over an activation and returns a JSON
value or an error. Nothing here knows which binding answers it: the one
adapter is `dw_studio.core.adapters.cel.CelCppEngine`, and a replacement joins
only by passing the same contract suite.

Stdlib only (import-linter, "Kernel is pure").
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, get_args

from dw_kernel.ids import TenantId

# The library a run pins on its run manifest (tenant-config R6.1). `v1` is the
# major; a new function is a minor (`time.add_workdays` makes it v1.1, W2), a
# changed one a major (ADR-0114 decision 3).
DW_CEL_LIBRARY = "dw.cel/v1.0"

# ---------------------------------------------------------------------------
# The closed type algebra (ADR-0114 decision 2)
# ---------------------------------------------------------------------------

ScalarKind = Literal[
    "null", "bool", "int", "double", "string", "bytes", "timestamp", "duration", "dyn"
]


@dataclass(frozen=True, slots=True)
class ScalarType:
    """`null`, `bool`, `int`, `double`, `string`, `bytes`, `timestamp`,
    `duration` or `dyn`."""

    kind: ScalarKind


@dataclass(frozen=True, slots=True)
class ListType:
    element: ExprType


@dataclass(frozen=True, slots=True)
class MapType:
    """`map[string, T]`: keys are always strings."""

    value: ExprType


@dataclass(frozen=True, slots=True)
class ObjectType:
    """`object{...}`: a named record of typed fields, sorted by name so two
    spellings of one shape are one type."""

    name: str
    fields: tuple[tuple[str, ExprType], ...]

    def field_type(self, name: str) -> ExprType | None:
        return dict(self.fields).get(name)


@dataclass(frozen=True, slots=True)
class OptionalType:
    """`optional[T]`: a value that may be absent, read as `null` and tested
    with `has()` or the optional extension (`.?f`, `orValue`)."""

    inner: ExprType


ExprType = ScalarType | ListType | MapType | ObjectType | OptionalType

NULL = ScalarType("null")
BOOL = ScalarType("bool")
INT = ScalarType("int")
DOUBLE = ScalarType("double")
STRING = ScalarType("string")
BYTES = ScalarType("bytes")
TIMESTAMP = ScalarType("timestamp")
DURATION = ScalarType("duration")
DYN = ScalarType("dyn")


def object_type(name: str, fields: Mapping[str, ExprType]) -> ObjectType:
    """An `object{...}` type, its fields in one canonical order."""
    return ObjectType(name, tuple(sorted(fields.items())))


def describe(expr_type: ExprType) -> str:
    """The canonical text of a type: what `env_hash` hashes and what a message
    names. Objects carry their name and every field, so two objects of one
    name and different fields describe differently."""
    match expr_type:
        case ScalarType(kind):
            return kind
        case ListType(element):
            return f"list[{describe(element)}]"
        case MapType(value):
            return f"map[string, {describe(value)}]"
        case OptionalType(inner):
            return f"optional[{describe(inner)}]"
        case ObjectType(name, fields):
            body = ", ".join(f"{key}: {describe(value)}" for key, value in fields)
            return f"object {name}{{{body}}}"


# ---------------------------------------------------------------------------
# Environment, results, issues and errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpressionEnv:
    """The typed variables an expression may name, for one tenant.

    `tenant_id` is `None` at the platform layer. It is not part of `env_hash`
    (the shape of the variables), but every cache keyed by an environment
    carries it beside the hash (R3.7; `CLAUDE.md`, Tenancy: cache keys include
    the tenant).
    """

    tenant_id: TenantId | None
    variables: Mapping[str, ExprType]
    library: str
    _hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        frozen = MappingProxyType(dict(sorted(self.variables.items())))
        object.__setattr__(self, "variables", frozen)
        text = "\n".join(f"{name}: {describe(t)}" for name, t in frozen.items())
        object.__setattr__(self, "_hash", hashlib.sha256(text.encode("utf-8")).hexdigest())

    def env_hash(self) -> str:
        """sha256 of the variables and their types, sorted by name; never the
        tenant."""
        return self._hash

    def __reduce__(self) -> tuple[type[ExpressionEnv], tuple[object, ...]]:
        # `MappingProxyType` does not pickle; an environment crosses a process
        # boundary to the evaluator as its plain parts.
        return (ExpressionEnv, (self.tenant_id, dict(self.variables), self.library))


@dataclass(frozen=True, slots=True)
class CheckedExpression:
    """A source that type-checked against `env`, with its result type."""

    source: str
    env: ExpressionEnv
    result_type: ExprType


IssueKind = Literal[
    "syntax",
    "undeclared_reference",
    "undefined_field",
    "no_matching_overload",
    "too_deep",
    "source_too_large",
    "other",
]


@dataclass(frozen=True, slots=True)
class ExpressionIssue:
    """One reason a source does not check. `name` is the identifier
    (`undeclared_reference`) or the field (`undefined_field`), else `None`;
    `message` speaks only of the source, never of a value."""

    kind: IssueKind
    line: int | None
    column: int | None
    name: str | None
    message: str


ErrorCode = Literal["expression_error", "expression_budget_exceeded"]
ErrorStatus = Literal[
    "INVALID_ARGUMENT",
    "NOT_FOUND",
    "OUT_OF_RANGE",
    "INTERNAL",
    "UNKNOWN",
    "DEADLINE_EXCEEDED",
    "RESOURCE_EXHAUSTED",
]
ERROR_STATUSES: frozenset[str] = frozenset(get_args(ErrorStatus))


@dataclass(frozen=True, slots=True)
class ExpressionError:
    """An evaluation that produced no value. It never carries the binding's
    text, which can hold a value (`Key not found in map : "nope"`), nor a node
    or a path: the caller knows its node and attaches it."""

    code: ErrorCode
    status: ErrorStatus


# A JSON value: what `evaluate` returns. Timestamps are RFC 3339 strings with
# an offset, durations `"3600s"`, bytes base64, messages objects without their
# absent fields.
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


class ExpressionEngine(Protocol):
    """The one door to tenant expressions (ADR-0114 decision 2)."""

    def check(self, source: str, env: ExpressionEnv) -> CheckedExpression | list[ExpressionIssue]:
        """Type-check `source` against `env`, synchronously."""
        ...

    async def evaluate(
        self, checked: CheckedExpression, activation: Mapping[str, object]
    ) -> JsonValue | ExpressionError:
        """Evaluate `checked` over `activation`. A caller that needs a `bool`
        and gets `None` treats it as `expression_error`, never as `false`."""
        ...


__all__ = [
    "BOOL",
    "BYTES",
    "DOUBLE",
    "DURATION",
    "DW_CEL_LIBRARY",
    "DYN",
    "ERROR_STATUSES",
    "INT",
    "NULL",
    "STRING",
    "TIMESTAMP",
    "CheckedExpression",
    "ErrorCode",
    "ErrorStatus",
    "ExprType",
    "ExpressionEngine",
    "ExpressionEnv",
    "ExpressionError",
    "ExpressionIssue",
    "IssueKind",
    "JsonValue",
    "ListType",
    "MapType",
    "ObjectType",
    "OptionalType",
    "ScalarKind",
    "ScalarType",
    "describe",
    "object_type",
]
