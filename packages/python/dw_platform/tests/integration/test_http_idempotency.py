"""Integration: the HTTP idempotency store against real Postgres, as dw_app.

The unit tests prove the decision. This proves the storage the decision rests
on, against the role and the policies that will actually be in force:

* a replay returns the stored response;
* a key reused for a different request is refused;
* two tenants may spend the same key string without meeting;
* a reservation abandoned by a dead process can be taken over;
* the application role can use the table with no GRANT written for it — the
  baseline's ``ALTER DEFAULT PRIVILEGES`` carries, which is exactly the claim
  migration 0002 relies on by writing none.

Connecting as ``dw_app`` rather than the migrator is the point: the migrator
holds BYPASSRLS and would prove nothing about either privileges or isolation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, IdempotencyConflictError
from dw_kernel.ports import SystemClock
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.idempotency_store import SqlIdempotencyStore
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.idempotency import (
    STALE_RESERVATION,
    HttpIdempotency,
    RequestFingerprint,
    Reservation,
    StoredResponse,
)

pytestmark = pytest.mark.integration

TENANT_ONE = uuid.UUID(int=0x1DE0)
WORKSPACE_ONE = uuid.UUID(int=0x1DE1)
TENANT_TWO = uuid.UUID(int=0x1DF0)
WORKSPACE_TWO = uuid.UUID(int=0x1DF1)

# Long enough that "now minus this" is unambiguously older than the stale
# cutoff, without the test having to know the cutoff's exact value.
BACKDATE = STALE_RESERVATION * 2


def context_for(tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        plan_id="professional",
    )


CALLER_A = context_for(TENANT_ONE, WORKSPACE_ONE)
CALLER_B = context_for(TENANT_ONE, WORKSPACE_ONE)


def fingerprint(
    *, body: bytes = b'{"approve":true}', context: AccessContext = CALLER_A
) -> RequestFingerprint:
    return RequestFingerprint.of(
        context=context, method="POST", path="/api/v1/approvals/decisions", body=body
    )


async def reserved(idempotency: HttpIdempotency, context: AccessContext, key: str) -> Reservation:
    claimed = await idempotency.claim(context, key=key, fingerprint=fingerprint(context=context))
    assert isinstance(claimed, Reservation)
    return claimed


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Tenant + workspace rows to hang the foreign key on, created as dw_app."""
    factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    for tenant_id, workspace_id, slug in (
        (TENANT_ONE, WORKSPACE_ONE, "idem-tenant-one"),
        (TENANT_TWO, WORKSPACE_TWO, "idem-tenant-two"),
    ):
        async with tenant_session(factory, TenantScope(tenant_id=tenant_id)) as session:
            await session.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name) VALUES (:id, :slug, :slug) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(tenant_id), "slug": slug},
            )
            await session.execute(
                sa.text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name) "
                    "VALUES (:id, :tenant, 'main', 'Main') ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(workspace_id), "tenant": str(tenant_id)},
            )
    return factory


@pytest.fixture
def idempotency(sessions: async_sessionmaker[AsyncSession]) -> HttpIdempotency:
    return HttpIdempotency(store=SqlIdempotencyStore(sessions), clock=SystemClock())


async def backdate(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, key: str
) -> None:
    """Age a reservation past the takeover cutoff, as a dead process would."""
    async with tenant_session(sessions, TenantScope(tenant_id=tenant_id)) as session:
        await session.execute(
            sa.update(tables.idempotency_keys)
            .where(
                tables.idempotency_keys.c.tenant_id == tenant_id,
                tables.idempotency_keys.c.idempotency_key == key,
            )
            .values(created_at=sa.func.now() - BACKDATE)
        )


