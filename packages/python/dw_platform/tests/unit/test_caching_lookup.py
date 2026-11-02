"""Unit: the caching membership lookup serves from cache, keyed by access version.

Fakes for the cache and the inner lookup — no database. What matters: a second
identical lookup is served from cache (the inner is not called again), a "no
membership" answer is cached too, a new access version of the tenant is a miss
(tenant-rbac R4.1), and an entry an older deploy wrote, or one carrying another
version, is rebuilt rather than read half (R4.2, RB13). A tenant with no version
row is never cached.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

from dw_platform.adapters.persistence.caching_lookup import CachingMembershipLookup
from dw_platform.application.access_context import Grant
from dw_platform.application.identity import MembershipAccess

TENANT = uuid.uuid4()
WS = uuid.uuid4()
ISSUER = "https://issuer.test/realms/dw"
SUBJECT = "sub-abc"


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self.store[key] = value


class _CountingLookup:
    """The database as the cache sees it: a version, and the access read at it."""

    def __init__(self, result: MembershipAccess | None, version: int | None = 7) -> None:
        self.result = result
        self.version = version
        self.calls = 0

    async def access_version(self, tenant_id: uuid.UUID) -> int | None:
        return self.version

    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        self.calls += 1
        if self.result is None:
            return None
        return replace(self.result, access_version=self.version)


def _access() -> MembershipAccess:
    return MembershipAccess(
        tenant_id=TENANT,
        workspace_id=WS,
        principal_id=uuid.uuid4(),
        roles=frozenset({"sales"}),
        scopes=frozenset({"crm.account.read", "crm.lead.write"}),
        groups=frozenset(),
        clearance="internal",
        plan_id="professional",
        feature_flags=frozenset({"knowledge_search"}),
        grants=(Grant(key="crm.lead.write", depth="workspace", anchor_workspace_id=WS),),
        access_version=7,
    )


async def test_second_lookup_is_served_from_cache() -> None:
    access = _access()
    inner = _CountingLookup(access)
    lookup = CachingMembershipLookup(inner, _FakeCache())

    first = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    second = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 1  # the database was hit once
    assert first == second == access  # and the round-trips the same value


async def test_restricted_visible_owners_survive_the_round_trip() -> None:
    # A restricted-tenant access carries the subtree it may see (ADR-003). The
    # cache serializes to JSON, so the frozenset of UUIDs has to come back intact
    # and typed — a str leaking through here would silently widen a query.
    owners = frozenset({uuid.uuid4(), uuid.uuid4()})
    access = MembershipAccess(
        tenant_id=TENANT,
        workspace_id=WS,
        principal_id=uuid.uuid4(),
        roles=frozenset({"sales"}),
        scopes=frozenset({"crm.account.read"}),
        groups=frozenset(),
        clearance="internal",
        plan_id="professional",
        feature_flags=frozenset(),
        record_visibility="restricted",
        visible_owners=owners,
    )
    inner = _CountingLookup(access)
    lookup = CachingMembershipLookup(inner, _FakeCache())

    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    served = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 1
    assert served is not None
    assert served.record_visibility == "restricted"
    assert served.visible_owners == owners
    # The point of the next line is that a cache round-trip returns real UUIDs
    # rather than the strings JSON turns them into, so it has to iterate what
    # came BACK. `None` is a real answer from this field - it means the whole
    # workspace - and it is not the answer under test here.
    assert served.visible_owners is not None
    assert all(isinstance(u, uuid.UUID) for u in served.visible_owners)


async def test_the_tenants_autonomy_ceiling_survives_the_round_trip() -> None:
    """The serializer lists every field by hand. One added to the access and not to
    the serializer comes back as its default — here, silently, a different ceiling
    from the one the tenant set."""
    access = replace(_access(), max_autonomy_level="A1")
    inner = _CountingLookup(access)
    lookup = CachingMembershipLookup(inner, _FakeCache())

    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    served = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 1
    assert served is not None
    assert served.max_autonomy_level == "A1"


def _drop_field(cache: _FakeCache, field_name: str) -> None:
    """Rewrite the one stored entry as a previous release wrote it: without the field."""
    [key] = cache.store
    legacy = json.loads(cache.store[key])
    del legacy[field_name]
    cache.store[key] = json.dumps(legacy)


async def test_an_entry_cached_before_the_ceiling_existed_is_re_read_not_guessed() -> None:
    """The cache outlives a deploy by up to its TTL, so an entry written by the
    previous release is read for real after every one. The tenant's ceiling is
    unknown in such an entry, not absent.

    This used to answer with the most restrictive level — safe, but still a guess,
    and it throttled an A4 tenant to A0 for the length of the TTL after every
    deploy. There is no need to guess: the database knows.
    """
    cache = _FakeCache()
    inner = _CountingLookup(replace(_access(), max_autonomy_level="A1"))
    lookup = CachingMembershipLookup(inner, cache)
    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    _drop_field(cache, "max_autonomy_level")

    served = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 2, "a legacy entry must be re-read, not read half"
    assert served is not None
    assert served.max_autonomy_level == "A1", "the real ceiling, not a guess"


async def test_a_legacy_entry_cannot_widen_a_restricted_tenant() -> None:
    """The fail-open this rule exists for.

    `record_visibility` was read as `open` when a cached entry did not carry it —
    the widest setting a tenant has. Every restricted tenant therefore read as
    unrestricted for the first TTL after a deploy: a rep saw the whole workspace's
    records rather than their own. Refusing to invent the value is the fix, and
    asserting the resolved value (not the call count) is what makes this a test of
    the leak rather than of the cache.
    """
    cache = _FakeCache()
    inner = _CountingLookup(replace(_access(), record_visibility="restricted"))
    lookup = CachingMembershipLookup(inner, cache)
    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    _drop_field(cache, "record_visibility")

    served = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert served is not None
    assert served.record_visibility == "restricted", "a stale entry must not widen the tenant"


async def test_a_no_membership_answer_is_cached_too() -> None:
    inner = _CountingLookup(None)
    lookup = CachingMembershipLookup(inner, _FakeCache())

    assert await lookup.find_access(SUBJECT, ISSUER, TENANT, WS) is None
    assert await lookup.find_access(SUBJECT, ISSUER, TENANT, WS) is None
    assert inner.calls == 1  # default-deny is not re-queried every request


async def test_a_new_access_version_is_a_fresh_lookup() -> None:
    """R4.1: whoever changed what the tenant grants, the database bumped its
    version, and the first request after the commit reads the new state."""
    access = _access()
    inner = _CountingLookup(access)
    lookup = CachingMembershipLookup(inner, _FakeCache())

    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    inner.version = 8
    served = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 2
    assert served is not None and served.access_version == 8


async def test_an_entry_without_grants_is_rebuilt_not_defaulted() -> None:
    """R4.2 (RB13): an entry the previous deploy wrote has no `grants`; reading it
    as "no grants" would be a guess, so it is a miss."""
    cache = _FakeCache()
    inner = _CountingLookup(_access())
    lookup = CachingMembershipLookup(inner, cache)
    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    _drop_field(cache, "grants")

    served = await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 2
    assert served is not None and served.grants == _access().grants


async def test_an_entry_carrying_another_version_is_a_miss() -> None:
    """R4.2: the body says which state it holds, and a body that disagrees with
    its key is not read."""
    cache = _FakeCache()
    inner = _CountingLookup(_access())
    lookup = CachingMembershipLookup(inner, cache)
    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    [key] = cache.store
    stale = json.loads(cache.store[key])
    stale["access_version"] = 6
    cache.store[key] = json.dumps(stale)

    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 2


async def test_a_tenant_without_a_version_row_is_read_and_never_cached() -> None:
    """R4.2: after offboarding purged the row, nothing can key an entry."""
    cache = _FakeCache()
    inner = _CountingLookup(_access(), version=None)
    lookup = CachingMembershipLookup(inner, cache)

    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)
    await lookup.find_access(SUBJECT, ISSUER, TENANT, WS)

    assert inner.calls == 2
    assert cache.store == {}
