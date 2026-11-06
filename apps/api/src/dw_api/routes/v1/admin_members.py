"""Org Admin membership management: /api/v1/admin/members and /admin/invitations.

Place a person in a workspace, list everyone in the tenant with their roles per
workspace, replace a person's roles in several workspaces at once, invite
someone who has never signed in, and set a member's permission sets. The
services own every rule (`RoleAssignmentService`: scope, tenant RLS, the hold
rule, two people, audit); a route shapes the request and the answer.

Roles a request adds are proposals another holder of `platform.roles.bind`
confirms (tenant-rbac R7.1), never the person placed: such a request answers
202 with `proposals`, and the roles it removed are in `applied`. A request that
only removes answers as before. A membership with no role (`role_keys: []`) is
written at once with `platform.members.write` alone (tenant-rbac/16). These routes are in `ROLE_ROUTES_WITHOUT_BYPASS`: the `platform_admin`
bypass does not open them (R3.16).

Refusals the web branches on: 409 with `details.reason_code`
`member_email_exists_in_tenant`, `support_staff_not_member`,
`no_checker_available`, `dw_principal_roles_fixed`, `last_owner`; 403
`rbac_escalation`, `rbac_self_assignment`; 422 `role_not_allowed_for_service`;
404 for a person or workspace outside the tenant, or an unknown role
(`details.roles`).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError, NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.membership_admin import MEMBERS_WRITE, RevokeMembership
from dw_platform.application.role_assignments import (
    AssignmentOutcome,
    GrantMembership,
    InviteMember,
    PersonRef,
    RoleAssignmentService,
    SetMemberships,
    SetPermissionSets,
    WorkspaceRoles,
)
from dw_platform.application.tenant_members import TenantMember, TenantMembersService

router = APIRouter(prefix="/admin/members", tags=["admin"])
invitations_router = APIRouter(prefix="/admin/invitations", tags=["admin"])

# The writes honour `Idempotency-Key` (optional; see README), each checking the
# `action` its service checks first (app-standards R2.21), under a fixed
# operation name its effect key carries.
GrantIdempotency = Annotated[
    IdempotentOperation, idempotent(MEMBERS_WRITE, operation="POST /admin/members")
]
RevokeIdempotency = Annotated[
    IdempotentOperation, idempotent(MEMBERS_WRITE, operation="DELETE /admin/members/{user_id}")
]
SetMembershipsIdempotency = Annotated[
    IdempotentOperation,
    idempotent(MEMBERS_WRITE, operation="PUT /admin/members/{user_id}/memberships"),
]
PermissionSetsIdempotency = Annotated[
    IdempotentOperation,
    idempotent(MEMBERS_WRITE, operation="PUT /admin/members/{user_id}/permission-sets"),
]
InviteIdempotency = Annotated[
    IdempotentOperation, idempotent(MEMBERS_WRITE, operation="POST /admin/invitations")
]


class GrantMemberRequest(BaseModel):
    email: str
    workspace_id: UUID
    role_keys: list[str] = Field(min_length=1)
    department: str = "general"


class AppliedRevokeView(BaseModel):
    """A role removed by the request, applied at once (R7.6)."""

    workspace_id: UUID
    role_key: str


class MemberRefView(BaseModel):
    user_id: UUID
    email: str | None
    display_name: str
    # The roles the request asked for, each waiting for a second person.
    proposals: list[UUID] = []


class MemberWorkspaceView(BaseModel):
    workspace_id: UUID
    workspace_name: str
    role_keys: list[str]


class TenantMemberView(BaseModel):
    user_id: UUID
    display_name: str
    email: str | None
    # `invited` until the person's first sign-in, then `active`.
    status: str
    memberships: list[MemberWorkspaceView]


class MemberMembershipsView(BaseModel):
    """A person's memberships in this tenant after a change; empty when none is
    left. `applied` are the roles removed; `proposals` the roles added, each
    waiting for a second person (202)."""

    user_id: UUID
    memberships: list[MemberWorkspaceView]
    applied: list[AppliedRevokeView] = []
    proposals: list[UUID] = []


class WorkspaceRolesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    role_keys: list[str]


class SetMembershipsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memberships: list[WorkspaceRolesBody]


class InviteMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=4, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    memberships: list[WorkspaceRolesBody] = Field(min_length=1)


class SetPermissionSetsBody(BaseModel):
    permission_set_keys: list[str]


class PermissionSetsChangeView(BaseModel):
    user_id: UUID
    applied: list[AppliedRevokeView]
    proposals: list[UUID]


def _members(container: ApiContainer) -> TenantMembersService:
    if container.tenant_members is None:
        raise InfrastructureError("database is not configured")
    return container.tenant_members


def _assignments(container: ApiContainer) -> RoleAssignmentService:
    if container.role_assignments is None:
        raise InfrastructureError("database is not configured")
    return container.role_assignments


def _member_view(member: TenantMember) -> TenantMemberView:
    return TenantMemberView(
        user_id=member.user_id,
        display_name=member.display_name,
        email=member.email,
        status=member.status,
        memberships=[
            MemberWorkspaceView(
                workspace_id=m.workspace_id,
                workspace_name=m.workspace_name,
                role_keys=list(m.role_keys),
            )
            for m in member.memberships
        ],
    )


def _rows(body: list[WorkspaceRolesBody]) -> tuple[WorkspaceRoles, ...]:
    return tuple(
        WorkspaceRoles(workspace_id=row.workspace_id, role_keys=frozenset(row.role_keys))
        for row in body
    )


def _applied(outcome: AssignmentOutcome) -> list[AppliedRevokeView]:
    return [
        AppliedRevokeView(workspace_id=r.workspace_id, role_key=r.role_key) for r in outcome.applied
    ]


async def _ref_view(work: Awaitable[tuple[PersonRef, AssignmentOutcome]]) -> MemberRefView:
    person, outcome = await work
    return MemberRefView(
        user_id=person.user_id,
        email=person.email,
        display_name=person.display_name,
        proposals=list(outcome.proposals),
    )


async def _member_ref(
    container: ApiContainer, context: AccessContext, user_id: UUID
) -> MemberRefView:
    """A retried placement or invitation, read back as `GET /admin/members`
    shows the person to this caller now, with their role proposals still
    waiting: absent when they are no longer there (app-standards R2.29)."""
    for member in await _members(container).list_members(context):
        if member.user_id == user_id:
            return MemberRefView(
                user_id=member.user_id,
                email=member.email,
                display_name=member.display_name,
                proposals=await _assignments(container).open_grants(context, user_id),
            )
    # Nothing of the effect: the answer of an id that does not exist.
    raise NotFoundError("no such member in this tenant")


async def _no_content(_: str) -> None:
    return None


def _status(view: Any, created: int) -> int:
    return 202 if view.proposals else created


@router.post(
    "",
    response_model=MemberRefView,
    status_code=202,
    responses={201: {"model": MemberRefView, "description": "Placed; no role to propose."}},
)
async def grant_member(
    body: GrantMemberRequest,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: GrantIdempotency,
) -> MemberRefView:
    """Place someone who has signed in in one workspace; the membership is
    written now, each role is a proposal (202)."""
    service = _assignments(container)
    command = GrantMembership(
        email=body.email,
        workspace_id=body.workspace_id,
        role_keys=frozenset(body.role_keys),
        department=body.department,
    )

    async def run(effect: PendingEffect | None) -> MemberRefView:
        return await _ref_view(service.grant_member(context, command, effect=effect))

    view = await idempotency.once(
        status=202, run=run, reread=lambda user_id: _member_ref(container, context, UUID(user_id))
    )
    response.status_code = _status(view, 201)
    return await idempotency.record(view, status_code=response.status_code)


@router.delete("/{user_id}", status_code=204)
async def revoke_member(
    user_id: UUID,
    workspace_id: UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: RevokeIdempotency,
) -> None:
    revoke = container.revoke_membership
    if revoke is None:
        raise InfrastructureError("database is not configured")
    command = RevokeMembership(user_id=user_id, workspace_id=workspace_id)
    # A 204 is answered as a 204 without a read (R2.29).
    await idempotency.once(
        status=204,
        run=lambda effect: revoke.handle(context, command, effect=effect),
        reread=_no_content,
    )
    await idempotency.record_no_content()


@router.get("", response_model=list[TenantMemberView])
async def list_members(
    context: RequireAccessContext, container: RequireContainer
) -> list[TenantMemberView]:
    """Everyone in the caller's tenant, by name (Vietnamese collation), with
    the roles assigned to them in each workspace."""
    return [_member_view(m) for m in await _members(container).list_members(context)]


@router.put(
    "/{user_id}/memberships",
    response_model=MemberMembershipsView,
    responses={202: {"model": MemberMembershipsView, "description": "Roles proposed."}},
)
async def set_memberships(
    user_id: UUID,
    body: SetMembershipsRequest,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: SetMembershipsIdempotency,
) -> MemberMembershipsView:
    """Replace the person's roles, workspace by workspace. Each workspace in
    the body is a membership the person has afterwards, its `role_keys` every
    role on it: `[]` is a membership with no role (one without a membership
    gets one; one with roles keeps the membership, its roles removed). A
    workspace left out goes, with every role and permission set on it. A role
    the body drops is removed now (200); a role it adds is a proposal (202),
    refused 409 `no_checker_available` when nobody but the caller and the
    person placed could confirm it. Nobody places themself in a new workspace
    (403 `rbac_self_assignment`). Permission sets stay
    (`PUT .../permission-sets`)."""
    service = _assignments(container)
    command = SetMemberships(user_id=user_id, memberships=_rows(body.memberships))

    async def view_now(outcome: AssignmentOutcome | None) -> MemberMembershipsView:
        now = [m for m in await _members(container).list_members(context) if m.user_id == user_id]
        return MemberMembershipsView(
            user_id=user_id,
            memberships=_member_view(now[0]).memberships if now else [],
            applied=_applied(outcome) if outcome else [],
            proposals=(
                list(outcome.proposals) if outcome else await service.open_grants(context, user_id)
            ),
        )

    async def run(effect: PendingEffect | None) -> MemberMembershipsView:
        return await view_now(await service.set_memberships(context, command, effect=effect))

    view = await idempotency.once(status=200, run=run, reread=lambda _id: view_now(None))
    response.status_code = _status(view, 200)
    return await idempotency.record(view, status_code=response.status_code)


@router.put(
    "/{user_id}/permission-sets",
    response_model=PermissionSetsChangeView,
    responses={202: {"model": PermissionSetsChangeView, "description": "Sets proposed."}},
)
async def set_permission_sets(
    user_id: UUID,
    payload: SetPermissionSetsBody,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: PermissionSetsIdempotency,
) -> PermissionSetsChangeView:
    """Replace a member's permission sets in the caller's workspace: a set
    removed now (200), a set added a proposal (202)."""
    service = _assignments(container)
    command = SetPermissionSets(
        user_id=user_id, permission_set_keys=frozenset(payload.permission_set_keys)
    )

    async def run(effect: PendingEffect | None) -> PermissionSetsChangeView:
        outcome = await service.set_permission_sets(context, command, effect=effect)
        return PermissionSetsChangeView(
            user_id=user_id, applied=_applied(outcome), proposals=list(outcome.proposals)
        )

    async def reread(_id: str) -> PermissionSetsChangeView:
        return PermissionSetsChangeView(
            user_id=user_id, applied=[], proposals=await service.open_grants(context, user_id)
        )

    view = await idempotency.once(status=200, run=run, reread=reread)
    response.status_code = _status(view, 200)
    return await idempotency.record(view, status_code=response.status_code)


@invitations_router.post("", response_model=MemberRefView, status_code=202)
async def invite_member(
    body: InviteMemberRequest,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: InviteIdempotency,
) -> MemberRefView:
    """Create the person (no sign-in yet) and their memberships now; every role
    of the invitation, `member` included, is a proposal (202, R7.1). No email
    is sent: the admin tells the person, who then signs in with that email."""
    service = _assignments(container)
    command = InviteMember(
        display_name=body.display_name, email=body.email, memberships=_rows(body.memberships)
    )

    async def run(effect: PendingEffect | None) -> MemberRefView:
        return await _ref_view(service.invite(context, command, effect=effect))

    view = await idempotency.once(
        status=202, run=run, reread=lambda user_id: _member_ref(container, context, UUID(user_id))
    )
    return await idempotency.record(view, status_code=202)
