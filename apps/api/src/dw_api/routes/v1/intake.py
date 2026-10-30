"""The signed lead intake and its key (leadcare R2).

`POST /api/v1/intake/leads`: a website form's lead, signed with the DW's
intake key; no account, the signature is the authority (`LeadIntake`). The raw
body is read and bounded (64 KiB) before anything parses it, because the
signature covers its bytes. Refusals the form's integrator branches on, in
`details.reason_code`: 401 `signature_invalid` (one answer for every untrusted
call), 422 `consent_missing`, `payload_invalid`, 409 `source_key_reused`, 503
`intake_disabled` (any deployed profile until real personal data is cleared,
R2.12) and `intake_unconfigured` (no signing secret, R2.7).

`GET /api/v1/digital-workers/{dw_id}/intake-key`: the key, for the DW's
Business Owner or Technical Owner only (404, then 403 `not_dw_owner`), each
read on the audit trail (R2.8, R2.11).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError, PayloadTooLargeError
from dw_platform.application.intake import MAX_BODY_BYTES, IntakeKeyReader, LeadIntake

router = APIRouter(tags=["intake"])


class Received(BaseModel):
    id: UUID


class IntakeKey(BaseModel):
    key: str


def _intake(container: ApiContainer) -> LeadIntake:
    if container.settings.is_deployed:
        raise InfrastructureError(
            "lead intake is closed in this profile", details={"reason_code": "intake_disabled"}
        )
    if container.intake is None:
        raise InfrastructureError(
            "lead intake is not configured", details={"reason_code": "intake_unconfigured"}
        )
    return container.intake


def _keys(container: ApiContainer) -> IntakeKeyReader:
    if container.intake_keys is None:
        raise InfrastructureError(
            "lead intake is not configured", details={"reason_code": "intake_unconfigured"}
        )
    return container.intake_keys


@router.post("/intake/leads", response_model=Received, status_code=202)
async def receive_lead(
    request: Request,
    container: RequireContainer,
    x_dw_worker: Annotated[str | None, Header()] = None,
    x_dw_event_id: Annotated[str | None, Header()] = None,
    x_dw_timestamp: Annotated[str | None, Header()] = None,
    x_dw_signature: Annotated[str | None, Header()] = None,
) -> Received:
    intake = _intake(container)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise PayloadTooLargeError("a lead is at most 64 KiB")
    item = await intake.receive(
        worker=x_dw_worker,
        event_id=x_dw_event_id,
        timestamp=x_dw_timestamp,
        signature=x_dw_signature,
        body=body,
    )
    return Received(id=item.id)


@router.get("/digital-workers/{dw_id}/intake-key", response_model=IntakeKey)
async def read_intake_key(
    dw_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> IntakeKey:
    return IntakeKey(key=await _keys(container).read(context, dw_id))