async def test_a_replay_returns_the_stored_response(idempotency: HttpIdempotency) -> None:
    context = CALLER_A
    key = "replay-me"
    body: dict[str, object] = {"id": "abc", "status": "approved"}

    held = await reserved(idempotency, context, key)
    await idempotency.complete(
        context,
        key=key,
        token=held.token,
        response=StoredResponse(
            status_code=201, body=body, headers={"ETag": '"3"', "Location": "/x/abc"}
        ),
    )

    replayed = await idempotency.claim(context, key=key, fingerprint=fingerprint())
    assert isinstance(replayed, StoredResponse)
    assert replayed.status_code == 201
    assert replayed.body == body
    assert replayed.headers == {"ETag": '"3"', "Location": "/x/abc"}


async def test_the_same_key_on_a_different_request_is_refused(
    idempotency: HttpIdempotency,
) -> None:
    context = CALLER_A
    key = "mismatched"

    await idempotency.claim(context, key=key, fingerprint=fingerprint(body=b'{"approve":true}'))

    with pytest.raises(IdempotencyConflictError):
        await idempotency.claim(
            context, key=key, fingerprint=fingerprint(body=b'{"approve":false}')
        )


async def test_a_second_request_while_the_first_is_in_flight_is_refused(
    idempotency: HttpIdempotency,
) -> None:
    """The reservation is committed before the handler runs, so it is visible."""
    context = CALLER_A
    key = "in-flight"

    await reserved(idempotency, context, key)
    with pytest.raises(ConflictError) as excinfo:
        await idempotency.claim(context, key=key, fingerprint=fingerprint())
    assert not isinstance(excinfo.value, IdempotencyConflictError), "in flight, not a mismatch"


async def test_an_abandoned_reservation_can_be_taken_over(
    idempotency: HttpIdempotency, sessions: async_sessionmaker[AsyncSession]
) -> None:
    context = CALLER_A
    key = "abandoned"

    await reserved(idempotency, context, key)
    await backdate(sessions, TENANT_ONE, key)

    taken = await idempotency.claim(context, key=key, fingerprint=fingerprint())
    assert isinstance(taken, Reservation) and taken.taken_over


async def test_releasing_lets_the_key_be_spent_again(idempotency: HttpIdempotency) -> None:
    context = CALLER_A
    key = "released"

    held = await reserved(idempotency, context, key)
    await idempotency.release(context, key=key, token=held.token)

    again = await idempotency.claim(context, key=key, fingerprint=fingerprint())
    assert isinstance(again, Reservation) and not again.taken_over


async def test_two_tenants_may_spend_the_same_key_string(idempotency: HttpIdempotency) -> None:
    """The primary key is (tenant, key). Clients choose keys without coordinating."""
    key = "1"
    one = context_for(TENANT_ONE, WORKSPACE_ONE)
    two = context_for(TENANT_TWO, WORKSPACE_TWO)

    await reserved(idempotency, one, key)
    assert isinstance(
        await idempotency.claim(two, key=key, fingerprint=fingerprint(context=two)), Reservation
    ), "tenant two's identical key must not collide with tenant one's"


async def test_one_tenant_cannot_see_another_tenants_keys(
    idempotency: HttpIdempotency, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """RLS, not the query, is what keeps the rows apart."""
    key = "isolated"
    await reserved(idempotency, CALLER_A, key)

    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_TWO)) as session:
        rows = (
            await session.execute(
                sa.select(tables.idempotency_keys.c.tenant_id).where(
                    tables.idempotency_keys.c.idempotency_key == key
                )
            )
        ).all()
    assert rows == []


async def row(
    sessions: async_sessionmaker[AsyncSession], key: str
) -> sa.Row[tuple[object, ...]] | None:
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_ONE)) as session:
        return (
            await session.execute(
                sa.select(
                    tables.idempotency_keys.c.caller_ref,
                    tables.idempotency_keys.c.reservation_token,
                    tables.idempotency_keys.c.created_at,
                    tables.idempotency_keys.c.response_status,
                ).where(
                    tables.idempotency_keys.c.tenant_id == TENANT_ONE,
                    tables.idempotency_keys.c.idempotency_key == key,
                )
            )
        ).one_or_none()


