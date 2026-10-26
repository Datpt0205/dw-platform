"""Contract test: what an error says, whichever route refused (ADR 0108, point 1).

The web client and integrators read `code`, `message`, `details` and
`request_id` today; those four survive every change to the envelope, so this
file asks for them by name before anything else. The rest asks that every
other door a request can fail at — a schema the body does not meet, a path no
route has, a method the path lacks, a handler that broke — answers in the same
problem+json, and that the last of them says nothing about why.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Header, Query
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.responses import Response

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import (
    get_access_context,
    get_access_context_or_support,
    get_provisioning_context,
    get_verified_identity,
)
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.errors import ConflictError, DomainError
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.provisioning import ProvisioningContext

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

SECRET = "contract-test-secret-0123456789abcdef"
PROBLEM = "application/problem+json"
# The values an IntegrityError carries from the database: the statement, the
# table, the constraint and the offending row. None may reach a caller.
SQL = "INSERT INTO platform.secret_ledger (email) VALUES ($1)"
ROW_VALUE = "an.nguyen@khach-hang.vn"
CONSTRAINT = "uq_secret_ledger_email"


class Item(BaseModel):
    count: int


def make_app() -> FastAPI:
    async def ok_probe() -> CheckState:
        return "ok"

    app = create_app(
        ApiContainer(
            settings=ApiSettings(profile="test", dev_secret=SECRET),
            engine=None,
            health_service=HealthService(probes={"database": ok_probe}),
            token_verifier=DevTokenVerifier(SECRET),
            access_context_factory=None,
            identity_bootstrap=None,
            uow_factory=None,
            authorization=ScopeAuthorizationService(),
            entitlement=PlanEntitlementService(DEFAULT_PLANS),
        )
    )

    async def refuse() -> None:
        raise ConflictError("already archived", details={"reason": "archived"})

    async def over_limit() -> None:
        raise DomainError("too many", details={"limit": 3, "names": ["a", "b"]})

    async def items(
        item: Item,
        limit: int = Query(10),
        x_batch: int = Header(1),
    ) -> dict[str, int]:
        return {"count": item.count}

    async def violate() -> None:
        raise IntegrityError(
            SQL,
            {"email": ROW_VALUE},
            Exception(
                f'duplicate key value violates unique constraint "{CONSTRAINT}"\n'
                f"DETAIL:  Key (email)=({ROW_VALUE}) already exists."
            ),
        )

    app.add_api_route("/api/v1/_test/refuse", refuse, methods=["POST"])
    app.add_api_route("/api/v1/_test/over-limit", over_limit, methods=["POST"])
    app.add_api_route("/api/v1/_test/items", items, methods=["POST"])
    app.add_api_route("/api/v1/_test/violate", violate, methods=["POST"])
    return app


async def send(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM)
    body: dict[str, Any] = response.json()
    assert body["type"] == f"urn:dw:problem:{code}"
    assert body["status"] == status
    assert body["code"] == code
    assert body["message"] == body["detail"]
    assert body["instance"] == f"urn:dw:request:{response.headers['X-Request-ID']}"
    return body


async def test_an_error_keeps_code_message_details_and_request_id() -> None:
    response = await send(
        make_app(), "POST", "/api/v1/_test/refuse", headers={"X-Request-ID": "req-g2"}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["message"] == "already archived"
    assert body["details"] == {"reason": "archived"}
    assert body["request_id"] == "req-g2"


async def test_an_error_is_a_problem_with_an_english_title_and_its_request() -> None:
    response = await send(
        make_app(), "POST", "/api/v1/_test/refuse", headers={"X-Request-ID": "req-r11"}
    )

    body = assert_problem(response, 409, "conflict")
    assert body["title"] == "Conflict"
    assert body["instance"] == "urn:dw:request:req-r11"


async def test_details_keep_their_json_types() -> None:
    response = await send(make_app(), "POST", "/api/v1/_test/over-limit")

    body = assert_problem(response, 422, "validation_failed")
    assert body["details"] == {"limit": 3, "names": ["a", "b"]}


async def test_trace_id_is_the_current_span_and_null_without_one() -> None:
    trace_id = 0x0AF7651916CD43DD8448EB211C80319C
    app = make_app()

    @app.middleware("http")
    async def in_a_span(request: Request, call_next: Any) -> Response:
        if request.headers.get("X-Traced") is None:
            response: Response = await call_next(request)
            return response
        span = NonRecordingSpan(SpanContext(trace_id, 0x00F067AA0BA902B7, is_remote=False))
        with trace.use_span(span):
            response = await call_next(request)
            return response

    traced = await send(app, "POST", "/api/v1/_test/refuse", headers={"X-Traced": "1"})
    untraced = await send(app, "POST", "/api/v1/_test/refuse")

    assert traced.json()["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    assert untraced.json()["trace_id"] is None


async def test_a_wrong_body_points_at_the_field_and_a_wrong_query_names_the_parameter() -> None:
    app = make_app()
    wrong_body = await send(app, "POST", "/api/v1/_test/items", json={"count": "many"})
    wrong_query = await send(app, "POST", "/api/v1/_test/items?limit=ten", json={"count": 1})
    wrong_header = await send(
        app, "POST", "/api/v1/_test/items", json={"count": 1}, headers={"X-Batch": "one"}
    )

    body_errors = assert_problem(wrong_body, 422, "validation_failed")["errors"]
    assert body_errors == [
        {"pointer": "/count", "code": "int_parsing", "detail": body_errors[0]["detail"]}
    ]
    query_errors = assert_problem(wrong_query, 422, "validation_failed")["errors"]
    assert [(e.get("parameter"), e["code"]) for e in query_errors] == [("limit", "int_parsing")]
    assert "pointer" not in query_errors[0]
    header_errors = assert_problem(wrong_header, 422, "validation_failed")["errors"]
    assert [(e.get("header"), e["code"]) for e in header_errors] == [("x-batch", "int_parsing")]


async def test_an_unknown_path_is_a_problem_not_found() -> None:
    response = await send(make_app(), "GET", "/api/v1/khong-co")

    assert_problem(response, 404, "not_found")


async def test_a_method_the_path_lacks_is_405_with_allow() -> None:
    response = await send(make_app(), "DELETE", "/api/v1/health")

    body = assert_problem(response, 405, "method_not_allowed")
    assert body["title"] == "Method Not Allowed"
    assert "GET" in response.headers["Allow"]


async def test_an_unexpected_error_says_nothing_about_why() -> None:
    response = await send(make_app(), "POST", "/api/v1/_test/violate")

    assert_problem(response, 500, "internal")
    text = response.text
    for leaked in (SQL, "INSERT", "secret_ledger", CONSTRAINT, ROW_VALUE, "Traceback"):
        assert leaked not in text


async def test_a_401_still_challenges_with_bearer() -> None:
    response = await send(make_app(), "GET", "/api/v1/auth/bootstrap")

    assert_problem(response, 401, "unauthenticated")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def _authenticated(app: FastAPI) -> FastAPI:
    """Every door past authentication open, so each body reaches its schema.

    Authentication is a dependency, and dependencies run before the body is
    checked: unauthenticated, all but one operation answer 401 and the walker
    would prove nothing about schema errors.
    """
    context = AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        roles=frozenset({"owner"}),
        plan_id="professional",
    )
    app.dependency_overrides[get_access_context] = lambda: context
    app.dependency_overrides[get_access_context_or_support] = lambda: context
    app.dependency_overrides[get_verified_identity] = lambda: object()
    app.dependency_overrides[get_provisioning_context] = lambda: ProvisioningContext(
        principal_id=uuid.uuid4()
    )
    return app


async def test_every_operation_answers_a_wrong_body_with_a_problem() -> None:
    from generate_contracts import build_app  # type: ignore[import-not-found]

    app = _authenticated(build_app())
    operations = [
        (method.upper(), path, op)
        for path, item in app.openapi()["paths"].items()
        for method, op in item.items()
        if "requestBody" in op
    ]
    assert len(operations) >= 20, "the walker found too few operations to mean anything"

    refused: list[str] = []
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for method, template, op in operations:
                path = template
                for parameter in op.get("parameters", []):
                    if parameter["in"] == "path":
                        path = path.replace("{" + parameter["name"] + "}", str(uuid.uuid4()))
                request_id = f"walk-{len(refused)}"
                response = await client.request(
                    method, path, json=0, headers={"X-Request-ID": request_id}
                )
                label = f"{method} {template}"
                assert response.status_code == 422, label
                assert response.headers["content-type"].startswith(PROBLEM), label
                body = response.json()
                assert body["type"] == "urn:dw:problem:validation_failed", label
                assert body["instance"] == f"urn:dw:request:{request_id}", label
                assert body["errors"], label
                refused.append(label)

            unknown = await client.get("/api/v1/khong-co")
            wrong_method = await client.delete("/api/v1/health")

    assert len(refused) == len(operations)
    assert unknown.headers["content-type"].startswith(PROBLEM)
    assert wrong_method.headers["content-type"].startswith(PROBLEM)
