"""Contract test: only two routes take a data route class (compliance-pdpl R2.7, R2.8).

`platform.tenants` carries no trigger that refuses a loosening (OPS-b): the
tenant's class is written only by `PATCH /api/v1/admin/tenant` and a
workspace's only by `PATCH /api/v1/admin/workspaces/{workspace_id}`, where the
service refuses a loosening. A request body of any other route, the operator's
`PATCH /api/v1/platform/tenants/{tenant_id}` included, that grows a
`data_route_class` field would be a second door the rule does not guard
(failure-modes #5), so this fails on it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

pytestmark = pytest.mark.contract

FIELD = "data_route_class"
ALLOWED = {
    ("patch", "/api/v1/admin/tenant"),
    ("patch", "/api/v1/admin/workspaces/{workspace_id}"),
}


def _properties(schema: Any, components: dict[str, Any], seen: frozenset[str]) -> set[str]:
    """Every property name reachable from `schema`, through `$ref`s and
    composition, so a field nested or merged in is found too."""
    if not isinstance(schema, dict):
        return set()
    names: set[str] = set()
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name not in seen:
            names |= _properties(components.get(name, {}), components, seen | {name})
    for key, value in (schema.get("properties") or {}).items():
        names.add(key)
        names |= _properties(value, components, seen)
    for key in ("allOf", "anyOf", "oneOf"):
        for part in schema.get(key) or []:
            names |= _properties(part, components, seen)
    for key in ("items", "additionalProperties"):
        names |= _properties(schema.get(key), components, seen)
    return names


def _bodies_with_the_field(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    components = openapi.get("components", {}).get("schemas", {})
    found: set[tuple[str, str]] = set()
    for path, item in openapi["paths"].items():
        for method, operation in item.items():
            content = (operation.get("requestBody") or {}).get("content") or {}
            for media in content.values():
                if FIELD in _properties(media.get("schema"), components, frozenset()):
                    found.add((method, path))
    return found


def _openapi() -> dict[str, Any]:
    built: dict[str, Any] = importlib.import_module("generate_contracts").build_openapi()
    return built


def test_only_the_two_admin_routes_take_a_data_route_class() -> None:
    assert _bodies_with_the_field(_openapi()) == ALLOWED


def test_the_check_finds_the_field_where_it_is_added() -> None:
    """The mutation this test exists for: the operator's rename body grows the
    field. Applied to the live schema, it must be seen."""
    openapi = _openapi()
    rename = openapi["components"]["schemas"]["RenameTenantRequest"]
    rename.setdefault("properties", {})[FIELD] = {"type": "string"}

    assert ("patch", "/api/v1/platform/tenants/{tenant_id}") in _bodies_with_the_field(openapi)
