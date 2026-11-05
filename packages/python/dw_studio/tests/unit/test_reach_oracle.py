"""The record reach oracle's own rules (record-access ticket 02, step 8), on
organisations written by hand: the differential test trusts it, so it is
checked against the ticket's cases first."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dw_studio.testing.reach import (
    OWNER,
    Assignment,
    Organisation,
    Person,
    Role,
    access_key,
    expected_scope,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
T, MKT, SALES, OLD = (uuid.uuid4() for _ in range(4))
LEAD, CAMPAIGN = uuid.uuid4(), uuid.uuid4()
READER, CREATOR, OWNER_ROLE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _org(*people: Person, status: str = "active") -> Organisation:
    roles = {
        READER: Role(READER, "reader", ((LEAD, "read", "workspace"),)),
        CREATOR: Role(CREATOR, "creator", ((LEAD, "create", "own"), (CAMPAIGN, "create", "own"))),
        OWNER_ROLE: Role(OWNER_ROLE, OWNER),
    }
    return Organisation(
        T, status, (MKT, SALES, OLD), frozenset({OLD}), (LEAD, CAMPAIGN), roles, people
    )


def test_the_key_is_the_md5_of_object_slash_workspace() -> None:
    expected = hashlib.md5(f"{LEAD}/{MKT}".encode(), usedforsecurity=False).hexdigest()
    assert access_key(LEAD, MKT) == uuid.UUID(expected)


def test_workspace_depth_fills_own_and_keys_and_not_tenant() -> None:
    p = Person(uuid.uuid4(), "active", (MKT,), (Assignment(MKT, READER),))
    scope = expected_scope(_org(p), p.id, NOW)
    assert scope.arm("read", "own") == {LEAD}
    assert scope.arm("read", "keys") == {access_key(LEAD, MKT)}
    assert scope.arm("read", "tenant") == frozenset()
    assert scope.workspace_ids == {MKT}


def test_create_at_own_depth_keys_each_object_with_its_own_anchor() -> None:
    p = Person(
        uuid.uuid4(),
        "active",
        (MKT, SALES),
        (Assignment(MKT, CREATOR), Assignment(SALES, CREATOR)),
    )
    only_lead_in_mkt = Organisation(
        T,
        "active",
        (MKT, SALES),
        frozenset(),
        (LEAD, CAMPAIGN),
        {
            CREATOR: Role(CREATOR, "c", ((LEAD, "create", "own"),)),
            READER: Role(READER, "r", ((CAMPAIGN, "create", "own"),)),
        },
        (
            Person(
                p.id, "active", (MKT, SALES), (Assignment(MKT, CREATOR), Assignment(SALES, READER))
            ),
        ),
    )
    keys = expected_scope(only_lead_in_mkt, p.id, NOW).create_own_keys
    assert keys == {access_key(LEAD, MKT), access_key(CAMPAIGN, SALES)}
    assert access_key(LEAD, SALES) not in keys


def test_the_owner_role_reaches_every_object_at_tenant_depth() -> None:
    p = Person(uuid.uuid4(), "active", (MKT,), (Assignment(MKT, OWNER_ROLE),))
    scope = expected_scope(_org(p), p.id, NOW)
    for action in ("read", "create", "update", "delete", "assign"):
        assert scope.arm(action, "tenant") == {LEAD, CAMPAIGN}
        assert scope.arm(action, "own") == {LEAD, CAMPAIGN}


def test_expired_archived_suspended_and_locked_give_nothing() -> None:
    expired = Person(
        uuid.uuid4(), "active", (MKT,), (Assignment(MKT, READER, NOW - timedelta(seconds=1)),)
    )
    archived = Person(uuid.uuid4(), "active", (OLD,), (Assignment(OLD, READER),))
    suspended = Person(uuid.uuid4(), "suspended", (MKT,), (Assignment(MKT, READER),))
    org = _org(expired, archived, suspended)
    for person in (expired, archived, suspended):
        assert expected_scope(org, person.id, NOW).arm("read", "own") == frozenset()
    assert expected_scope(org, archived.id, NOW).workspace_ids == frozenset()
    assert expected_scope(org, suspended.id, NOW).workspace_ids == frozenset()
    locked = Person(uuid.uuid4(), "active", (MKT,), (Assignment(MKT, READER),))
    gone = expected_scope(_org(locked, status="locked"), locked.id, NOW)
    assert gone.arm("read", "own") == frozenset()
    assert gone.workspace_ids == frozenset()


def test_valid_until_is_the_earliest_live_expiry_and_a_stranger_has_no_scope() -> None:
    soon, later = NOW + timedelta(hours=1), NOW + timedelta(days=2)
    p = Person(
        uuid.uuid4(),
        "active",
        (MKT, SALES),
        (Assignment(MKT, READER, later), Assignment(SALES, CREATOR, soon)),
    )
    assert expected_scope(_org(p), p.id, NOW).valid_until == soon
    assert expected_scope(_org(p), uuid.uuid4(), NOW).arms == {}


# record-access ticket 03: default access (ADR-0105 decision 2 (a); gate (c)).

_BOTH = uuid.uuid4()


def _defaulted(access: str, *privileges: tuple[uuid.UUID, str, str]) -> tuple[Organisation, Person]:
    role = Role(_BOTH, "editor", privileges)
    p = Person(uuid.uuid4(), "active", (MKT,), (Assignment(MKT, _BOTH),))
    org = Organisation(
        T,
        "active",
        (MKT, SALES),
        frozenset(),
        (LEAD, CAMPAIGN),
        {_BOTH: role},
        (p,),
        {LEAD: access},
    )
    return org, p


@pytest.mark.parametrize("depth", ["own", "workspace", "tenant"])
def test_public_read_puts_the_object_in_the_read_tenant_arm_at_any_depth(depth: str) -> None:
    org, p = _defaulted("public_read", (LEAD, "read", depth), (LEAD, "update", depth))
    scope = expected_scope(org, p.id, NOW)
    assert scope.arm("read", "tenant") == {LEAD}
    assert scope.arm("update", "tenant") == (
        frozenset({LEAD}) if depth == "tenant" else frozenset()
    )


def test_public_read_write_opens_update_and_read_but_never_delete_or_assign() -> None:
    org, p = _defaulted(
        "public_read_write",
        *((LEAD, action, "own") for action in ("read", "update", "delete", "assign")),
    )
    scope = expected_scope(org, p.id, NOW)
    assert scope.arm("read", "tenant") == scope.arm("update", "tenant") == {LEAD}
    assert scope.arm("delete", "tenant") == scope.arm("assign", "tenant") == frozenset()


def test_default_access_gives_nothing_to_someone_without_the_privilege() -> None:
    org, p = _defaulted("public_read_write", (CAMPAIGN, "read", "own"))
    scope = expected_scope(org, p.id, NOW)
    assert LEAD not in scope.arm("read", "tenant") | scope.arm("update", "tenant")
    private, q = _defaulted("private", (LEAD, "read", "own"))
    assert expected_scope(private, q.id, NOW).arm("read", "tenant") == frozenset()
