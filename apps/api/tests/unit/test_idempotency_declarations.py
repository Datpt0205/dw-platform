"""Every route that honours `Idempotency-Key` declares the check its service makes.

app-standards R2.18, R2.21 and R2.28 (APS19, APS30), asked of the built app and
of the route modules' source, not of a list kept beside them:

* an operation with the header and no declaration is named (R2.18);
* a declaration is the service's own constant or check function, never a string
  written a second time (R2.21). Read from the source, not compared with `is`:
  CPython interns a literal that looks like an identifier, so `is` tells a copy
  from the constant only while the action has a dot in it (measured
  28/10/2026: `"platform.members.write"` is not interned across modules);
* a route hidden from the schema is on a frozen list with its reason, because
  the walks above read `app.openapi()` and cannot see it (R2.28).
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Header
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import Mount

from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_api.dependencies.idempotency import IDEMPOTENCY_HEADER
from dw_api.routes.v1 import admin_roles as role_routes
from dw_api.routes.v1 import admin_service_principals as service_principal_routes
from dw_api.routes.v1 import connections as connection_routes
from dw_api.routes.v1 import digital_workers as digital_workers_routes
from dw_api.routes.v1 import studio_artifacts as studio_routes
from dw_api.routes.v1 import studio_bindings as bindings_routes
from dw_api.routes.v1 import studio_kill as kill_routes
from dw_api.routes.v1 import studio_lifecycle as lifecycle_routes
from dw_api.routes.v1 import studio_records as records_routes
from dw_api.routes.v1 import work_items as work_items_routes
from dw_platform.application import (
    control_switches,
    digital_workers,
    membership_admin,
    role_admin,
    support_access,
)
from dw_platform.application.connection_admin import ConnectionService
from dw_platform.application.service_principals import ServicePrincipalService
from dw_studio.core.application.service import ArtifactService
from dw_studio.lifecycle.application.kill import KILL_SEGMENTS, KillSwitchService
from dw_studio.lifecycle.application.service import SUBMIT_SEGMENTS, LifecycleService
from dw_studio.records.application.record_service import RecordService

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Route:
    path: str
    route: APIRoute
    in_schema: bool


ROUTES = Path(__file__).resolve().parents[2] / "src" / "dw_api" / "routes" / "v1"
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))

# The operations that take a key today (README, "Idempotent requests"), each
# with what its service checks. A DW's state and people are checked against
# the DW the path names, so their route declares a function that calls the
# service's own `require_owner` (R2.30), held to that below; so is a change of
# its earned level, whose service then tells a raise (BO) from a lowering.
DECLARED: dict[tuple[str, str], object] = {
    ("POST", "/api/v1/admin/members"): membership_admin.MEMBERS_WRITE,
    ("DELETE", "/api/v1/admin/members/{user_id}"): membership_admin.MEMBERS_WRITE,
    ("PUT", "/api/v1/admin/members/{user_id}/memberships"): membership_admin.MEMBERS_WRITE,
    ("PUT", "/api/v1/admin/members/{user_id}/permission-sets"): membership_admin.MEMBERS_WRITE,
    ("POST", "/api/v1/admin/invitations"): membership_admin.MEMBERS_WRITE,
    # A company's roles: the write key; a proposal's confirmation and withdrawal
    # are checked against the proposal the path names (tenant-rbac R8.2, R7.1).
    ("POST", "/api/v1/admin/roles"): role_admin.ROLES_WRITE,
    ("PATCH", "/api/v1/admin/roles/{role_id}"): role_admin.ROLES_WRITE,
    ("PUT", "/api/v1/admin/roles/{role_id}/permissions"): role_admin.ROLES_WRITE,
    ("DELETE", "/api/v1/admin/roles/{role_id}"): role_admin.ROLES_WRITE,
    ("POST", "/api/v1/admin/role-changes/{request_id}/confirm"): role_routes._may_confirm,
    ("POST", "/api/v1/admin/role-changes/{request_id}/withdraw"): role_routes._may_withdraw,
    # A tenant-depth key (agent-lifecycle R7.10).
    ("POST", "/api/v1/admin/freeze"): control_switches.LIFECYCLE_FREEZE,
    ("POST", "/api/v1/admin/unfreeze"): control_switches.LIFECYCLE_FREEZE,
    ("POST", "/api/v1/support/grants"): support_access.check_request,
    ("POST", "/api/v1/support/grants/{grant_id}/approve"): support_access.check_approve,
    ("POST", "/api/v1/support/grants/{grant_id}/reject"): support_access.check_close,
    ("POST", "/api/v1/support/grants/{grant_id}/revoke"): support_access.check_close,
    ("POST", "/api/v1/digital-workers"): digital_workers.DW_MANAGE,
    (
        "POST",
        "/api/v1/digital-workers/{dw_id}/state",
    ): digital_workers_routes._owner_of_path,
    (
        "PUT",
        "/api/v1/digital-workers/{dw_id}/people",
    ): digital_workers_routes._owner_of_path,
    (
        "POST",
        "/api/v1/digital-workers/{dw_id}/decision-classes/{key}/autonomy",
    ): digital_workers_routes._owner_of_path,
    (
        "PUT",
        "/api/v1/digital-workers/{dw_id}/workflow-draft",
    ): digital_workers_routes._owner_of_path,
    (
        "POST",
        "/api/v1/digital-workers/{dw_id}/workflow-draft/simulate",
    ): digital_workers_routes._owner_of_path,
    (
        "POST",
        "/api/v1/digital-workers/{dw_id}/workflow-draft/submit",
    ): digital_workers_routes._owner_of_path,
    (
        "POST",
        "/api/v1/digital-workers/{dw_id}/workflow-draft/withdraw",
    ): digital_workers_routes._owner_of_path,
    (
        "POST",
        "/api/v1/work-items/{item_id}/complete",
    ): work_items_routes._holder_of_path,
    (
        "POST",
        "/api/v1/digital-workers/{dw_id}/work-items",
    ): work_items_routes._assigner_of_path,
    # The kind's write key, at the acting workspace or the artifact's
    # (tenant-config R2.1, R2.21; ADR-0108 decision 4).
    ("POST", "/api/v1/studio/artifacts"): studio_routes._may_create,
    ("POST", "/api/v1/studio/artifacts/{artifact_id}/draft"): studio_routes._may_write,
    # The propose key at the artifact's owning workspace, after its read key;
    # the proposer alone withdraws (tenant-config R8.2, R8.14, R8.17).
    (
        "POST",
        "/api/v1/studio/artifacts/{artifact_id}/bindings/proposals",
    ): bindings_routes._may_propose,
    (
        "POST",
        "/api/v1/studio/artifacts/{artifact_id}/bindings/proposals/{config_version_id}/withdraw",
    ): bindings_routes._may_withdraw,
    # The stored kind's submit key, or the retire key, at the artifact's owning
    # workspace, one segment per kind (agent-lifecycle R2.1, R2.4, R2.5).
    **{
        ("POST", f"/api/v1/studio/{segment}/{{artifact_id}}/versions/{{version_id}}/{action}"): (
            lifecycle_routes._may_retire if action == "retire" else lifecycle_routes._may_submit
        )
        for segment in SUBMIT_SEGMENTS
        for action in ("submit", "withdraw", "retire")
    },
    # `studio.lifecycle.kill` at the component's owning workspace, after its
    # read key, one segment per kind a switch kills (agent-lifecycle R8.1, R8.6).
    **{
        ("POST", f"/api/v1/studio/{segment}/{{artifact_id}}/{action}"): kill_routes._may_kill
        for segment in KILL_SEGMENTS
        for action in ("kill", "revive-requests")
    },
    # The object, then `obj.<api_name>.create`, RecordService's own check
    # (custom-objects ticket 03).
    ("POST", "/api/v1/studio/objects/{api_name}/records"): records_routes._may_create,
    ("POST", "/api/v1/studio/objects/{api_name}/records/upsert"): records_routes._may_create,
    # The owning workspace is the company's, then `.manage` reaches it
    # (org-and-principals R6.1).
    ("POST", "/api/v1/admin/service-principals"): service_principal_routes._may_create,
    # `connections.manage` at the working workspace, or reaching the
    # connection's own (connections-and-vault R5.18).
    ("POST", "/api/v1/connections"): connection_routes._may_create,
    ("PATCH", "/api/v1/connections/{connection_id}"): connection_routes._may_write,
    ("POST", "/api/v1/connections/{connection_id}/disable"): connection_routes._may_write,
    ("POST", "/api/v1/connections/{connection_id}/enable"): connection_routes._may_write,
    (
        "POST",
        "/api/v1/connections/{connection_id}/revoke-credentials",
    ): connection_routes._may_write,
}
DECIDE = ("POST", "/api/v1/approvals/{approval_id}/decisions")

# Routes outside the schema, each with why. Frozen: a new one is a decision.
HIDDEN: dict[tuple[str, str], str] = {
    ("GET", "/metrics"): "Prometheus scrape, not part of the published API",
    ("POST", "/api/v1/zalo/webhook"): "the channel provider's callback, verified by its own secret",
}

# The route modules whose `idempotent(...)` declarations are read, and the
# modules a declared name may come from: the services those routes call.
SERVICE_MODULES = {
    "dw_platform.application.digital_workers",
    "dw_platform.application.work_queue",
    "dw_platform.application.membership_admin",
    "dw_platform.application.role_admin",
    "dw_platform.application.support_access",
    "dw_platform.application.control_switches",
}


def app() -> FastAPI:
    from generate_contracts import build_app  # type: ignore[import-not-found]

    built: FastAPI = build_app()
    return built


def api_routes(routes: list[Any], prefix: str = "", visible: bool = True) -> Iterator[Route]:
    """Every API route with its full path and whether the schema shows it,
    through included routers: FastAPI 0.141 keeps an included router nested
    (`_IncludedRouter`) rather than copying its routes onto the app."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield Route(prefix + route.path, route, visible and route.include_in_schema)
        elif isinstance(route, Mount):
            yield from api_routes(list(route.routes), prefix + route.path, visible)
        elif hasattr(route, "original_router") and hasattr(route, "include_context"):
            context = route.include_context
            yield from api_routes(
                list(route.original_router.routes),
                prefix + (context.prefix or ""),
                visible and context.include_in_schema,
            )


