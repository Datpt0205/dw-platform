"""What the app-build tests read from `app.openapi()`: which routes write a
versioned resource (app-standards R3.12) and which take a cursor (R6.3).

Kept apart from the tests so a test can run the same reading over a small app
of its own and show that the reading names what it should.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

WRITE_METHODS = ("put", "patch", "delete")
Operation = tuple[str, str]


def _resolve(spec: Mapping[str, Any], schema: Mapping[str, Any]) -> Mapping[str, Any]:
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    return schema


def _is_integer(spec: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    schema = _resolve(spec, schema)
    if schema.get("type") == "integer":
        return True
    # `int | None` is `anyOf [integer, null]`: still a record version.
    return any(_is_integer(spec, option) for option in schema.get("anyOf", []))


def returns_version(spec: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    """A 2xx of ``operation`` whose body has a top-level integer `version`."""
    for status, response in operation.get("responses", {}).items():
        if not str(status).startswith("2"):
            continue
        for content in response.get("content", {}).values():
            schema = _resolve(spec, content.get("schema", {}))
            version = schema.get("properties", {}).get("version")
            if version is not None and _is_integer(spec, version):
                return True
    return False


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0]


def _is_child(path: str, of: str) -> bool:
    return _parent(path) == of and path != of


def versioned_resources(spec: Mapping[str, Any]) -> set[str]:
    """Paths whose `GET`, `PUT`, `PATCH` or `DELETE`, or a `POST` on a child,
    answers a 2xx with an integer `version` (the spec's "API" section)."""
    found: set[str] = set()
    for path, item in spec["paths"].items():
        for method in ("get", *WRITE_METHODS):
            if method in item and returns_version(spec, item[method]):
                found.add(path)
        if (
            "post" in item
            and returns_version(spec, item["post"])
            and _parent(path) in spec["paths"]
        ):
            found.add(_parent(path))
    return found


def write_routes(spec: Mapping[str, Any]) -> set[Operation]:
    """Every operation that writes a versioned resource, whatever it returns."""
    paths: Mapping[str, Any] = spec["paths"]
    writes: set[Operation] = set()
    for resource in versioned_resources(spec):
        writes |= {(m.upper(), resource) for m in WRITE_METHODS if m in paths.get(resource, {})}
        writes |= {
            ("POST", child)
            for child in paths
            if _is_child(child, resource) and "post" in paths[child]
        }
        last = resource.rsplit("/", 1)[-1]
        if not last.startswith("{"):
            continue
        # An item's list: writing the list writes its items (an upsert, a
        # batch), and so does a custom method of the list. `POST <list>` is
        # the create, which never overwrites; `POST <list>/query` reads.
        listing = _parent(resource)
        writes |= {(m.upper(), listing) for m in WRITE_METHODS if m in paths.get(listing, {})}
        for child in paths:
            if not _is_child(child, listing):
                continue
            for method in ("post", *WRITE_METHODS):
                if method in paths[child] and (method, child) != ("post", f"{listing}/query"):
                    writes.add((method.upper(), child))
    return writes


def requires_if_match(operation: Mapping[str, Any]) -> bool:
    return any(
        p.get("in") == "header" and p.get("name") == "If-Match"
        for p in operation.get("parameters", [])
    )


def unconditional_writes(spec: Mapping[str, Any]) -> set[Operation]:
    """Write routes of a versioned resource that do not turn `RequireIfMatch` on."""
    return {
        (method, path)
        for method, path in write_routes(spec)
        if not requires_if_match(spec["paths"][path][method.lower()])
    }


def _takes_cursor(spec: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    if any(
        p.get("in") == "query" and p.get("name") == "cursor"
        for p in operation.get("parameters", [])
    ):
        return True
    for content in operation.get("requestBody", {}).get("content", {}).values():
        schema = _resolve(spec, content.get("schema", {}))
        if "cursor" in schema.get("properties", {}):
            return True
    return False


def cursor_operations(spec: Mapping[str, Any]) -> set[Operation]:
    """Every operation that takes a `cursor`, in its query or its body (R6.3)."""
    return {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, Mapping) and _takes_cursor(spec, operation)
    }


def frozen_list_problems(
    frozen: Mapping[Operation, str], *, present: set[Operation], covered: set[Operation]
) -> Iterator[str]:
    """A frozen exemption list's own faults: a name without a reason, one that
    no longer names an operation, one the rule already covers."""
    for operation, reason in frozen.items():
        if not reason.strip():
            yield f"{operation}: no reason"
        if operation not in present:
            yield f"{operation}: no such operation"
        if operation in covered:
            yield f"{operation}: no longer exempt"
