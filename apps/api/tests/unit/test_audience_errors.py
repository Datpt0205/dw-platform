"""A refused audience answers 422 with `errors[]` located in the caller's body
(org-and-principals ticket 04, R8.2).

A probe route on the real app stands in for agent-builder/04: it calls the
validator with `at="/audience"` and lets the error through, which is all a
consumer is meant to do.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.application.access_context import AccessContext
from dw_platform.application.audience import AudienceValidator
from dw_platform.application.authorization import ScopeAuthorizationService

pytestmark = pytest.mark.unit

KNOWN = uuid.uuid4()


class FakeWorkspaces:
    async def known(
        self, context: AccessContext, ids: frozenset[uuid.UUID]
    ) -> frozenset[uuid.UUID]:
        return ids & {KNOWN}


def app() -> FastAPI:
    async def ok() -> CheckState:
        return "ok"

    built = create_app(
        ApiContainer(
            settings=ApiSettings(profile="test", dev_secret="x" * 40),
            engine=None,
            health_service=HealthService(probes={"database": ok}),
            token_verifier=None,
            access_context_factory=None,
            identity_bootstrap=None,
            uow_factory=None,
            authorization=ScopeAuthorizationService(),
        )
    )
    validator = AudienceValidator(FakeWorkspaces())
    context = AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset(),
        plan_id="professional",
    )

    @built.post("/api/v1/probe/audience")
    async def store(body: dict[str, Any]) -> dict[str, Any]:
        document = await validator.validate(context, body.get("audience"), at="/audience")
        return document.as_json()

    return built


async def _post(body: object) -> httpx.Response:
    built = app()
    async with LifespanManager(built):
        transport = httpx.ASGITransport(app=built)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/probe/audience", json=body)


def _audience(*groups: list[object]) -> dict[str, Any]:
    return {"schema": "dw.audience/v1", "any_of": [{"all_of": list(g)} for g in groups]}


async def test_an_unsupported_condition_is_a_422_located_under_the_callers_member() -> None:
    answered = await _post({"audience": _audience([{"team": "SECRET-team"}])})

    assert answered.status_code == 422
    problem = answered.json()
    assert problem["code"] == "validation_failed"
    assert problem["details"] == {"reason_code": "audience_invalid"}
    assert problem["errors"] == [
        {
            "pointer": "/audience/any_of/0/all_of/0",
            "code": "audience_condition_unsupported",
            "detail": "this kind of condition is not supported",
        }
    ]
    assert "SECRET" not in answered.text


async def test_an_empty_audience_says_so_in_its_reason_code() -> None:
    answered = await _post({"audience": _audience([])})

    assert answered.status_code == 422
    problem = answered.json()
    assert problem["details"] == {"reason_code": "audience_empty"}
    assert [(e["pointer"], e["code"]) for e in problem["errors"]] == [
        ("/audience/any_of", "audience_empty")
    ]


async def test_an_unknown_workspace_names_no_value() -> None:
    stranger = uuid.uuid4()
    answered = await _post(
        {
            "audience": _audience(
                [{"workspace_subtree": str(KNOWN)}], [{"workspace_subtree": str(stranger)}]
            )
        }
    )

    assert answered.status_code == 422
    assert [(e["pointer"], e["code"]) for e in answered.json()["errors"]] == [
        ("/audience/any_of/1/all_of/0", "audience_workspace_unknown")
    ]
    assert str(stranger) not in answered.text


async def test_a_valid_audience_passes() -> None:
    body = _audience([{"workspace_subtree": str(KNOWN)}])

    answered = await _post({"audience": body})

    assert answered.status_code == 200
    assert answered.json() == body
