"""`RateLimiterPort` and its counter per process (usage-and-limits R7, UL14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.ids import TenantId, UserId
from dw_kernel.ports import FixedClock
from dw_platform.adapters.rate_limit import InProcessRateLimiter
from dw_platform.application.rate_limit import (
    PrincipalObjectKey,
    RateDecision,
    RateLimiterPort,
    SourceKey,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
TEN_MINUTES = timedelta(minutes=10)


def _limiter(replicas: int = 1) -> tuple[InProcessRateLimiter, FixedClock]:
    clock = FixedClock(T0)
    return InProcessRateLimiter(replicas=replicas, clock=clock), clock


def _source(tenant: TenantId | None = None, source: uuid.UUID | None = None) -> SourceKey:
    return SourceKey(tenant or TenantId(uuid.uuid4()), source or uuid.uuid4())


async def _acquire_n(
    limiter: RateLimiterPort, key: SourceKey | PrincipalObjectKey, n: int, limit: int, window
) -> list[RateDecision]:
    return [await limiter.acquire(key, limit, window) for _ in range(n)]


def test_the_adapter_is_a_rate_limiter_port() -> None:
    limiter: RateLimiterPort = _limiter()[0]
    assert limiter is not None


# ---- R7.1: a process's share is floor(limit / replicas) -----------------------


async def test_with_two_replicas_the_thirtieth_call_passes_and_the_thirty_first_waits() -> None:
    limiter, clock = _limiter(replicas=2)
    key = _source()
    decisions = await _acquire_n(limiter, key, 30, 60, MINUTE)
    assert all(d.allowed for d in decisions)

    clock.advance_to(T0 + timedelta(seconds=30))
    refused = await limiter.acquire(key, 60, MINUTE)
    assert refused == RateDecision(allowed=False, retry_at=T0 + MINUTE)

    clock.advance_to(T0 + MINUTE)
    assert (await limiter.acquire(key, 60, MINUTE)).allowed


async def test_with_one_replica_the_sixtieth_call_passes_and_the_sixty_first_waits() -> None:
    limiter, _ = _limiter(replicas=1)
    key = _source()
    decisions = await _acquire_n(limiter, key, 60, 60, MINUTE)
    assert all(d.allowed for d in decisions)
    refused = await limiter.acquire(key, 60, MINUTE)
    assert not refused.allowed
    assert refused.retry_at == T0 + MINUTE


async def test_a_refused_call_counts_nothing_so_the_oldest_leaving_lets_one_in() -> None:
    """M2: a caller who keeps trying is let in at the `retry_at` it was given."""
    limiter, clock = _limiter()
    key = _source()
    await limiter.acquire(key, 2, MINUTE)
    clock.advance_to(T0 + timedelta(seconds=10))
    await limiter.acquire(key, 2, MINUTE)
    for second in range(11, 60):
        clock.advance_to(T0 + timedelta(seconds=second))
        assert not (await limiter.acquire(key, 2, MINUTE)).allowed
    clock.advance_to(T0 + MINUTE)
    assert (await limiter.acquire(key, 2, MINUTE)).allowed
    assert not (await limiter.acquire(key, 2, MINUTE)).allowed


async def test_a_limit_below_the_replica_count_refuses_every_call() -> None:
    """M3: a share of zero fails closed, never rounded up to one."""
    limiter, _ = _limiter(replicas=3)
    key = _source()
    assert await limiter.acquire(key, 2, MINUTE) == RateDecision(allowed=False, retry_at=None)
    assert await limiter.peek(key, 2, MINUTE) == RateDecision(allowed=False, retry_at=None)


@pytest.mark.parametrize("replicas", [0, -1, True, 1.5])
def test_a_replica_count_that_is_not_a_positive_int_is_refused(replicas: object) -> None:
    with pytest.raises(ValueError, match="replicas"):
        InProcessRateLimiter(replicas=replicas, clock=FixedClock(T0))  # type: ignore[arg-type]


async def test_a_negative_limit_or_an_empty_window_is_refused() -> None:
    limiter, _ = _limiter()
    with pytest.raises(ValueError, match="limit"):
        await limiter.acquire(_source(), -1, MINUTE)
    with pytest.raises(ValueError, match="window"):
        await limiter.peek(_source(), 1, timedelta(0))


# ---- R7.2: the key is typed and verified, never a string -----------------------


async def test_two_source_keys_built_apart_from_one_source_share_one_counter() -> None:
    """Two requests carrying two bearers build two keys from the same verified
    (tenant, source); both count in one bucket."""
    limiter, _ = _limiter()
    tenant_raw, source = uuid.uuid4(), uuid.uuid4()
    first = SourceKey(TenantId(tenant_raw), source)
    second = SourceKey(TenantId(uuid.UUID(str(tenant_raw))), uuid.UUID(str(source)))
    assert first is not second
    assert (await limiter.acquire(first, 2, MINUTE)).allowed
    assert (await limiter.acquire(second, 2, MINUTE)).allowed
    assert not (await limiter.acquire(first, 2, MINUTE)).allowed
    assert not (await limiter.peek(second, 2, MINUTE)).allowed


def test_a_source_key_carrying_a_bearer_hash_is_refused() -> None:
    with pytest.raises(TypeError, match="source_id"):
        SourceKey(TenantId(uuid.uuid4()), "băm-bearer")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "build",
    [
        lambda: SourceKey(uuid.uuid4(), uuid.uuid4()),  # type: ignore[arg-type]
        lambda: SourceKey(UserId(uuid.uuid4()), uuid.uuid4()),  # type: ignore[arg-type]
        lambda: PrincipalObjectKey(TenantId(uuid.uuid4()), "người", uuid.uuid4()),  # type: ignore[arg-type]
        lambda: PrincipalObjectKey(TenantId(uuid.uuid4()), uuid.uuid4(), str(uuid.uuid4())),  # type: ignore[arg-type]
        lambda: PrincipalObjectKey("tenant", uuid.uuid4(), uuid.uuid4()),  # type: ignore[arg-type]
    ],
)
def test_a_key_field_of_the_wrong_type_is_refused(build) -> None:
    with pytest.raises(TypeError):
        build()


@pytest.mark.parametrize("key", ["chuỗi", ("tenant", "source"), uuid.uuid4()])
async def test_the_adapter_refuses_a_key_that_is_not_a_rate_limit_key(key: object) -> None:
    limiter, _ = _limiter()
    with pytest.raises(TypeError, match="RateLimitKey"):
        await limiter.acquire(key, 60, MINUTE)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RateLimitKey"):
        await limiter.peek(key, 60, MINUTE)  # type: ignore[arg-type]
    assert len(limiter) == 0


async def test_another_person_or_another_object_counts_apart() -> None:
    limiter, _ = _limiter()
    tenant = TenantId(uuid.uuid4())
    person, other_person, obj, other_obj = (uuid.uuid4() for _ in range(4))
    key = PrincipalObjectKey(tenant, person, obj)
    await _acquire_n(limiter, key, 2, 2, TEN_MINUTES)
    assert not (await limiter.acquire(key, 2, TEN_MINUTES)).allowed
    assert (
        await limiter.acquire(PrincipalObjectKey(tenant, other_person, obj), 2, TEN_MINUTES)
    ).allowed
    assert (
        await limiter.acquire(PrincipalObjectKey(tenant, person, other_obj), 2, TEN_MINUTES)
    ).allowed


async def test_a_source_and_a_person_with_the_same_ids_count_apart() -> None:
    """The table is keyed by the key's type too, not only its field values."""
    limiter, _ = _limiter()
    tenant, same = TenantId(uuid.uuid4()), uuid.uuid4()
    await _acquire_n(limiter, SourceKey(tenant, same), 1, 1, MINUTE)
    assert (await limiter.acquire(PrincipalObjectKey(tenant, same, same), 1, MINUTE)).allowed


