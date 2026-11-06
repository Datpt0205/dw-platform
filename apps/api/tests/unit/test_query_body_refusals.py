"""A `POST <list>/query` body that does not meet its shape answers like any
other wrong body (ADR 0108, point 1; app-standards R5.7).

`read_query_body` reads the body itself, so FastAPI never checks it: each
refusal of its shape is located here as FastAPI locates a declared body's, a
pointer and the error's type, and never repeats a value or a member the caller
made up. The contract walker (`test_error_envelope.py`) sends one wrong body;
this file sends each wrong shape.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from dw_api.dependencies.listing import read_query_body
from dw_api.exception_handlers import register_exception_handlers

pytestmark = pytest.mark.unit

PROBLEM = "application/problem+json"


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/counted/query")
    async def counted(request: Request) -> dict[str, Any]:
        raw = await read_query_body(request, route="/counted", counts=True)
        return {"order_by": raw.order_by, "limit": raw.limit, "count": raw.count}

    @app.post("/plain/query")
    async def plain(request: Request) -> dict[str, Any]:
        raw = await read_query_body(request, route="/plain")
        return {"limit": raw.limit, "count": raw.count}

    return app


async def _post(path: str, content: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path, content=content, headers={"content-type": "application/json"}
        )


def _errors(response: httpx.Response) -> list[tuple[str, str]]:
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith(PROBLEM)
    body = response.json()
    assert body["code"] == "validation_failed"
    return [(e.get("pointer", e.get("parameter")), e["code"]) for e in body["errors"]]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"0", ("", "model_attributes_type")),
        (b"[]", ("", "model_attributes_type")),
        (b"null", ("", "model_attributes_type")),
        (b"{", ("", "json_invalid")),
        (b'{"limit": NaN}', ("", "json_invalid")),
        (b'{"limit": 1, "limit": 2}', ("", "json_invalid")),
        (b'{"order_by": 1}', ("/order_by", "string_type")),
        (b'{"fields": ["name"]}', ("/fields", "string_type")),
        (b'{"cursor": {}}', ("/cursor", "string_type")),
        (b'{"count": "all"}', ("/count", "literal_error")),
        (b'{"limit": "ten"}', ("limit", "limit_out_of_range")),
    ],
)
async def test_a_wrong_shape_is_located_like_a_declared_body(
    content: bytes, expected: tuple[str, str]
) -> None:
    assert _errors(await _post("/counted/query", content)) == [expected]


async def test_a_member_the_caller_made_up_is_refused_at_the_root_without_its_name() -> None:
    response = await _post("/counted/query", b'{"khong_co": "0901234567"}')

    assert _errors(response) == [("", "extra_forbidden")]
    assert "khong_co" not in response.text and "0901234567" not in response.text


async def test_count_is_a_member_only_of_a_counted_listing() -> None:
    assert _errors(await _post("/plain/query", b'{"count": "exact"}')) == [("", "extra_forbidden")]


async def test_a_body_of_its_shape_is_read() -> None:
    counted = await _post(
        "/counted/query", b'{"order_by": "name desc", "limit": 3, "count": "exact"}'
    )
    plain = await _post("/plain/query", b"{}")

    assert counted.status_code == 200, counted.text
    assert counted.json() == {"order_by": "name desc", "limit": 3, "count": "exact"}
    assert plain.json() == {"limit": 50, "count": None}
