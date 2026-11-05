"""What `LifecycleService` asks of storage, of the run controls, and of each
kind's submit checks (agent-lifecycle R2.1, R2.4-R2.7, R7.9).

One transaction is the envelope's own (`ArtifactTx`, under the caller's
tenant), so a seal, its checks, the stage it moves to and the audit commit or
roll back together; this port adds only what the stage machine reads beyond
the envelope. Who may act is the service's question, what a row may become is
`studio.guard_version_stage()`'s.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from dw_platform.application.access_context import AccessContext
from dw_platform.application.control_switches import ControlSwitchTx
from dw_platform.domain.approval import ApprovalRequest
from dw_studio.core.application.bindings import BindingVerdict
from dw_studio.core.application.ports import ArtifactTx, Dependent, VersionRow
from dw_studio.core.domain.artifacts import ClosureItem


class LifecycleTx(Protocol):
    @property
    def envelope(self) -> ArtifactTx:
        """The envelope's transaction this one extends; `seal` runs in it."""
        ...

    async def has_quality_gate(self, kind: str) -> bool:
        """`studio.artifact_kinds.has_quality_gate`, the flag's one owner
        (tenant-config R2.14)."""
        ...

    async def publish_approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        """The request a version's `publish_approval_id` names, read `FOR
        UPDATE` under the tenant's RLS alone: the right to withdraw comes from
        the submit key at the artifact's workspace, not the request's (R2.4)."""
        ...

    async def save_approval(self, request: ApprovalRequest) -> None:
        """The request's new status, by its version (a concurrent decision wins
        and this one is a conflict)."""
        ...

    async def live_dependents(self, version_id: uuid.UUID) -> list[Dependent]:
        """Other artifacts whose `live` version pins this very version
        (`studio.dependencies.to_version_id`), read after the artifact's lock
        (R2.6)."""
        ...


class LifecycleStore(Protocol):
    def transaction(self, context: AccessContext) -> AbstractAsyncContextManager[LifecycleTx]:
        """Commits on a clean exit, rolls back on an exception."""
        ...


class KillTx(Protocol):
    """A kill's transaction (agent-lifecycle ticket 05): the envelope's, under
    the caller's tenant, so the component read for its owning workspace and
    the switch written for it commit or roll back together."""

    @property
    def envelope(self) -> ArtifactTx: ...

    @property
    def switches(self) -> ControlSwitchTx:
        """`platform.control_switches`' statements on the envelope's session."""
        ...


class KillStore(Protocol):
    def transaction(self, context: AccessContext) -> AbstractAsyncContextManager[KillTx]:
        """Commits on a clean exit, rolls back on an exception."""
        ...


class ControlStatePort(Protocol):
    """The one question a submit asks of the run controls (R7.9): agent-lifecycle
    ticket 01's `RunControlPort.admission_state`, which `SqlRunControl`
    answers, fail closed."""

    async def admission_state(
        self, tenant_id: uuid.UUID, artifacts: Sequence[uuid.UUID] = ()
    ) -> str | None:
        """The reason the company may not act now (`tenant_frozen`,
        `platform_frozen`, `control_state_unavailable`, ...), or None."""
        ...


@dataclass(frozen=True, slots=True)
class SubmitRefusal:
    """A per-kind check's no: 422 with its `reason_code` (R2.7)."""

    reason_code: str
    detail: str


class SubmitCheck(Protocol):
    """One check a kind's submit runs at the composition root's table (R2.7):
    the transaction, the version just sealed and its closure; it refuses or
    lets it through. Raising instead rolls the submit back (a 500), never a
    pass."""

    async def __call__(
        self, tx: ArtifactTx, version: VersionRow, closure: Sequence[ClosureItem]
    ) -> SubmitRefusal | None: ...


class PublishBindingsCheck(Protocol):
    """Whether a version's required bindings all have approved values
    (agent-lifecycle R2.11, R5.10; tenant-config R7.2), asked at the submit and
    by the publish handler; `BindingStatus.satisfied` answers it at the
    composition root (tenant-config ticket 05). The submit and the handler
    that ask it are agent-lifecycle ticket 04's. Its own transaction, under the
    tenant alone: the handler has no caller. Raising stops the publish."""

    async def satisfied(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> BindingVerdict: ...
