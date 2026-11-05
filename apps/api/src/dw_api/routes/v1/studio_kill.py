"""`/api/v1/studio/{agents|workflows}/{artifact_id}/kill` and
`.../revive-requests` (agent-lifecycle R8.1, R8.6-R8.8; the spec's "API").

- `POST .../kill` (`studio.lifecycle.kill` at the component's workspace,
  `Idempotency-Key`; body `reason_code`, `reason`): 201 with `{switch_id}`,
  one `control.kill.set`; a kill already open is 409 `conflict` with
  `already_killed` and no audit.
- `POST .../revive-requests` (same key, `Idempotency-Key`): 202 with the strict
  `studio.lifecycle.revive` approval a second person decides through
  `/api/v1/approvals/{id}/decisions`; nothing is lifted yet. 409 `not_killed`
  when no kill is open, 409 `lift_pending` while a revive waits.

One pair of routes per segment of `KILL_SEGMENTS`, each naming one kind: a
component of another kind under that segment is a 404, as one that does not
exist (`KillSwitchService`). Mounted inside the Studio group
(`dw_api.main.mount_studio`); the company is the access context's, never the
body's.

No `from __future__ import annotations`: the routes are defined inside
`_mount`, and FastAPI resolves a string annotation against the module's
globals, where each segment's idempotency dependency is not.
"""

import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_platform.application.control_switches import ReasonCode
from dw_studio.lifecycle.application.kill import KillSwitchService


def _service(container: Any) -> KillSwitchService:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    service: KillSwitchService = container.studio.kill_switches
    return service


class KillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: ReasonCode
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class KillView(BaseModel):
    switch_id: uuid.UUID


class ReviveRequestView(BaseModel):
    """The approval that lifts the kill once a second person approves it."""

    approval_id: uuid.UUID
    status: str = "pending"


def _target(check: CheckInput) -> tuple[str, uuid.UUID] | None:
    """The kind the request's segment names and the component's id."""
    studio = check.container.studio
    segment = check.request.url.path.partition("/studio/")[2].split("/", 1)[0]
    kind = None if studio is None else studio.kill_segments.get(segment)
    try:
        artifact_id = uuid.UUID(check.request.path_params["artifact_id"])
    except (KeyError, ValueError):
        return None
    return None if kind is None else (kind, artifact_id)


async def _may_kill(check: CheckInput) -> None:
    """The service's own question, before a key row is read (app-standards R2.30)."""
    target = _target(check)
    if target is not None:
        await _service(check.container).check(check.context, *target)


def _mount(router: APIRouter, segment: str, kind: str) -> None:
    base = f"/{segment}/{{artifact_id}}"

    kill_idempotency = Annotated[
        IdempotentOperation, idempotent(_may_kill, operation=f"POST /studio{base}/kill")
    ]
    revive_idempotency = Annotated[
        IdempotentOperation,
        idempotent(_may_kill, operation=f"POST /studio{base}/revive-requests"),
    ]

    async def kill(
        artifact_id: uuid.UUID,
        body: KillBody,
        context: RequireStudioAccess,
        container: RequireContainer,
        idempotency: kill_idempotency,
    ) -> KillView:
        service = _service(container)

        async def run(effect: Any) -> KillView:
            switch_id = await service.kill(
                context,
                kind,
                artifact_id,
                reason_code=body.reason_code,
                reason=body.reason,
                effect=effect,
            )
            return KillView(switch_id=switch_id)

        async def reread(found: str) -> KillView:
            return KillView(switch_id=uuid.UUID(found))

        view = await idempotency.once(status=201, run=run, reread=reread)
        result: KillView = await idempotency.record(view, status_code=201)
        return result

    async def revive(
        artifact_id: uuid.UUID,
        context: RequireStudioAccess,
        container: RequireContainer,
        response: Response,
        idempotency: revive_idempotency,
    ) -> ReviveRequestView:
        service = _service(container)

        async def run(effect: Any) -> ReviveRequestView:
            return ReviveRequestView(
                approval_id=await service.request_revive(context, kind, artifact_id, effect=effect)
            )

        async def reread(found: str) -> ReviveRequestView:
            return ReviveRequestView(approval_id=uuid.UUID(found))

        view = await idempotency.once(status=202, run=run, reread=reread)
        headers = {"Location": f"/api/v1/approvals/{view.approval_id}"}
        response.headers.update(headers)
        result: ReviveRequestView = await idempotency.record(view, status_code=202, headers=headers)
        return result

    name = segment.replace("-", "_")
    router.add_api_route(
        f"{base}/kill",
        kill,
        methods=["POST"],
        response_model=KillView,
        status_code=201,
        name=f"kill_{name}",
        summary=f"Kill a {kind}: its live and test runs stop at their next door",
    )
    router.add_api_route(
        f"{base}/revive-requests",
        revive,
        methods=["POST"],
        response_model=ReviveRequestView,
        status_code=202,
        name=f"request_{name}_revive",
        summary=f"Ask a second person to revive a killed {kind}",
    )


def kill_router(segments: Mapping[str, str]) -> APIRouter:
    """The routes of each segment the composition root names, in its order."""
    router = APIRouter()
    for segment, kind in segments.items():
        _mount(router, segment, kind)
    return router
