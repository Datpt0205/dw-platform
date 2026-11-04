"""R3.16 (RB42), G2: the `platform_admin` bypass does not open a route of role
administration or role assignment (tenant-rbac ticket 03, step 10; Q-h7).

`ROLE_ROUTES_WITHOUT_BYPASS` is declared once, beside the routers. Here it is
held to the routers the app really mounts: every route under
`/api/v1/admin/roles`, `/role-templates`, `/role-changes`, `/invitations`, and
the three member routes that assign roles, nothing more and nothing less; a
role route added without its entry turns this red. `without_platform_bypass`
strips `platform_admin` on exactly those routes, and through a real request
the route template it reads is the full one of an included router.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, FastAPI
from fastapi.routing import iter_route_contexts
from starlette.requests import Request
from starlette.routing import BaseRoute
from test_support_endpoint import ENABLED, GRANTER, SECRET, TENANT, WORKSPACE, _container

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext, without_platform_bypass
from dw_api.main import create_app
from dw_api.routes.v1.admin_roles import ROLE_ROUTES_WITHOUT_BYPASS
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import PLATFORM_ADMIN_ROLE
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess

pytestmark = pytest.mark.unit

_ADMIN = "/api/v1/admin"
_PREFIXES = (
    f"{_ADMIN}/roles",
    f"{_ADMIN}/role-templates",
    f"{_ADMIN}/role-changes",
    f"{_ADMIN}/invitations",
)
# The member routes that assign roles (step 6); the rest of `/admin/members`
# (the list, `DELETE /{user_id}`) stays under G2.
_MEMBER_ROUTES = frozenset(
    {
        ("PUT", f"{_ADMIN}/members/{{user_id}}/memberships"),
        ("PUT", f"{_ADMIN}/members/{{user_id}}/permission-sets"),
        ("POST", f"{_ADMIN}/members"),
    }
)


def _endpoints(app: FastAPI) -> Iterator[tuple[str, str, BaseRoute]]:
    """(method, full path, route) of every endpoint, included routers walked
    into. The route is the object Starlette puts in `scope["route"]` when it
    serves a request: inside a router included under `/api/v1` its own `path`
    lacks that prefix (FastAPI 0.141), which is what a request-level test sees."""
    for context in iter_route_contexts(app.routes):
        if getattr(context, "dependant", None) is None:
            continue
        for method in context.methods or ():
            yield method, str(context.path), context.original_route


def _routes(app: FastAPI) -> Iterator[tuple[str, str]]:
    for method, path, _ in _endpoints(app):
        yield method, path


def role_routes(app: FastAPI) -> set[tuple[str, str]]:
    """The routes the ticket says the bypass must not open, read off the app."""
    return {
        (method, path)
        for method, path in _routes(app)
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in _PREFIXES)
        or (method, path) in _MEMBER_ROUTES
    }


def _app() -> FastAPI:
    return create_app(_container(GRANTER, ENABLED))


def test_the_list_is_every_role_route_the_app_mounts() -> None:
    assert role_routes(_app()) == set(ROLE_ROUTES_WITHOUT_BYPASS)


def test_the_walker_finds_the_routes_it_compares() -> None:
    # A floor under the comparison: an empty walk could not equal the list.
    found = role_routes(_app())
    assert ("POST", f"{_ADMIN}/role-changes/{{request_id}}/confirm") in found
    assert ("PUT", f"{_ADMIN}/members/{{user_id}}/memberships") in found
    assert ("GET", f"{_ADMIN}/members") not in found


def test_a_role_route_added_without_its_entry_turns_the_comparison_red() -> None:
    app = _app()
    extra = APIRouter(prefix="/admin/roles")

    @extra.post("/{role_id}/restore")
    async def restore(role_id: uuid.UUID, context: RequireAccessContext) -> None: ...

    app.include_router(extra, prefix="/api/v1")
    missing = role_routes(app) - set(ROLE_ROUTES_WITHOUT_BYPASS)
    assert missing == {("POST", f"{_ADMIN}/roles/{{role_id}}/restore")}


def _admin_context() -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=uuid.uuid4(),
        roles=frozenset({PLATFORM_ADMIN_ROLE, "org_admin"}),
        plan_id="professional",
    )


def _request(app: FastAPI, method: str, route: BaseRoute) -> Request:
    """The request scope as Starlette builds it for ``route``."""
    return Request({"type": "http", "app": app, "method": method, "headers": [], "route": route})


def _roles_on(app: FastAPI, method: str, path: str) -> frozenset[str]:
    container: ApiContainer = app.state.container
    [route] = [r for m, p, r in _endpoints(app) if (m, p) == (method, path)]
    return without_platform_bypass(_request(app, method, route), container, _admin_context()).roles


def test_the_bypass_is_stripped_on_exactly_the_listed_routes() -> None:
    app = _app()
    container: ApiContainer = app.state.container
    assert container.no_platform_bypass_routes == ROLE_ROUTES_WITHOUT_BYPASS
    context = _admin_context()
    every = list(_endpoints(app))
    assert {(m, p) for m, p, _ in every} >= ROLE_ROUTES_WITHOUT_BYPASS
    wrong = []
    for method, path, route in sorted(every, key=lambda e: (e[1], e[0])):
        roles = without_platform_bypass(_request(app, method, route), container, context).roles
        listed = (method, path) in ROLE_ROUTES_WITHOUT_BYPASS
        assert "org_admin" in roles, (method, path)
        if (PLATFORM_ADMIN_ROLE in roles) is listed:
            wrong.append((method, path, "kept" if listed else "stripped"))
    assert wrong == []


def test_the_same_path_under_another_method_keeps_the_bypass() -> None:
    # `GET /admin/members` shares a path with `POST /admin/members` and is G2's.
    app = _app()
    assert PLATFORM_ADMIN_ROLE in _roles_on(app, "GET", f"{_ADMIN}/members")
    assert PLATFORM_ADMIN_ROLE not in _roles_on(app, "POST", f"{_ADMIN}/members")


class _AdminLookup:
    """A member who holds `platform_admin` (from `memberships.role_keys`) and no key."""

    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=uuid.uuid4(),
            roles=frozenset({PLATFORM_ADMIN_ROLE}),
            scopes=frozenset(),
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


async def test_through_a_request_the_dependency_reads_the_included_routers_template() -> None:
    """The template `get_access_context` compares is the full one of a route
    inside a router included under `/api/v1`, path parameters unexpanded."""
    container = _container(GRANTER, ENABLED)
    container.access_context_factory = DbAccessContextFactory(_AdminLookup())
    app = create_app(container)
    probe = APIRouter(prefix="/probe")

    @probe.get("/listed/{item_id}")
    async def listed(item_id: str, context: RequireAccessContext) -> list[str]:
        return sorted(context.roles)

    @probe.get("/open/{item_id}")
    async def open_(item_id: str, context: RequireAccessContext) -> list[str]:
        return sorted(context.roles)

    app.include_router(probe, prefix="/api/v1")
    container.no_platform_bypass_routes = ROLE_ROUTES_WITHOUT_BYPASS | {
        ("GET", "/api/v1/probe/listed/{item_id}")
    }
    token = DevTokenVerifier(SECRET).issue("dev|admin", email="admin@example.test")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            stripped = await client.get("/api/v1/probe/listed/1", headers=headers)
            kept = await client.get("/api/v1/probe/open/1", headers=headers)
    assert stripped.status_code == kept.status_code == 200, (stripped.text, kept.text)
    assert PLATFORM_ADMIN_ROLE not in stripped.json()
    assert PLATFORM_ADMIN_ROLE in kept.json()
