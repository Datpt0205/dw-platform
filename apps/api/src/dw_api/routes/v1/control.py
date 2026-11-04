"""The company's freeze: /api/v1/admin/freeze, /api/v1/admin/unfreeze and
/api/v1/control-state (agent-lifecycle R7.4-R7.6, R7.10, R7.11; ADR-0120
decisions 5, 7, amended 2026-11-04; D11).

- `POST /admin/freeze` (`studio.lifecycle.freeze`, `Idempotency-Key`; body
  `reason_code`, `reason`): one person, 201 with `{switch_id}` and one
  `control.freeze.set`; a company-set freeze already open is 409 `conflict`
  with `already_frozen` and no audit.
- `POST /admin/unfreeze` (`studio.lifecycle.freeze`, `Idempotency-Key`): 202
  with the strict `studio.lifecycle.unfreeze` approval a second person decides
  through `/api/v1/approvals/{id}/decisions`; nothing is lifted yet. 403 when
  only an operator's freeze holds the company, 409 `not_frozen` when nothing
  does, 409 `lift_pending` while a lift waits.
- `GET /control-state`: every member; what holds the company, codes only.

The company is never the body's: it is the access context's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_platform.application.control_switches import (
    LIFECYCLE_FREEZE,
    ControlState,
    ControlSwitchService,
    ReasonCode,
)

router = APIRouter(prefix="/admin", tags=["admin"])
state_router = APIRouter(tags=["control"])


def _service(container: ApiContainer) -> ControlSwitchService:
    if container.control_switches is None:
        raise InfrastructureError("control switches are not configured")
    return container.control_switches


class FreezeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: ReasonCode
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class FreezeView(BaseModel):
    switch_id: UUID


class UnfreezeRequestView(BaseModel):
    """The approval that lifts the freeze once a second person approves it."""

    approval_id: UUID
    status: str = "pending"


class OpenFreezeView(BaseModel):
    origin: Literal["tenant", "platform"]
    reason_code: str
    set_at: datetime


class ControlStateView(BaseModel):
    state: Literal["open", "platform_frozen", "tenant_frozen"]
    # The operators' freeze of the whole platform, when one holds.
    platform_freeze: OpenFreezeView | None
    # The company's freezes: its own, and an operator's of this company.
    freezes: list[OpenFreezeView]


def _state(found: ControlState) -> ControlStateView:
    platform = (
        None
        if found.platform_freeze_set_at is None or found.platform_freeze_reason_code is None
        else OpenFreezeView(
            origin="platform",
            reason_code=found.platform_freeze_reason_code,
            set_at=found.platform_freeze_set_at,
        )
    )
    return ControlStateView(
        state=found.state,
        platform_freeze=platform,
        freezes=[
            OpenFreezeView(origin=f.origin, reason_code=f.reason_code, set_at=f.set_at)
            for f in found.freezes
        ],
    )


FreezeIdempotency = Annotated[
    IdempotentOperation, idempotent(LIFECYCLE_FREEZE, operation="POST /admin/freeze")
]
UnfreezeIdempotency = Annotated[
    IdempotentOperation, idempotent(LIFECYCLE_FREEZE, operation="POST /admin/unfreeze")
]


@router.post("/freeze", response_model=FreezeView, status_code=201)
async def freeze(
    body: FreezeBody,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: FreezeIdempotency,
) -> FreezeView:
    service = _service(container)

    async def run(effect: Any) -> FreezeView:
        switch_id = await service.freeze(
            context, reason_code=body.reason_code, reason=body.reason, effect=effect
        )
        return FreezeView(switch_id=switch_id)

    async def reread(found: str) -> FreezeView:
        return FreezeView(switch_id=UUID(found))

    view = await idempotency.once(status=201, run=run, reread=reread)
    return await idempotency.record(view, status_code=201)


@router.post("/unfreeze", response_model=UnfreezeRequestView, status_code=202)
async def unfreeze(
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: UnfreezeIdempotency,
) -> UnfreezeRequestView:
    service = _service(container)

    async def run(effect: Any) -> UnfreezeRequestView:
        return UnfreezeRequestView(
            approval_id=await service.request_unfreeze(context, effect=effect)
        )

    async def reread(found: str) -> UnfreezeRequestView:
        return UnfreezeRequestView(approval_id=UUID(found))

    view = await idempotency.once(status=202, run=run, reread=reread)
    headers = {"Location": f"/api/v1/approvals/{view.approval_id}"}
    response.headers.update(headers)
    return await idempotency.record(view, status_code=202, headers=headers)


@state_router.get("/control-state", response_model=ControlStateView)
async def control_state(
    context: RequireAccessContext, container: RequireContainer
) -> ControlStateView:
    return _state(await _service(container).state(context))
