"""A workflow version's data boundary, derived from its document
(workflow-engine R1.7, R3.13, R3.15; record-access R6.7; ADR-0103 decision 5).

Pure, over the document's `WorkflowIR`, so a step at any depth counts: a lane,
an error lane. Each step whose type's door is `records` or `assign` declares
what it does to records (`NodeTypeSpec.record_uses`), never read from its
type's name: each object a step names is one row, with the union of the flags
of every statement its door runs under the record policies (`_FLAGS`: a write
reads the record back, so it needs `can_read` too); each field a step's config
names is one row, `edit` when a step writes it, `read` otherwise. A field no
step names is not granted, so its value stays masked (closed when missing).

The `workflow` kind's publish hook and `RunRequestService`'s provisional
boundary both call `derive_workflow_boundary`; nothing else derives one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.ir import lower
from dw_agent_runtime.wflite.registry import NodeTypeSpec, RecordCommand
from dw_studio.core.application.boundaries import (
    DerivedBoundary,
    FieldAccess,
    FieldBoundary,
    ObjectBoundary,
)

# The record-policy flags each step command's statements need.
_FLAGS: Final[Mapping[RecordCommand, frozenset[str]]] = {
    "read": frozenset({"read"}),
    "create": frozenset({"create", "read"}),
    "update": frozenset({"update", "read"}),
    "delete": frozenset({"delete", "read"}),
    "assign": frozenset({"assign", "read"}),
}
_RECORD_DOORS: Final = frozenset({"records", "assign"})


def derive_workflow_boundary(
    document: Any, registry: Mapping[str, NodeTypeSpec]
) -> DerivedBoundary:
    """The boundary of `document`: empty when no step touches a record."""
    parsed = WorkflowDocument.model_validate(document)
    ir = lower(parsed, registry)
    flags: dict[str, set[str]] = {}
    fields: dict[tuple[str, str], FieldAccess] = {}
    for placed in ir.steps:
        spec = placed.spec
        if spec is None or spec.effect_door not in _RECORD_DOORS:
            continue
        for use in spec.record_uses(placed.step.config):
            flags.setdefault(use.object_api_name, set()).update(_FLAGS[use.command])
            for name in use.fields:
                fields.setdefault((use.object_api_name, name), "read")
            for name in use.writes:
                fields[(use.object_api_name, name)] = "edit"
    return DerivedBoundary(
        objects=tuple(
            ObjectBoundary(
                api_name=api_name,
                can_read="read" in granted,
                can_create="create" in granted,
                can_update="update" in granted,
                can_delete="delete" in granted,
                can_assign="assign" in granted,
            )
            for api_name, granted in sorted(flags.items())
        ),
        fields=tuple(
            FieldBoundary(object_api_name=obj, field_api_name=name, access=access)
            for (obj, name), access in sorted(fields.items())
        ),
    )


def pinnable_steps(document: Any, registry: Mapping[str, NodeTypeSpec]) -> frozenset[str]:
    """The steps of `document`, at any depth, that a pinned result may stand
    in for: those whose type has a door (R3.23). An approval or a switch has
    none, so its result is never pinned (workflow-nodes R9.9)."""
    ir = lower(WorkflowDocument.model_validate(document), registry)
    return frozenset(
        placed.step.id
        for placed in ir.steps
        if placed.spec is not None and placed.spec.effect_door is not None
    )
