"""`GET /api/v1/studio/node-types`: the step-type catalogue (workflow-nodes
R1.1, R1.2).

Mounted inside the Studio group (`dw_api.main.mount_studio`). The caller
holds `studio.workflows.edit` in its working workspace, or the answer is 403:
the catalogue is what a workflow author builds from. No parameter and no 404:
an unregistered type is the submit validator's `wf.unknown_type`. The answer
is never cached by anyone (`private, no-store`): what a caller may use joins
it per caller with the first type that declares a limit or a lock.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_studio.kinds import WORKFLOWS_EDIT_SCOPE
from dw_studio.workflows.presentation.node_types import (
    NodeTypeCatalogueView,
    node_type_catalogue,
)

router = APIRouter(prefix="/node-types")


@router.get("", response_model=NodeTypeCatalogueView)
async def list_node_types(
    context: RequireStudioAccess, container: RequireContainer, response: Response
) -> NodeTypeCatalogueView:
    await container.authorization.require(
        context=context, action=WORKFLOWS_EDIT_SCOPE, resource_type="node_type"
    )
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    response.headers["Cache-Control"] = "private, no-store"
    return node_type_catalogue(container.studio.node_types)
