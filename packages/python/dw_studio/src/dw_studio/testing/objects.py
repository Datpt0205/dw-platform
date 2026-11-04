"""Object documents and object managers for the tests of custom objects
(custom-objects ticket 02).

`object_document` and `object_field` build a valid `dw.object/v1` with
Vietnamese labels; `plant_manager` plants a member holding
`studio.objects.manage` at tenant depth, the only depth the key takes;
`running_kinds` is what `build_studio` registers without `kinds=`, with a
tool register that knows no tool.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from dw_agent_runtime.wflite.registry import build_node_registry
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
)
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.kinds import OBJECTS_MANAGE_SCOPE, platform_kinds
from dw_studio.records.adapters.definition_store import object_store_of
from dw_studio.testing.workflows import NoTools
from dw_studio.testing.world import Person
from dw_studio.workflows.adapters.triggers import NoTriggerSubscriptions


def object_field(api_name: str, type_: str = "text", **over: Any) -> dict[str, Any]:
    field: dict[str, Any] = {
        "api_name": api_name,
        "labels": {"vi": f"Trường {api_name}"},
        "type": type_,
        "pd_category": "none",
    }
    if type_ == "number":
        field["number_mode"] = "exact"
    if type_ == "currency":
        field["currency_code"] = "VND"
    if type_ == "picklist":
        field["options"] = [
            {"key": "moi", "labels": {"vi": "Mới"}, "position": 0},
            {"key": "da_lien_he", "labels": {"vi": "Đã liên hệ"}, "position": 1},
        ]
    field.update(over)
    return field


def object_document(*fields: dict[str, Any], **over: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "labels": {"vi": "Khách hàng tiềm năng"},
        "name_field": {"labels": {"vi": "Họ tên"}, "pd_category": "basic"},
        "fields": list(fields),
    }
    document.update(over)
    return document


async def plant_manager(
    conn: AsyncConnection, tenant: PlantedTenant, workspace: uuid.UUID | None = None
) -> Person:
    """A member of `workspace` (the tenant's main one) holding the object key."""
    workspace = workspace or tenant.main
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, workspace, user)
    role = await plant_role(
        conn, tenant.tenant_id, f"objects_{user.hex[:12]}", {OBJECTS_MANAGE_SCOPE: "tenant"}
    )
    await assign(conn, tenant.tenant_id, workspace, membership, role)
    return Person(user, tenant.tenant_id, workspace)


def running_kinds() -> tuple[ArtifactKindEntry, ...]:
    return platform_kinds(
        object_store_of,
        clock=SystemClock(),
        ids=Uuid7Generator(),
        nodes=build_node_registry(),
        tools=NoTools(),
        triggers=NoTriggerSubscriptions(),
    )
