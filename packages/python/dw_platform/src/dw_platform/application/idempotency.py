"""Replay protection for mutating HTTP requests that carry an idempotency key.

The platform already enforces idempotency for *tools*
(``dw_agent_runtime.executor`` against ``platform.tool_executions``). This is the
HTTP half: the same guarantee for a client of the published API, which until now
could only retry a timed-out POST and hope.

Three outcomes, and the whole point is that they are decided here rather than in
a route:

* the key is unspent — the caller owns it and runs the handler;
* the key was spent on the *same* request by the *same* caller — the stored
  response is returned and the handler never runs;
* the key was spent on a different request, or by somebody else — refused,
  because answering it with the first request's response would hide a client
  bug behind a plausible reply, or hand one person another's answer.

What counts as "the same request" is :class:`RequestFingerprint`. It includes
the caller (app-standards R2.2), the workspace, and the preconditions the client
sent, not only the method, path and body: one key reused across two workspaces
of a tenant, or by two people, must be a conflict, never a replay.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from dw_kernel.errors import ConflictError, IdempotencyConflictError
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext

# How long a reservation may stay in flight before its own caller may take it
# over. A reservation is committed before the handler runs — it has to be, or a
# concurrent request could not see it — so a process killed mid-handler leaves
# one behind, and without a takeover that key would answer 409 forever.
#
# Chosen as a large multiple of the longest a request may legitimately take: the
# API's own upstream timeouts are seconds, so five minutes is far past "still
# working" and still short enough that a client's own retry schedule outlives it.
STALE_RESERVATION = timedelta(minutes=5)

# The only response headers a replay carries (app-standards R2.1); the database
# refuses any other (`ck_idempotency_keys_response_headers_allowed`).
REPLAYED_HEADERS = ("ETag", "Location")


def caller_ref(context: AccessContext) -> str:
    """Who spent a key: the grant under support access (ADR 0024), else the
    principal, a service principal included (R2.20).

    A support grant is its own caller even for one staff member: two grants are
    two authorities, and a replay under the second must not return what the
    first produced (R2.2)."""
    if context.support is not None:
        return f"support:{context.support.grant_id}"
    return f"user:{context.principal_id}"


@dataclass(frozen=True)
class RequestFingerprint:
    """What a key was spent on, and by whom. Compared whole; any difference is
    a conflict. ``caller_ref`` of a row written before callers were bound is
    ``''``, which equals no caller (R2.3)."""

    method: str
    path: str
    workspace_id: uuid.UUID
    body_hash: str
    caller_ref: str
    # `If-Match` then `If-None-Match`, as sent; '' when neither was.
    preconditions: str = ""

    @classmethod
    def of(
        cls,
        *,
        context: AccessContext,
        method: str,
        path: str,
        body: bytes,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> RequestFingerprint:
        return cls(
            method=method.upper(),
            path=path,
            workspace_id=context.workspace_id,
            # The raw bytes, not a parsed and re-serialised body: hashing what
            # actually arrived is the cheaper claim to defend, and it costs a
            # client nothing, because a retry re-sends what it sent.
            body_hash=hashlib.sha256(body).hexdigest(),
            caller_ref=caller_ref(context),
            preconditions=preconditions_of(if_match, if_none_match),
        )

    def request_hash(self) -> str:
        """The request without its caller: what an effect key compares
        alongside ``caller_ref`` (R2.23). The one function that hashes it, so
        the HTTP key and the effect key cannot disagree on what "the same
        request" is."""
        canonical = json.dumps(
            [self.method, self.path, str(self.workspace_id), self.body_hash, self.preconditions],
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def preconditions_of(if_match: str | None, if_none_match: str | None) -> str:
    """One stored string for the two headers; empty when neither was sent."""
    if not if_match and not if_none_match:
        return ""
    return json.dumps([if_match or "", if_none_match or ""], separators=(",", ":"))


@dataclass(frozen=True)
class StoredResponse:
    """A response worth replaying: the handler produced it and it succeeded."""

    status_code: int
    # ``None`` is a 204, which has no body. Everything else this API returns is
    # a JSON object.
    body: dict[str, object] | None
    # `ETag` and `Location` only.
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReservedKey:
    """An existing row: what the key was spent on, and what it produced."""

    fingerprint: RequestFingerprint
    # ``None`` while the request that reserved the key is still running.
    response: StoredResponse | None


@dataclass(frozen=True)
class Reservation:
    """This request holds the key. ``token`` is its fence: only it completes or
    releases the row. ``taken_over`` says the row predates this request (an
    abandoned reservation of the same caller), which an effect key must know
    (R2.37)."""

    token: uuid.UUID
    taken_over: bool


class IdempotencyStorePort(Protocol):
    """Persistence for spent keys, tenant-scoped through RLS.

    Every method commits on its own rather than joining the handler's
    transaction. That is deliberate: a reservation the handler's transaction
    could roll back would be invisible to the concurrent request it exists to
    stop, and a completion written inside the handler's transaction would be
    lost in exactly the case the reservation is there to survive.
    """

    async def reserve(
        self, context: AccessContext, *, key: str, fingerprint: RequestFingerprint
    ) -> uuid.UUID | ReservedKey:
        """Claim the key for this request.

        Returns the new reservation's token when the claim succeeded, or the
        existing row when the key is already spent or held.
        """
        ...

    async def take_over(
        self,
        context: AccessContext,
        *,
        key: str,
        fingerprint: RequestFingerprint,
        older_than: datetime,
    ) -> uuid.UUID | None:
        """Re-claim a reservation of the same caller in flight since before
        ``older_than``, under a new token (R2.4, R2.10).

        ``None`` when this request did not win it. Never wins a key whose
        response is already stored, so a completed response cannot be
        overwritten.
        """
        ...

    async def complete(
        self, context: AccessContext, *, key: str, token: uuid.UUID, response: StoredResponse
    ) -> None:
        """Store the answer, only under the reservation's own token (R2.5)."""
        ...

    async def release(self, context: AccessContext, *, key: str, token: uuid.UUID) -> None:
        """Give the key back, so a retry may spend it on a fresh attempt; only
        under the reservation's own token (R2.5)."""
        ...


@dataclass(frozen=True)
class HttpIdempotency:
    """Decides replay, conflict or run. Holds no per-request state."""

    store: IdempotencyStorePort
    clock: UtcClock

    async def claim(
        self, context: AccessContext, *, key: str, fingerprint: RequestFingerprint
    ) -> StoredResponse | Reservation:
        """Claim ``key`` for this request.

        A :class:`Reservation` means the caller owns the key and must run the
        handler, then call :meth:`complete` or :meth:`release` with its token.
        A :class:`StoredResponse` means the handler must not run: return this
        instead.
        """
        reserved = await self.store.reserve(context, key=key, fingerprint=fingerprint)
        if isinstance(reserved, uuid.UUID):
            return Reservation(token=reserved, taken_over=False)

        if reserved.fingerprint != fingerprint:
            raise IdempotencyConflictError(
                "idempotency key already used for a different request",
                details={
                    "hint": "use a new key for a new request, or resend the original one",
                },
            )
        if reserved.response is not None:
            return reserved.response

        # Still in flight. Take the reservation over if it has been abandoned,
        # and otherwise refuse rather than wait: waiting would hold this
        # request's worker and connection for the length of the other request's
        # handler, which is how a client's retry storm becomes the server's
        # outage. The store decides who wins, in one statement.
        token = await self.store.take_over(
            context,
            key=key,
            fingerprint=fingerprint,
            older_than=self.clock.now() - STALE_RESERVATION,
        )
        if token is not None:
            return Reservation(token=token, taken_over=True)
        raise ConflictError(
            "a request with this idempotency key is still in progress",
            details={"hint": "retry in a few seconds"},
        )

    async def complete(
        self, context: AccessContext, *, key: str, token: uuid.UUID, response: StoredResponse
    ) -> None:
        await self.store.complete(context, key=key, token=token, response=response)

    async def release(self, context: AccessContext, *, key: str, token: uuid.UUID) -> None:
        await self.store.release(context, key=key, token=token)