def declared_check(dependant: Dependant) -> object | None:
    for sub in dependant.dependencies:
        if sub.call is not None and hasattr(sub.call, "idempotency_check"):
            return sub.call.idempotency_check  # type: ignore[union-attr]
        found = declared_check(sub)
        if found is not None:
            return found
    return None


def keyed_operations(built: FastAPI) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in built.openapi()["paths"].items()
        for method, op in item.items()
        if any(
            p.get("in") == "header" and p.get("name") == IDEMPOTENCY_HEADER
            for p in op.get("parameters", [])
        )
    }


def undeclared(built: FastAPI) -> list[str]:
    """Each operation with the header whose route declares no check."""
    keyed = keyed_operations(built)
    missing = []
    for found in api_routes(list(built.routes)):
        for method in found.route.methods:
            if (method, found.path) in keyed and declared_check(found.route.dependant) is None:
                missing.append(f"{method} {found.path}")
    return sorted(missing)


def hidden_routes(built: FastAPI) -> set[tuple[str, str]]:
    return {
        (method, found.path)
        for found in api_routes(list(built.routes))
        if not found.in_schema
        for method in found.route.methods
    }


def test_every_operation_with_the_header_declares_its_check() -> None:
    built = app()

    assert keyed_operations(built) == set(DECLARED) | {DECIDE}
    assert undeclared(built) == []


