"""`AgentSettingsService`: who may invoke an agent, who answers for it, and
whether it is on, beside its versions (ADR-0117 decision 3; agent-builder
R1.1, R1.2, R1.4, R1.5, R1.7, R1.11, R6.1).

A setting is not a version: changing one seals nothing and every change is
audited as `studio.agent.settings_changed`, in the same transaction, with each
changed field's value before and after. Every write runs the audience
validator of org-and-principals (R8.1, R8.2) and checks the accountable owner
is an active person of the company; either refusing, or the validator
failing, writes nothing.

One question of the caller, at the depth `platform.workspace_reach` gives
`studio.agents.manage_settings` over the agent's owning workspace: holding it
is enough, without the author key; holding only the author key (who reads the
agent) is a 403; holding neither, an artifact of another kind or company, or a
soft-deleted one, is the 404 of an id that does not exist (R1.11; app-standards
R3.7, R3.13). An agent with no settings row is closed: nobody lists or opens
it (agent-builder/04).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

from dw_kernel.errors import NotFoundError, PermissionDeniedError, PreconditionFailedError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectClaim, PendingEffect
from dw_platform.domain.audience import AudienceDocument
from dw_platform.domain.audit import AuditEvent
from dw_studio.agents.domain.document import AGENT_KIND
from dw_studio.core.application.ports import ArtifactRow
from dw_studio.core.domain.artifacts import DocumentInvalidError, DocumentProblem

# The `agent` kind's read and write key (R1.8): a builder's, over the
# definition. `studio.agents.read`, the `/chat` user's, is agent-builder/04's.
AGENTS_AUTHOR_SCOPE = "studio.agents.author"
# The settings routes' key (V4.19), enough on its own to see the agent exists.
AGENTS_MANAGE_SETTINGS_SCOPE = "studio.agents.manage_settings"

SETTINGS_CHANGED: Final = "studio.agent.settings_changed"
RESOURCE: Final = "studio_agent_settings"
FIELDS: Final = ("audience", "owner_user_id", "enabled")
AUDIENCE_POINTER: Final = "/audience"


@dataclass(frozen=True, slots=True)
class AgentSettingsRow:
    artifact_id: uuid.UUID
    audience: Mapping[str, Any]
    # NULL only after the owner left the company (the key's SET NULL); no
    # write here ever stores it.
    owner_user_id: uuid.UUID | None
    enabled: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NewSettings:
    audience: Mapping[str, Any]
    owner_user_id: uuid.UUID
    enabled: bool


class AgentSettingsTx(Protocol):
    async def artifact(self, artifact_id: uuid.UUID, *, lock: bool = False) -> ArtifactRow | None:
        """The artifact, not soft-deleted, under the caller's tenant."""
        ...

    async def reach(self, permission_key: str) -> frozenset[uuid.UUID]: ...

    async def settings(self, artifact_id: uuid.UUID, *, lock: bool) -> AgentSettingsRow | None: ...

    async def insert_settings(self, artifact_id: uuid.UUID, row: NewSettings) -> AgentSettingsRow:
        """`ConflictError` (`settings_exist`) when the agent has a row, a
        concurrent insert included; the owner's key refused is the 422 of an
        owner who is not a member."""
        ...

    async def update_settings(
        self, artifact_id: uuid.UUID, changes: Mapping[str, Any], *, row_version: int
    ) -> AgentSettingsRow: ...

    async def active_person(self, user_id: uuid.UUID) -> bool:
        """A human of the company whose membership is `active`."""
        ...

    async def audit(self, event: AuditEvent) -> None: ...

    async def claim(self, claim: EffectClaim) -> None: ...


class AgentSettingsStore(Protocol):
    def transaction(
        self, context: AccessContext
    ) -> AbstractAsyncContextManager[AgentSettingsTx]: ...


class AudienceCheck(Protocol):
    """org-and-principals' validator (`AudienceValidator`): the one owner of
    what an audience may be and which workspaces are the caller's company's."""

    async def validate(
        self, context: AccessContext, document: object, *, at: str = ""
    ) -> AudienceDocument: ...


def owner_refused() -> DocumentInvalidError:
    """One answer for an owner who is no member, a service account, an
    inactive member and an id of nobody (R1.5)."""
    return DocumentInvalidError(
        "the owner is not valid",
        [
            DocumentProblem(
                "/owner_user_id",
                "owner_unknown",
                "the owner is not an active person of this company",
            )
        ],
    )


def _not_found() -> NotFoundError:
    return NotFoundError("agent not found")


def _patch_problems(patch: Mapping[str, Any]) -> list[DocumentProblem]:
    """A merge patch of the three settings, each stated with a value (R1.11):
    any other key, `artifact_id` included, and a `null` are refused."""
    problems = [
        DocumentProblem(f"/{name}", "not_patchable", "only audience, owner_user_id and enabled")
        for name in sorted(set(patch) - set(FIELDS))
    ]
    for name in FIELDS:
        if name in patch and patch[name] is None:
            problems.append(DocumentProblem(f"/{name}", "required", "a setting is never null"))
    if (
        "enabled" in patch
        and patch["enabled"] is not None
        and not isinstance(patch["enabled"], bool)
    ):
        problems.append(DocumentProblem("/enabled", "wrong_type", "enabled is true or false"))
    owner = patch.get("owner_user_id")
    if owner is not None and _as_uuid(owner) is None:
        problems.append(DocumentProblem("/owner_user_id", "wrong_type", "the owner is a user id"))
    return problems


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _as_json(value: Any) -> Any:
    return str(value) if isinstance(value, uuid.UUID) else value


