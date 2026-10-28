"""The effect half of an idempotent request (app-standards R2.16, R2.23).

`platform.idempotency_keys` remembers what a request answered; it is released
when a handler fails, so a client's retry gets a fresh attempt. That is right
for a failure before the effect, and wrong for one after it: the effect has
committed, the key is gone, and the retry would do it again. So every operation
that takes a key also writes an *effect key* in the effect's own transaction,
and a retry that finds one is answered with the effect that exists.

Three outcomes, decided by one rule (:func:`existing_effect`), wherever the row
is met:

* no row (or an expired one, under a fresh reservation, R2.37) — run the effect;
* a row of the same caller for the same request — :class:`ExistingEffect`, and
  the route reads the resource back under the caller's current authority (R2.29);
* a row of anyone else, or for a different request — 409 `idempotency_conflict`,
  carrying nothing of the effect (R2.23).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from dw_kernel.errors import IdempotencyConflictError
from dw_platform.application.access_context import AccessContext


@dataclass(frozen=True)
class EffectKey:
    """Which effect a request may claim, and whether its HTTP reservation is new.

    ``operation`` is the route's method and path template, fixed where the route
    declares it, so a parameter renamed in the URL does not change it."""

    operation: str
    idempotency_key: str
    caller_ref: str
    request_hash: str
    # True when the HTTP reservation was a fresh insert, False when it took over
    # an abandoned one of the same caller: only a fresh one may treat an
    # expired effect key as unused (R2.37), because a take-over's own earlier
    # attempt may be the effect that row records (R2.31).
    fresh: bool


@dataclass(frozen=True)
class EffectResult:
    """What an effect produced: the first response's status and the resource's
    id. Never a body: the resource is read back on a retry (R2.29)."""

    status: int
    id: str


@dataclass(frozen=True)
class PendingEffect:
    """An effect key and the status its route answers with; the service names
    the resource, which only it knows before the write (a new id, a user found
    by email)."""

    key: EffectKey
    status: int

    def of(self, resource_id: object) -> EffectClaim:
        return EffectClaim(
            key=self.key, result=EffectResult(status=self.status, id=str(resource_id))
        )


@dataclass(frozen=True)
class EffectClaim:
    """The row a service writes first in its effect's transaction."""

    key: EffectKey
    result: EffectResult


class ExistingEffect(Exception):  # noqa: N818 — a control-flow signal, not a failure
    """The same caller's same request already had its effect: answer with it."""

    def __init__(self, result: EffectResult) -> None:
        super().__init__("the effect already exists")
        self.result = result


def existing_effect(
    key: EffectKey, *, caller_ref: str, request_hash: str, result: EffectResult
) -> ExistingEffect:
    """The one rule for a row already there: the same caller's same request is
    its effect; anything else is a conflict that says nothing of the effect."""
    if caller_ref != key.caller_ref or request_hash != key.request_hash:
        raise IdempotencyConflictError(
            "idempotency key already used for a different request",
            details={"hint": "use a new key for a new request, or resend the original one"},
        )
    return ExistingEffect(result)


class EffectKeyPort(Protocol):
    """Looks an effect key up before the operation reads any state, so a retry
    of an effect that changed that state meets its effect, not a refusal of the
    state it left behind (a grant no longer pending, a run no longer waiting)."""

    async def existing(self, context: AccessContext, key: EffectKey) -> EffectResult | None:
        """The effect of the same caller's same request, or None when there is
        none to answer with; a row of anyone else is a conflict."""
        ...


class EffectKeyWriterPort(Protocol):
    """The insert, inside the effect's own transaction and before any of its
    writes or row locks (R2.38): a concurrent attempt of the same key waits at
    the primary key and then meets this one's effect (R2.33)."""

    async def claim(self, claim: EffectClaim) -> None: ...
