"""The built app keeps the list and write conventions (app-standards R3.12, R5.12, R6.3).

Asked of `app.openapi()`, not of a list kept beside it, through the readings in
`conventions.py`; each reading is also run over a small app of this file's own
to show it names what it should (APS22, APS47, APS50).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from conventions import (
    cursor_operations,
    frozen_list_problems,
    requires_if_match,
    unconditional_writes,
    write_routes,
)
from fastapi import FastAPI, Response
from plan_shape import EXEMPT as PLAN_EXEMPT
from plan_shape import REGISTERED as PLAN_REGISTERED
from pydantic import BaseModel

from dw_api.dependencies.conditions import RequireIfMatch
from dw_api.dependencies.listing import RequireListPage
from dw_api.middleware.access_log import REDACTED, install_access_log_redaction
from dw_observability.span_filter import allowed_attributes

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))

# Writes of a versioned resource that do not turn `RequireIfMatch` on yet, each
# with why: an upsert or a batch until its spec defines a per-item comparison,
# or a resource until its spec turns R3 on. Frozen: a new one is a decision.
EXEMPT_WRITES: dict[tuple[str, str], str] = {}

# Writes of a resource the schema reading cannot see as versioned (wrapped in
# an envelope), declared here under the same rule (the spec's "API" section).
WRAPPED_WRITES: dict[tuple[str, str], str] = {}


def built() -> dict[str, Any]:
    from generate_contracts import build_app  # type: ignore[import-not-found]

    spec: dict[str, Any] = build_app().openapi()
    return spec


def operations(spec: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }


# ------------------------------------------------------------------ R3.12 --


def test_every_write_of_a_versioned_resource_requires_if_match() -> None:
    spec = built()
    wrapped = {
        op for op in WRAPPED_WRITES if not requires_if_match(spec["paths"][op[1]][op[0].lower()])
    }

    assert (unconditional_writes(spec) | wrapped) - set(EXEMPT_WRITES) == set()
    conditional = write_routes(spec) - unconditional_writes(spec)
    present = operations(spec)
    assert list(frozen_list_problems(EXEMPT_WRITES, present=present, covered=conditional)) == []
    assert list(frozen_list_problems(WRAPPED_WRITES, present=present, covered=set())) == []


class Thing(BaseModel):
    id: str
    version: int


class MaybeThing(BaseModel):
    id: str
    version: int | None


class Label(BaseModel):
    # A semver, not a record version.
    version: str


class Done(BaseModel):
    ok: bool


def probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/things/{thing_id}", response_model=Thing)
    async def read(thing_id: str) -> Thing: ...

    @app.patch("/things/{thing_id}", response_model=Thing)
    async def patch(thing_id: str) -> Thing: ...

    @app.delete("/things/{thing_id}", status_code=204)
    async def delete(thing_id: str) -> Response: ...

    @app.post("/things/{thing_id}/archive", response_model=Done)
    async def archive(thing_id: str) -> Done: ...

    @app.post("/things", response_model=Thing, status_code=201)
    async def create() -> Thing: ...

    @app.post("/things/query", response_model=Done)
    async def query() -> Done: ...

    @app.post("/things/batch-update", response_model=Done)
    async def batch() -> Done: ...

    @app.patch("/things", response_model=Done)
    async def upsert() -> Done: ...

    @app.get("/labels/{label_id}", response_model=Label)
    async def label(label_id: str) -> Label: ...

    @app.patch("/labels/{label_id}", response_model=Label)
    async def relabel(label_id: str) -> Label: ...

    @app.patch("/guarded/{guarded_id}", response_model=MaybeThing)
    async def guarded(guarded_id: str, expected: RequireIfMatch) -> MaybeThing: ...

    @app.delete("/guarded/{guarded_id}", status_code=204)
    async def guarded_delete(guarded_id: str) -> Response: ...

    return app


def test_the_reading_names_every_unconditional_write_of_a_versioned_resource() -> None:
    # APS22, APS50: a PATCH returning `version`, a DELETE answering 204 and a
    # custom method answering another shape on a path whose GET returns it, a
    # batch and a PATCH on the list. Not the create, not the query, not a
    # string `version`, not a write that requires If-Match.
    assert unconditional_writes(probe_app().openapi()) == {
        ("PATCH", "/things/{thing_id}"),
        ("DELETE", "/things/{thing_id}"),
        ("POST", "/things/{thing_id}/archive"),
        ("POST", "/things/batch-update"),
        ("PATCH", "/things"),
        ("DELETE", "/guarded/{guarded_id}"),
    }


def test_a_frozen_list_names_its_own_faults() -> None:
    faults = list(
        frozen_list_problems(
            {("PATCH", "/things"): "", ("PUT", "/gone"): "an upsert", ("GET", "/ok"): "kept"},
            present={("PATCH", "/things"), ("GET", "/ok")},
            covered={("GET", "/ok")},
        )
    )
    assert faults == [
        "('PATCH', '/things'): no reason",
        "('PUT', '/gone'): no such operation",
        "('GET', '/ok'): no longer exempt",
    ]


# ------------------------------------------------------------------- R6.3 --


def test_every_operation_that_takes_a_cursor_is_planned_or_exempt() -> None:
    spec = built()
    taking = cursor_operations(spec)

    assert taking == set(PLAN_REGISTERED) | set(PLAN_EXEMPT)
    assert (
        list(frozen_list_problems(PLAN_EXEMPT, present=taking, covered=set(PLAN_REGISTERED))) == []
    )


class Page(BaseModel):
    items: list[str]


class QueryBody(BaseModel):
    cursor: str | None = None


def test_a_new_route_taking_a_cursor_is_named() -> None:
    # APS47: in the query string or in a `POST <list>/query` body.
    app = FastAPI()

    @app.get("/api/v1/things", response_model=Page)
    async def things(page: RequireListPage) -> Page: ...

    @app.post("/api/v1/things/query", response_model=Page)
    async def query(body: QueryBody) -> Page: ...

    assert cursor_operations(app.openapi()) - set(PLAN_REGISTERED) == {
        ("GET", "/api/v1/things"),
        ("POST", "/api/v1/things/query"),
    }


# ------------------------------------------------------------------ R5.12 --


class Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def test_a_list_querys_values_stay_out_of_the_access_log() -> None:
    # APS36: uvicorn's own call, as its default formatter renders it.
    install_access_log_redaction()
    logger = logging.getLogger("uvicorn.access")
    handler = Lines()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    cursor = "eyJ2IjoyLCJrIjoiU0VDUkVULTEyMyJ9"
    target = (
        "/api/v1/things?limit=5&filter=%7B%22name%22%3A%7B%22%24eq%22%3A%22SECRET-123%22%7D%7D"
        f"&cursor={cursor}&f%69lter=SECRET-123"
    )
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", target, "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    (line,) = handler.lines
    assert "SECRET-123" not in line and cursor not in line
    assert f"filter={REDACTED}" in line and f"cursor={REDACTED}" in line and "limit=5" in line


def test_a_url_attribute_never_leaves_on_a_span() -> None:
    # The API starts no HTTP span; were one to carry the target, the exporter's
    # allowlist drops it (`dw_observability.semconv.ALLOWED_KEYS`).
    attributes = {
        "url.query": "filter=SECRET-123",
        "url.full": "/x?cursor=abc",
        "http.target": "/x",
    }
    assert allowed_attributes(attributes) == {}
