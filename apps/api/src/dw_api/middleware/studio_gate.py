"""The door of `/api/v1/studio`: the token before the body, and the body capped
as it streams (studio-skeleton R6.5, R6.8, R6.10; ADR-0108 decision 3).

Measured on FastAPI 0.141.1 (3/11/2026): a route that declares a body has it
read in full (`request.body()`) before any dependency runs, so a dependency
can neither refuse an anonymous caller before the bytes arrive nor cap them.
Hence an ASGI middleware on the path prefix, mounted with the group by
`mount_studio` and innermost of the app's middleware, so the request id is
set and CORS answers a preflight before this runs:

1. The bearer token, through `verify_bearer`, the one verifier the API's
   dependencies call. No token, a bad one, or a verifier that failed (the IdP
   unreachable): refused, 401 or 503, nothing of the body read. The identity
   goes to `request.state` for the group's dependency (R6.11).
2. `Content-Encoding` other than `identity`: 415, nothing decompressed (R6.10).
3. A declared `Content-Length` past the cap: 413 unread. Otherwise `receive`
   counts what it hands over, whatever was declared, and the byte past the cap
   ends the body: 413 `payload_too_large`, the source never asked for more.

A handler that reads `request.stream()` itself and answers before the end
cannot be overruled once it started its response (gate MEDIUM (g)); none in
the group does.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dw_api.dependencies.auth import VERIFIED_IDENTITY_STATE
from dw_api.errors import problem_response, status_for
from dw_kernel.errors import DWError, ErrorCode, PayloadTooLargeError
from dw_platform.application.ports import VerifiedIdentity

_LOG = logging.getLogger(__name__)

STUDIO_PREFIX: Final = "/api/v1/studio"
MAX_BODY_BYTES: Final = 1_048_576

Verify = Callable[[str | None], Awaitable[VerifiedIdentity]]


def under_studio(path: str) -> bool:
    """`/api/v1/studio` itself and everything below it, never `/api/v1/studio-x`."""
    return path == STUDIO_PREFIX or path.startswith(STUDIO_PREFIX + "/")


class StudioGate:
    def __init__(self, app: ASGIApp, *, verify: Verify, max_body: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.verify = verify
        self.max_body = max_body

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        code: ErrorCode,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if status_for(code) == 401 else None
        response = problem_response(Request(scope), code, message, details=details, headers=headers)
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not under_studio(scope["path"]):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            identity = await self.verify(request.headers.get("authorization"))
        except DWError as exc:
            await self._refuse(scope, receive, send, exc.code, exc.message, exc.details)
            return
        except Exception:
            # A verifier that failed is a refusal, never a pass (gate MEDIUM (e)).
            _LOG.exception("token verification failed at the Studio gate")
            await self._refuse(
                scope,
                receive,
                send,
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "the token could not be verified",
            )
            return
        scope.setdefault("state", {})[VERIFIED_IDENTITY_STATE] = identity

        encoding = request.headers.get("content-encoding", "").strip().lower()
        if encoding not in ("", "identity"):
            await self._refuse(
                scope,
                receive,
                send,
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "a Studio request body is not compressed",
                {"header": "Content-Encoding"},
            )
            return
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_body:
            await self._too_large(scope, receive, send)
            return
        await self._capped(scope, receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._refuse(
            scope,
            receive,
            send,
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"a Studio request body is at most {self.max_body} bytes",
            {"max_bytes": self.max_body},
        )

    async def _capped(self, scope: Scope, receive: Receive, send: Send) -> None:
        state: dict[str, Any] = {"read": 0, "over": False, "started": False}

        async def counted() -> Message:
            if state["over"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["read"] += len(message.get("body", b""))
                if state["read"] > self.max_body:
                    state["over"] = True
                    raise PayloadTooLargeError("the body passed the cap")
            return message

        async def guarded(message: Message) -> None:
            # Whatever the app answers to a body cut short (FastAPI makes it a
            # 400) is replaced by the 413 below.
            if state["over"] and not state["started"]:
                return
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, counted, guarded)
        except Exception:
            if not state["over"] or state["started"]:
                raise
        if state["over"] and not state["started"]:
            await self._too_large(scope, receive, send)
