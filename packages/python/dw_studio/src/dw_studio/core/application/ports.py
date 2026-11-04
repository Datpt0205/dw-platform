"""What `ArtifactService` asks of storage: one transaction under the caller's
tenant, and the reads and writes inside it.

The store decides nothing. Who may read or write is the service's question,
answered by `reach` (`platform.workspace_reach`, the one owner of depth,
ADR-0104 decision 5); what a row may become is the database's, whose refusals
the store turns into the errors named here by constraint.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from dw_kernel.pagination import CursorPosition
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.audit import AuditEvent
from dw_studio.core.domain.artifacts import Stage, TargetKind, Usage


@dataclass(frozen=True, slots=True)
class ArtifactRow:
    id: uuid.UUID
    kind: str
    api_name: str
    owning_workspace_id: uuid.UUID
    labels: tuple[str, ...]
    last_version_no: int
    row_version: int
    created_at: datetime
    updated_at: datetime
    # `studio.artifact_display_stage` (agent-lifecycle R1.5), read in the same
    # statement; None only where the statement could not read it (an insert).
    display_stage: str | None


@dataclass(frozen=True, slots=True)
class VersionRow:
    id: uuid.UUID
    artifact_id: uuid.UUID
    stage: Stage
    version_no: int | None
    document_schema: str
    document: Any
    content_hash: str | None
    definition_hash: str | None
    row_version: int
    based_on_version_id: uuid.UUID | None
    change_note: str | None
    # The lifecycle columns (agent-lifecycle ticket 03; ADR-0120 decision 1).
    contributor_ids: tuple[uuid.UUID, ...]
    gate_run_id: uuid.UUID | None
    publish_approval_id: uuid.UUID | None
    tighten_only: bool
    compared_live_hash: str | None
    submitted_by: uuid.UUID | None
    submitted_at: datetime | None
    published_by: uuid.UUID | None
    published_at: datetime | None
    retired_by: uuid.UUID | None
    retired_at: datetime | None
    retire_reason_code: str | None


@dataclass(frozen=True, slots=True)
class LiveTarget:
    """The `live` version an `artifact` reference pins (R3.3)."""

    artifact_id: uuid.UUID
    kind: str
    version_id: uuid.UUID
    version_no: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class DependencyRow:
    to_kind: TargetKind
    to_key: str
    usage: Usage
    path: str
    to_artifact_id: uuid.UUID | None = None
    to_version_id: uuid.UUID | None = None
    to_version: int | None = None
    to_hash: str | None = None


@dataclass(frozen=True, slots=True)
class Dependent:
    """An artifact one of whose in-use versions depends on the one asked about."""

    artifact_id: uuid.UUID
    kind: str
    api_name: str
    owning_workspace_id: uuid.UUID
    stage: Stage


@dataclass(frozen=True, slots=True)
class ListScope:
    """One kind the caller may list, and the workspaces where they may read it."""

    kind: str
    workspaces: frozenset[uuid.UUID]


class ArtifactTx(Protocol):
    """One transaction, bound to the caller's tenant (RLS)."""

    async def reach(self, permission_key: str) -> frozenset[uuid.UUID]:
        """The workspaces where the caller holds `permission_key` at a depth
        that reaches them: `platform.workspace_reach`, nothing recomputed."""
        ...

    async def artifact(self, artifact_id: uuid.UUID, *, lock: bool = False) -> ArtifactRow | None:
        """The artifact unless soft-deleted; `lock` takes `FOR UPDATE`."""
        ...

    async def versions(self, artifact_id: uuid.UUID) -> list[VersionRow]: ...

    async def insert_artifact(
        self,
        *,
        artifact_id: uuid.UUID,
        kind: str,
        api_name: str,
        owning_workspace_id: uuid.UUID,
        labels: Sequence[str],
    ) -> ArtifactRow:
        """Raises `ConflictError` `api_name_taken` by `uq_artifacts_api_name`."""
        ...

    async def insert_draft(
        self,
        *,
        version_id: uuid.UUID,
        artifact_id: uuid.UUID,
        document_schema: str,
        document: Any,
        based_on_version_id: uuid.UUID | None,
        contributor_ids: Sequence[uuid.UUID],
    ) -> VersionRow:
        """Raises `ConflictError` `draft_exists` by `uq_artifact_versions_unreleased`."""
        ...

    async def update_artifact(self, artifact_id: uuid.UUID, **values: Any) -> ArtifactRow:
        """Raises `ConflictError` `api_name_taken` or `api_name_immutable`."""
        ...

    async def update_version(self, version_id: uuid.UUID, **values: Any) -> VersionRow:
        """Raises `ConflictError` `stage_refused` by
        `ck_artifact_versions_stage_transition` (the stage machine's trigger)
        and `live_exists` by `uq_artifact_versions_live`."""
        ...

    async def soft_delete(self, artifact_id: uuid.UUID) -> None:
        """Raises `ConflictError` `artifact_in_use` by `ck_artifacts_not_in_use`."""
        ...

    async def live_target(self, artifact_id: uuid.UUID) -> LiveTarget | None:
        """The target's `live` version, its artifact row read `FOR SHARE`, so a
        concurrent soft delete waits and then meets the new dependency (R3.3)."""
        ...

    async def connection_ids(self, candidates: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
        """Which of `candidates` are ids of the tenant's connections, under RLS
        (tenant-config R7.1)."""
        ...

    async def version_documents(self, version_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Any]:
        """The document of each version, by id, under RLS."""
        ...

    async def put_manifest(self, definition_hash: str, body: dict[str, Any]) -> None: ...

    async def replace_dependencies(
        self, *, artifact_id: uuid.UUID, version_id: uuid.UUID, rows: Sequence[DependencyRow]
    ) -> None: ...

    async def dependents(self, artifact_id: uuid.UUID) -> list[Dependent]: ...

    async def list_page(
        self,
        scopes: Sequence[ListScope],
        *,
        label: str | None,
        after: CursorPosition | None,
        fetch_limit: int,
    ) -> list[ArtifactRow]: ...

    async def audit(self, event: AuditEvent) -> None: ...

    async def claim(self, claim: EffectClaim) -> None:
        """An idempotent request's effect key, first in the transaction."""
        ...


class ArtifactStore(Protocol):
    def transaction(self, context: AccessContext) -> AbstractAsyncContextManager[ArtifactTx]:
        """Commits on a clean exit, rolls back on an exception."""
        ...


@dataclass(frozen=True, slots=True)
class RootVersion:
    """The version a run starts from, with its artifact's kind and owning
    workspace (the run's workspace, workflow-engine R3.18)."""

    kind: str
    version: VersionRow
    owning_workspace_id: uuid.UUID


# ---- bindings (tenant-config ticket 05) ----------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectionFacts:
    """What a binding's check reads of one of the tenant's connections."""

    id: uuid.UUID
    connector_key: str
    connector_major: int
    scopes: tuple[str, ...]
    owning_workspace_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class BindingSetRow:
    """One `binding_set` row of `platform.config_versions`."""

    id: uuid.UUID
    status: str
    version_no: int
    document: Any
    workspace_id: uuid.UUID
    proposed_by: uuid.UUID
    decided_at: datetime | None


class BindingTx(ArtifactTx, Protocol):
    """What the bindings read beyond the envelope, in one transaction under the
    caller's tenant (RLS)."""

    async def root_version(self, version_id: uuid.UUID) -> RootVersion | None:
        """The version and its artifact's kind, the artifact row read `FOR
        SHARE` first and the version read after it, so a `save_draft` (which
        takes that row `FOR UPDATE`) waits for this transaction and the content
        read is the content received. None for another tenant's, a missing
        version, or a soft-deleted artifact."""
        ...

    async def pinned_versions(self, version_id: uuid.UUID) -> list[uuid.UUID]:
        """The `to_version_id` of each `artifact` row of the version's
        where-used index: the one source of a sealed root's closure versions."""
        ...

    async def connections(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ConnectionFacts]:
        """The tenant's connections among `ids`, deleted ones excluded."""
        ...

    async def principal_status(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, bool]:
        """For each id that is a member or a service principal of the tenant,
        whether it is active; another company's is absent."""
        ...

    async def binding_set(self, artifact_id: uuid.UUID, status: str) -> BindingSetRow | None:
        """The artifact's one `approved` or one `proposed` Binding set."""
        ...

    async def binding_sets_using(self, connection_id: uuid.UUID) -> list[uuid.UUID]:
        """The artifacts, not soft-deleted, whose `approved` Binding set has
        `connection_id` as a value (tenant-config R3.7)."""
        ...


class BindingStore(Protocol):
    def transaction(self, context: AccessContext) -> AbstractAsyncContextManager[BindingTx]: ...

    def for_tenant(self, tenant_id: uuid.UUID) -> AbstractAsyncContextManager[BindingTx]:
        """A transaction bound to the tenant alone, for a question asked on
        behalf of a run or a recorded decision rather than a person."""
        ...


class ModelRoutePinPort(Protocol):
    """What a Studio run's manifest pins of the models it may use
    (model-connections R1.4; ADR-0118 decision 1, Amendments 2026-11-04).
    Satisfied at the composition root by `ModelResolver.pin`, which applies the
    same layer order and plan filter as every call of the run."""

    async def pin(
        self, tenant_id: uuid.UUID, plan_id: str | None, profile_ids: frozenset[str]
    ) -> dict[str, Any]:
        """`{"model_routes": ..., "default_model_profile": ...}` for `engine`:
        each of `profile_ids` and the deployment's default, by value. A profile
        of `profile_ids` with no answer raises `model_profile_unavailable`; a
        default the plan does not list is left out, as null."""
        ...


class RunManifestTx(BindingTx, Protocol):
    """What `RunManifestBuilder` asks of the caller's transaction beyond the
    envelope's own reads (tenant-config ticket 04): the same one, so the run
    row the door writes after it commits or rolls back with the manifest."""

    async def definition_manifest(self, definition_hash: str) -> dict[str, Any] | None:
        """The body of `studio.definition_manifests` under this hash."""
        ...

    async def put_run_manifest(self, manifest_hash: str, body: dict[str, Any]) -> None:
        """`INSERT ... ON CONFLICT DO NOTHING`; a body past the table's 1 MiB
        CHECK is `PayloadTooLargeError`, by the constraint's name."""
        ...

    async def put_run_manifest_keys(
        self,
        manifest_hash: str,
        version_ids: Sequence[uuid.UUID],
        config_version_id: uuid.UUID | None = None,
    ) -> None:
        """One key row per version, and one for the Binding set the manifest
        pins (tenant-config R2.18, R7.4), `ON CONFLICT DO NOTHING`."""
        ...
