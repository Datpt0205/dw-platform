"""The type algebra of `dw_kernel.expressions` in the binding's terms, and back.

- An `object{...}` becomes a protobuf message of a descriptor pool built per
  environment, in the package `dwenv_<first 12 of env_hash>`. A scalar field is
  a wrapper type, never a proto3 scalar: an absent proto3 scalar reads as its
  zero value (`''`, `0`), so `x.tier == ''` would hold for missing data
  (failure-modes #7), while an absent wrapper reads as `null` (measured).
- An activation dict becomes a message through `json_format.ParseDict`, which
  refuses a key the type does not declare.
- A result becomes a JSON value: timestamps RFC 3339 with an offset, durations
  `"3600s"`, bytes base64, messages objects without their absent fields.

Measured on cel-expr-python 0.1.3 and the reason for two refusals below: a
`str` or `bytes` the binding receives as a Python value is cut at its first
U+0000 (`'a\\x00b'` reads as `'a'`), while one inside a message is kept whole.
Values of objects travel as messages; a plain string or bytes value holding
U+0000 is refused instead of being read short.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from cel_expr_python import cel
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    duration_pb2,
    json_format,
    message_factory,
    struct_pb2,
    timestamp_pb2,
    wrappers_pb2,
)

from dw_kernel.expressions import (
    DYN,
    ExpressionEnv,
    ExprType,
    JsonValue,
    ListType,
    MapType,
    ObjectType,
    OptionalType,
    ScalarType,
    describe,
)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# FieldDescriptorProto type and label numbers.
_TYPE_DOUBLE, _TYPE_INT64, _TYPE_BOOL, _TYPE_STRING = 1, 3, 8, 9
_TYPE_MESSAGE, _TYPE_BYTES = 11, 12
_LABEL_OPTIONAL, _LABEL_REPEATED = 1, 3

_WRAPPER = {
    "bool": ".google.protobuf.BoolValue",
    "int": ".google.protobuf.Int64Value",
    "double": ".google.protobuf.DoubleValue",
    "string": ".google.protobuf.StringValue",
    "bytes": ".google.protobuf.BytesValue",
}
_WELL_KNOWN = {
    "timestamp": ".google.protobuf.Timestamp",
    "duration": ".google.protobuf.Duration",
    "dyn": ".google.protobuf.Value",
}
_PLAIN = {
    "bool": _TYPE_BOOL,
    "int": _TYPE_INT64,
    "double": _TYPE_DOUBLE,
    "string": _TYPE_STRING,
    "bytes": _TYPE_BYTES,
}
_WELL_KNOWN_FILES = (wrappers_pb2, timestamp_pb2, duration_pb2, struct_pb2)


class ActivationError(Exception):
    """An activation the environment cannot hold: the evaluation answers
    `expression_error` (`INVALID_ARGUMENT`). The text is for logs of this
    module's tests only and never reaches a caller."""


class UnrepresentableResultError(Exception):
    """A result with no JSON form: an optional, a type or a non-finite double."""


@dataclass(frozen=True, slots=True)
class BoundSchema:
    """One environment in the binding's terms."""

    pool: descriptor_pool.DescriptorPool
    message_names: Mapping[ObjectType, str]
    objects_by_message: Mapping[str, ObjectType]
    variables: Mapping[str, cel.Type]


def bind_schema(env: ExpressionEnv) -> BoundSchema:
    package = f"dwenv_{env.env_hash()[:12]}"
    names = _message_names(env, package)
    pool = descriptor_pool.DescriptorPool()
    for module in _WELL_KNOWN_FILES:
        proto = descriptor_pb2.FileDescriptorProto()
        module.DESCRIPTOR.CopyToProto(proto)
        pool.Add(proto)
    if names:
        file = descriptor_pb2.FileDescriptorProto(
            name=f"{package}.proto",
            package=package,
            syntax="proto3",
            dependency=[module.DESCRIPTOR.name for module in _WELL_KNOWN_FILES],
        )
        for obj, full_name in names.items():
            _add_message(file, obj, full_name, names)
        pool.Add(file)
    variables = {name: _binding_type(t, names) for name, t in env.variables.items()}
    for name in env.variables:
        _require_identifier(name)
    return BoundSchema(
        pool=pool,
        message_names=names,
        objects_by_message={full: obj for obj, full in names.items()},
        variables=variables,
    )


