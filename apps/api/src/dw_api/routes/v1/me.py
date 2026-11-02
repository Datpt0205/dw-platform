"""GET /api/v1/me — the caller's verified access context (safe fields only).

The web's one source for what the caller may do in the workspace it works in
(tenant-rbac R2.6): `scopes` is the projection of `grants` for this workspace,
both read from `platform.effective_grants`; `platform_bypass` says the W1
`platform_admin` bypass applies (G2), so the web never re-derives it from a
role key.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_platform.application.authorization import PLATFORM_ADMIN_ROLE


class GrantView(BaseModel):
    key: str
    depth: str
    anchor_workspace_id: UUID


class MeResponse(BaseModel):
    tenant_id: UUID
    workspace_id: UUID
    principal_id: UUID
    roles: list[str]
    scopes: list[str]
    grants: list[GrantView]
    access_version: int | None
    platform_bypass: bool
    clearance: str
    plan_id: str
    feature_flags: list[str]


router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeResponse)
async def me(context: RequireAccessContext) -> MeResponse:
    return MeResponse(
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
        roles=sorted(context.roles),
        scopes=sorted(context.scopes),
        grants=[
            GrantView(key=g.key, depth=g.depth, anchor_workspace_id=g.anchor_workspace_id)
            for g in context.grants
        ],
        access_version=context.access_version,
        platform_bypass=PLATFORM_ADMIN_ROLE in context.roles,
        clearance=context.clearance,
        plan_id=context.plan_id,
        feature_flags=sorted(context.feature_flags),
    )
