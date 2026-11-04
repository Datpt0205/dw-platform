"""The company's Allowed hosts: /api/v1/egress/allowed-hosts
(connections-and-vault R3.8-R3.12, R3.18, R3.19; ADR-0115 decision 6).

Every route needs `integrations.admin` (403 `permission_denied` without it).

- `GET` lists the live rows, newest first.
- `POST` asks for a host: 422 for a pattern that is an IP literal, malformed,
  or a wildcard on a public suffix (`details.reason_code`); 409 `conflict`
  with `no_checker_available` when nobody but the caller could approve it;
  otherwise 202 with the `egress.allowed_host` approval's id, and nothing is
  allowed yet. A second person holding the key approves it through
  `/api/v1/approvals/{id}/decisions`.
- `DELETE /{id}` removes a live row at once; another company's id, an unknown
  one and a row already removed are one 404 `not_found`.

The tenant is never the body's: it is the access context's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.pagination import Page
from dw_platform.application.egress_allowlist import EgressAllowlistService, NewAllowedHost
from dw_platform.domain.allowed_hosts import AllowedHost, AllowedHostPurpose

router = APIRouter(prefix="/egress/allowed-hosts", tags=["egress"])

Port = Annotated[int, Field(ge=1, le=65535)]


def _service(container: ApiContainer) -> EgressAllowlistService:
    if container.egress_allowlist is None:
        raise InfrastructureError("allowed hosts are not configured")
    return container.egress_allowlist


class AllowedHostRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_pattern: str = Field(min_length=1, max_length=255)
    purpose: AllowedHostPurpose
    ports: list[Port] = Field(default_factory=lambda: [443], min_length=1, max_length=16)
    note: str | None = Field(default=None, max_length=500)


class AllowedHostRequestView(BaseModel):
    """The approval that will add the host once a second person approves it."""

    approval_id: UUID
    status: str = "pending"


class AllowedHostView(BaseModel):
    id: UUID
    host_pattern: str
    ports: list[int]
    purpose: str
    note: str | None
    owning_workspace_id: UUID
    created_by: UUID
    created_at: datetime


def _view(host: AllowedHost) -> AllowedHostView:
    return AllowedHostView(
        id=host.id,
        host_pattern=host.host_pattern,
        ports=list(host.ports),
        purpose=host.purpose,
        note=host.note,
        owning_workspace_id=host.owning_workspace_id,
        created_by=host.created_by,
        created_at=host.created_at,
    )


@router.get("", response_model=Page[AllowedHostView])
async def list_allowed_hosts(
    context: RequireAccessContext, container: RequireContainer, page: RequireListPage
) -> Page[AllowedHostView]:
    request = page.request(
        context, key="egress_allowed_hosts", filters={"tenant": context.tenant_id}
    )
    listed = await _service(container).list(context, request)
    return listed.map_items(_view)


@router.post("", response_model=AllowedHostRequestView, status_code=202)
async def request_allowed_host(
    body: AllowedHostRequestBody,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
) -> AllowedHostRequestView:
    approval_id = await _service(container).propose(
        context,
        NewAllowedHost(
            host_pattern=body.host_pattern,
            purpose=body.purpose,
            ports=tuple(body.ports),
            note=body.note,
        ),
    )
    response.headers["Location"] = f"/api/v1/approvals/{approval_id}"
    return AllowedHostRequestView(approval_id=approval_id)


@router.delete("/{host_id}", status_code=204)
async def remove_allowed_host(
    host_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> Response:
    await _service(container).remove(context, host_id)
    return Response(status_code=204)