class AgentSettingsService:
    def __init__(
        self,
        store: AgentSettingsStore,
        audience: AudienceCheck,
        clock: UtcClock,
        ids: IdGenerator,
    ) -> None:
        self.store = store
        self.audience = audience
        self.clock = clock
        self.ids = ids

    async def _agent(self, tx: AgentSettingsTx, artifact_id: uuid.UUID) -> ArtifactRow:
        """The agent if the caller manages its settings; 403 if they only read
        it; 404 otherwise (R1.11)."""
        row = await tx.artifact(artifact_id)
        if row is None or row.kind != AGENT_KIND:
            raise _not_found()
        if row.owning_workspace_id in await tx.reach(AGENTS_MANAGE_SETTINGS_SCOPE):
            return row
        if row.owning_workspace_id in await tx.reach(AGENTS_AUTHOR_SCOPE):
            raise PermissionDeniedError(
                "you may read this agent and not change its settings",
                details={"action": AGENTS_MANAGE_SETTINGS_SCOPE},
            )
        raise _not_found()

    async def _owner(self, tx: AgentSettingsTx, user_id: uuid.UUID) -> None:
        if not await tx.active_person(user_id):
            raise owner_refused()

    def _event(
        self, context: AccessContext, artifact_id: uuid.UUID, changes: Mapping[str, Any]
    ) -> AuditEvent:
        return AuditEvent(
            id=self.ids.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            actor_id=UserId(context.principal_id),
            action=SETTINGS_CHANGED,
            resource_type=RESOURCE,
            resource_id=str(artifact_id),
            occurred_at=self.clock.now(),
            details={"changes": dict(changes)},
        )

    async def check(self, context: AccessContext, artifact_id: uuid.UUID) -> None:
        """The create's own question, for an idempotent retry (app-standards R2.30)."""
        async with self.store.transaction(context) as tx:
            await self._agent(tx, artifact_id)

    async def get(self, context: AccessContext, artifact_id: uuid.UUID) -> AgentSettingsRow:
        async with self.store.transaction(context) as tx:
            await self._agent(tx, artifact_id)
            row = await tx.settings(artifact_id, lock=False)
        if row is None:
            raise NotFoundError(
                "this agent has no settings", details={"reason_code": "no_settings"}
            )
        return row

    async def create(
        self,
        context: AccessContext,
        artifact_id: uuid.UUID,
        *,
        audience: object,
        owner_user_id: uuid.UUID,
        enabled: bool,
        effect: PendingEffect | None = None,
    ) -> AgentSettingsRow:
        """R1.1: the one row, from the body and no default, with its audit."""
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(artifact_id))
            await self._agent(tx, artifact_id)
            checked = await self.audience.validate(context, audience, at=AUDIENCE_POINTER)
            await self._owner(tx, owner_user_id)
            values = NewSettings(checked.as_json(), owner_user_id, enabled)
            row = await tx.insert_settings(artifact_id, values)
            await tx.audit(
                self._event(
                    context,
                    artifact_id,
                    {
                        name: {"before": None, "after": _as_json(getattr(values, name))}
                        for name in FIELDS
                    },
                )
            )
        return row

    async def update(
        self,
        context: AccessContext,
        artifact_id: uuid.UUID,
        expected: ExpectedVersion,
        patch: Mapping[str, Any],
    ) -> AgentSettingsRow:
        """R1.2, R1.7, R1.11: a merge patch of the three settings under
        `If-Match`; `audience` replaces the whole value. A patch that changes
        nothing answers the row as it is, unversioned and unaudited
        (app-standards R3.16)."""
        async with self.store.transaction(context) as tx:
            await self._agent(tx, artifact_id)
            row = await tx.settings(artifact_id, lock=True)
            if row is None:
                raise NotFoundError(
                    "this agent has no settings", details={"reason_code": "no_settings"}
                )
            problems = _patch_problems(patch)
            if problems:
                raise DocumentInvalidError("the patch is not valid", problems)
            if not expected.matches(row.row_version):
                raise PreconditionFailedError(
                    "the settings you read are no longer current",
                    details={"reason_code": "stale_version"},
                )
            proposed: dict[str, Any] = {}
            if "audience" in patch:
                checked = await self.audience.validate(
                    context, patch["audience"], at=AUDIENCE_POINTER
                )
                proposed["audience"] = checked.as_json()
            if "owner_user_id" in patch:
                proposed["owner_user_id"] = _as_uuid(patch["owner_user_id"])
            if "enabled" in patch:
                proposed["enabled"] = patch["enabled"]
            changes = {
                name: value for name, value in proposed.items() if value != getattr(row, name)
            }
            if not changes:
                return row
            owner = changes.get("owner_user_id")
            if owner is not None:
                await self._owner(tx, owner)
            updated = await tx.update_settings(
                artifact_id, changes, row_version=row.row_version + 1
            )
            await tx.audit(
                self._event(
                    context,
                    artifact_id,
                    {
                        name: {"before": _as_json(getattr(row, name)), "after": _as_json(value)}
                        for name, value in changes.items()
                    },
                )
            )
        return updated
