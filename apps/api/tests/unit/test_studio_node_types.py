"""Unit: `GET /api/v1/studio/node-types` (workflow-nodes ticket 02, step 4:
R1.1, R1.2).

The route over a small app: the Studio group's dependency is overridden with
a context, so what is asked is the route's own check and answer; that the
group's gate answers an anonymous call 401 is `test_studio_seam`'s, which
walks every Studio path of the schema, this one included.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from dw_agent_runtime.wflite.catalog import PackCatalog, ShippedToolSpecs
from dw_agent_runtime.wflite.compile import WfPorts, _Builder
from dw_agent_runtime.wflite.registry import NodeTypeSpec, build_node_registry, catalogue_hash
from dw_api.dependencies.auth import get_studio_access_context
from dw_api.exception_handlers import register_exception_handlers
from dw_api.routes.v1.studio_node_types import router
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_studio.kinds import WORKFLOWS_EDIT_SCOPE, WORKFLOWS_READ_SCOPE

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
PATH = "/api/v1/studio/node-types"


def context(*scopes: str) -> AccessContext:
    return AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset(scopes),
        plan_id="starter",
    )


def app_with(
    caller: AccessContext,
    nodes: Mapping[str, NodeTypeSpec] | None = None,
    authorization: Any = None,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.container = SimpleNamespace(
        authorization=authorization or ScopeAuthorizationService(),
        studio=SimpleNamespace(node_types=build_node_registry() if nodes is None else nodes),
    )
    group = APIRouter(prefix="/studio")
    group.include_router(router)
    app.include_router(group, prefix="/api/v1")
    app.dependency_overrides[get_studio_access_context] = lambda: caller
    return app


async def get(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(PATH)


def _type(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(entry for entry in body["types"] if entry["type"] == name)


# ------------------------------------------------------------------ R1.2 --


async def test_a_caller_with_the_edit_key_reads_the_catalogue() -> None:
    answer = await get(app_with(context(WORKFLOWS_EDIT_SCOPE)))

    assert answer.status_code == 200
    assert answer.headers["cache-control"] == "private, no-store"
    body = answer.json()
    assert [entry["type"] for entry in body["types"]] == sorted(build_node_registry())

    approval = _type(body, "human.approval@1")
    assert approval["label_vi"] == "Người duyệt"
    assert approval["config_schema"]["required"] == ["decision_class", "proposal"]
    assert approval["output"]["kind"] == "fixed"
    assert set(approval["output"]["schema"]["properties"]) == {"proposal", "approved", "comment"}
    assert approval["error"]["on_error"] == ["continue", "route"]
    assert approval["error"]["schema"]["required"] == ["code", "message"]
    assert [(p["name"], p["label_vi"]) for p in approval["ports"]["ports"]] == [
        ("approved", "Duyệt"),
        ("rejected", "Từ chối"),
    ]
    assert approval["side_effect_level"] == "none"

    switch = _type(body, "logic.switch@1")
    assert switch["ports"] == {
        "kind": "keyed",
        "key": "cases",
        "default": {"name": "default", "label_vi": "Khác"},
    }
    assert _type(body, "ai.llm@1")["output"] == {"kind": "config", "key": "output_schema"}


async def test_two_tenants_read_one_catalogue_at_the_platform_layer() -> None:
    """What a deployment can do does not depend on who asks (`CLAUDE.md`,
    Per-tenant artifacts): another tenant's caller reads the same bytes."""
    first = await get(app_with(context(WORKFLOWS_EDIT_SCOPE)))
    second = await get(app_with(context(WORKFLOWS_EDIT_SCOPE)))
    assert first.status_code == second.status_code == 200
    assert first.content == second.content


@pytest.mark.parametrize("scopes", [(), (WORKFLOWS_READ_SCOPE,)])
async def test_a_caller_without_the_edit_key_is_403(scopes: tuple[str, ...]) -> None:
    answer = await get(app_with(context(*scopes)))

    assert answer.status_code == 403
    assert "types" not in answer.text


async def test_without_the_check_the_same_caller_would_read_it() -> None:
    """The 403's control removed: an authorization that allows everything
    lets the caller without the key through, so the test above is red."""

    class AllowAll:
        async def require(self, **_: Any) -> None:
            return None

    answer = await get(app_with(context(), authorization=AllowAll()))
    assert answer.status_code == 200


# ------------------------------------------------------------------ R1.1 --


def _worker_registry() -> Mapping[str, NodeTypeSpec]:
    """The registry the worker's compiler holds for a shipped pack."""
    tools = ShippedToolSpecs.load(REPO / "configs" / "tools")
    pinned = PackCatalog.load(REPO / "configs" / "packs", tools).all()[0]
    return _Builder(pinned, cast(WfPorts, None)).registry


async def test_the_route_and_the_worker_compiler_hash_one_catalogue() -> None:
    answer = await get(app_with(context(WORKFLOWS_EDIT_SCOPE)))

    assert answer.json()["catalogue_hash"] == catalogue_hash(_worker_registry())


async def test_a_route_built_from_a_changed_registry_hashes_differently() -> None:
    nodes = dict(build_node_registry())
    nodes["time.wait@1"] = dataclasses.replace(nodes["time.wait@1"], config_schema={})
    answer = await get(app_with(context(WORKFLOWS_EDIT_SCOPE), nodes=nodes))

    assert answer.json()["catalogue_hash"] != catalogue_hash(_worker_registry())
