import uuid

import pytest

from dw_kernel.errors import EntitlementDeniedError, PermissionDeniedError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import PlanEntitlementService

pytestmark = pytest.mark.unit


def make_context(**overrides: object) -> AccessContext:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "principal_id": uuid.uuid4(),
        "roles": frozenset({"member"}),
        "scopes": frozenset({"demo.read"}),
        "plan_id": "basic",
    }
    defaults.update(overrides)
    return AccessContext(**defaults)


async def test_scope_allows_action() -> None:
    service = ScopeAuthorizationService()
    await service.require(context=make_context(), action="demo.read", resource_type="meeting")


async def test_missing_scope_denied_with_details() -> None:
    service = ScopeAuthorizationService()
    with pytest.raises(PermissionDeniedError) as excinfo:
        await service.require(
            context=make_context(),
            action="demo.write",
            resource_type="meeting",
            resource_id="m-1",
        )
    assert excinfo.value.details["action"] == "demo.write"


async def test_platform_admin_bypasses_scopes() -> None:
    service = ScopeAuthorizationService()
    admin = make_context(roles=frozenset({"platform_admin"}), scopes=frozenset())
    await service.require(context=admin, action="anything.at_all", resource_type="any")


async def test_a_feature_is_the_one_the_access_context_carries() -> None:
    """The plan's features reach the context from `platform.plans.features`
    with the tenant's overrides; the service reads nothing else (ticket 01)."""
    service = PlanEntitlementService()
    basic = make_context(plan_id="basic", feature_flags=frozenset({"knowledge_search"}))
    await service.require_feature(basic, "knowledge_search")
    with pytest.raises(EntitlementDeniedError):
        await service.require_feature(basic, "audit_export")

    with_override = make_context(
        plan_id="basic", feature_flags=frozenset({"knowledge_search", "audit_export"})
    )
    await service.require_feature(with_override, "audit_export")


async def test_a_context_carrying_no_feature_is_denied_on_any_plan() -> None:
    service = PlanEntitlementService()
    with pytest.raises(EntitlementDeniedError):
        await service.require_feature(make_context(plan_id="enterprise"), "knowledge_search")
