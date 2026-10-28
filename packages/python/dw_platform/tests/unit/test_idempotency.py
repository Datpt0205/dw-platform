"""Unit: the three answers an idempotency key can get, and the two edges.

A fake store, no database. What matters here is the decision — replay, conflict,
or run — because that is what a route inherits and what a client's retry policy
is written against.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.errors import ConflictError, IdempotencyConflictError
from dw_kernel.ports import FixedClock
from dw_platform.application.access_context import AccessContext, SupportScope
from dw_platform.application.idempotency import (
    STALE_RESERVATION,
    HttpIdempotency,
    RequestFingerprint,
    Reservation,
    ReservedKey,
    StoredResponse,
    caller_ref,
)

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
OTHER_WORKSPACE = uuid.uuid4()
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
KEY = "retry-me-once"
TOKEN = uuid.uuid4()

CONTEXT = AccessContext(
    tenant_id=TENANT,
    workspace_id=WORKSPACE,
    principal_id=uuid.uuid4(),
    roles=frozenset({"org_admin"}),
    plan_id="professional",
)
SOMEONE_ELSE = CONTEXT.model_copy(update={"principal_id": uuid.uuid4()})


def fingerprint(
    *,
    body: bytes = b'{"approve":true}',
    context: AccessContext = CONTEXT,
    if_match: str | None = None,
) -> RequestFingerprint:
    return RequestFingerprint.of(
        context=context,
        method="post",
        path="/api/v1/approvals/1/decisions",
        body=body,
        if_match=if_match,
    )


class FakeStore:
    """One key's worth of state, plus what was asked of it."""

    def __init__(self, existing: ReservedKey | None = None, *, takeover_wins: bool = False) -> None:
        self.existing = existing
        self.takeover_wins = takeover_wins
        self.completed: tuple[uuid.UUID, StoredResponse] | None = None
        self.released: uuid.UUID | None = None
        self.take_over_calls: list[tuple[datetime, RequestFingerprint]] = []

    async def reserve(
        self, context: AccessContext, *, key: str, fingerprint: RequestFingerprint
    ) -> uuid.UUID | ReservedKey:
        return TOKEN if self.existing is None else self.existing

    async def take_over(
        self,
        context: AccessContext,
        *,
        key: str,
        fingerprint: RequestFingerprint,
        older_than: datetime,
    ) -> uuid.UUID | None:
        self.take_over_calls.append((older_than, fingerprint))
        return TOKEN if self.takeover_wins else None

    async def complete(
        self, context: AccessContext, *, key: str, token: uuid.UUID, response: StoredResponse
    ) -> None:
        self.completed = (token, response)

    async def release(self, context: AccessContext, *, key: str, token: uuid.UUID) -> None:
        self.released = token


def build(store: FakeStore) -> HttpIdempotency:
    return HttpIdempotency(store=store, clock=FixedClock(NOW))


async def test_an_unspent_key_lets_the_handler_run() -> None:
    claimed = await build(FakeStore(existing=None)).claim(
        CONTEXT, key=KEY, fingerprint=fingerprint()
    )

    assert claimed == Reservation(token=TOKEN, taken_over=False)


async def test_the_same_request_twice_replays_the_stored_response() -> None:
    stored = StoredResponse(status_code=200, body={"status": "approved"})
    idempotency = build(FakeStore(ReservedKey(fingerprint=fingerprint(), response=stored)))

    assert await idempotency.claim(CONTEXT, key=KEY, fingerprint=fingerprint()) == stored


async def test_a_different_body_under_the_same_key_is_refused() -> None:
    """The client reused a key for a new request. Answering it would hide that."""
    first = ReservedKey(
        fingerprint=fingerprint(body=b'{"approve":true}'),
        response=StoredResponse(status_code=200, body={"status": "approved"}),
    )

    with pytest.raises(IdempotencyConflictError):
        await build(FakeStore(first)).claim(
            CONTEXT, key=KEY, fingerprint=fingerprint(body=b'{"approve":false}')
        )


async def test_the_same_key_in_another_workspace_is_refused() -> None:
    """A key is tenant-scoped, so this is a conflict — never a cross-workspace replay."""
    elsewhere = CONTEXT.model_copy(update={"workspace_id": OTHER_WORKSPACE})
    first = ReservedKey(
        fingerprint=fingerprint(context=elsewhere),
        response=StoredResponse(status_code=200, body={"status": "approved"}),
    )

    with pytest.raises(IdempotencyConflictError):
        await build(FakeStore(first)).claim(CONTEXT, key=KEY, fingerprint=fingerprint())


async def test_another_callers_key_is_a_conflict_with_nothing_of_theirs() -> None:
    """app-standards R2.2: B sends A's key and body and gets 409, not A's answer."""
    first = ReservedKey(
        fingerprint=fingerprint(),
        response=StoredResponse(status_code=200, body={"status": "approved"}),
    )

    with pytest.raises(IdempotencyConflictError) as refused:
        await build(FakeStore(first)).claim(
            SOMEONE_ELSE, key=KEY, fingerprint=fingerprint(context=SOMEONE_ELSE)
        )
    assert "approved" not in str(refused.value.details)


