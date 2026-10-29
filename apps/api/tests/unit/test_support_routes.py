"""SA7: a support context reaches only the routes that opted in (ADR 0024).

Default deny is the real gate: a missing scope only stops a route that checks
one, and `GET /runs/{id}` checks none. So `RequireAccessContext` refuses the
support header outright, and the set of routes taking
`RequireAccessContextOrSupport` must equal `SUPPORT_ALLOWED_ROUTES` (empty on
the platform). A context opening a route adds it there with its own negative
test.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts
from test_support_endpoint import ENABLED, GRANTER, SECRET, TENANT, WORKSPACE, _container

from dw_api.bootstrap.wiring import SUPPORT_ALLOWED_ROUTES
from dw_api.dependencies.auth import (
    SUPPORT_GRANT_HEADER,
    RequireAccessContextOrSupport,
    get_access_context_or_support,
)
from dw_api.main import create_app
from dw_platform.adapters.identity.dev_token import DevTokenVerifier

pytestmark = pytest.mark.unit


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _calls(sub)


def _endpoints(app: FastAPI) -> Iterator[tuple[str, str, Dependant]]:
    """(method, full path, dependant) of every endpoint, routers included.

    `app.routes` holds an included router as one `_IncludedRouter` entry
    (FastAPI 0.141), so a loop over it filtered to `APIRoute` saw only the
    routes mounted on the app itself. `iter_route_contexts` walks into every
    included router, with the prefix in the path and the router's own
    `dependencies=[...]` in the dependant."""
    for context in iter_route_contexts(app.routes):
        dependant = getattr(context, "dependant", None)
        if dependant is None:
            continue
        for method in context.methods or ():
            yield method, context.path, dependant


def support_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Every (method, path) whose dependency tree builds a support context."""
    return {
        (method, path)
        for method, path, dependant in _endpoints(app)
        if get_access_context_or_support in set(_calls(dependant))
    }


def test_the_walker_sees_a_route_that_opts_in() -> None:
    # The guard below can fail: a route taking the dependency is found.
    app = FastAPI()

    @app.get("/probe/{item_id}")
    async def probe(item_id: str, context: RequireAccessContextOrSupport) -> None: ...

    assert support_routes(app) == {("GET", "/probe/{item_id}")}


def test_the_walker_sees_a_route_inside_an_included_router() -> None:
    # The blind spot of the old walker: every platform route lives in a router
    # included under `/api/v1`, never on the app itself.
    app = FastAPI()
    router = APIRouter()

    @router.get("/probe/{item_id}")
    async def probe(item_id: str, context: RequireAccessContextOrSupport) -> None: ...

    app.include_router(router, prefix="/api/v1")

    assert support_routes(app) == {("GET", "/api/v1/probe/{item_id}")}


def test_the_walker_sees_the_real_apps_routes() -> None:
    # A floor under the comparison below: an empty walk would equal the empty
    # allow-list too.
    app = create_app(_container(GRANTER, ENABLED))
    assert ("GET", "/api/v1/runs/{run_id}") in {
        (method, path) for method, path, _ in _endpoints(app)
    }


def test_only_the_allowed_routes_take_a_support_context() -> None:
    app = create_app(_container(GRANTER, ENABLED))
    assert support_routes(app) == set(SUPPORT_ALLOWED_ROUTES)


@pytest.mark.parametrize(
    "path",
    [
        # Fixed, not uuid4(): a parametrize id must be the same in every
        # pytest-xdist worker, or the workers refuse a collection that differs.
        "/runs/00000000-0000-4000-8000-000000000001",
        "/approvals",
        "/knowledge/documents",
        "/audit/events",
        "/admin/members",
        "/support/grants",
    ],
)
async def test_sa7_a_route_not_opened_to_support_refuses_the_header(path: str) -> None:
    token = DevTokenVerifier(SECRET).issue("dev|staff", amr=["pwd", "otp"])
    app = create_app(_container(GRANTER, ENABLED))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/v1{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Tenant-Id": str(TENANT),
                    "X-Workspace-Id": str(WORKSPACE),
                    SUPPORT_GRANT_HEADER: str(uuid.uuid4()),
                },
            )
    assert response.status_code == 403, path
    assert response.json()["details"]["reason_code"] == "support_context_not_allowed", path


async def test_the_dependency_itself_refuses_a_route_missing_from_the_list() -> None:
    # Belt and braces: a route that takes the dependency without being listed
    # still refuses support, before any grant is read.
    app = create_app(_container(GRANTER, ENABLED))

    @app.get("/api/v1/probe/{item_id}")
    async def probe(item_id: str, context: RequireAccessContextOrSupport) -> dict[str, str]:
        return {"tenant": str(context.tenant_id)}

    token = DevTokenVerifier(SECRET).issue("dev|staff", amr=["pwd", "otp"])
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/probe/1",
                headers={
                    "Authorization": f"Bearer {token}",
                    SUPPORT_GRANT_HEADER: str(uuid.uuid4()),
                },
            )
    assert response.status_code == 403
    assert response.json()["details"]["reason_code"] == "support_context_not_allowed"
