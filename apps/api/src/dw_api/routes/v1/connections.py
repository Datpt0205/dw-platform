"""The shared connections of a workspace: /api/v1/connections
(connections-and-vault R1.15, R5.1-R5.3, R5.8, R5.10, R5.13, R5.18, R5.20,
R5.21; ADR-0115 decision 2).

One rule for every route (R5.18), read from `platform.workspace_reach`: a
connection the caller does not reach with `connections.read` is 404
`not_found`, another company's included; a write on one they read and do not
reach with `connections.manage` is 403 `permission_denied`, nothing written.
`POST` creates in the working workspace, which needs `connections.manage`.

- `POST`: `name`, `connector_key`, `connector_major`, `external_account`,
  `share_scope` (`workspace` only, R5.20) and `secrets`, exactly the fields
  the connector declares; 409 `connection_exists` while another connection not
  revoked holds the account (R5.21).
- `PATCH`: `name` and new values of declared secret fields (a rotation);
  anything else is 422.
- `.../disable`: at once; 409 `connection_not_active` otherwise.
- `.../enable`: 202 with a `connections.enable` approval a second person
  decides through `/api/v1/approvals/{id}/decisions`; 409
  `connection_not_disabled`, `enable_pending` or `no_checker_available`.
- `.../revoke-credentials`: every secret version revoked and the connection
  marked compromised, at once, one person (R1.15).
- `DELETE`: 409 `connection_in_use` while something depends on it (R5.8).

A secret value goes in and never comes out (R5.2): the bodies' `secrets` are
write-only, an answer names each declared field and whether it is configured,
and `Idempotency-Key` (optional on every POST and PATCH) fingerprints the body
without the values, so the same key sent again with another value replays the
first answer and stores nothing new.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.pagination import Page
from dw_kernel.secret import Secret
from dw_platform.application.access_context import AccessContext
from dw_platform.application.connection_admin import (
    ConnectionDetail,
    ConnectionPatch,
    ConnectionService,
    NewConnection,
)
from dw_platform.application.connections import Connection

router = APIRouter(prefix="/connections", tags=["connections"])

_BASE = "/api/v1/connections"
_WRITE_ONLY: dict[str, Any] = {"writeOnly": True}


def _service(container: ApiContainer) -> ConnectionService:
    if container.connections is None:
        raise InfrastructureError("connections are not configured")
    return container.connections


# ---- bodies --------------------------------------------------------------------


SecretValues = Annotated[
    dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")], SecretStr],
    Field(json_schema_extra=_WRITE_ONLY),
]


class NewConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    connector_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    connector_major: int = Field(ge=0)
    # Required and not blank: R5.21's unique cannot be walked around with NULL.
    external_account: str = Field(min_length=1, max_length=320)
    # P1 shares by workspace only (R5.20; DO-48.1).
    share_scope: Literal["workspace"] = "workspace"
    secrets: SecretValues = Field(default_factory=dict)


class ConnectionPatchBody(BaseModel):
    """The name and a rotation; the status, scope, connector and account never
    change here (the account is the connection's identity: delete and create)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    secrets: SecretValues = Field(default_factory=dict)


def _values(given: dict[str, SecretStr]) -> dict[str, Secret]:
    return {name: Secret(value.get_secret_value()) for name, value in given.items()}


def _without_secret_values(body: bytes) -> bytes:
    """What the stored fingerprint hashes: the body with each secret value
    dropped and its field name kept (R1.2). A body that does not parse is
    refused by the route; it is never hashed as sent."""
    try:
        parsed = json.loads(body) if body else None
    except ValueError:
        return b"\x00unparseable"
    if isinstance(parsed, dict) and "secrets" in parsed:
        given = parsed["secrets"]
        parsed = {**parsed, "secrets": sorted(given) if isinstance(given, dict) else None}
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ---- answers -------------------------------------------------------------------


class ConnectionView(BaseModel):
    id: UUID
    name: str
    connector_key: str
    connector_major: int
    share_scope: str
    external_account: str | None
    status: str
    scopes: list[str]
    owning_workspace_id: UUID
    last_used_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None
    compromised_at: datetime | None


class SecretFieldView(BaseModel):
    """A declared secret field: `configured` while a version of it is not
    revoked ("Đã cấu hình"). Never a value."""

    field: str
    configured: bool


class ConnectionDetailView(ConnectionView):
    secret_fields: list[SecretFieldView]
    # The `connections.enable` request waiting for a second person, if any.
    pending_enable_approval_id: UUID | None


class EnableRequestView(BaseModel):
    """The approval that enables the connection once a second person approves it."""

    approval_id: UUID
    status: str = "pending"


class ConnectionDependentView(BaseModel):
    kind: str
    id: UUID
    name: str


class ConnectionDependentsView(BaseModel):
    """`total` counts every dependent; `visible` those the caller may read."""

    total: int
    visible: list[ConnectionDependentView]


def _view(row: Connection) -> ConnectionView:
    return ConnectionView(
        id=row.id,
        name=row.name,
        connector_key=row.connector_key,
        connector_major=row.connector_major,
        share_scope=row.share_scope,
        external_account=row.external_account,
        status=row.status,
        scopes=list(row.scopes),
        owning_workspace_id=row.owning_workspace_id,
        last_used_at=row.last_used_at,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        disabled_at=row.disabled_at,
        compromised_at=row.compromised_at,
    )


def _detail(found: ConnectionDetail) -> ConnectionDetailView:
    return ConnectionDetailView(
        **_view(found.connection).model_dump(),
        secret_fields=[
            SecretFieldView(field=s.field, configured=s.configured) for s in found.secret_fields
        ],
        pending_enable_approval_id=found.pending_enable_approval_id,
    )


# ---- checks for an idempotent retry ---------------------------------------------


async def _may_create(check: CheckInput) -> None:
    """The create's own check, before a key row is read (app-standards R2.30)."""
    await _service(check.container).check_create(check.context)


async def _may_write(check: CheckInput) -> None:
    try:
        connection_id = UUID(check.request.path_params["connection_id"])
    except (KeyError, ValueError):
        return  # the route refuses the path itself
    await _service(check.container).check_write(check.context, connection_id)


CreateIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_create, operation="POST /connections", fingerprint_body=_without_secret_values),
]
PatchIdempotency = Annotated[
    IdempotentOperation,
    idempotent(
        _may_write,
        operation="PATCH /connections/{connection_id}",
        fingerprint_body=_without_secret_values,
    ),
]
DisableIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_write, operation="POST /connections/{connection_id}/disable"),
]
EnableIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_write, operation="POST /connections/{connection_id}/enable"),
]
RevokeIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_write, operation="POST /connections/{connection_id}/revoke-credentials"),
]


