"""R2.9 of workflow-engine (ticket 05): a field a step type marks
`x-dw-binding` names a binding the document's `bindings[]` declares, read by
tenant-config/05's one model of `bindings[]` and handed to the core validator
as `declared_bindings`; a name it does not declare, or a connection's id in
its place, is `wf.binding_undeclared` at the field."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest

from dw_agent_runtime.testing.studio_runs import NoExpressions
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.registry import registry_of
from dw_studio.testing.workflows import NoTools, studio_document, studio_step
from dw_studio.workflows.application.rules import WorkflowValidator

pytestmark = pytest.mark.unit

_EFFECT = fixture_node_registry()["fixture.effect@1"]
BOUND = dataclasses.replace(
    _EFFECT,
    type="fixture.bound@1",
    config_schema={
        "type": "object",
        "required": ["connection"],
        "properties": {"connection": {"type": "string", "x-dw-binding": True}},
        "additionalProperties": False,
    },
)
REGISTRY = registry_of((*fixture_node_registry().values(), BOUND))
CRM = {
    "name": "crm_main",
    "kind": "connection",
    "required": True,
    "connector_key": "crm",
    "connector_major": 1,
}


def document(connection: str, *bindings: dict[str, Any]) -> dict[str, Any]:
    body = studio_document(studio_step("gui", "fixture.bound@1", connection=connection))
    return {**body, "bindings": list(bindings)} if bindings else body


def problems(document: dict[str, Any]) -> list[tuple[str, str]]:
    found = WorkflowValidator(REGISTRY, NoTools(), NoExpressions())(document)
    return [(p.pointer, p.code) for p in found]


def test_a_declared_binding_passes() -> None:
    assert problems(document("crm_main", CRM)) == []


def test_an_undeclared_binding_is_refused_at_its_field() -> None:
    assert problems(document("crm_main")) == [
        ("/steps/0/config/connection", "wf.binding_undeclared")
    ]


def test_a_connections_id_in_place_of_a_name_is_refused() -> None:
    assert ("/steps/0/config/connection", "wf.binding_undeclared") in problems(
        document(str(uuid.uuid4()), CRM)
    )


def test_a_field_not_marked_is_not_a_binding() -> None:
    plain = dataclasses.replace(
        BOUND,
        config_schema={
            **BOUND.config_schema,
            "properties": {"connection": {"type": "string"}},
        },
    )
    found = WorkflowValidator(
        registry_of((*fixture_node_registry().values(), plain)), NoTools(), NoExpressions()
    )(document("anything"))
    assert found == []
