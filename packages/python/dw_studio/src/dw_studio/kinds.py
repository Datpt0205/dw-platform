"""The Studio kinds of the running app (tenant-config R2.15; custom-objects
ticket 02 step 4).

A module of `dw_studio`, not a sub-package: the registry the app runs with
needs each capability's entry, and "Studio core imports no capability" keeps
that list out of `dw_studio.core`. It names no adapter either: what a kind's
hook needs from storage arrives as a factory the composition root builds from
the core's SQL adapter and the capability's, over one session (`CLAUDE.md`:
only a composition root imports a concrete adapter).

`build_studio(..., kinds=None)` and every other composition root that runs a
publish hook register exactly `platform_kinds(...)`, and a test-only kind
reaches an app only through `kinds=` (`studio_kinds=` of `create_app`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from dw_agent_runtime.wflite.document import SCHEMA_ID as WORKFLOW_DOCUMENT_SCHEMA
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.validate import ToolSpecLookup
from dw_kernel.ports import IdGenerator, UtcClock
from dw_studio.core.application.boundaries import (
    ActorBoundaryPort,
    BoundaryDeriver,
    DerivedBoundary,
)
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.lifecycle.application.service import VERSIONS_SUBMIT_SCOPE
from dw_studio.records.application.metadata import MetadataService
from dw_studio.records.application.ports import ObjectDefinitionStore
from dw_studio.records.domain.document import OBJECT_DOCUMENT_SCHEMA, OBJECT_KIND
from dw_studio.records.domain.rules import extract_object, validate_object
from dw_studio.workflows.application.boundary import derive_workflow_boundary, pinnable_steps
from dw_studio.workflows.application.dependencies import WorkflowDependencies
from dw_studio.workflows.application.ports import TriggerActivationPort
from dw_studio.workflows.application.publish import workflow_publish_hook
from dw_studio.workflows.application.rules import WorkflowValidator

# The read, write and submit key of the `object` kind, tenant depth only
# (custom-objects R1.3; tenant-config R2.11, R2.12, R2.15). Which roles hold
# it is tenant-rbac's.
OBJECTS_MANAGE_SCOPE = "studio.objects.manage"

# The `workflow` kind (workflow-engine R1.5; tenant-config R2.15): read and
# write keys at workspace depth, the submit key the agent kind shares, and the
# key a test run asks (H-19), which the run door's table names
# (`dw_api.bootstrap.studio._RUN_KEYS`).
WORKFLOW_KIND: Final = "workflow"
WORKFLOWS_READ_SCOPE = "studio.workflows.read"
WORKFLOWS_EDIT_SCOPE = "studio.workflows.edit"
WORKFLOWS_TEST_SCOPE = "studio.workflows.test"


def object_kind(
    object_store: Callable[[ArtifactTx], ObjectDefinitionStore],
    *,
    clock: UtcClock,
    ids: IdGenerator,
) -> ArtifactKindEntry:
    return ArtifactKindEntry(
        kind=OBJECT_KIND,
        document_schema=OBJECT_DOCUMENT_SCHEMA,
        read_key=OBJECTS_MANAGE_SCOPE,
        write_key=OBJECTS_MANAGE_SCOPE,
        submit_key=OBJECTS_MANAGE_SCOPE,
        publish_hook=MetadataService(object_store, clock, ids).apply,
        validate=validate_object,
        extract=extract_object,
    )


def workflow_kind(
    *,
    nodes: Mapping[str, NodeTypeSpec],
    tools: ToolSpecLookup,
    triggers: TriggerActivationPort,
    boundaries: ActorBoundaryPort,
) -> ArtifactKindEntry:
    """`nodes` is the step-type registry the composition root builds, `tools`
    the platform layer of the tool register (workflow-engine R1.4), and
    `boundaries` where a version's data boundary is recorded when it goes
    live (R1.7)."""
    return ArtifactKindEntry(
        kind=WORKFLOW_KIND,
        document_schema=WORKFLOW_DOCUMENT_SCHEMA,
        read_key=WORKFLOWS_READ_SCOPE,
        write_key=WORKFLOWS_EDIT_SCOPE,
        submit_key=VERSIONS_SUBMIT_SCOPE,
        publish_hook=workflow_publish_hook(triggers, boundaries, nodes),
        validate=WorkflowValidator(nodes, tools),
        extract=WorkflowDependencies(nodes),
    )


def platform_kinds(
    object_store: Callable[[ArtifactTx], ObjectDefinitionStore],
    *,
    clock: UtcClock,
    ids: IdGenerator,
    nodes: Mapping[str, NodeTypeSpec],
    tools: ToolSpecLookup,
    triggers: TriggerActivationPort,
    boundaries: ActorBoundaryPort,
) -> tuple[ArtifactKindEntry, ...]:
    """Every kind of `studio.artifact_kinds`, one entry each; the
    composition-root test holds the two equal."""
    return (
        object_kind(object_store, clock=clock, ids=ids),
        workflow_kind(nodes=nodes, tools=tools, triggers=triggers, boundaries=boundaries),
    )


def run_boundary_derivers(nodes: Mapping[str, NodeTypeSpec]) -> Mapping[str, BoundaryDeriver]:
    """Each kind's data-boundary derivation, for `RunRequestService`'s
    provisional boundaries (workflow-engine R3.13, R3.15); agent-builder adds
    the `agent` kind's here."""

    def workflow(document: Any) -> DerivedBoundary:
        return derive_workflow_boundary(document, nodes)

    return {WORKFLOW_KIND: BoundaryDeriver("workflow", workflow)}


def run_pinnable_steps(
    nodes: Mapping[str, NodeTypeSpec],
) -> Mapping[str, Callable[[Any], frozenset[str]]]:
    """Each kind whose runs take pinned results, and which of a document's
    steps may carry one (workflow-engine R3.23)."""

    def workflow(document: Any) -> frozenset[str]:
        return pinnable_steps(document, nodes)

    return {WORKFLOW_KIND: workflow}
