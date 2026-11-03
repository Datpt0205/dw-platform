"""A company's service accounts: /api/v1/admin/service-principals
(org-and-principals R6.1, R6.12-R6.14, R6.16).

Create one, list those whose owning workspace the caller reaches with
`platform.service_principals.manage` or `.use`, and change a name, a
description or the accountable owner. The service owns every rule and the
database keeps them; the route shapes the request. Roles reach an account
through the role-assignment API, as for any member.

Refusals, in `details.reason_code` unless said: 422 `validation_failed` at
`/owning_workspace_id` for a workspace that is not the caller's company's (or
does not exist, the same answer); 422 `owner_not_member`; 409
`service_principal_name_taken`; 403 without `.manage` reaching the owning
workspace. An account the caller's company does not own, a Digital Worker's
principal, a person and an unknown id are one 404 `not_found`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.pagination import Page, SortType
from dw_platform.application.service_principals import (
    ListedServicePrincipal,
    NewServicePrincipal,
    ServicePrincipalChanges,
    ServicePrincipalService,
    WorkspaceNotInTenantError,
)

router = APIRouter(prefix="/admin/service-principals", tags=["admin"])

_NAME = r"\S"


def _service(container: ApiContainer) -> ServicePrincipalService:
    if container.service_principals is None:
        raise InfrastructureError("service accounts are not configured")
    return container.service_principals


async def _located[T](work: Callable[[], Awaitable[T]]) -> T:
    """A workspace outside the company, as the schema error it is: 422 at its
    member, with nothing of the value repeated (app-standards R1.10)."""
    try:
        return await work()
    except WorkspaceNotInTenantError as exc:
        raise RequestValidationError(
            [
                {
                    "type": "workspace_unknown",
                    "loc": ("body", exc.pointer.lstrip("/")),
                    "msg": exc.message,
                    "input": None,
                }
            ]
        ) from exc


async def _may_create(check: CheckInput) -> None:
    """The create's own check, before a key row is read (app-standards R2.30)."""
    try:
        workspace = (await check.request.json()).get("owning_workspace_id")
        workspace_id = UUID(str(workspace))
    except (ValueError, AttributeError, TypeError):
        return  # the route refuses the body itself
    await _service(check.container).require_manage(check.context, workspace_id)


CreateIdempotency = Annotated[
    IdempotentOperation, idempotent(_may_create, operation="POST /admin/service-principals")
]


class CreateServicePrincipalBody(BaseModel):
    """The tenant is never the body's: it is the access context's."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120, pattern=_NAME)
    description: str | None = Field(default=None, max_length=1000)
    owning_workspace_id: UUID
    owner_user_id: UUID


class UpdateServicePrincipalBody(BaseModel):
    """Only the members sent change; `description: null` empties it. A name
    or an accountable owner cannot be emptied (R6.16)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120, pattern=_NAME)
    description: str | None = Field(default=None, max_length=1000)
    owner_user_id: UUID | None = None

    @field_validator("name", "owner_user_id")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("this member cannot be null")
        return value


class ServicePrincipalView(BaseModel):
    id: UUID
    name: str
    description: str | None
    owning_workspace_id: UUID
    # None once the owner's company row is gone; `owner_missing` is what counts.
    owner_user_id: UUID | None
    owner_missing: bool
    # The account's company row; None once it is gone, which is not `active`.
    status: Literal["invited", "active", "suspended"] | None
    bindable_by_me: bool


def _view(listed: ListedServicePrincipal) -> ServicePrincipalView:
    p = listed.principal
    return ServicePrincipalView(
        id=p.id,
        name=p.name,
        description=p.description,
        owning_workspace_id=p.owning_workspace_id,
        owner_user_id=p.owner_user_id,
        owner_missing=p.owner_missing,
        status=p.status,
        bindable_by_me=listed.bindable_by_me,
    )


async def _viewed(listed: Awaitable[ListedServicePrincipal]) -> ServicePrincipalView:
    return _view(await listed)


def _changes(body: UpdateServicePrincipalBody) -> ServicePrincipalChanges:
    named = body.model_fields_set
    return ServicePrincipalChanges(
        name=body.name,
        description=body.description,
        clear_description="description" in named and body.description is None,
        owner_user_id=body.owner_user_id,
    )


@router.post("", response_model=ServicePrincipalView, status_code=201)
async def create_service_principal(
    body: CreateServicePrincipalBody,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: CreateIdempotency,
) -> ServicePrincipalView:
    service = _service(container)
    command = NewServicePrincipal(
        name=body.name,
        description=body.description,
        owning_workspace_id=body.owning_workspace_id,
        owner_user_id=body.owner_user_id,
    )
    view = await _located(
        lambda: idempotency.once(
            status=201,
            run=lambda effect: _viewed(service.create(context, command, effect=effect)),
            reread=lambda found: _viewed(service.read(context, UUID(found))),
        )
    )
    return await idempotency.record(view, status_code=201)


@router.get("", response_model=Page[ServicePrincipalView])
async def list_service_principals(
    context: RequireAccessContext, container: RequireContainer, page: RequireListPage
) -> Page[ServicePrincipalView]:
    request = page.request(
        context,
        key="service_principals",
        filters={"tenant": context.tenant_id},
        sort_type=SortType.TEXT,
    )
    listed = await _service(container).list(context, request)
    return listed.map_items(_view)


@router.patch("/{service_principal_id}", response_model=ServicePrincipalView)
async def update_service_principal(
    service_principal_id: UUID,
    body: UpdateServicePrincipalBody,
    context: RequireAccessContext,
    container: RequireContainer,
) -> ServicePrincipalView:
    # No If-Match in W1: the row has no version, the last write wins (M8).
    return _view(await _service(container).update(context, service_principal_id, _changes(body)))