async def test_a_row_from_before_callers_were_bound_replays_to_nobody() -> None:
    """R2.3: `caller_ref = ''` equals no real caller, not every caller."""
    legacy = fingerprint()
    legacy = RequestFingerprint(
        method=legacy.method,
        path=legacy.path,
        workspace_id=legacy.workspace_id,
        body_hash=legacy.body_hash,
        caller_ref="",
    )
    first = ReservedKey(
        fingerprint=legacy, response=StoredResponse(status_code=200, body={"status": "approved"})
    )

    with pytest.raises(IdempotencyConflictError):
        await build(FakeStore(first)).claim(CONTEXT, key=KEY, fingerprint=fingerprint())


async def test_a_different_precondition_under_the_same_key_is_refused() -> None:
    """R2.1: `If-Match` is part of what the key was spent on."""
    first = ReservedKey(
        fingerprint=fingerprint(if_match='"7"'),
        response=StoredResponse(status_code=200, body={"version": 8}),
    )

    with pytest.raises(IdempotencyConflictError):
        await build(FakeStore(first)).claim(
            CONTEXT, key=KEY, fingerprint=fingerprint(if_match='"6"')
        )


async def test_a_request_still_in_flight_is_refused_rather_than_run_again() -> None:
    """The second of two concurrent retries must not reach the handler."""
    store = FakeStore(ReservedKey(fingerprint=fingerprint(), response=None), takeover_wins=False)

    with pytest.raises(ConflictError) as excinfo:
        await build(store).claim(CONTEXT, key=KEY, fingerprint=fingerprint())

    assert excinfo.value.code.value == "conflict"
    assert store.completed is None


async def test_an_abandoned_reservation_is_taken_over_by_its_own_caller() -> None:
    """A process killed mid-handler must not brick the key forever; the store
    is asked with the caller's fingerprint, which it matches (R2.10)."""
    store = FakeStore(ReservedKey(fingerprint=fingerprint(), response=None), takeover_wins=True)

    claimed = await build(store).claim(CONTEXT, key=KEY, fingerprint=fingerprint())

    assert claimed == Reservation(token=TOKEN, taken_over=True)
    assert store.take_over_calls == [(NOW - STALE_RESERVATION, fingerprint())]


async def test_another_callers_abandoned_reservation_is_never_asked_for() -> None:
    store = FakeStore(ReservedKey(fingerprint=fingerprint(), response=None), takeover_wins=True)

    with pytest.raises(IdempotencyConflictError):
        await build(store).claim(
            SOMEONE_ELSE, key=KEY, fingerprint=fingerprint(context=SOMEONE_ELSE)
        )
    assert store.take_over_calls == []


async def test_a_takeover_cutoff_is_in_the_past() -> None:
    """Guards the sign of the subtraction: a future cutoff would steal live keys."""
    store = FakeStore(ReservedKey(fingerprint=fingerprint(), response=None), takeover_wins=True)
    await build(store).claim(CONTEXT, key=KEY, fingerprint=fingerprint())

    cutoff = store.take_over_calls[0][0]
    assert cutoff < NOW
    assert NOW - cutoff >= timedelta(minutes=1)


async def test_completing_and_releasing_carry_the_reservations_token() -> None:
    store = FakeStore()
    response = StoredResponse(status_code=201, body={"user_id": "u-1"})

    await build(store).complete(CONTEXT, key=KEY, token=TOKEN, response=response)
    await build(store).release(CONTEXT, key=KEY, token=TOKEN)

    assert store.completed == (TOKEN, response)
    assert store.released == TOKEN


def test_the_fingerprint_normalises_the_method_but_not_the_body() -> None:
    """Method case is HTTP's business. Body bytes are compared as they arrived."""
    assert fingerprint().method == "POST"
    assert fingerprint(body=b'{"a":1,"b":2}') != fingerprint(body=b'{"b":2,"a":1}')


def test_a_caller_is_a_principal_or_a_support_grant() -> None:
    """R2.20: a service principal is a principal; R2.2: under support access the
    grant is the caller, so two grants of one person are two callers."""
    grant = uuid.uuid4()
    supporting = CONTEXT.model_copy(
        update={
            "support": SupportScope(
                grant_id=grant,
                code="SUP-1",
                resource_type="workspace",
                resource_id=None,
                scope_set_key="read",
            )
        }
    )

    assert caller_ref(CONTEXT) == f"user:{CONTEXT.principal_id}"
    assert caller_ref(supporting) == f"support:{grant}"


def test_the_request_hash_is_the_fingerprint_without_its_caller() -> None:
    """R2.23: an effect key compares the caller on its own, and every other part
    of the request through this hash."""
    assert fingerprint().request_hash() == fingerprint(context=SOMEONE_ELSE).request_hash()
    elsewhere = CONTEXT.model_copy(update={"workspace_id": OTHER_WORKSPACE})
    for other in (
        fingerprint(body=b"{}"),
        fingerprint(if_match='"1"'),
        fingerprint(context=elsewhere),
    ):
        assert other.request_hash() != fingerprint().request_hash()