def test_a_route_reading_the_header_without_a_declaration_is_named() -> None:
    built = app()

    @built.post("/api/v1/probe/undeclared")
    async def undeclared_probe(
        key: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
    ) -> None:
        return None

    built.openapi_schema = None
    assert undeclared(built) == ["POST /api/v1/probe/undeclared"]


def test_each_declaration_is_the_check_its_service_makes() -> None:
    """The declared object is the service's own, compared by identity; the
    source test below is what tells a look-alike string from it."""
    built = app()
    checks = {
        (method, found.path): declared_check(found.route.dependant)
        for found in api_routes(list(built.routes))
        for method in found.route.methods
    }

    for operation, expected in DECLARED.items():
        assert checks[operation] is expected, operation
    decide = checks[DECIDE]
    assert callable(decide) and "authorize_decision" in ast.dump(ast.parse(_source_of(decide))), (
        "decisions must call the service's own check (R2.30)"
    )
    assert hasattr(ApproveAndResumeService, "authorize_decision")
    owner = ast.dump(ast.parse(_source_of(digital_workers_routes._owner_of_path)))
    assert "require_owner" in owner, "a DW write must call the service's own owner check"
    assert hasattr(digital_workers.DigitalWorkerService, "require_owner")
    for check, service_check in (
        (work_items_routes._holder_of_path, "require_holder"),
        (work_items_routes._assigner_of_path, "require_work_assigner"),
    ):
        assert service_check in ast.dump(ast.parse(_source_of(check))), service_check
    for check, service_check in (
        (studio_routes._may_create, "check_create"),
        (studio_routes._may_write, "check_write"),
    ):
        assert service_check in ast.dump(ast.parse(_source_of(check))), service_check
        assert hasattr(ArtifactService, service_check)
    assert "require" in ast.dump(ast.parse(_source_of(records_routes._may_create)))
    assert hasattr(RecordService, "require")
    for check in (lifecycle_routes._may_submit, lifecycle_routes._may_retire):
        assert "check" in ast.dump(ast.parse(_source_of(check)))
        assert hasattr(LifecycleService, "check")
    assert "check" in ast.dump(ast.parse(_source_of(kill_routes._may_kill)))
    assert hasattr(KillSwitchService, "check")
    for check, service_check in (
        (connection_routes._may_create, "check_create"),
        (connection_routes._may_write, "check_write"),
    ):
        assert service_check in ast.dump(ast.parse(_source_of(check))), service_check
        assert hasattr(ConnectionService, service_check)
    for check, service_check in (
        (role_routes._may_confirm, "require_may_confirm"),
        (role_routes._may_withdraw, "require_may_withdraw"),
    ):
        assert service_check in ast.dump(ast.parse(_source_of(check))), service_check
        assert hasattr(role_admin.RoleAdminService, service_check)
    create = ast.dump(ast.parse(_source_of(service_principal_routes._may_create)))
    assert "require_manage" in create, "a service account's create calls the service's check"
    assert hasattr(ServicePrincipalService, "require_manage")