async def _reread(
    service: ConnectionService, context: AccessContext, found: str
) -> ConnectionDetailView:
    return _detail(await service.get(context, UUID(found)))


# ---- routes --------------------------------------------------------------------


@router.get("", response_model=Page[ConnectionView])
async def list_connections(
    context: RequireAccessContext, container: RequireContainer, page: RequireListPage
) -> Page[ConnectionView]:
    request = page.request(context, key="connections", filters={"tenant": context.tenant_id})
    listed = await _service(container).list(context, request)
    return listed.map_items(_view)


@router.post("", response_model=ConnectionDetailView, status_code=201)
async def create_connection(
    body: NewConnectionBody,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: CreateIdempotency,
) -> ConnectionDetailView:
    service = _service(container)
    command = NewConnection(
        name=body.name,
        connector_key=body.connector_key,
        connector_major=body.connector_major,
        external_account=body.external_account,
        share_scope=body.share_scope,
        secrets=_values(body.secrets),
    )

    async def run(effect: Any) -> ConnectionDetailView:
        created = await service.create(context, command, effect=effect)
        return await _reread(service, context, str(created))

    view = await idempotency.once(
        status=201, run=run, reread=lambda found: _reread(service, context, found)
    )
    headers = {"Location": f"{_BASE}/{view.id}"}
    response.headers.update(headers)
    return await idempotency.record(view, status_code=201, headers=headers)


@router.get("/{connection_id}", response_model=ConnectionDetailView)
async def get_connection(
    connection_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> ConnectionDetailView:
    return _detail(await _service(container).get(context, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionDetailView)
async def update_connection(
    connection_id: UUID,
    body: ConnectionPatchBody,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: PatchIdempotency,
) -> ConnectionDetailView:
    service = _service(container)
    patch = ConnectionPatch(name=body.name, secrets=_values(body.secrets))

    async def run(effect: Any) -> ConnectionDetailView:
        await service.update(context, connection_id, patch, effect=effect)
        return await _reread(service, context, str(connection_id))

    view = await idempotency.once(
        status=200, run=run, reread=lambda found: _reread(service, context, found)
    )
    return await idempotency.record(view)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> Response:
    await _service(container).delete(context, connection_id)
    return Response(status_code=204)


@router.post("/{connection_id}/disable", response_model=ConnectionDetailView)
async def disable_connection(
    connection_id: UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: DisableIdempotency,
) -> ConnectionDetailView:
    service = _service(container)

    async def run(effect: Any) -> ConnectionDetailView:
        await service.disable(context, connection_id, effect=effect)
        return await _reread(service, context, str(connection_id))

    view = await idempotency.once(
        status=200, run=run, reread=lambda found: _reread(service, context, found)
    )
    return await idempotency.record(view)


@router.post("/{connection_id}/enable", response_model=EnableRequestView, status_code=202)
async def enable_connection(
    connection_id: UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: EnableIdempotency,
) -> EnableRequestView:
    service = _service(container)

    async def run(effect: Any) -> EnableRequestView:
        approval_id = await service.request_enable(context, connection_id, effect=effect)
        return EnableRequestView(approval_id=approval_id)

    async def reread(found: str) -> EnableRequestView:
        return EnableRequestView(approval_id=UUID(found))

    view = await idempotency.once(status=202, run=run, reread=reread)
    headers = {"Location": f"/api/v1/approvals/{view.approval_id}"}
    response.headers.update(headers)
    return await idempotency.record(view, status_code=202, headers=headers)


@router.post("/{connection_id}/revoke-credentials", response_model=ConnectionDetailView)
async def revoke_connection_credentials(
    connection_id: UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: RevokeIdempotency,
) -> ConnectionDetailView:
    service = _service(container)

    async def run(effect: Any) -> ConnectionDetailView:
        await service.revoke_credentials(context, connection_id, effect=effect)
        return await _reread(service, context, str(connection_id))

    view = await idempotency.once(
        status=200, run=run, reread=lambda found: _reread(service, context, found)
    )
    return await idempotency.record(view)


@router.get("/{connection_id}/dependents", response_model=ConnectionDependentsView)
async def connection_dependents(
    connection_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> ConnectionDependentsView:
    found = await _service(container).dependents(context, connection_id)
    return ConnectionDependentsView(
        total=found.total,
        visible=[ConnectionDependentView(kind=d.kind, id=d.id, name=d.name) for d in found.visible],
    )
