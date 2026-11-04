"""`/api/v1/admin/roles`, `/role-templates` and `/role-changes`: a company's
roles, as its administrators change them (tenant-rbac ticket 03, R6-R8).

The service owns every rule (`dw_platform.application.role_admin`); a route
shapes the request and the answer. A change that widens answers 202 with the
proposal another holder of the same permission confirms; one that only
narrows answers 200, applied. A role is an R3 resource of app-standards: its
`version` is its ETag, and every write on an existing role requires
`If-Match` (412 stale, 428 missing; ADR-0108 decision 3). Refusals keep the
error envelope of ADR-0108 and say why in `details.reason_code`.

`ROLE_ROUTES_WITHOUT_BYPASS` names, once and beside the routers, every route
of role administration and role assignment: the `platform_admin` bypass (G2)
does not open them, so a caller passes only by holding the route's key
through `platform.effective_grants` (R3.16, Q-h7). `get_access_context` reads
the list; `test_role_routes_without_bypass.py` holds it to the routers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.conditions import MergePatch, RequireIfMatch
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.http_conditions import etag_of
from dw_kernel.pagination import Page
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.role_admin import (
    ROLES_WRITE,
    CreateRole,
    FieldPermission,
    ObjectPrivilege,
    Privilege,
    Proposal,
    RoleAdminService,
    RoleDetail,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_API = "/api/v1/admin"

# R3.16: the routes the `platform_admin` bypass does not open, as
# (method, path template). Read by `get_access_context`; held to the routers by
# `apps/api/tests/unit/test_role_routes_without_bypass.py`.
ROLE_ROUTES_WITHOUT_BYPASS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", f"{_API}/roles"),
        ("POST", f"{_API}/roles"),
        ("GET", f"{_API}/roles/{{role_id}}"),
        ("PATCH", f"{_API}/roles/{{role_id}}"),
        ("DELETE", f"{_API}/roles/{{role_id}}"),
        ("PUT", f"{_API}/roles/{{role_id}}/permissions"),
        ("GET", f"{_API}/roles/{{role_id}}/assignments"),
        ("GET", f"{_API}/role-templates"),
        ("GET", f"{_API}/role-changes"),
        ("POST", f"{_API}/role-changes/{{request_id}}/confirm"),
        ("POST", f"{_API}/role-changes/{{request_id}}/withdraw"),
        ("PUT", f"{_API}/members/{{user_id}}/memberships"),
        ("PUT", f"{_API}/members/{{user_id}}/permission-sets"),
        ("POST", f"{_API}/members"),
        ("POST", f"{_API}/invitations"),
    }
)


def _service(container: Any) -> RoleAdminService:
    if container.role_admin is None:
        raise InfrastructureError("database is not configured")
    service: RoleAdminService = container.role_admin
    return service


class PrivilegeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    depth: str = Field(description="`own`, `workspace` or `tenant`.")


class ObjectPrivilegeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: uuid.UUID = Field(description="A live object definition of this company.")
    action: str = Field(description="An enforced action of `platform.object_actions`.")
    depth: str = Field(description="`own`, `workspace` or `tenant`.")


class FieldPermissionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: uuid.UUID = Field(description="A field of a live object of this company.")
    access: str = Field(description="`read`, or `edit`, which gives read too.")


class RoleView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    kind: str
    is_system: bool
    template_key: str | None
    holder_count: int
    version: int = Field(description="The role's ETag; `If-Match` of its writes.")
    assignable_by_me: bool = Field(
        description="`platform.rbac_refusals` refuses the caller nothing in assigning it"
        " to someone else in the caller's workspace."
    )
    updated_at: datetime


class RoleDetailView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    kind: str
    is_system: bool
    template_key: str | None
    holder_count: int
    version: int = Field(description="The role's ETag; `If-Match` of its writes.")
    updated_at: datetime
    permissions: list[PrivilegeView]
    object_privileges: list[ObjectPrivilegeView]
    field_permissions: list[FieldPermissionView]


class RoleAssignmentView(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    assigned_at: datetime
    expires_at: datetime | None


class RoleTemplateView(BaseModel):
    key: str
    name: str
    kind: str
    permissions: list[PrivilegeView]


class ProposalView(BaseModel):
    id: uuid.UUID
    kind: str
    role_id: uuid.UUID | None
    base_version: int | None
    payload: dict[str, Any] = Field(description="The change exactly as it will be applied.")
    required_permission: str
    proposed_by: uuid.UUID
    proposed_at: datetime
    expires_at: datetime
    status: str
    confirmed_by: uuid.UUID | None
    decided_at: datetime | None


class RoleChangeView(BaseModel):
    """The answer to a change of an existing role: the role as it is now, and
    the proposal when the change waits for a second person (202)."""

    role: RoleDetailView
    proposal: ProposalView | None


class CreateRoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=63)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    kind: str = Field(default="role", pattern="^(role|permission_set)$")
    from_template: str | None = None
    clone_of: uuid.UUID | None = None


class PermissionsBody(BaseModel):
    """Each array present replaces that kind of the role's grants; one left
    out keeps it (R9.14)."""

    model_config = ConfigDict(extra="forbid")

    permissions: list[PrivilegeView] | None = None
    object_privileges: list[ObjectPrivilegeView] | None = None
    field_permissions: list[FieldPermissionView] | None = None


def _role_view(role: RoleDetail) -> RoleDetailView:
    return RoleDetailView(
        id=role.id,
        key=role.key,
        name=role.name,
        description=role.description,
        kind=role.kind,
        is_system=role.is_system,
        template_key=role.template_key,
        holder_count=role.holder_count,
        version=role.version,
        updated_at=role.updated_at,
        permissions=[PrivilegeView(key=p.key, depth=p.depth) for p in role.privileges],
        object_privileges=[
            ObjectPrivilegeView(object_id=p.object_id, action=p.action, depth=p.depth)
            for p in role.object_privileges
        ],
        field_permissions=[
            FieldPermissionView(field_id=p.field_id, access=p.access)
            for p in role.field_permissions
        ],
    )


def proposal_view(proposal: Proposal) -> ProposalView:
    return ProposalView(
        id=proposal.id,
        kind=proposal.kind,
        role_id=proposal.role_id,
        base_version=proposal.base_version,
        payload=dict(proposal.payload),
        required_permission=proposal.required_permission,
        proposed_by=proposal.proposed_by,
        proposed_at=proposal.proposed_at,
        expires_at=proposal.expires_at,
        status=proposal.status,
        confirmed_by=proposal.confirmed_by,
        decided_at=proposal.decided_at,
    )


async def _may_confirm(check: CheckInput) -> None:
    """404 then 403, before a key row is read (app-standards R2.30)."""
    try:
        request_id = uuid.UUID(check.request.path_params["request_id"])
    except (KeyError, ValueError):
        return
    await _service(check.container).require_may_confirm(check.context, request_id)


async def _may_withdraw(check: CheckInput) -> None:
    try:
        request_id = uuid.UUID(check.request.path_params["request_id"])
    except (KeyError, ValueError):
        return
    await _service(check.container).require_may_withdraw(check.context, request_id)


CreateIdempotency = Annotated[
    IdempotentOperation, idempotent(ROLES_WRITE, operation="POST /admin/roles")
]
PatchIdempotency = Annotated[
    IdempotentOperation, idempotent(ROLES_WRITE, operation="PATCH /admin/roles/{role_id}")
]
PermissionsIdempotency = Annotated[
    IdempotentOperation,
    idempotent(ROLES_WRITE, operation="PUT /admin/roles/{role_id}/permissions"),
]
DeleteIdempotency = Annotated[
    IdempotentOperation, idempotent(ROLES_WRITE, operation="DELETE /admin/roles/{role_id}")
]
ConfirmIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_confirm, operation="POST /admin/role-changes/{request_id}/confirm"),
]
WithdrawIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_withdraw, operation="POST /admin/role-changes/{request_id}/withdraw"),
]


@router.get("/roles", response_model=list[RoleView])
async def list_roles(context: RequireAccessContext, container: RequireContainer) -> list[RoleView]:
    """Every live role of the company. At most 200 (R3.7), so not paged."""
    return [
        RoleView(
            id=r.id,
            key=r.key,
            name=r.name,
            description=r.description,
            kind=r.kind,
            is_system=r.is_system,
            template_key=r.template_key,
            holder_count=r.holder_count,
            version=r.version,
            assignable_by_me=r.assignable_by_me,
            updated_at=r.updated_at,
        )
        for r in await _service(container).list_roles(context)
    ]


@router.get("/roles/{role_id}", response_model=RoleDetailView)
async def get_role(
    role_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
) -> RoleDetailView:
    view = _role_view(await _service(container).get_role(context, role_id))
    response.headers["ETag"] = etag_of(view.version)
    return view


@router.get("/roles/{role_id}/assignments", response_model=list[RoleAssignmentView])
async def list_role_assignments(
    role_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> list[RoleAssignmentView]:
    return [
        RoleAssignmentView(
            id=a.id,
            membership_id=a.membership_id,
            workspace_id=a.workspace_id,
            user_id=a.user_id,
            assigned_at=a.assigned_at,
            expires_at=a.expires_at,
        )
        for a in await _service(container).list_assignments(context, role_id)
    ]


@router.get("/role-templates", response_model=list[RoleTemplateView])
async def list_role_templates(
    context: RequireAccessContext, container: RequireContainer
) -> list[RoleTemplateView]:
    """The platform's templates a role may start from; never a tenant's."""
    return [
        RoleTemplateView(
            key=t.key,
            name=t.name,
            kind=t.kind,
            permissions=[PrivilegeView(key=p.key, depth=p.depth) for p in t.privileges],
        )
        for t in await _service(container).list_templates(context)
    ]


@router.post("/roles", response_model=ProposalView, status_code=202)
async def create_role(
    body: CreateRoleBody,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: CreateIdempotency,
) -> ProposalView:
    """Always a proposal: making a role widens (R7.1)."""
    service = _service(container)
    command = CreateRole(
        key=body.key,
        name=body.name,
        description=body.description,
        kind="permission_set" if body.kind == "permission_set" else "role",
        from_template=body.from_template,
        clone_of=body.clone_of,
    )

    async def run(effect: PendingEffect | None) -> ProposalView:
        return proposal_view(await service.create_role(context, command, effect=effect))

    async def reread(request_id: str) -> ProposalView:
        return await _proposal(container, context, uuid.UUID(request_id))

    view = await idempotency.once(status=202, run=run, reread=reread)
    return await idempotency.record(view, status_code=202)


_PROPOSED: dict[int | str, dict[str, Any]] = {
    202: {"model": RoleChangeView, "description": "Proposed for a second person."}
}


@router.patch("/roles/{role_id}", response_model=RoleChangeView, responses=_PROPOSED)
async def update_role(
    role_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: PatchIdempotency,
    expected: RequireIfMatch,
    patch: MergePatch,
) -> RoleChangeView:
    """`name`, `description`: a proposal (202), or the role unchanged (200)."""
    service = _service(container)

    async def run(effect: PendingEffect | None) -> RoleChangeView:
        return await _change(
            container,
            context,
            role_id,
            await service.update_role(context, role_id, expected, patch, effect=effect),
        )

    return await _answer(container, context, role_id, response, idempotency, run)


@router.put("/roles/{role_id}/permissions", response_model=RoleChangeView, responses=_PROPOSED)
async def set_role_permissions(
    role_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: PermissionsIdempotency,
    expected: RequireIfMatch,
    body: Annotated[PermissionsBody, Body()],
) -> RoleChangeView:
    """The role's privileges, object privileges and field permissions, each
    array present replacing its kind: applied at once (200) when it only
    narrows, else a proposal (202, R7.1, R7.6, RB32, R9.14)."""
    service = _service(container)
    target = (
        None if body.permissions is None else [Privilege(p.key, p.depth) for p in body.permissions]
    )
    objects = (
        None
        if body.object_privileges is None
        else [ObjectPrivilege(p.object_id, p.action, p.depth) for p in body.object_privileges]
    )
    fields = (
        None
        if body.field_permissions is None
        else [FieldPermission(p.field_id, p.access) for p in body.field_permissions]
    )

    async def run(effect: PendingEffect | None) -> RoleChangeView:
        return await _change(
            container,
            context,
            role_id,
            await service.set_permissions(
                context,
                role_id,
                expected,
                target,
                object_privileges=objects,
                field_permissions=fields,
                effect=effect,
            ),
        )

    return await _answer(container, context, role_id, response, idempotency, run)


@router.delete("/roles/{role_id}", response_model=RoleDetailView)
async def delete_role(
    role_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: DeleteIdempotency,
    expected: RequireIfMatch,
) -> RoleDetailView:
    """A soft delete of a role nobody holds, one person and one audit event
    (R7.6); 409 `role_in_use`, `role_is_system`."""
    service = _service(container)

    async def run(effect: PendingEffect | None) -> RoleDetailView:
        return _role_view(await service.delete_role(context, role_id, expected, effect=effect))

    async def reread(_id: str) -> RoleDetailView:
        role = await service.repo.get_role(context, role_id)
        if role is None:
            raise InfrastructureError("the deleted role cannot be read back")
        return _role_view(role)

    view = await idempotency.once(status=200, run=run, reread=reread)
    response.headers["ETag"] = etag_of(view.version)
    return await idempotency.record(view, headers={"ETag": etag_of(view.version)})


@router.get("/role-changes", response_model=Page[ProposalView])
async def list_role_changes(
    context: RequireAccessContext, container: RequireContainer, page: RequireListPage
) -> Page[ProposalView]:
    """Proposals still waiting and not expired, newest first."""
    request = page.request(context, key="role_changes", filters={"tenant": context.tenant_id})
    listed = await _service(container).list_proposals(context, request)
    return listed.map_items(proposal_view)


@router.post("/role-changes/{request_id}/confirm", response_model=ProposalView)
async def confirm_role_change(
    request_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: ConfirmIdempotency,
) -> ProposalView:
    """A second person applies the proposal in their own transaction (R7.1,
    R7.2, R7.4, R7.8, R8.7)."""
    service = _service(container)

    async def run(effect: PendingEffect | None) -> ProposalView:
        await service.confirm(context, request_id, effect=effect)
        return await _proposal(container, context, request_id)

    async def reread(_id: str) -> ProposalView:
        return await _proposal(container, context, request_id)

    view = await idempotency.once(status=200, run=run, reread=reread)
    return await idempotency.record(view)


@router.post("/role-changes/{request_id}/withdraw", response_model=ProposalView)
async def withdraw_role_change(
    request_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: WithdrawIdempotency,
) -> ProposalView:
    service = _service(container)

    async def run(effect: PendingEffect | None) -> ProposalView:
        return proposal_view(await service.withdraw(context, request_id, effect=effect))

    async def reread(_id: str) -> ProposalView:
        return await _proposal(container, context, request_id)

    view = await idempotency.once(status=200, run=run, reread=reread)
    return await idempotency.record(view)


async def _proposal(container: Any, context: Any, request_id: uuid.UUID) -> ProposalView:
    found = await _service(container).repo.get_proposal(context, request_id)
    if found is None:
        from dw_kernel.errors import NotFoundError

        raise NotFoundError("no such role change request")
    return proposal_view(found)


async def _change(
    container: Any, context: Any, role_id: uuid.UUID, result: Proposal | RoleDetail
) -> RoleChangeView:
    if isinstance(result, RoleDetail):
        return RoleChangeView(role=_role_view(result), proposal=None)
    role = await _service(container).get_role(context, role_id)
    return RoleChangeView(role=_role_view(role), proposal=proposal_view(result))


async def _answer(
    container: Any,
    context: Any,
    role_id: uuid.UUID,
    response: Response,
    idempotency: IdempotentOperation,
    run: Any,
) -> RoleChangeView:
    async def reread(_id: str) -> RoleChangeView:
        role = await _service(container).get_role(context, role_id)
        return RoleChangeView(role=_role_view(role), proposal=None)

    view: RoleChangeView = await idempotency.once(status=200, run=run, reread=reread)
    status = 202 if view.proposal is not None else 200
    headers = {"ETag": etag_of(view.role.version)}
    response.status_code = status
    response.headers.update(headers)
    return await idempotency.record(view, status_code=status, headers=headers)
