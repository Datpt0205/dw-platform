"""Maps every way a request can fail onto the one problem+json description."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dw_api.dependencies.idempotency import IDEMPOTENCY_HEADER, ReplayedResponse
from dw_api.errors import ProblemError, code_for, problem_response, status_for
from dw_kernel.errors import DWError, ErrorCode


def _json_pointer(path: Sequence[Any]) -> str:
    return "".join("/" + str(step).replace("~", "~0").replace("/", "~1") for step in path)


def _located(error: Mapping[str, Any]) -> ProblemError:
    """Where in the request one schema error is: body, header or parameter."""
    where, *path = error.get("loc") or ("body",)
    code = str(error.get("type", "invalid"))
    detail = str(error.get("msg", ""))
    if where == "body":
        # A body that is not JSON at all is located by byte offset, not by key.
        return ProblemError(
            pointer="" if code == "json_invalid" else _json_pointer(path), code=code, detail=detail
        )
    name = str(path[0]) if path else str(where)
    if where == "header":
        return ProblemError(header=name, code=code, detail=detail)
    return ProblemError(parameter=name, code=code, detail=detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReplayedResponse)
    async def handle_replay(request: Request, exc: ReplayedResponse) -> Response:
        """Return what the first request returned, byte for byte.

        The handler never ran, so there is nothing to serialise: the stored body
        is sent back as it was stored. The header is echoed so a client (or a
        proxy log) can tell a replay from a first attempt.
        """
        stored = exc.response
        headers = {IDEMPOTENCY_HEADER: request.headers.get(IDEMPOTENCY_HEADER, "")}
        if stored.body is None:
            return Response(status_code=stored.status_code, headers=headers)
        return JSONResponse(status_code=stored.status_code, content=stored.body, headers=headers)

    @app.exception_handler(DWError)
    async def handle_dw_error(request: Request, exc: DWError) -> Response:
        # Every 401 names the scheme that would satisfy it (RFC 9110 15.5.2).
        headers = {"WWW-Authenticate": "Bearer"} if status_for(exc.code) == 401 else None
        return problem_response(
            request, exc.code, exc.message, details=exc.details, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_invalid_request(request: Request, exc: RequestValidationError) -> Response:
        return problem_response(
            request,
            ErrorCode.VALIDATION_FAILED,
            "the request does not match its schema",
            errors=[_located(error) for error in exc.errors()],
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # No route for the path (404), or none for the method (405, with the
        # `Allow` Starlette put on the exception).
        if exc.status_code in {204, 304}:
            return Response(status_code=exc.status_code, headers=exc.headers)
        return problem_response(
            request,
            code_for(exc.status_code),
            exc.detail if isinstance(exc.detail, str) else "request refused",
            status=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> Response:
        # Never leak internals: no message, statement or value of the exception.
        return problem_response(request, ErrorCode.INTERNAL, "internal error")
