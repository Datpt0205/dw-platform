"""Integration: `platform.effect_keys` against real Postgres, as dw_app.

The effect half of an idempotent request (app-standards R2.16, R2.23-R2.25,
R2.31, R2.33, R2.37-R2.40): the row an operation writes first in its effect's
own transaction, the look-up before it reads state, and the purge. What is
proved here is the table's rule; the nine operations that write it are proved
over HTTP in `apps/api/tests/integration`.

Rows are aged as the migrator, which holds BYPASSRLS: `dw_app` may not update an
effect key, which is the point (3c54129c940c).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from collections.abc import AsyncIterator

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
from dw_platform.adapters.persistence.effect_key_store import (
    SqlEffectKeyLookup,
    SqlEffectKeyRetention,
    claim_effect_key,
)
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import (
    EffectKey,
    EffectResult,
    ExistingEffect,
    PendingEffect,
)

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID(int=0xEFA0)
WORKSPACE_A = uuid.UUID(int=0xEFA1)
TENANT_B = uuid.UUID(int=0xEFB0)
WORKSPACE_B = uuid.UUID(int=0xEFB1)
CALLER = f"user:{uuid.UUID(int=0xEFC1)}"
OTHER_CALLER = f"user:{uuid.UUID(int=0xEFC2)}"
HASH = "a" * 64
OTHER_HASH = "b" * 64


def context_for(tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        plan_id="professional",
    )


A = context_for(TENANT_A, WORKSPACE_A)
B = context_for(TENANT_B, WORKSPACE_B)


def effect_key(
    key: str,
    *,
    caller: str = CALLER,
    request_hash: str = HASH,
    fresh: bool = True,
    operation: str = "POST /probe",
) -> EffectKey:
    return EffectKey(
        operation=operation,
        idempotency_key=key,
        caller_ref=caller,
        request_hash=request_hash,
        fresh=fresh,
    )


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    for tenant_id, workspace_id, slug in (
        (TENANT_A, WORKSPACE_A, "effect-tenant-a"),
        (TENANT_B, WORKSPACE_B, "effect-tenant-b"),
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


async def claim(
    sessions: async_sessionmaker[AsyncSession],
    context: AccessContext,
    key: EffectKey,
    resource_id: str = "r-1",
) -> None:
    async with tenant_session(sessions, TenantScope.from_access_context(context)) as session:
        await claim_effect_key(session, PendingEffect(key=key, status=201).of(resource_id))


async def age(migrator: AsyncEngine, key: str, hours: int) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.effect_keys SET created_at = now() - make_interval(hours => :h)"
                " WHERE idempotency_key = :k"
            ),
            {"h": hours, "k": key},
        )


async def stored(migrator: AsyncEngine, key: str) -> list[sa.Row[tuple[object, ...]]]:
    async with migrator.connect() as conn:
        return list(
            await conn.execute(
                sa.text(
                    "SELECT tenant_id, request_hash, result FROM platform.effect_keys"
                    " WHERE idempotency_key = :k ORDER BY tenant_id"
                ),
                {"k": key},
            )
        )


async def test_the_same_callers_same_request_meets_its_effect(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    key = effect_key(f"same-{uuid.uuid4()}")
    await claim(sessions, A, key, "member-1")

    with pytest.raises(ExistingEffect) as met:
        await claim(sessions, A, key, "member-2")

    assert met.value.result == EffectResult(status=201, id="member-1")
    assert await SqlEffectKeyLookup(sessions).existing(A, key) == met.value.result


@pytest.mark.parametrize(
    "other",
    [
        effect_key("{name}", caller=OTHER_CALLER),
        effect_key("{name}", request_hash=OTHER_HASH),
    ],
    ids=["another caller", "another request"],
)
async def test_anyone_else_or_any_other_request_is_a_conflict_with_nothing_of_it(
    sessions: async_sessionmaker[AsyncSession], other: EffectKey
) -> None:
    """R2.23 (APS24): 409, and the refusal carries no part of the effect."""
    name = f"theirs-{uuid.uuid4()}"
    await claim(sessions, A, effect_key(name), "member-1")

    theirs = dataclasses.replace(other, idempotency_key=name)
    for attempt in (claim(sessions, A, theirs), SqlEffectKeyLookup(sessions).existing(A, theirs)):
        with pytest.raises(IdempotencyConflictError) as refused:
            await attempt
        assert "member-1" not in str(refused.value.details)


async def test_another_tenant_never_meets_this_tenants_effect_key(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.24 (APS26): B's effect is written as if the key were unused, A's row
    is unchanged, and B reads none of A's rows, even with `app.worker_drain`."""
    name = f"tenant-{uuid.uuid4()}"
    await claim(sessions, A, effect_key(name), "a-thing")
    await claim(sessions, B, effect_key(name, caller=OTHER_CALLER), "b-thing")

    rows = await stored(migrator, name)
    assert {(row.tenant_id, row.result["id"]) for row in rows} == {
        (TENANT_A, "a-thing"),
        (TENANT_B, "b-thing"),
    }
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_B)) as session:
        await session.execute(sa.text("SELECT set_config('app.worker_drain', 'on', true)"))
        seen = await session.scalar(
            sa.text("SELECT count(*) FROM platform.effect_keys WHERE tenant_id = :t"),
            {"t": str(TENANT_A)},
        )
    assert seen == 0