async def test_a_take_over_fences_the_request_that_lost_it(
    idempotency: HttpIdempotency, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """app-standards R2.4, R2.5 (APS5): the take-over gets a new token, a fresh
    `created_at` and the same caller; the old request's late `complete` and
    `release` change nothing."""
    key = "fenced"
    old = await reserved(idempotency, CALLER_A, key)
    await backdate(sessions, TENANT_ONE, key)
    before = await row(sessions, key)
    taken = await idempotency.claim(CALLER_A, key=key, fingerprint=fingerprint())
    assert isinstance(taken, Reservation)

    after = await row(sessions, key)
    assert before is not None and after is not None
    assert after.reservation_token == taken.token != old.token
    assert after.created_at > before.created_at
    assert after.caller_ref == before.caller_ref == f"user:{CALLER_A.principal_id}"

    await idempotency.complete(
        CALLER_A, key=key, token=old.token, response=StoredResponse(status_code=200, body={})
    )
    await idempotency.release(CALLER_A, key=key, token=old.token)
    untouched = await row(sessions, key)
    assert untouched is not None and untouched.response_status is None


async def test_another_caller_cannot_take_an_abandoned_reservation_over(
    idempotency: HttpIdempotency, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R2.10 (APS13): B is refused, and asking the store directly changes no
    column of A's row."""
    key = "not-yours"
    await reserved(idempotency, CALLER_A, key)
    await backdate(sessions, TENANT_ONE, key)
    before = await row(sessions, key)

    with pytest.raises(IdempotencyConflictError):
        await idempotency.claim(CALLER_B, key=key, fingerprint=fingerprint(context=CALLER_B))
    won = await SqlIdempotencyStore(sessions).take_over(
        CALLER_B,
        key=key,
        fingerprint=fingerprint(context=CALLER_B),
        older_than=datetime.now(UTC),
    )

    assert won is None
    assert await row(sessions, key) == before


async def test_two_take_overs_of_one_reservation_have_one_winner(
    idempotency: HttpIdempotency, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R2.19 (APS20): two real concurrent take-overs by the same caller; one wins
    and the other is told the key is still in progress."""
    key = "raced"
    await reserved(idempotency, CALLER_A, key)
    await backdate(sessions, TENANT_ONE, key)

    outcomes = await asyncio.gather(
        idempotency.claim(CALLER_A, key=key, fingerprint=fingerprint()),
        idempotency.claim(CALLER_A, key=key, fingerprint=fingerprint()),
        return_exceptions=True,
    )

    assert sum(isinstance(o, Reservation) for o in outcomes) == 1
    assert sum(type(o) is ConflictError for o in outcomes) == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("caller_ref", "'someone'"),
        ("response_headers", """'{"Set-Cookie": "x"}'::jsonb"""),
    ],
)
async def test_the_database_refuses_a_malformed_caller_or_header(
    sessions: async_sessionmaker[AsyncSession], column: str, value: str
) -> None:
    """R2.20: the CHECKs, not the code, hold the caller's shape and the two
    headers a replay may carry."""
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_ONE)) as session:
        with pytest.raises(Exception, match=f"ck_idempotency_keys_{column}"):
            await session.execute(
                sa.text(
                    "INSERT INTO platform.idempotency_keys (tenant_id, idempotency_key,"
                    " workspace_id, request_method, request_path, body_hash, "
                    f"{column}) VALUES (:t, 'bad-row', :w, 'POST', '/x', 'h', {value})"
                ),
                {"t": str(TENANT_ONE), "w": str(WORKSPACE_ONE)},
            )


async def test_setting_worker_drain_reads_no_other_tenants_keys(
    idempotency: HttpIdempotency, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R2.12 (APS12): no drain policy opens this table to `dw_app`."""
    await reserved(idempotency, CALLER_A, "drained")

    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_TWO)) as session:
        await session.execute(sa.text("SELECT set_config('app.worker_drain', 'on', true)"))
        seen = await session.scalar(
            sa.text("SELECT count(*) FROM platform.idempotency_keys WHERE tenant_id = :t"),
            {"t": str(TENANT_ONE)},
        )
    assert seen == 0