def _require_identifier(name: str) -> None:
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"{name!r} is not an identifier an expression can name")


def _message_names(env: ExpressionEnv, package: str) -> dict[ObjectType, str]:
    """One message per distinct object, named after it; a second object of the
    same name and another shape gets a numbered name."""
    names: dict[ObjectType, str] = {}
    taken: set[str] = set()

    def visit(t: ExprType) -> None:
        match t:
            case ListType(element):
                visit(element)
            case MapType(value) | OptionalType(value):
                visit(value)
            case ObjectType(name, fields) if t not in names:
                base = re.sub(r"[^A-Za-z0-9_]", "_", name) or "Object"
                if not base[0].isalpha():
                    base = "O" + base
                candidate, n = base, 1
                while candidate in taken:
                    n += 1
                    candidate = f"{base}_{n}"
                taken.add(candidate)
                names[t] = f"{package}.{candidate}"
                for _, field_type in fields:
                    visit(field_type)
            case _:
                return

    for t in env.variables.values():
        visit(t)
    return names


def _add_message(
    file: descriptor_pb2.FileDescriptorProto,
    obj: ObjectType,
    full_name: str,
    names: Mapping[ObjectType, str],
) -> None:
    message = file.message_type.add(name=full_name.rsplit(".", 1)[1])
    for number, (field_name, field_type) in enumerate(obj.fields, start=1):
        _require_identifier(field_name)
        field = message.field.add(name=field_name, number=number, json_name=field_name)
        inner = field_type.inner if isinstance(field_type, OptionalType) else field_type
        match inner:
            case ScalarType(kind) if kind in _WRAPPER:
                _message_field(field, _WRAPPER[kind], _LABEL_OPTIONAL)
            case ScalarType(kind) if kind in _WELL_KNOWN:
                _message_field(field, _WELL_KNOWN[kind], _LABEL_OPTIONAL)
            case ObjectType():
                _message_field(field, "." + names[inner], _LABEL_OPTIONAL)
            case ListType(element):
                _element(field, element, names, f"{obj.name}.{field_name}")
                field.label = _LABEL_REPEATED
            case MapType(value):
                entry = message.nested_type.add(name=_entry_name(field_name))
                entry.options.map_entry = True
                entry.field.add(
                    name="key", number=1, type=_TYPE_STRING, label=_LABEL_OPTIONAL, json_name="key"
                )
                value_field = entry.field.add(name="value", number=2, json_name="value")
                _element(value_field, value, names, f"{obj.name}.{field_name}")
                value_field.label = _LABEL_OPTIONAL
                _message_field(field, f".{full_name}.{entry.name}", _LABEL_REPEATED)
            case _:
                raise ValueError(
                    f"{obj.name}.{field_name}: {describe(field_type)} has no field form"
                )


def _entry_name(field_name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in field_name.split("_")) + "Entry"


def _message_field(field: Any, type_name: str, label: int) -> None:
    field.type = _TYPE_MESSAGE
    field.type_name = type_name
    field.label = label


def _element(field: Any, element: ExprType, names: Mapping[ObjectType, str], where: str) -> None:
    """A list element or a map value: proto has no absent element, so a plain
    scalar; nested lists and maps have no proto form and are refused."""
    match element:
        case ScalarType(kind) if kind in _PLAIN:
            field.type = _PLAIN[kind]
        case ScalarType(kind) if kind in _WELL_KNOWN:
            _message_field(field, _WELL_KNOWN[kind], _LABEL_OPTIONAL)
        case ObjectType():
            _message_field(field, "." + names[element], _LABEL_OPTIONAL)
        case _:
            raise ValueError(f"{where}: an element of {describe(element)} has no field form")


def _binding_type(t: ExprType, names: Mapping[ObjectType, str]) -> cel.Type:
    match t:
        case ScalarType(kind):
            return cast(cel.Type, getattr(cel.Type, kind.upper()))
        case ListType(element):
            return cel.Type.List(_binding_type(element, names))
        case MapType(value):
            return cel.Type.Map(cel.Type.STRING, _binding_type(value, names))
        case ObjectType():
            return cel.Type(names[t])
        case OptionalType(inner):
            # A variable the binding cannot declare optional (measured: no
            # `optional_type` signature it accepts). Absent, it is left out of
            # the activation, and reading it fails closed.
            return _binding_type(inner, names)