async def test_the_database_refuses_a_result_that_is_more_than_status_and_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R2.24: no body is ever stored beside an effect, by CHECK."""
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_A)) as session:
        with pytest.raises(Exception, match="ck_effect_keys_result"):
            await session.execute(
                sa.text(
                    "INSERT INTO platform.effect_keys (tenant_id, operation, idempotency_key,"
                    " caller_ref, request_hash, result) VALUES (:t, 'POST /probe', 'bodied',"
                    " :c, :h, CAST(:r AS jsonb))"
                ),
                {
                    "t": str(TENANT_A),
                    "c": CALLER,
                    "h": HASH,
                    "r": '{"status": 201, "id": "x", "body": {"email": "a@b.c"}}',
                },
            )


async def test_a_concurrent_attempt_waits_then_meets_the_first_effect(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R2.33, R2.38 (APS37): the first attempt holds its transaction open after
    its effect key; the second waits at the primary key, and when the first
    commits it meets that effect instead of failing on the effect's own rows."""
    key = effect_key(f"race-{uuid.uuid4()}")
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_A)) as first:
        await claim_effect_key(first, PendingEffect(key=key, status=201).of("first"))
        second = asyncio.create_task(claim(sessions, A, key, "second"))
        await asyncio.sleep(0.5)
        assert not second.done(), "the second attempt must wait for the first"
    with pytest.raises(ExistingEffect) as met:
        await second
    assert met.value.result.id == "first"


