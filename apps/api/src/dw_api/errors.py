"""The one error description every route answers with (ADR 0108, point 1).

RFC 9457 problem+json, plus the four members the web client already read
before it (`code`, `message`, `details`, `request_id`) and the two that locate
the failure (`trace_id`, `errors`). Every handler builds its response through
``problem_response`` so there is one place that decides what a failure says.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Self

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator
from starlette.requests import Request

from dw_api.middleware.request_id import REQUEST_ID_HEADER
from dw_kernel.errors import ErrorCode
from dw_observability.otel import current_trace_id

PROBLEM_MEDIA_TYPE = "application/problem+json"

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.CONFLICT: 409,
    ErrorCode.PRECONDITION_FAILED: 412,
    ErrorCode.PRECONDITION_REQUIRED: 428,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.ENTITLEMENT_DENIED: 403,
    ErrorCode.APPROVAL_REQUIRED: 409,
    ErrorCode.TENANT_CONTEXT_MISSING: 401,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: 415,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}

# Fixed English, for machines and logs: a person reads the sentence the web
# builds from `code` (DO-57), never this.
_TITLE_BY_CODE: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_FAILED: "Validation Failed",
    ErrorCode.NOT_FOUND: "Not Found",
    ErrorCode.METHOD_NOT_ALLOWED: "Method Not Allowed",
    ErrorCode.CONFLICT: "Conflict",
    ErrorCode.PRECONDITION_FAILED: "Precondition Failed",
    ErrorCode.PRECONDITION_REQUIRED: "Precondition Required",
    ErrorCode.UNAUTHENTICATED: "Unauthenticated",
    ErrorCode.PERMISSION_DENIED: "Permission Denied",
    ErrorCode.ENTITLEMENT_DENIED: "Entitlement Denied",
    ErrorCode.APPROVAL_REQUIRED: "Approval Required",
    ErrorCode.TENANT_CONTEXT_MISSING: "Tenant Context Missing",
    ErrorCode.IDEMPOTENCY_CONFLICT: "Idempotency Conflict",
    ErrorCode.RATE_LIMITED: "Rate Limited",
    ErrorCode.PAYLOAD_TOO_LARGE: "Payload Too Large",
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: "Unsupported Media Type",
    ErrorCode.TIMEOUT: "Timeout",
    ErrorCode.UPSTREAM_UNAVAILABLE: "Upstream Unavailable",
    ErrorCode.INTERNAL: "Internal Error",
}

# Read from the status map rather than written out a second time: the first
# code listed for a status is the one an HTTP-level refusal (no route, wrong
# method) carries.
_CODE_BY_STATUS: dict[int, ErrorCode] = {}
for _code, _status in _STATUS_BY_CODE.items():
    _CODE_BY_STATUS.setdefault(_status, _code)


class ProblemError(BaseModel):
    """One thing wrong with the request, located in exactly one place."""

    pointer: str | None = None
    """A JSON pointer into the body (RFC 6901); ``""`` is the whole body."""
    parameter: str | None = None
    header: str | None = None
    code: str
    detail: str

    @model_validator(mode="after")
    def _exactly_one_location(self) -> Self:
        located = [self.pointer, self.parameter, self.header]
        if sum(where is not None for where in located) != 1:
            raise ValueError("an error names exactly one of pointer, parameter or header")
        return self


class Problem(BaseModel):
    """The single error description returned by every endpoint."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None
    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str | None = None
    trace_id: str | None = None
    errors: list[ProblemError] = []


# Every operation's 4XX and 5XX, declared once on the app's router so a route
# mounted later inherits them. Declaring a 4XX also stops FastAPI adding its
# own 422 `HTTPValidationError`, which this envelope replaces.
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": Problem, "description": "The request was refused"},
    "5XX": {"model": Problem, "description": "The server failed"},
}


def status_for(code: ErrorCode) -> int:
    return _STATUS_BY_CODE.get(code, 500)


def code_for(status: int) -> ErrorCode:
    return _CODE_BY_STATUS.get(status, ErrorCode.INTERNAL)


def problem_response(
    request: Request,
    code: ErrorCode,
    message: str,
    *,
    status: int | None = None,
    details: Mapping[str, object] | None = None,
    errors: Sequence[ProblemError] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    status = status_for(code) if status is None else status
    request_id: str | None = getattr(request.state, "request_id", None)
    problem = Problem(
        type=f"urn:dw:problem:{code.value}",
        title=_TITLE_BY_CODE.get(code, _TITLE_BY_CODE[ErrorCode.INTERNAL]),
        status=status,
        detail=message,
        instance=f"urn:dw:request:{request_id}" if request_id is not None else None,
        code=code.value,
        message=message,
        details=jsonable_encoder(dict(details or {})),
        request_id=request_id,
        trace_id=current_trace_id(),
        errors=list(errors),
    )
    content = problem.model_dump(mode="json")
    # A location the error does not have is absent, not null: "exactly one of"
    # is what a reader checks with `in`.
    content["errors"] = [
        error.model_dump(mode="json", exclude_none=True) for error in problem.errors
    ]
    sent = dict(headers or {})
    # A 500 is answered outside the request-id middleware, and is the failure
    # someone most needs to quote.
    if request_id is not None:
        sent.setdefault(REQUEST_ID_HEADER, request_id)
    return JSONResponse(content, status_code=status, headers=sent, media_type=PROBLEM_MEDIA_TYPE)


def publish_problems_as_problem_json(app: FastAPI) -> None:
    """File every 4XX and 5XX schema under ``application/problem+json``.

    FastAPI files a declared response model under the route's own media type,
    so ``PROBLEM_RESPONSES`` alone would describe the errors as plain JSON,
    which is not what the handlers send.
    """
    build: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        schema = build()
        for item in schema.get("paths", {}).values():
            for operation in item.values():
                for status in PROBLEM_RESPONSES:
                    content = operation.get("responses", {}).get(status, {}).get("content", {})
                    if "application/json" in content:
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
