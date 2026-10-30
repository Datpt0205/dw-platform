"""The one-address unsubscribe door: /api/v1/public/unsubscribe/{token}
(ADR-0124 decision 5; compliance-pdpl R3.4, R3.6).

Public: the person who clicks has no account. The token is the whole
authority: signed with HMAC-SHA256, it names the tenant, the channel and the
address's hash, never the address. `GET` only checks it, so a mailbox's link
scanner that follows every link opts nobody out; `POST`, the page's confirm
button, writes the suppression under the token's own tenant, once.

A token that does not verify (forged, altered, older than 400 days) is the
same 404, with the same body, on both. Both pass the API's per-address rate
limit like any other route. Without a signing secret (a profile that is not
deployed; a deployed one refuses to start) the door answers 503.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError, NotFoundError
from dw_platform.application.marketing_send import UnsubscribeClaim, UnsubscribeService

router = APIRouter(prefix="/public/unsubscribe", tags=["public"])


class UnsubscribeView(BaseModel):
    channel: str
    unsubscribed: bool


def _service(container: ApiContainer) -> UnsubscribeService:
    if container.unsubscribe is None:
        raise InfrastructureError("unsubscribe links are not configured")
    return container.unsubscribe


def _found(claim: UnsubscribeClaim | None) -> UnsubscribeClaim:
    if claim is None:
        # One answer for every token that does not verify.
        raise NotFoundError("not found")
    return claim


@router.get("/{token}", response_model=UnsubscribeView)
async def check_unsubscribe(token: str, container: RequireContainer) -> UnsubscribeView:
    claim = _found(_service(container).check(token))
    return UnsubscribeView(channel=claim.channel, unsubscribed=False)


@router.post("/{token}", response_model=UnsubscribeView)
async def confirm_unsubscribe(token: str, container: RequireContainer) -> UnsubscribeView:
    claim = _found(await _service(container).confirm(token))
    return UnsubscribeView(channel=claim.channel, unsubscribed=True)
