"""`KillSwitchService`: an agent or a workflow killed by one person and
revived by two (agent-lifecycle R8.1, R8.6-R8.8; ADR-0120 decisions 5, 7;
D11).

- **Kill** (`POST /studio/{agents|workflows}/{id}/kill`): `studio.lifecycle.kill`
  reaching the component's `owning_workspace_id` (ADR-0120 decision 7, "in the
  artifact's workspace"). One transaction writes the `platform.control_switches`
  row (`action='kill'`, `origin='tenant'`), `control.kill.set` and the outbox
  event `control.switch.changed`, so the `control_switch` lane hears every kill
  that committed and no other. A kill already open is 409 `already_killed`
  with nothing written. Every door of the runtime refuses the component's
  `live` and `test` runs from then on (`RunControlPort`, `artifact_killed`);
  a `simulate` run still runs, so a fix can be evaluated.
- **Ask to revive** (`POST .../revive-requests`): the same key at the same
  depth opens a strict, run-less `studio.lifecycle.revive` approval stamped
  `studio.lifecycle.kill`, in the component's workspace, its payload only the
  open kill's `switch_id`. Nothing is lifted: the second person's decision is
  carried out on the worker by `SwitchLiftSettler` (`REVIVE_LIFT`). No kill
  open: 409 `not_killed`; a revive already waiting: 409 `lift_pending`, held
  by ticket 01's partial unique index.

Who may: `ArtifactService.open_for`, the envelope's own rule, as ticket 03's
routes ask it. Another company's component, an id that is not there, a stored
kind the route segment does not name, or one the caller cannot read at its
workspace is a 404 as if it did not exist; one they read without the key is a
403.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.control_switches import (
    KILL_SET,
    LIFECYCLE_KILL_SCOPE,
    LIFECYCLE_REVIVE,
    ReasonCode,
    already_killed,
    switch_changed,
)
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent
from dw_studio.core.application.ports import ArtifactRow
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.core.application.service import ArtifactService
from dw_studio.lifecycle.application.ports import KillStore, KillTx

__all__ = ["KILL_SEGMENTS", "KillSwitchService"]

# The route segment of each kind a switch can kill: the `scope_type` values of
# `ck_control_switches_scope_type` other than the company's.
KILL_SEGMENTS: Final[Mapping[str, Literal["agent", "workflow"]]] = MappingProxyType(
    {"agents": "agent", "workflows": "workflow"}
)
_KILLABLE: Final = frozenset(KILL_SEGMENTS.values())
_RESOURCE: Final = "control_switch"


def _kill_key(_entry: ArtifactKindEntry) -> str:
    return LIFECYCLE_KILL_SCOPE


def _scope_type(kind: str) -> Literal["agent", "workflow"]:
    for scope_type in _KILLABLE:
        if scope_type == kind:
            return scope_type
    # A segment the composition root never mounts: no route reaches it.
    raise NotFoundError("artifact not found")


class KillSwitchService:
    def __init__(
        self,
        store: KillStore,
        artifacts: ArtifactService,
        clock: UtcClock,
        ids: IdGenerator,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.clock = clock
        self.ids = ids

    async def _open(self, tx: KillTx, kind: str, artifact_id: uuid.UUID) -> ArtifactRow:
        _scope_type(kind)
        row, _ = await self.artifacts.open_for(
            tx.envelope, artifact_id, kind=kind, key=_kill_key, lock=False
        )
        return row

    async def check(self, context: AccessContext, kind: str, artifact_id: uuid.UUID) -> None:
        """The routes' own question for an idempotent retry, before any key row
        is read (app-standards R2.30)."""
        async with self.store.transaction(context) as tx:
            await self._open(tx, kind, artifact_id)

    async def kill(
        self,
        context: AccessContext,
        kind: str,
        artifact_id: uuid.UUID,
        *,
        reason_code: ReasonCode,
        reason: str,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """R8.1, R8.8: the switch, `control.kill.set` and `control.switch.changed`
        in one transaction; the switch's id."""
        switch_id = self.ids.new_uuid()
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.envelope.claim(effect.of(switch_id))
            row = await self._open(tx, kind, artifact_id)
            if await tx.switches.open_kill(artifact_id) is not None:
                raise already_killed()
            await tx.switches.insert_kill(
                switch_id=switch_id,
                scope_type=_scope_type(kind),
                target_id=artifact_id,
                owning_workspace_id=row.owning_workspace_id,
                reason_code=reason_code,
                reason=reason,
                set_by=context.principal_id,
            )
            now = self.clock.now()
            await tx.envelope.audit(
                AuditEvent(
                    id=self.ids.new_uuid(),
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(row.owning_workspace_id),
                    actor_id=UserId(context.principal_id),
                    action=KILL_SET,
                    resource_type=_RESOURCE,
                    resource_id=str(switch_id),
                    occurred_at=now,
                    # Ids and codes only (R8.8): the reason's text stays on the row.
                    details={
                        "reason_code": reason_code,
                        "artifact_id": str(artifact_id),
                        "kind": kind,
                    },
                )
            )
            await tx.switches.announce(
                switch_changed(
                    self.ids.new_uuid(),
                    tenant_id=context.tenant_id,
                    workspace_id=row.owning_workspace_id,
                    switch_id=switch_id,
                    actor_id=context.principal_id,
                    at=now,
                )
            )
        return switch_id

    async def request_revive(
        self,
        context: AccessContext,
        kind: str,
        artifact_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """R8.6: a strict run-less approval naming the open kill; the approval's
        id. It has no run, so `ApproveAndResumeService.decide` asks no switch
        before it is decided: it can be decided under this very kill, or a
        freeze."""
        approval_id = self.ids.new_uuid()
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.envelope.claim(effect.of(approval_id))
            row = await self._open(tx, kind, artifact_id)
            kill = await tx.switches.open_kill(artifact_id)
            if kill is None:
                raise ConflictError(
                    "the component is not killed", details={"reason_code": "not_killed"}
                )
            await tx.switches.open_lift_request(
                ApprovalRequest(
                    id=approval_id,
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(row.owning_workspace_id),
                    approval_type=LIFECYCLE_REVIVE,
                    requested_by=UserId(context.principal_id),
                    reason=LIFECYCLE_REVIVE,
                    payload={"switch_id": str(kill.id)},
                    required_scope=LIFECYCLE_KILL_SCOPE,
                )
            )
        return approval_id
