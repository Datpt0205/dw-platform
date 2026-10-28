"""The ``Idempotency-Key`` header, enforced.

A dependency rather than middleware, because the key is scoped to a tenant and
the tenant comes from the resolved :class:`AccessContext` — which middleware
runs too early to have. The dependency also gets to be per-route, which is the
point: idempotency belongs on the mutations where a duplicate does damage, not
on every write in the API.

A route declares, once, the check its service makes and the operation it is::

    Idempotency = idempotent(MEMBERS_WRITE, operation="POST /admin/members")

    async def grant_member(..., idempotency: Idempotency) -> MemberRefView:
        ref = await idempotency.once(
            status=201,
            run=lambda effect: service.handle(context, command, effect=effect),
            reread=lambda user_id: members.member(context, user_id),
        )
        return await idempotency.record(view_of(ref), status_code=201)

and that is the whole contract. Everything else happens around the handler:

* **The check first.** Before any key row is read or written, the route's
  declared check runs: the same constant the service checks, or the service's
  own check function (app-standards R2.17, R2.21, R2.30, R2.42). A caller who
  has lost the right gets 403, never a stored body. It runs when the handler
  starts ``once`` (or ``claim_fields``), not when the dependency is entered:
  FastAPI enters dependencies before it validates the body, and a wrong body
  is a 422 whoever sends it. Only when a key is sent: without one nothing reads
  a key row, and the service's own check refuses the caller (R2.22).
* **No header.** Nothing is stored and ``record`` returns what it was given,
  unless the route requires the key (422 ``idempotency_key_required``, R2.6).
* **First use of a key.** The dependency reserves it before the handler runs.
  ``record`` stores the status, body, `ETag` and `Location` it returns.
* **Replay.** The stored response is raised as :class:`ReplayedResponse` from the
  dependency, so the handler never runs at all. Only for the caller who spent
  the key (R2.2).
* **Same key, different request or caller.** 409 ``idempotency_conflict``.
* **The handler fails.** ``record`` is never reached, so the exit below releases
  the reservation and a retry gets a fresh attempt. A 5xx is not a decision the
  server made about the request, it is a failure to reach one; storing it would
  turn a transient fault into a permanent answer and defeat the retry the header
  exists to make safe. The same applies to a 4xx raised out of the handler.
  A failure *after* the effect committed is what ``once`` is for: the effect
  key written in the effect's own transaction answers the retry with the effect
  that exists, read back under the caller's current authority (R2.16, R2.29).

A multipart route (a file upload) cannot be fingerprinted from the raw body:
FastAPI parses a form through ``request.form()``, which consumes the stream, so
``request.body()`` in a dependency raises "Stream consumed"; and the body holds
a boundary the browser picks afresh on every send, so a retry's bytes never
match the first attempt's. Such a route declares ``idempotent(..., form=True)``
and claims the key itself, from the fields it parsed::

    await idempotency.claim_fields({"doc_type": ..., "sha256": ...})

before it acts. The rest (replay, conflict, release on failure) is the same.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

from fastapi import Depends, Header, Request
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import DomainError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import (
    EffectKey,
    EffectKeyPort,
    ExistingEffect,
    PendingEffect,
)
from dw_platform.application.idempotency import (
    HttpIdempotency,
    RequestFingerprint,
    Reservation,
    StoredResponse,
)

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer

IDEMPOTENCY_HEADER = "Idempotency-Key"
KEY_REQUIRED = "idempotency_key_required"

# Long enough for a UUID, a ULID or a request id from the client's own system;
# short enough that the header cannot be used as free storage. Anything longer
# is refused rather than truncated, because two keys that differ only past the
# cut would silently become one.
MAX_KEY_LENGTH = 255

ModelT = TypeVar("ModelT", bound=BaseModel)
T = TypeVar("T")


@dataclass(frozen=True)
class CheckInput:
    """What a route's declared check may read: the verified context, the
    container's services, and the request's path and body."""

    context: AccessContext
    container: ApiContainer
    request: Request


ContextCheck = Callable[[AccessContext], None]
"""A service's own check of the caller's context, for a permission that is not
one fixed `action`: the branch the context selects (`POST /support/grants`), or
an entitlement the service checks first (R2.42)."""

RouteCheck = Callable[[CheckInput], Awaitable[None]]
"""A check that needs the row the request names, calling the service's own
check function on it (`decide`, R2.30)."""

Declared = str | ContextCheck | RouteCheck


class IdempotencyKeyRequiredError(DomainError):
    """A route that requires the key was called without it (R2.6): 422
    `validation_failed`, `details.reason_code` and one header error."""

    def __init__(self) -> None:
        super().__init__(
            f"this operation requires an {IDEMPOTENCY_HEADER} header",
            details={"reason_code": KEY_REQUIRED},
        )


class ReplayedResponse(Exception):  # noqa: N818 — a control-flow signal, not a failure
    """Carries a stored response out of the dependency, past the handler.

    Named without an ``Error`` suffix on purpose: nothing went wrong. The client
    asked the same question twice and is getting the same answer.
    """

    def __init__(self, response: StoredResponse) -> None:
        super().__init__("idempotent replay")
        self.response = response


class IdempotentOperation:
    """A key held for the length of one request, or an inert stand-in.

    The inert form — no header, or no database — is what keeps the routes free
    of ``if``: ``record`` returns its argument, ``once`` runs the effect with no
    key, and nothing is persisted.
    """

    def __init__(
        self,
        idempotency: HttpIdempotency | None,
        effects: EffectKeyPort | None,
        context: AccessContext,
        key: str | None,
        *,
        operation: str,
        method: str,
        target: str,
        authorize: Callable[[], Awaitable[None]] | None = None,
        fingerprint: RequestFingerprint | None = None,
    ) -> None:
        self._authorize = authorize
        self._request_fingerprint = fingerprint
        self._started = False
        self._idempotency = idempotency
        self._effects = effects
        self._context = context
        self._key = key
        self._operation = operation
        self._method = method
        self._target = target
        self._reservation: Reservation | None = None
        self._fingerprint: RequestFingerprint | None = None
        self._recorded = False

    async def start(self) -> None:
        """The route's check, then the claim of a JSON route's key: once, and
        before anything reads a key row (R2.17)."""
        if self._started:
            return
        self._started = True
        # With no key there is no key row to guard, and the service makes the
        # same check itself (R2.22); for `decide` running it here too would read
        # the approval twice.
        if self._authorize is not None and self._idempotency is not None and self._key is not None:
            await self._authorize()
        if self._request_fingerprint is not None:
            await self.claim(self._request_fingerprint)

    async def claim(self, fingerprint: RequestFingerprint) -> None:
        """Reserve the key, or raise the stored response past the handler."""
        if self._idempotency is None or self._key is None:
            return
        claimed = await self._idempotency.claim(
            self._context, key=self._key, fingerprint=fingerprint
        )
        if isinstance(claimed, StoredResponse):
            raise ReplayedResponse(claimed)
        self._reservation = claimed
        self._fingerprint = fingerprint

    async def claim_fields(self, fields: Mapping[str, str]) -> None:
        """Reserve the key for a request identified by its parsed ``fields``.

        For a route whose body is not stable bytes (multipart). The route
        passes every field that makes the request what it is, a file as its
        hash; the same fields in any order fingerprint alike, and the method,
        path, workspace and caller are part of it as for every other route."""
        await self.start()
        body = json.dumps(dict(fields), sort_keys=True, ensure_ascii=False).encode()
        await self.claim(
            RequestFingerprint.of(
                context=self._context, method=self._method, path=self._target, body=body
            )
        )

    def pending_effect(self, status: int) -> PendingEffect | None:
        """The effect key this request may claim, or None with no key held."""
        if self._reservation is None or self._fingerprint is None or self._key is None:
            return None
        return PendingEffect(
            key=EffectKey(
                operation=self._operation,
                idempotency_key=self._key,
                caller_ref=self._fingerprint.caller_ref,
                request_hash=self._fingerprint.request_hash(),
                fresh=not self._reservation.taken_over,
            ),
            status=status,
        )

    async def once(
        self,
        *,
        status: int,
        run: Callable[[PendingEffect | None], Awaitable[T]],
        reread: Callable[[str], Awaitable[T]],
    ) -> T:
        """Run the effect once per key: or answer with the one that exists.

        The effect key is looked up before ``run`` reads any state (a retry of
        an approval must meet its decision, not "already decided"), and claimed
        again inside the effect's transaction, which decides a race (R2.33).
        Either way the existing effect is read back by ``reread`` under the
        caller's current authority, so a resource they can no longer see is
        absent rather than replayed (R2.29)."""
        await self.start()
        pending = self.pending_effect(status)
        if pending is not None and self._effects is not None:
            existing = await self._effects.existing(self._context, pending.key)
            if existing is not None:
                return await reread(existing.id)
        try:
            return await run(pending)
        except ExistingEffect as exc:
            return await reread(exc.result.id)

    async def record(
        self,
        result: ModelT,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> ModelT:
        """Store ``result`` as this key's answer and hand it back unchanged.

        Returning the argument is what lets a route end with
        ``return await idempotency.record(view)`` instead of growing a branch.
        ``status_code`` mirrors the one declared on the route, because a replay
        has to reproduce the whole answer and 201 is part of it; ``headers`` are
        the `ETag` and `Location` the route sets, which a replay carries (R2.1).
        """
        body = result.model_dump(mode="json")
        await self._store(
            StoredResponse(status_code=status_code, body=body, headers=dict(headers or {}))
        )
        return result

    async def record_no_content(self) -> None:
        """Store a 204 — the answer to a route that succeeds without a body."""
        await self._store(StoredResponse(status_code=204, body=None))

    async def _store(self, response: StoredResponse) -> None:
        # Only a key this request reserved: one it never claimed may be
        # another request's reservation, and is not this request's to fill.
        if self._reservation is None:
            return
        assert self._idempotency is not None and self._key is not None
        await self._idempotency.complete(
            self._context, key=self._key, token=self._reservation.token, response=response
        )
        self._recorded = True

    async def abandon_unless_recorded(self) -> None:
        # Never release a key this request did not reserve: that would free
        # another in-flight request's reservation. The token fences it too.
        if self._reservation is None or self._recorded:
            return
        assert self._idempotency is not None and self._key is not None
        await self._idempotency.release(self._context, key=self._key, token=self._reservation.token)


def _key(idempotency_key: str | None, *, required: bool) -> str | None:
    key = (idempotency_key or "").strip()
    if len(key) > MAX_KEY_LENGTH:
        # Refused rather than truncated: the key becomes part of a primary key,
        # and two keys differing only past the cut would collapse into one.
        raise DomainError(
            f"{IDEMPOTENCY_HEADER} must be at most {MAX_KEY_LENGTH} characters",
            details={"header": IDEMPOTENCY_HEADER, "max_length": MAX_KEY_LENGTH},
        )
    if not key and required:
        raise IdempotencyKeyRequiredError()
    return key or None


def _target(request: Request) -> str:
    # The query string is part of what identifies the request, not decoration:
    # `DELETE /admin/members/{id}?workspace_id=A` and the same path with
    # `workspace_id=B` are two different mutations. Compared as sent — a retry
    # that reorders its parameters is answered with a conflict, which is the
    # conservative half of the two ways to be wrong.
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return target


async def _authorize(declared: Declared, check: CheckInput, operation: str) -> None:
    if isinstance(declared, str):
        await check.container.authorization.require(
            context=check.context, action=declared, resource_type=operation
        )
    elif inspect.iscoroutinefunction(declared):
        await cast(RouteCheck, declared)(check)
    else:
        cast(ContextCheck, declared)(check.context)


def _key_header(required: bool) -> Any:
    # Declared rather than read off ``request.headers`` so that the header
    # appears in the OpenAPI schema, and therefore in the generated client, on
    # exactly the routes that honour it. A contract clients are told to rely on
    # should be discoverable from the contract.
    return Header(
        default=None,
        alias=IDEMPOTENCY_HEADER,
        description=(
            ("Required. " if required else "Optional. ")
            + "Retrying with the same key returns the first response instead of "
            "acting twice; reusing it for a different request, or another "
            "person's key, is a 409."
        ),
    )


def idempotent(
    check: Declared, *, operation: str, required: bool = False, form: bool = False
) -> Any:
    """The dependency of one route that honours ``Idempotency-Key``.

    ``check`` is what the route's service checks: its `action` constant, or a
    check function of the service; never a string written a second time (R2.21).
    ``operation`` is the method and path template, fixed here so that renaming
    a path parameter does not orphan an effect key.
    """

    async def dependency(
        request: Request,
        context: RequireAccessContext,
        container: RequireContainer,
        idempotency_key: str | None = _key_header(required),
        if_match: str | None = Header(default=None, alias="If-Match", include_in_schema=False),
        if_none_match: str | None = Header(
            default=None, alias="If-None-Match", include_in_schema=False
        ),
    ) -> AsyncIterator[IdempotentOperation]:
        target = _target(request)
        key = _key(idempotency_key, required=required)

        async def authorize() -> None:
            # The route's permission before any key row is read or written: a
            # replay is answered only to someone who may still ask (R2.17).
            await _authorize(
                check, CheckInput(context=context, container=container, request=request), operation
            )

        # For a JSON (or empty) body FastAPI has already read it through
        # ``request.body()``, which caches the bytes, so reading it here costs
        # nothing and leaves the handler its parameters. Not for a form:
        # FastAPI parses that through ``request.form()``, which consumes the
        # stream without caching it, and the route claims from its fields.
        fingerprint = (
            None
            if form
            else RequestFingerprint.of(
                context=context,
                method=request.method,
                path=target,
                body=await request.body(),
                if_match=if_match,
                if_none_match=if_none_match,
            )
        )
        idempotent_operation = IdempotentOperation(
            container.idempotency,
            container.effect_keys,
            context,
            key,
            operation=operation,
            method=request.method,
            target=target,
            authorize=authorize,
            fingerprint=fingerprint,
        )
        try:
            yield idempotent_operation
        finally:
            await idempotent_operation.abandon_unless_recorded()

    # Read by the declaration test: every operation with the header names the
    # check it runs (R2.18).
    dependency.idempotency_check = check  # type: ignore[attr-defined]
    dependency.idempotency_operation = operation  # type: ignore[attr-defined]
    return Depends(dependency)