# ---- R7.2 (the gate's CRITICAL): no counter crosses tenants -------------------


async def test_a_company_spending_its_limit_leaves_another_with_the_same_ids_untouched() -> None:
    limiter, _ = _limiter()
    tenant_a, tenant_b = TenantId(uuid.uuid4()), TenantId(uuid.uuid4())
    source, person, obj = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    await _acquire_n(limiter, SourceKey(tenant_a, source), 60, 60, MINUTE)
    await _acquire_n(limiter, PrincipalObjectKey(tenant_a, person, obj), 20, 20, TEN_MINUTES)
    assert not (await limiter.acquire(SourceKey(tenant_a, source), 60, MINUTE)).allowed
    assert not (
        await limiter.peek(PrincipalObjectKey(tenant_a, person, obj), 20, TEN_MINUTES)
    ).allowed

    assert await limiter.peek(SourceKey(tenant_b, source), 60, MINUTE) == RateDecision(True, None)
    assert await limiter.peek(PrincipalObjectKey(tenant_b, person, obj), 20, TEN_MINUTES) == (
        RateDecision(True, None)
    )
    assert (await limiter.acquire(SourceKey(tenant_b, source), 60, MINUTE)).allowed
    assert (
        await limiter.acquire(PrincipalObjectKey(tenant_b, person, obj), 20, TEN_MINUTES)
    ).allowed


