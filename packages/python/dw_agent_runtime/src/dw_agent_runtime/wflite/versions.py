"""A Digital Worker's pinned workflow, a pack's or its tenant's own version
(wf-ai R1.3, R6.5, R6.16).

A pin is `<semver>` for the document a pack ships, or `<semver>+t<n>` for a
version the tenant published for that one DW. A tenant version is read from
storage under the DW's own tenant and workspace and by the DW's own id, so
one DW never runs, shows or edits another's version and a tenant never sees
another's (R6.16); what is not found is not shipped. It is the pack's document
with other steps (R2.1), so it keeps the pack's work-kind schemas and path.

A tenant version runs at its `run_version` (`1.0.0+t1.<content sha256>`).
Graphs are registered per process at start, and a tenant version is published
while processes run, so `TenantWorkflowGraphs.ensure` registers the graph of
a run's version on first use: at its start, and wherever it resumes (the API
for a decision, the worker for a timer). It reads the version by its key,
label and content hash under the run's tenant and workspace; the same content
compiles to the same graph, so two DWs sharing one is no leak. One graph per
published version stays registered for the life of the process, bounded by
the versions published; a restart forgets them and the next run registers
its own again.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from dw_agent_runtime.registry import GraphRegistry, LoadedWorker, WorkerRegistry
from dw_agent_runtime.wflite.catalog import PackCatalog, PinnedWorkflow, workflow_sha256
from dw_agent_runtime.wflite.compile import (
    WORKER_PREFIX,
    WfPorts,
    compile_workflow,
    worker_definition_of,
)
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_kernel.errors import NotFoundError
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.digital_worker import DigitalWorker, is_tenant_pin, pack_version_of

# `1.0.0+t3.<sha256>`: what `PinnedWorkflow.run_version` makes of a tenant's.
_RUN_VERSION = re.compile(r"(\d+\.\d+\.\d+\+t[1-9][0-9]*)\.([0-9a-f]{64})")


@dataclass(frozen=True, slots=True)
class TenantVersion:
    dw_id: uuid.UUID
    key: str
    version: str
    content: Mapping[str, Any]
    content_sha256: str
    base_sha256: str
    author_ids: tuple[uuid.UUID, ...]
    approved_by: uuid.UUID
    approval_id: uuid.UUID
    created_at: datetime


class TenantVersionsPort(Protocol):
    async def of_dw(self, scope: WorkScope, dw_id: uuid.UUID, version: str) -> TenantVersion | None:
        """The version `version` of this DW, under `scope`; None for another
        DW's or another tenant's (R6.16)."""
        ...

    async def by_content(
        self, scope: WorkScope, *, key: str, version: str, content_sha256: str
    ) -> TenantVersion | None:
        """Any version of `key` labelled `version` with this content, under
        `scope`: what a run's graph is rebuilt from."""
        ...


class PinnedWorkflowsPort(Protocol):
    """What reads a DW's pin: its document, and the pack's of the same key."""

    async def pinned(self, worker: DigitalWorker) -> PinnedWorkflow | None: ...

    def pack(self, key: str, version: str) -> PinnedWorkflow | None: ...


def tenant_pinned(pack: PinnedWorkflow, version: TenantVersion) -> PinnedWorkflow:
    """A tenant version as a pinned workflow: its document and content hash,
    the pack's schemas and path."""
    return PinnedWorkflow(
        document=WorkflowDocument.model_validate(dict(version.content)),
        sha256=version.content_sha256,
        path=pack.path,
        work_schemas=pack.work_schemas,
        label=version.version,
    )


def base_sha256(pinned: PinnedWorkflow) -> str:
    """The hash a draft's base and its publication compare by (R6): the
    content's, for a pack's document and a tenant's version alike. A tenant
    version's is the one stored with it, never a hash of its document read
    back, which is not guaranteed to be the same bytes."""
    if pinned.label is not None:
        return pinned.sha256
    return workflow_sha256(pinned.document.model_dump(by_alias=True, exclude_none=True))


def not_shipped() -> NotFoundError:
    return NotFoundError(
        "the digital worker's pinned workflow is not shipped",
        details={"reason_code": "workflow_not_shipped"},
    )


@dataclass(frozen=True)
class PinnedWorkflows:
    """Implements ``PinnedWorkflowsPort``: the catalog for a pack's pin, the
    tenant's store, under the DW's own scope and id, for its own."""

    catalog: PackCatalog
    versions: TenantVersionsPort

    def pack(self, key: str, version: str) -> PinnedWorkflow | None:
        return self.catalog.workflow(key, pack_version_of(version))

    async def pinned(self, worker: DigitalWorker) -> PinnedWorkflow | None:
        config = worker.configuration
        if not is_tenant_pin(config.workflow_version):
            return self.catalog.workflow(config.workflow_key, config.workflow_version)
        pack = self.pack(config.workflow_key, config.workflow_version)
        if pack is None:
            return None
        found = await self.versions.of_dw(
            WorkScope(tenant_id=worker.tenant_id, workspace_id=worker.workspace_id),
            worker.id,
            config.workflow_version,
        )
        if found is None or found.key != config.workflow_key:
            return None
        return tenant_pinned(pack, found)


@dataclass(frozen=True)
class TenantWorkflowGraphs:
    """The graphs of tenant versions, registered in this process on first use
    (see the module docstring)."""

    catalog: PackCatalog
    versions: TenantVersionsPort
    ports: WfPorts
    graphs: GraphRegistry
    workers: WorkerRegistry

    def _hosted(self, worker_id: str, worker_version: str) -> bool:
        try:
            self.workers.resolve(worker_id, worker_version)
        except NotFoundError:
            return False
        return True

    async def ensure(
        self,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        worker_id: str,
        worker_version: str,
    ) -> None:
        """Register the graph of a tenant version's run when this process does
        not hold it yet. Anything else is left as it is: a pack's version is
        registered at start, and a version this tenant does not have stays
        unhosted, which the caller refuses as it refuses any."""
        if self._hosted(worker_id, worker_version):
            return
        matched = _RUN_VERSION.fullmatch(worker_version)
        if matched is None or not worker_id.startswith(WORKER_PREFIX):
            return
        label, sha = matched.groups()
        key = worker_id.removeprefix(WORKER_PREFIX)
        pack = self.catalog.workflow(key, pack_version_of(label))
        if pack is None:
            return
        found = await self.versions.by_content(
            WorkScope(tenant_id=tenant_id, workspace_id=workspace_id),
            key=key,
            version=label,
            content_sha256=sha,
        )
        # The row is append-only; its content still hashing to its name is
        # checked anyway, since the graph is shared by that name.
        if found is None or workflow_sha256(found.content) != sha:
            return
        self.host(tenant_pinned(pack, found))

    def host(self, pinned: PinnedWorkflow) -> None:
        definition = worker_definition_of(pinned)
        # Checked again after the read: two runs of one version may both have
        # waited on it.
        if self._hosted(definition.worker_id, definition.worker_version):
            return
        ports = self.ports
        self.graphs.register(
            definition.worker_id,
            definition.graph_version,
            lambda: compile_workflow(pinned, ports),
        )
        self.workers.register(
            LoadedWorker(
                definition=definition, checksum=pinned.sha256, source_path=str(pinned.path)
            )
        )


__all__ = [
    "PinnedWorkflows",
    "PinnedWorkflowsPort",
    "TenantVersion",
    "TenantVersionsPort",
    "TenantWorkflowGraphs",
    "base_sha256",
    "not_shipped",
    "tenant_pinned",
]