# ---------------------------------------------------------------------------
# Result types, back to the algebra
# ---------------------------------------------------------------------------

_SCALAR_NAMES: dict[str, ExprType] = {
    "BOOL": ScalarType("bool"),
    "INT": ScalarType("int"),
    "UINT": ScalarType("int"),
    "DOUBLE": ScalarType("double"),
    "STRING": ScalarType("string"),
    "BYTES": ScalarType("bytes"),
    "NULL": ScalarType("null"),
    "null_type": ScalarType("null"),
    "TIMESTAMP": ScalarType("timestamp"),
    "DURATION": ScalarType("duration"),
    "DYN": DYN,
    "google.protobuf.Value": DYN,
    "google.protobuf.Struct": MapType(DYN),
    "google.protobuf.ListValue": ListType(DYN),
}


def result_type(binding_type: cel.Type, schema: BoundSchema) -> ExprType | None:
    """The algebra's name for a result type, or `None` for one with no JSON
    form (an optional, a type, an error)."""
    return _parse_type(binding_type.name(), schema)


def _parse_type(text: str, schema: BoundSchema) -> ExprType | None:
    text = text.strip()
    if text in _SCALAR_NAMES:
        return _SCALAR_NAMES[text]
    if text in schema.objects_by_message:
        return schema.objects_by_message[text]
    head, _, rest = text.partition("<")
    if not rest.endswith(">"):
        return None
    args = _split_args(rest[:-1])
    if head == "LIST" and len(args) == 1:
        element = _parse_type(args[0], schema)
        return None if element is None else ListType(element)
    if head == "MAP" and len(args) == 2:
        value = _parse_type(args[1], schema)
        if value is None:
            return None
        # A map with keys other than strings becomes a JSON object all the
        # same, its keys written as text.
        return MapType(value) if args[0].strip() == "STRING" else MapType(DYN)
    return None


def _split_args(text: str) -> list[str]:
    args, depth, start = [], 0, 0
    for index, ch in enumerate(text):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(text[start:index])
            start = index + 1
    args.append(text[start:])
    return args


# ---------------------------------------------------------------------------
# Activation, into the binding's values
# ---------------------------------------------------------------------------


def binding_activation(
    schema: BoundSchema, env: ExpressionEnv, activation: Mapping[str, object]
) -> dict[str, object]:
    unknown = set(activation) - set(env.variables)
    if unknown:
        raise ActivationError(f"undeclared variables: {sorted(unknown)}")
    data: dict[str, object] = {}
    for name, t in env.variables.items():
        if name not in activation:
            continue
        value = activation[name]
        if isinstance(t, OptionalType):
            if value is None:
                continue
            t = t.inner
        data[name] = _to_binding(value, t, schema)
    return data


def _to_binding(value: object, t: ExprType, schema: BoundSchema) -> object:
    match t:
        case ObjectType():
            if not isinstance(value, Mapping):
                raise ActivationError("an object needs a mapping")
            cls = message_factory.GetMessageClass(
                schema.pool.FindMessageTypeByName(schema.message_names[t])
            )
            try:
                return json_format.ParseDict(_json_ready(value), cls())
            except (json_format.ParseError, TypeError, ValueError) as exc:
                raise ActivationError("object does not match its type") from exc
        case ListType(element):
            if not isinstance(value, list | tuple):
                raise ActivationError("a list needs a sequence")
            return [_to_binding(item, element, schema) for item in value]
        case MapType(inner):
            if not isinstance(value, Mapping):
                raise ActivationError("a map needs a mapping")
            return {
                _plain_text(key): _to_binding(item, inner, schema) for key, item in value.items()
            }
        case OptionalType(inner):
            if value is None:
                raise ActivationError("an absent value inside a list or a map")
            return _to_binding(value, inner, schema)
        case ScalarType(kind):
            return _scalar(value, kind)


def _scalar(value: object, kind: str) -> object:
    match kind:
        case "null" if value is None:
            return None
        case "bool" if isinstance(value, bool):
            return value
        case "int" if isinstance(value, int) and not isinstance(value, bool):
            return value
        case "double" if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        case "string" if isinstance(value, str):
            return _plain_text(value)
        case "bytes":
            return _plain_bytes(value)
        case "timestamp":
            return _timestamp(value)
        case "duration":
            return _duration(value)
        case "dyn":
            return _plain_dyn(value)
    raise ActivationError(f"a value is not of type {kind}")