def _source_of(function: object) -> str:
    import inspect
    import textwrap

    return textwrap.dedent(inspect.getsource(function))  # type: ignore[arg-type]


def literal_declarations(source: str) -> list[str]:
    """Each `idempotent(...)` whose check is not a name from a service module
    or a function of this module: a string, an f-string, an attribute of
    something else."""
    tree = ast.parse(source)
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in SERVICE_MODULES
        for alias in node.names
    }
    local = {
        node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    bad = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "idempotent"
            and node.args
        ):
            check = node.args[0]
            if not (isinstance(check, ast.Name) and (check.id in imported or check.id in local)):
                bad.append(ast.unparse(check))
    return bad


def test_no_route_module_writes_a_check_a_second_time() -> None:
    for module in ("admin_members.py", "admin_roles.py", "approvals.py", "support.py"):
        assert literal_declarations((ROUTES / module).read_text(encoding="utf-8")) == [], module


def test_a_string_equal_to_the_constant_is_still_named() -> None:
    planted = (
        "from dw_platform.application.membership_admin import MEMBERS_WRITE\n"
        'a = idempotent("platform.members.write", operation="POST /x")\n'
        "b = idempotent(MEMBERS_WRITE, operation='POST /y')\n"
    )
    assert literal_declarations(planted) == ["'platform.members.write'"]


def test_the_support_request_check_takes_either_side_and_refuses_neither() -> None:
    """R2.21: `POST /support/grants` grants with `support.grant` and requests
    with `support.request`; the flag first (R2.42)."""
    import uuid

    from dw_kernel.errors import PermissionDeniedError
    from dw_platform.application.access_context import AccessContext

    def context(*scopes: str, flagged: bool = True) -> AccessContext:
        return AccessContext(
            tenant_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            principal_id=uuid.uuid4(),
            roles=frozenset(),
            scopes=frozenset(scopes),
            plan_id="professional",
            feature_flags=frozenset({support_access.SUPPORT_ACCESS_FEATURE} if flagged else ()),
        )

    support_access.check_request(context(support_access.SUPPORT_GRANT_SCOPE))
    support_access.check_request(context(support_access.SUPPORT_REQUEST_SCOPE))
    for refused in (context(), context(support_access.SUPPORT_GRANT_SCOPE, flagged=False)):
        with pytest.raises(PermissionDeniedError):
            support_access.check_request(refused)
    support_access.check_close(context(support_access.SUPPORT_GRANT_SCOPE, flagged=False))


def test_only_the_frozen_routes_are_hidden_from_the_schema() -> None:
    # The webhook mounts only with a channel secret configured; neither may be
    # anything but these two.
    assert hidden_routes(app()) <= set(HIDDEN)
    assert all(reason.strip() for reason in HIDDEN.values())


def test_a_route_hidden_from_the_schema_is_named() -> None:
    built = app()

    @built.post("/api/v1/probe/hidden", include_in_schema=False)
    async def hidden_probe() -> None:
        return None

    assert hidden_routes(built) - set(HIDDEN) == {("POST", "/api/v1/probe/hidden")}
