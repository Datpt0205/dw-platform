"""A 4xx names where and what, never a value (app-standards R1.10, APS21).

Probe routes on the real app. The values are planted as `SECRET-...` so any
echo of them is found by a substring check, whatever field it lands in.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.errors import ConflictError
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService

pytestmark = pytest.mark.unit


class Cat(BaseModel):
    kind: Literal["cat"]


class Dog(BaseModel):
    kind: Literal["dog"]


class ProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = 0
    owner: uuid.UUID | None = None
    pet: Annotated[Cat | Dog, Field(discriminator="kind")] | None = None
    code: str = "ok"

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        if value != "ok":
            raise ValueError(f"code {value!r} is not allowed")
        return value


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
            entitlement=PlanEntitlementService(DEFAULT_PLANS),
        )
    )

    @built.post("/api/v1/probe/values")
    async def values(body: ProbeBody) -> dict[str, str]:
        return {"ok": "yes"}

    @built.post("/api/v1/probe/taken")
    async def taken() -> None:
        try:
            raise IntegrityError(
                "INSERT INTO platform.things (name) VALUES ('SECRET-123')",
                {"name": "SECRET-123"},
                Exception(
                    'duplicate key value violates unique constraint "uq_things_name"'
                    " DETAIL: Key (name)=(SECRET-OLD) already exists."
                ),
            )
        except IntegrityError as exc:
            raise ConflictError(
                "the name is already taken", details={"reason_code": "duplicate_value"}
            ) from exc

    return built


async def _post(path: str, body: object) -> httpx.Response:
    built = app()
    async with LifespanManager(built):
        transport = httpx.ASGITransport(app=built)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=body, headers={"X-Request-ID": "probe-1"})


@pytest.mark.parametrize(
    "body",
    [
        {"count": "SECRET-123"},
        {"owner": "SECRET-123"},
        {"pet": {"kind": "SECRET-123"}},
        {"code": "SECRET-123"},
        {"SECRET-KEY": 1},
    ],
    ids=["wrong type", "uuid", "discriminator", "own validator", "unknown member"],
)
async def test_a_schema_error_names_no_value_the_caller_sent(body: dict[str, object]) -> None:
    answered = await _post("/api/v1/probe/values", body)

    assert answered.status_code == 422
    assert "SECRET" not in answered.text
    problem = answered.json()
    assert problem["request_id"] == "probe-1" and "trace_id" in problem
    assert problem["errors"] and all(e["code"] and e["detail"] for e in problem["errors"])


async def test_an_unknown_member_is_located_at_its_parent() -> None:
    [error] = (await _post("/api/v1/probe/values", {"SECRET-KEY": 1})).json()["errors"]

    assert (error["pointer"], error["code"]) == ("", "extra_forbidden")


async def test_a_refused_duplicate_names_no_value_table_or_constraint() -> None:
    answered = await _post("/api/v1/probe/taken", None)

    assert answered.status_code == 409
    for leaked in ("SECRET", "platform.things", "uq_things_name", "INSERT"):
        assert leaked not in answered.text, leaked
    assert answered.json()["details"] == {"reason_code": "duplicate_value"}