def _plain_text(value: object) -> str:
    if not isinstance(value, str):
        raise ActivationError("a map key must be a string")
    if "\x00" in value:
        raise ActivationError("U+0000 in a plain string")
    return value


def _plain_bytes(value: object) -> bytes:
    if isinstance(value, str):
        try:
            value = base64.b64decode(value, validate=True)
        except binascii.Error as exc:
            raise ActivationError("bytes need base64") from exc
    if not isinstance(value, bytes | bytearray):
        raise ActivationError("a value is not bytes")
    if b"\x00" in value:
        raise ActivationError("U+0000 in plain bytes")
    return bytes(value)


def _plain_dyn(value: object) -> object:
    match value:
        case None | bool() | int() | float():
            return value
        case str():
            return _plain_text(value)
        case list() | tuple():
            return [_plain_dyn(item) for item in value]
        case Mapping():
            return {_plain_text(key): _plain_dyn(item) for key, item in value.items()}
    raise ActivationError("a dyn value is not JSON")


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        stamp = timestamp_pb2.Timestamp()
        try:
            stamp.FromJsonString(value)
        except ValueError as exc:
            raise ActivationError("not an RFC 3339 timestamp") from exc
        return cast(datetime, stamp.ToDatetime(tzinfo=UTC))
    raise ActivationError("a value is not a timestamp")


def _duration(value: object) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, str):
        span = duration_pb2.Duration()
        try:
            span.FromJsonString(value)
        except ValueError as exc:
            raise ActivationError("not a duration") from exc
        return cast(timedelta, span.ToTimedelta())
    raise ActivationError("a value is not a duration")


def _json_ready(value: object) -> object:
    """What `ParseDict` reads: timestamps, durations and bytes as their JSON
    text."""
    match value:
        case datetime():
            return value.isoformat()
        case timedelta():
            span = duration_pb2.Duration()
            span.FromTimedelta(value)
            return span.ToJsonString()
        case bytes() | bytearray():
            return base64.b64encode(value).decode("ascii")
        case list() | tuple():
            return [_json_ready(item) for item in value]
        case Mapping():
            return {key: _json_ready(item) for key, item in value.items()}
    return value


# ---------------------------------------------------------------------------
# Results, out to JSON
# ---------------------------------------------------------------------------


def to_json(value: object) -> JsonValue:
    match value:
        case None | bool() | int() | str():
            return value
        case float():
            if not math.isfinite(value):
                raise UnrepresentableResultError("a non-finite double")
            return value
        case bytes() | bytearray():
            return base64.b64encode(bytes(value)).decode("ascii")
        case datetime():
            return value.astimezone(UTC).isoformat()
        case timedelta():
            span = duration_pb2.Duration()
            span.FromTimedelta(value)
            return cast(str, span.ToJsonString())
        case list() | tuple():
            return [to_json(item) for item in value]
        case dict():
            return {_key(key): to_json(item) for key, item in value.items()}
    if hasattr(value, "DESCRIPTOR") and hasattr(value, "ListFields"):
        return _message_json(value)
    raise UnrepresentableResultError(type(value).__name__)


def _key(key: object) -> str:
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int | str):
        return str(key)
    raise UnrepresentableResultError("a map key that is not text")


def _message_json(message: Any) -> JsonValue:
    full_name = message.DESCRIPTOR.full_name
    if full_name in (
        "google.protobuf.Value",
        "google.protobuf.Struct",
        "google.protobuf.ListValue",
    ):
        return cast(JsonValue, json_format.MessageToDict(message))
    if full_name == "google.protobuf.Timestamp":
        return to_json(message.ToDatetime(tzinfo=UTC))
    if full_name == "google.protobuf.Duration":
        return cast(str, message.ToJsonString())
    if full_name.startswith("google.protobuf.") and full_name.endswith("Value"):
        return to_json(message.value)
    out: dict[str, JsonValue] = {}
    for field, value in message.ListFields():
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            out[field.name] = {str(key): to_json(item) for key, item in value.items()}
        elif field.is_repeated:
            out[field.name] = [to_json(item) for item in value]
        else:
            out[field.name] = to_json(value)
    return out


def json_size(value: JsonValue) -> int:
    """The UTF-8 size of the serialized result, which the 256 KiB cap reads."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return len(text.encode("utf-8"))