async def test_a_wait_past_five_seconds_is_refused_as_still_in_progress(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R2.39 (APS37): the wait is bounded; the second attempt writes nothing."""
    key = effect_key(f"slow-{uuid.uuid4()}")
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_A)) as first:
        await claim_effect_key(first, PendingEffect(key=key, status=201).of("first"))
        with pytest.raises(ConflictError) as refused:
            await asyncio.wait_for(claim(sessions, A, key, "second"), timeout=15)
        assert type(refused.value) is ConflictError


async def test_an_expired_key_under_a_fresh_reservation_is_replaced(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.37 (APS42): past its term, with no HTTP key row, the key is unused
    even before the retention lane runs, for the same caller's new request."""
    name = f"expired-{uuid.uuid4()}"
    await claim(sessions, A, effect_key(name), "old")
    await age(migrator, name, 25)

    assert (
        await SqlEffectKeyLookup(sessions).existing(A, effect_key(name, request_hash=OTHER_HASH))
        is None
    )
    await claim(sessions, A, effect_key(name, request_hash=OTHER_HASH), "new")

    [row] = await stored(migrator, name)
    assert (row.request_hash, row.result["id"]) == (OTHER_HASH, "new")


async def test_an_expired_key_under_a_take_over_is_kept(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.37, R2.31 (APS34): a reservation taken over late may be the attempt
    that made this effect, so its retry meets the effect."""
    name = f"taken-{uuid.uuid4()}"
    await claim(sessions, A, effect_key(name), "made")
    await age(migrator, name, 25)

    late = effect_key(name, fresh=False)
    assert await SqlEffectKeyLookup(sessions).existing(A, late) == EffectResult(201, "made")
    with pytest.raises(ExistingEffect):
        await claim(sessions, A, late, "again")


async def test_a_missing_term_fails_closed_and_removes_nothing(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.40, R2.15: with no term loaded, neither the route nor the purge
    decides a row has expired."""
    name = f"termless-{uuid.uuid4()}"
    await claim(sessions, A, effect_key(name), "kept")
    await age(migrator, name, 25)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.retention_terms WHERE store_key = 'platform.effect_keys'")
        )
    try:
        with pytest.raises(Exception, match="no retention term"):
            await claim(sessions, A, effect_key(name, request_hash=OTHER_HASH), "replacement")
        async with sessions() as session:
            with pytest.raises(Exception, match="no retention term"):
                await session.execute(sa.text("SELECT platform.purge_expired_effect_keys()"))
    finally:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.retention_terms VALUES ('platform.effect_keys', 1)"
                    " ON CONFLICT DO NOTHING"
                )
            )
    [row] = await stored(migrator, name)
    assert row.result["id"] == "kept"


async def test_the_purge_removes_only_expired_keys_whose_http_key_is_gone(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.25, R2.31 (APS31, APS34): 25-hour rows of two tenants go, a 1-hour row
    stays, an expired row whose HTTP key still lives stays; only a count comes
    back."""
    tag = uuid.uuid4().hex[:8]
    gone_a, gone_b, young, held = (f"{n}-{tag}" for n in ("gone-a", "gone-b", "young", "held"))
    await claim(sessions, A, effect_key(gone_a))
    await claim(sessions, B, effect_key(gone_b))
    await claim(sessions, A, effect_key(young))
    await claim(sessions, A, effect_key(held))
    for name in (gone_a, gone_b, held):
        await age(migrator, name, 25)
    await age(migrator, young, 1)
    async with tenant_session(sessions, TenantScope(tenant_id=TENANT_A)) as session:
        await session.execute(
            sa.text(
                "INSERT INTO platform.idempotency_keys (tenant_id, idempotency_key, workspace_id,"
                " request_method, request_path, body_hash) VALUES (:t, :k, :w, 'POST', '/p', 'h')"
            ),
            {"t": str(TENANT_A), "k": held, "w": str(WORKSPACE_A)},
        )

    async with sessions() as session, session.begin():
        removed = (
            await session.execute(sa.text("SELECT platform.purge_expired_effect_keys()"))
        ).one()

    assert len(removed) == 1 and isinstance(removed[0], int) and removed[0] >= 2
    for name, left in ((gone_a, 0), (gone_b, 0), (young, 1), (held, 1)):
        assert len(await stored(migrator, name)) == left, name


async def test_the_registered_purger_logs_a_count_and_writes_no_audit_row(
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R2.9: housekeeping of operational rows (`CLAUDE.md` "Agent and tool
    rules"; ADR-0011 "Not applied")."""
    name = f"logged-{uuid.uuid4()}"
    await claim(sessions, A, effect_key(name))
    await age(migrator, name, 25)
    async with migrator.connect() as conn:
        audits = await conn.scalar(sa.text("SELECT count(*) FROM platform.audit_events"))

    with caplog.at_level(logging.INFO):
        await SqlEffectKeyRetention(sessions).purge()

    purged = [r for r in caplog.records if r.getMessage() == "effect keys purged"]
    assert purged and vars(purged[0])["deleted"] >= 1
    async with migrator.connect() as conn:
        assert await conn.scalar(sa.text("SELECT count(*) FROM platform.audit_events")) == audits
    assert await stored(migrator, name) == []
