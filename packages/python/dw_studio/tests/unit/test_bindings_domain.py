"""The shared `bindings[]` shape, the manifest's pins, the kind register and
the config registry, without a database (tenant-config ticket 05)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from dw_kernel.errors import DomainError
from dw_platform.application.config_versions import ConfigKindRegistry
from dw_platform.application.connections import Usability, UsableContext
from dw_studio.core.application.bindings import (
    BindingTypes,
    bound_value,
    declaration_problems,
    platform_binding_types,
    variable_problems,
)
from dw_studio.core.domain.bindings import (
    BindingKind,
    binding_references,
    binding_set_values,
    bindings_hash,
    connection_strings,
    declaration_paths,
    document_problems,
    merge,
    parse_declarations,
    unset_required,
)
from dw_studio.core.domain.run_manifest import BindingsSection, BoundValue

pytestmark = pytest.mark.unit


def _codes(document: Any) -> list[tuple[str, str]]:
    return [(p.pointer, p.code) for p in parse_declarations(document).problems]


def test_a_document_without_bindings_declares_nothing() -> None:
    assert parse_declarations({"title": "x"}).items == ()
    assert parse_declarations("not a document").items == ()
    assert _codes({"bindings": {}}) == [("/bindings", "binding_invalid")]


def test_each_kind_keeps_its_own_fields_and_required_is_stated() -> None:
    document = {
        "bindings": [
            {"name": "Bad", "kind": "connection", "required": True},
            {"name": "x", "kind": "secret", "required": True},
            {"name": "v", "kind": "variable", "schema": {"type": "string", "pattern": "a"}},
            {"name": "p", "kind": "principal", "required": False, "connector_key": "smtp"},
            {"name": "p", "kind": "principal", "required": False},
            "nope",
        ]
    }
    assert _codes(document) == [
        ("/bindings/0/name", "binding_name_invalid"),
        ("/bindings/0/connector_key", "binding_invalid"),
        ("/bindings/0/connector_major", "binding_invalid"),
        ("/bindings/1/kind", "binding_kind_unknown"),
        ("/bindings/2/required", "binding_required_missing"),
        ("/bindings/2/schema/pattern", "binding_schema_invalid"),
        ("/bindings/3/connector_key", "binding_field_unknown"),
        ("/bindings/4/name", "binding_name_repeated"),
        ("/bindings/5", "binding_invalid"),
    ]


def test_a_connection_with_scopes_and_a_default_that_is_no_json() -> None:
    document = {
        "bindings": [
            {
                "name": "zalo_oa",
                "kind": "connection",
                "required": True,
                "connector_key": "zalo",
                "connector_major": 1,
                "required_scopes": ["oa"],
            },
            {
                "name": "n",
                "kind": "variable",
                "required": True,
                "schema": {"type": "integer"},
                "default": "{",
            },
        ]
    }
    assert _codes(document) == [
        ("/bindings/0/required_scopes", "binding_scopes_unsupported"),
        ("/bindings/1/default", "binding_default_invalid"),
    ]


def test_a_variable_default_is_checked_against_its_schema() -> None:
    document = {
        "bindings": [
            {
                "name": "score",
                "kind": "variable",
                "required": True,
                "schema": {"type": "integer", "maximum": 10},
                "default": "50",
            }
        ]
    }
    decls = parse_declarations(document).items
    found = declaration_problems(decls, declaration_paths(document))
    assert [(p.pointer, p.code) for p in found] == [
        ("/bindings/0/default", "binding_value_invalid")
    ]
    assert variable_problems(decls[0], 5, "/v") == []
    # A required variable with a default counts as set (gate 4/11/2026 (k)).
    assert unset_required(decls, {}) == []


def test_references_hash_and_merge() -> None:
    document = {
        "bindings": [
            {"name": "b", "kind": "principal", "required": True},
            {"name": "a", "kind": "principal", "required": False, "description": "x"},
        ]
    }
    refs = binding_references(document)
    assert [(r.to_key, r.path) for r in refs] == [("b", "/bindings/0"), ("a", "/bindings/1")]
    decls = parse_declarations(document).items
    assert bindings_hash(decls) == bindings_hash(reversed(decls))
    renamed = parse_declarations(
        {"bindings": [{"name": "a", "kind": "principal", "required": False}]}
    ).items
    # The description is not what a value is checked against.
    assert bindings_hash(renamed) == bindings_hash(decls[1:])
    other = parse_declarations(
        {
            "bindings": [
                {"name": "a", "kind": "variable", "required": True, "schema": {"type": "string"}}
            ]
        }
    ).items
    assert merge([decls, other]).conflicts == ("a",)
    assert set(merge([decls]).items) == {"a", "b"}


def test_strings_that_read_as_ids_are_found_with_their_pointer() -> None:
    one = uuid.uuid4()
    found = connection_strings({"a/b": [str(one), "x"], "n": 1})
    assert found == [("/a~1b/0", one)]


def test_a_binding_sets_document_is_one_values_object() -> None:
    assert document_problems({"values": {"a": 1}}) == []
    assert [p.code for p in document_problems({"values": 1})] == ["binding_set_invalid"]
    assert [p.code for p in document_problems({"values": {}, "x": 1})] == ["binding_set_invalid"]
    assert [p.code for p in document_problems({"values": {"a": 1.5}})] == ["binding_set_invalid"]
    big = {"values": {"a": "x" * 300_000}}
    assert [p.code for p in document_problems(big)] == ["binding_set_too_large"]
    assert binding_set_values(None) == {}


def test_a_pin_carries_its_kinds_one_field_and_never_a_secret() -> None:
    decls = {
        d.name: d
        for d in parse_declarations(
            {
                "bindings": [
                    {
                        "name": "c",
                        "kind": "connection",
                        "required": True,
                        "connector_key": "smtp",
                        "connector_major": 1,
                    },
                    {
                        "name": "v",
                        "kind": "variable",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                ]
            }
        ).items
    }
    connection = uuid.uuid4()
    pins = {"c": bound_value(decls["c"], str(connection)), "v": bound_value(decls["v"], 3)}
    section = BindingsSection.model_validate({"config_version_id": None, "values": pins})
    assert section.values["c"].connection_id == connection
    with pytest.raises(ValidationError):
        BoundValue.model_validate({"kind": "connection", "content_hash": pins["v"]["content_hash"]})
    with pytest.raises(ValidationError):
        BindingsSection.model_validate(
            {"config_version_id": None, "values": pins, "secret_version": 1}
        )


class _Never:
    async def connection_usable(
        self, connection: uuid.UUID, context: UsableContext, purpose: str
    ) -> Usability:
        raise NotImplementedError("not exercised")


def test_every_binding_kind_has_a_proposal_check_or_startup_fails() -> None:
    types = platform_binding_types(_Never())
    assert all(types.check(kind) is not None for kind in BindingKind)
    with pytest.raises(ValueError, match="principal"):
        BindingTypes({BindingKind.CONNECTION: types.check(BindingKind.CONNECTION)})
    with pytest.raises(ValueError, match="variable"):
        BindingTypes(
            {
                **dict.fromkeys(BindingKind, types.check(BindingKind.PRINCIPAL)),
                BindingKind.VARIABLE: None,
            }
        )


class _Kind:
    kind = "binding_set"


def test_the_config_registry_takes_each_kind_once_and_refuses_an_unknown_one() -> None:
    registry = ConfigKindRegistry([_Kind()])  # type: ignore[list-item]
    assert registry.get("binding_set") is not None
    with pytest.raises(DomainError) as caught:
        registry.require("prompt")
    assert caught.value.details["reason_code"] == "config_kind_unknown"
    with pytest.raises(ValueError):
        ConfigKindRegistry([_Kind(), _Kind()])  # type: ignore[list-item]
