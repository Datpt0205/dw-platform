"""`/api/v1/studio/agents/{artifact_id}/settings`: who may invoke an agent,
who answers for it and whether it is on (agent-builder R1.1, R1.2, R1.5, R1.7,
R1.11, R6.1; ADR-0117 decision 3).

An agent's definition has no route of its own: it is created and edited
through the envelope's (`POST /studio/artifacts` with `kind: agent`,
`PUT .../draft`). Its settings are an R3 resource of app-standards (ADR-0108
decision 3): the row carries `version`, its `ETag` is that version, a `PATCH`
is a merge patch that requires `If-Match`, and the create takes an optional
`Idempotency-Key` (ADR-0108 decision 4). Mounted inside the Studio group, so
every route has a verified identity before it runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.conditions import MergePatch, RequireIfMatch
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.http_conditions import etag_of
from dw_studio.agents.application.settings import AgentSettingsRow, AgentSettingsService

router = APIRouter(prefix="/agents")

_BASE = "/api/v1/studio/agents"


def _service(container: Any) -> AgentSettingsService:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    service: AgentSettingsService = container.studio.agent_settings
    return service


class AgentSettingsView(BaseModel):
    artifact_id: uuid.UUID
    audience: dict[str, Any] = Field(description="A `dw.audience/v1` document.")
    owner_user_id: uuid.UUID | None = Field(
        description="The accountable owner; null only after that person left the company."
    )
    enabled: bool
    version: int = Field(description="The settings' ETag; `If-Match` of a `PATCH`.")
    created_at: datetime
    updated_at: datetime


class NewAgentSettings(BaseModel):
    """Every setting stated: none has a default (AB10)."""

    model_config = ConfigDict(extra="forbid")

    audience: dict[str, Any] = Field(description="A `dw.audience/v1` document.")
    owner_user_id: uuid.UUID
    enabled: StrictBool


def _view(row: AgentSettingsRow) -> AgentSettingsView:
    return AgentSettingsView(
        artifact_id=row.artifact_id,
        audience=dict(row.audience),
        owner_user_id=row.owner_user_id,
        enabled=row.enabled,
        version=row.row_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _may_manage(check: CheckInput) -> None:
    """The create's own check, before a key row is read (app-standards R2.30)."""
    try:
        artifact_id = uuid.UUID(check.request.path_params["artifact_id"])
    except (KeyError, ValueError):
        return  # the route refuses the path itself
    await _service(check.container).check(check.context, artifact_id)


CreateIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_manage, operation="POST /studio/agents/{artifact_id}/settings"),
]


@router.post("/{artifact_id}/settings", response_model=AgentSettingsView, status_code=201)
async def create_agent_settings(
    artifact_id: uuid.UUID,
    body: NewAgentSettings,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    idempotency: CreateIdempotency,
) -> AgentSettingsView:
    service = _service(container)

    async def run(effect: Any) -> AgentSettingsView:
        return _view(
            await service.create(
                context,
                artifact_id,
                audience=body.audience,
                owner_user_id=body.owner_user_id,
                enabled=body.enabled,
                effect=effect,
            )
        )

    async def reread(_id: str) -> AgentSettingsView:
        return _view(await service.get(context, artifact_id))

    view = await idempotency.once(status=201, run=run, reread=reread)
    headers = {"ETag": etag_of(view.version), "Location": f"{_BASE}/{artifact_id}/settings"}
    response.headers.update(headers)
    result: AgentSettingsView = await idempotency.record(view, status_code=201, headers=headers)
    return result


@router.get("/{artifact_id}/settings", response_model=AgentSettingsView)
async def read_agent_settings(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
) -> AgentSettingsView:
    view = _view(await _service(container).get(context, artifact_id))
    response.headers["ETag"] = etag_of(view.version)
    return view


@router.patch("/{artifact_id}/settings", response_model=AgentSettingsView)
async def update_agent_settings(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    expected: RequireIfMatch,
    patch: MergePatch,
) -> AgentSettingsView:
    row = await _service(container).update(context, artifact_id, expected, patch)
    response.headers["ETag"] = etag_of(row.row_version)
    return _view(row)
