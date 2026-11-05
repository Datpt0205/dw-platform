"""`SqlAgentSettingsStore`: `studio.agent_settings` on the envelope's own
session, as `dw_app` under the caller's tenant (RLS); see `AgentSettingsTx`.

It decides nothing. PostgreSQL refuses a second row for an agent (the primary
key), a row without `enabled` and an owner who is not a member of the company
(the composite key), and this module reads each refusal back by the
constraint it names, so two concurrent creates answer 201 and 409, never 500.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables as platform
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.audit import AuditEvent
from dw_studio.agents.adapters.tables import agent_settings
from dw_studio.agents.application.settings import AgentSettingsRow, NewSettings, owner_refused
from dw_studio.core.adapters.artifact_store import SqlArtifactStore, SqlArtifactTx
from dw_studio.core.application.ports import ArtifactRow

_ONE_PER_AGENT = "pk_agent_settings"
_OWNER_KEY = "fk_agent_settings_owner_user_id_tenant_members"

# A human whose company row is `active` in the caller's tenant, named in the
# statement and not left to RLS alone (a membership policy may show a person
# their own rows elsewhere): a service account is never an accountable owner.
_ACTIVE_PERSON = (
    sa.select(sa.literal(True))
    .select_from(
        platform.tenant_members.join(
            platform.users, platform.users.c.id == platform.tenant_members.c.user_id
        )
    )
    .where(
        platform.tenant_members.c.status == "active",
        platform.users.c.kind == "human",
    )
)


def _row(row: Any) -> AgentSettingsRow:
    return AgentSettingsRow(
        artifact_id=row.artifact_id,
        audience=row.audience,
        owner_user_id=row.owner_user_id,
        enabled=row.enabled,
        row_version=row.row_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass
class SqlAgentSettingsTx:
    envelope: SqlArtifactTx

    async def artifact(self, artifact_id: uuid.UUID, *, lock: bool = False) -> ArtifactRow | None:
        return await self.envelope.artifact(artifact_id, lock=lock)

    async def reach(self, permission_key: str) -> frozenset[uuid.UUID]:
        return await self.envelope.reach(permission_key)

    async def settings(self, artifact_id: uuid.UUID, *, lock: bool) -> AgentSettingsRow | None:
        statement = sa.select(agent_settings).where(agent_settings.c.artifact_id == artifact_id)
        if lock:
            statement = statement.with_for_update()
        row = (await self.envelope.session.execute(statement)).one_or_none()
        return None if row is None else _row(row)

    async def insert_settings(self, artifact_id: uuid.UUID, row: NewSettings) -> AgentSettingsRow:
        statement = (
            sa.insert(agent_settings)
            .values(
                tenant_id=self.envelope.tenant_id,
                artifact_id=artifact_id,
                audience=dict(row.audience),
                owner_user_id=row.owner_user_id,
                enabled=row.enabled,
                row_version=1,
            )
            .returning(agent_settings)
        )
        try:
            inserted = (await self.envelope.session.execute(statement)).one()
        except IntegrityError as exc:
            refused = refusal(exc)
            name = None if refused is None else refused[0]
            if name == _ONE_PER_AGENT:
                raise ConflictError(
                    "this agent already has settings", details={"reason_code": "settings_exist"}
                ) from None
            if name == _OWNER_KEY:
                raise owner_refused() from None
            raise
        return _row(inserted)

    async def update_settings(
        self, artifact_id: uuid.UUID, changes: Mapping[str, Any], *, row_version: int
    ) -> AgentSettingsRow:
        statement = (
            sa.update(agent_settings)
            .where(agent_settings.c.artifact_id == artifact_id)
            .values(**changes, row_version=row_version)
            .returning(agent_settings)
        )
        try:
            updated = (await self.envelope.session.execute(statement)).one()
        except IntegrityError as exc:
            refused = refusal(exc)
            if refused is not None and refused[0] == _OWNER_KEY:
                raise owner_refused() from None
            raise
        return _row(updated)

    async def active_person(self, user_id: uuid.UUID) -> bool:
        found = await self.envelope.session.scalar(
            _ACTIVE_PERSON.where(
                platform.tenant_members.c.tenant_id == self.envelope.tenant_id,
                platform.tenant_members.c.user_id == user_id,
            )
        )
        return bool(found)

    async def audit(self, event: AuditEvent) -> None:
        await self.envelope.audit(event)

    async def claim(self, claim: EffectClaim) -> None:
        await self.envelope.claim(claim)


@dataclass(frozen=True)
class SqlAgentSettingsStore:
    envelope: SqlArtifactStore

    @asynccontextmanager
    async def transaction(self, context: AccessContext) -> AsyncIterator[SqlAgentSettingsTx]:
        async with self.envelope.transaction(context) as tx:
            yield SqlAgentSettingsTx(tx)