# ---- R7.3: peek counts nothing -------------------------------------------------


async def test_peek_counts_nothing_and_reports_when_the_oldest_leaves() -> None:
    limiter, clock = _limiter()
    key = PrincipalObjectKey(TenantId(uuid.uuid4()), uuid.uuid4(), uuid.uuid4())
    for minute in range(19):
        clock.advance_to(T0 + timedelta(seconds=10 * minute))
        assert (await limiter.acquire(key, 20, TEN_MINUTES)).allowed

    for _ in range(5):
        assert await limiter.peek(key, 20, TEN_MINUTES) == RateDecision(True, None)
    # The counter is still 19: one more counted call has room, the next not.
    assert (await limiter.acquire(key, 20, TEN_MINUTES)).allowed

    full = await limiter.peek(key, 20, TEN_MINUTES)
    assert full == RateDecision(allowed=False, retry_at=T0 + TEN_MINUTES)

    clock.advance_to(T0 + TEN_MINUTES - timedelta(microseconds=1))
    assert not (await limiter.peek(key, 20, TEN_MINUTES)).allowed
    clock.advance_to(T0 + TEN_MINUTES)
    assert await limiter.peek(key, 20, TEN_MINUTES) == RateDecision(True, None)


async def test_peek_on_a_key_never_counted_adds_nothing_to_the_table() -> None:
    limiter, _ = _limiter()
    assert (await limiter.peek(_source(), 1, MINUTE)).allowed
    assert len(limiter) == 0


# ---- failure-modes #6: an idle key is dropped ----------------------------------


async def test_a_key_idle_past_its_window_and_a_minute_is_dropped() -> None:
    limiter, clock = _limiter()
    idle, busy = _source(), _source()
    await limiter.acquire(idle, 5, MINUTE)
    await limiter.acquire(busy, 5, TEN_MINUTES)
    assert len(limiter) == 2

    clock.advance_to(T0 + 2 * MINUTE + timedelta(seconds=1))
    await limiter.acquire(busy, 5, TEN_MINUTES)
    assert len(limiter) == 1

    # The kept key still holds both its calls: the sweep drops no live count.
    assert (await limiter.acquire(busy, 3, TEN_MINUTES)).allowed
    assert not (await limiter.acquire(busy, 3, TEN_MINUTES)).allowed


async def test_a_key_used_within_its_window_and_a_minute_is_kept() -> None:
    limiter, clock = _limiter()
    key = _source()
    await limiter.acquire(key, 1, MINUTE)
    clock.advance_to(T0 + 2 * MINUTE)
    await limiter.acquire(_source(), 1, MINUTE)
    assert len(limiter) == 2
