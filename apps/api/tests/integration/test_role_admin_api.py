# ruff: noqa: F811  (the fixture of test_tenant_roles_api is imported by name)
"""Role administration and role assignment through the real app on a migrated
Postgres (tenant-rbac ticket 03).

The API-level acceptance criteria: two people open, one closes (R7.1-R7.6,
RB21, RB32), nobody hands out what they do not hold or hands it to themselves
(R6.1, R6.3-R6.7), a proposal applies once and only as it was made (R7.8,
R8.7), the answers and audit events of the routes (R8.1-R8.8), another
tenant's ids (R3.3), the `platform_admin` bypass on these routes (R3.16, G2),
service accounts (RB16), Digital Worker principals (R7.5) and the lock order a
confirmation and a DW creation share (R7.8, RB43). The raw-SQL cases of the
same criteria are `dw_platform`'s `test_role_administration_db.py`.

Every world is planted by the migrator (`dw_platform.testing.rbac`); every
change under test goes through the app as `dw_app`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_tenant_roles_api import SECRET, Api, api  # noqa: F401  (fixture, used by name)

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence import role_admin_repo
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    unregister_key,
)

pytestmark = pytest.mark.integration

_ADMIN = "/api/v1/admin"
_ROLES = f"{_ADMIN}/roles"
_CHANGES = f"{_ADMIN}/role-changes"

READ = "platform.roles.read"
WRITE = "platform.roles.write"
BIND = "platform.roles.bind"
MEMBERS_READ = "platform.members.read"
MEMBERS_WRITE = "platform.members.write"


def admin(**extra: str) -> dict[str, str]:
    """Every key of role administration and assignment at tenant depth, plus ``extra``."""
    keys = dict.fromkeys((READ, WRITE, BIND, MEMBERS_READ, MEMBERS_WRITE), "tenant")
    return {**keys, **extra}


@dataclass(frozen=True)
class Keys:
    """Test keys of the catalogue: three `standard`, one `critical`."""

    one: str
    two: str
    three: str
    crit: str


@pytest.fixture
async def keys(api_db: DatabaseUrls) -> AsyncIterator[Keys]:
    suffix = uuid.uuid4().hex[:10]
    made = Keys(
        f"test.ra{suffix}.one",
        f"test.ra{suffix}.two",
        f"test.ra{suffix}.three",
        f"test.ra{suffix}.crit",
    )
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            for key in (made.one, made.two, made.three):
                await register_key(conn, key)
            await register_key(conn, made.crit, risk="critical")
        yield made
        async with migrator.begin() as conn:
            for key in (made.one, made.two, made.three, made.crit):
                await unregister_key(conn, key)
    finally:
        await migrator.dispose()


@pytest.fixture
async def dw_api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    """The app with the agent runtime composed, which the Digital Worker routes
    are wired with: lazy clients over a placeholder store and the mock model,
    as `test_dw_scorecard_autonomy.py` builds it."""
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    assert container.engine is not None and container.digital_workers is not None
    app = create_app(container)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield Api(client, migrator, container)
    finally:
        await container.engine.dispose()
        await migrator.dispose()


@dataclass(frozen=True)
class Who:
    subject: str
    user_id: uuid.UUID
    tenant: PlantedTenant
    workspace: uuid.UUID
    membership: uuid.UUID

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id


async def _who(
    api: Api,
    t: PlantedTenant,
    privileges: dict[str, str] | None = None,
    *,
    anchor: uuid.UUID | None = None,
    email: str | None = None,
) -> Who:
    """A person with a membership in `main` and, when given, a role of their
    own carrying ``privileges``, assigned at ``anchor`` (`main` otherwise)."""
    anchor = anchor or t.main
    async with api.migrator.begin() as conn:
        person = await plant_person(conn, t.tenant_id, email=email)
        subject = f"ra-api-{person}"
        await conn.execute(
            sa.text("UPDATE platform.users SET subject = :s WHERE id = :u"),
            {"s": subject, "u": person},
        )
        here = await plant_membership(conn, t.tenant_id, t.main, person)
        there = (
            here if anchor == t.main else await plant_membership(conn, t.tenant_id, anchor, person)
        )
        if privileges:
            role = await plant_role(conn, t.tenant_id, f"p_{person.hex[:12]}", privileges)
            await assign(conn, t.tenant_id, anchor, there, role)
    return Who(subject, person, t, t.main, here)


def _own_role(who: Who) -> str:
    """The key of the role `_who` planted for ``who``."""
    return f"p_{who.user_id.hex[:12]}"


async def _call(api: Api, who: Who, method: str, path: str, **kw: Any) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue(who.subject)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(who.t),
        "X-Workspace-Id": str(who.workspace),
        **kw.pop("headers", {}),
    }
    response: httpx.Response = await api.client.request(method, path, headers=headers, **kw)
    return response


async def _rows(api: Api, sql: str, **values: object) -> list[Any]:
    async with api.migrator.connect() as conn:
        return list((await conn.execute(sa.text(sql), values)).all())


async def _one(api: Api, sql: str, **values: object) -> Any:
    async with api.migrator.connect() as conn:
        return await conn.scalar(sa.text(sql), values)


async def _plant_role(
    api: Api, t: PlantedTenant, key: str, privileges: dict[str, str]
) -> uuid.UUID:
    async with api.migrator.begin() as conn:
        return await plant_role(conn, t.tenant_id, key, privileges)


async def _assign(api: Api, who: Who, role: uuid.UUID, workspace: uuid.UUID | None = None) -> None:
    workspace = workspace or who.tenant.main
    async with api.migrator.begin() as conn:
        membership = await conn.scalar(
            sa.text(
                "SELECT id FROM platform.memberships"
                " WHERE tenant_id = :t AND workspace_id = :w AND user_id = :u"
            ),
            {"t": who.t, "w": workspace, "u": who.user_id},
        )
        if membership is None:
            membership = await plant_membership(conn, who.t, workspace, who.user_id)
        await assign(conn, who.t, workspace, membership, role)


async def _privileges(api: Api, role: uuid.UUID) -> set[tuple[str, str]]:
    rows = await _rows(
        api,
        "SELECT permission_key, depth FROM platform.tenant_role_permissions WHERE role_id = :r",
        r=role,
    )
    return {(r.permission_key, r.depth) for r in rows}


async def _version(api: Api, role: uuid.UUID) -> int:
    return int(await _one(api, "SELECT version FROM platform.tenant_roles WHERE id = :r", r=role))


async def _proposals(api: Api, t: uuid.UUID) -> int:
    return int(
        await _one(
            api, "SELECT count(*) FROM platform.role_change_requests WHERE tenant_id = :t", t=t
        )
    )


async def _status(api: Api, request: object) -> str:
    return str(
        await _one(api, "SELECT status FROM platform.role_change_requests WHERE id = :r", r=request)
    )


async def _holds(api: Api, user: uuid.UUID, role: uuid.UUID) -> int:
    return int(
        await _one(
            api,
            "SELECT count(*) FROM platform.role_assignments a JOIN platform.memberships m"
            " ON m.id = a.membership_id WHERE m.user_id = :u AND a.role_id = :r",
            u=user,
            r=role,
        )
    )


async def _audits(api: Api, t: uuid.UUID, action: str, **details: str) -> int:
    sql = "SELECT count(*) FROM platform.audit_events WHERE tenant_id = :t AND action = :a"
    for name in details:
        sql += f" AND details->>'{name}' = :{name}"
    return int(await _one(api, sql, t=t, a=action, **details))


async def _all_audits(api: Api, t: uuid.UUID) -> int:
    return int(
        await _one(api, "SELECT count(*) FROM platform.audit_events WHERE tenant_id = :t", t=t)
    )


def _reason(response: httpx.Response) -> tuple[int, str | None]:
    body = response.json()
    details = body.get("details") if isinstance(body, dict) else None
    return response.status_code, (details or {}).get("reason_code")


async def _etag(api: Api, who: Who, role: uuid.UUID) -> str:
    found = await _call(api, who, "GET", f"{_ROLES}/{role}")
    assert found.status_code == 200, found.text
    return found.headers["ETag"]


async def _put_permissions(
    api: Api, who: Who, role: uuid.UUID, privileges: dict[str, str], etag: str | None = None
) -> httpx.Response:
    etag = etag or await _etag(api, who, role)
    return await _call(
        api,
        who,
        "PUT",
        f"{_ROLES}/{role}/permissions",
        json={"permissions": [{"key": k, "depth": d} for k, d in privileges.items()]},
        headers={"If-Match": etag},
    )


async def _set_memberships(
    api: Api, who: Who, person: uuid.UUID, rows: dict[uuid.UUID, list[str]], **kw: Any
) -> httpx.Response:
    body = {"memberships": [{"workspace_id": str(w), "role_keys": k} for w, k in rows.items()]}
    return await _call(api, who, "PUT", f"{_ADMIN}/members/{person}/memberships", json=body, **kw)


async def _confirm(api: Api, who: Who, request: object, **kw: Any) -> httpx.Response:
    return await _call(api, who, "POST", f"{_CHANGES}/{request}/confirm", **kw)


async def _create_role(api: Api, who: Who, key: str, **kw: Any) -> httpx.Response:
    return await _call(
        api,
        who,
        "POST",
        _ROLES,
        json={"key": key, "name": f"Vai {key}", **kw.pop("body", {})},
        **kw,
    )


def _key() -> str:
    return f"r_{uuid.uuid4().hex[:12]}"


async def _tenant(api: Api, workspaces: int = 1) -> PlantedTenant:
    async with api.migrator.begin() as conn:
        return await plant_tenant(conn, workspaces=workspaces)


# ---- R7.1 (RB21): what widens waits for a second person ----------------------


async def test_what_widens_is_a_proposal_until_a_second_person_confirms_it(
    api: Api, keys: Keys
) -> None:
    """R7.1 (RB21): create a role, add a key, assign a role, invite: each 202
    and nothing in force; the confirmation puts it in force with exactly one
    `.confirmed` and one change audit event."""
    t = await _tenant(api)
    maker = await _who(api, t, admin(**{keys.one: "tenant"}))
    checker = await _who(api, t, admin(**{keys.one: "tenant"}))
    role_key = _key()

    made = await _create_role(api, maker, role_key)
    assert made.status_code == 202, made.text
    request = made.json()["id"]
    new_role = uuid.UUID(made.json()["payload"]["role_id"])
    assert (
        await _one(api, "SELECT count(*) FROM platform.tenant_roles WHERE id = :r", r=new_role) == 0
    )
    confirmed = await _confirm(api, checker, request)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert (
        await _one(api, "SELECT key FROM platform.tenant_roles WHERE id = :r", r=new_role)
        == role_key
    )
    assert (
        await _audits(api, t.tenant_id, "platform.role_change.confirmed", request_id=request) == 1
    )
    assert await _audits(api, t.tenant_id, "platform.role.create", request_id=request) == 1

    added = await _put_permissions(api, maker, new_role, {keys.one: "tenant"})
    assert added.status_code == 202, added.text
    request = added.json()["proposal"]["id"]
    assert await _privileges(api, new_role) == set()
    assert (await _confirm(api, checker, request)).status_code == 200
    assert await _privileges(api, new_role) == {(keys.one, "tenant")}
    assert (
        await _audits(api, t.tenant_id, "platform.role_change.confirmed", request_id=request) == 1
    )
    assert await _audits(api, t.tenant_id, "platform.role.permissions_set", request_id=request) == 1

    grantee = await _who(api, t)
    granted = await _set_memberships(api, maker, grantee.user_id, {t.main: [role_key]})
    assert granted.status_code == 202, granted.text
    [request] = granted.json()["proposals"]
    assert await _holds(api, grantee.user_id, new_role) == 0
    assert (await _confirm(api, checker, request)).status_code == 200
    assert await _holds(api, grantee.user_id, new_role) == 1
    assert (
        await _audits(api, t.tenant_id, "platform.role_change.confirmed", request_id=request) == 1
    )
    assert (
        await _audits(api, t.tenant_id, "platform.role_assignment.grant", request_id=request) == 1
    )

    email = f"{uuid.uuid4().hex[:10]}@khach.vn"
    invited = await _call(
        api,
        maker,
        "POST",
        f"{_ADMIN}/invitations",
        json={
            "display_name": "Người được mời",
            "email": email,
            "memberships": [{"workspace_id": str(t.main), "role_keys": [role_key]}],
        },
    )
    assert invited.status_code == 202, invited.text
    [request] = invited.json()["proposals"]
    invitee = uuid.UUID(invited.json()["user_id"])
    assert (
        await _one(api, "SELECT count(*) FROM platform.memberships WHERE user_id = :u", u=invitee)
        == 1
    )

    async def me() -> httpx.Response:
        token = DevTokenVerifier(SECRET).issue(f"dev-{email}", email=email)
        headers = {"Authorization": f"Bearer {token}"}
        booted = await api.client.get("/api/v1/auth/bootstrap", headers=headers)
        assert booted.status_code == 200, booted.text
        answer: httpx.Response = await api.client.get(
            "/api/v1/me",
            headers={**headers, "X-Tenant-Id": str(t.tenant_id), "X-Workspace-Id": str(t.main)},
        )
        return answer

    before = await me()
    assert before.status_code == 200, before.text
    assert before.json()["scopes"] == []
    assert (await _confirm(api, checker, request)).status_code == 200
    after = await me()
    assert keys.one in after.json()["scopes"]


async def test_a_confirmation_takes_the_proposals_own_permission(api: Api, keys: Keys) -> None:
    """R7.1 (RB21): a holder of only `platform.roles.bind` confirming a
    `role_permissions` proposal, or of only `platform.roles.write` confirming an
    `assignment_grant`, is refused 403 and nothing changes."""
    t = await _tenant(api)
    maker = await _who(api, t, admin(**{keys.one: "tenant"}))
    await _who(api, t, admin(**{keys.one: "tenant"}))  # someone may confirm
    binder = await _who(api, t, {READ: "tenant", BIND: "tenant", keys.one: "tenant"})
    writer = await _who(api, t, {READ: "tenant", WRITE: "tenant", keys.one: "tenant"})
    role = await _plant_role(api, t, _key(), {})
    grantee = await _who(api, t)

    widen = await _put_permissions(api, maker, role, {keys.one: "tenant"})
    assert widen.status_code == 202, widen.text
    grant = await _set_memberships(
        api, maker, grantee.user_id, {t.main: [await _role_key(api, role)]}
    )
    assert grant.status_code == 202, grant.text

    refused = await _confirm(api, binder, widen.json()["proposal"]["id"])
    assert refused.status_code == 403, refused.text
    refused = await _confirm(api, writer, grant.json()["proposals"][0])
    assert refused.status_code == 403, refused.text
    assert await _privileges(api, role) == set()
    assert await _holds(api, grantee.user_id, role) == 0
    assert await _status(api, widen.json()["proposal"]["id"]) == "proposed"
    assert await _status(api, grant.json()["proposals"][0]) == "proposed"


async def _role_key(api: Api, role: uuid.UUID) -> str:
    return str(await _one(api, "SELECT key FROM platform.tenant_roles WHERE id = :r", r=role))


async def test_a_mixed_change_widens(api: Api, keys: Keys) -> None:
    """R7.1 (RB32): removing one key and adding another, or raising a depth,
    is a proposal and nothing changes; a membership change dropping role A and
    adding B applies the drop and proposes B."""
    t = await _tenant(api)
    maker = await _who(api, t, admin(**{keys.one: "tenant", keys.two: "tenant"}))
    await _who(api, t, admin(**{keys.one: "tenant", keys.two: "tenant"}))
    role = await _plant_role(api, t, _key(), {keys.one: "workspace"})

    swapped = await _put_permissions(api, maker, role, {keys.two: "workspace"})
    assert swapped.status_code == 202, swapped.text
    assert swapped.json()["proposal"]["kind"] == "role_permissions"
    raised = await _put_permissions(api, maker, role, {keys.one: "tenant"})
    assert raised.status_code == 202, raised.text
    assert await _privileges(api, role) == {(keys.one, "workspace")}

    a = await _plant_role(api, t, _key(), {keys.one: "workspace"})
    b = await _plant_role(api, t, _key(), {keys.two: "workspace"})
    grantee = await _who(api, t)
    await _assign(api, grantee, a)
    moved = await _set_memberships(api, maker, grantee.user_id, {t.main: [await _role_key(api, b)]})
    assert moved.status_code == 202, moved.text
    assert [r["role_key"] for r in moved.json()["applied"]] == [await _role_key(api, a)]
    [proposal] = moved.json()["proposals"]
    assert await _holds(api, grantee.user_id, a) == 0
    assert await _holds(api, grantee.user_id, b) == 0
    assert (
        await _one(
            api, "SELECT role_id FROM platform.role_change_requests WHERE id = :r", r=proposal
        )
        == b
    )


# ---- R7.2, R7.3, R7.4 -------------------------------------------------------


async def test_the_proposer_cannot_confirm(api: Api, keys: Keys) -> None:
    """R7.2 (RB21): 409 `second_person_required`, the proposal still open."""
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    await _who(api, t, admin())
    made = await _create_role(api, maker, _key())
    assert made.status_code == 202, made.text
    refused = await _confirm(api, maker, made.json()["id"])
    assert _reason(refused) == (409, "second_person_required")
    assert await _status(api, made.json()["id"]) == "proposed"
    assert await _audits(api, t.tenant_id, "platform.role_change.confirmed") == 0


async def test_with_nobody_else_to_confirm_nothing_is_proposed_but_a_revocation_applies(
    api: Api, keys: Keys
) -> None:
    """R7.3 (RB22): the only holder of `platform.roles.write` is refused 409
    `no_checker_available` with no proposal row; the same tenant revokes an
    assignment that is not the last owner's, 200."""
    t = await _tenant(api)
    solo = await _who(api, t, admin(**{keys.one: "tenant"}))
    role = await _plant_role(api, t, _key(), {keys.one: "workspace"})
    grantee = await _who(api, t)
    await _assign(api, grantee, role)

    for refused in (
        await _create_role(api, solo, _key()),
        await _put_permissions(api, solo, role, {keys.one: "tenant"}),
        await _set_memberships(api, solo, grantee.user_id, {t.main: ["member"]}),
    ):
        assert _reason(refused) == (409, "no_checker_available"), refused.text
    assert await _proposals(api, t.tenant_id) == 0

    revoked = await _set_memberships(api, solo, grantee.user_id, {})
    assert revoked.status_code == 200, revoked.text
    assert await _holds(api, grantee.user_id, role) == 0


@pytest.mark.parametrize(("offset", "expected"), [(-1.0, 409), (2.0, 200)])
async def test_a_proposal_is_confirmed_only_before_it_expires(
    api: Api, keys: Keys, offset: float, expected: int
) -> None:
    """R7.4 (RB23): aged by the migrator, whom the guard lets move the clock.
    Two seconds rather than one on the open side: the confirmation takes a few
    round trips after the row is aged, and `now()` is the transaction's start."""
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    checker = await _who(api, t, admin())
    made = await _create_role(api, maker, _key())
    request = made.json()["id"]
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.role_change_requests"
                " SET expires_at = now() + make_interval(secs => :o),"
                "     proposed_at = now() + make_interval(secs => :o) - interval '7 days'"
                " WHERE id = :r"
            ),
            {"o": offset, "r": request},
        )
    answer = await _confirm(api, checker, request)
    if expected == 409:
        assert _reason(answer) == (409, "proposal_expired")
        assert await _status(api, request) == "proposed"
    else:
        assert answer.status_code == 200, answer.text
        assert await _status(api, request) == "confirmed"


# ---- R7.6 (RB32): what only narrows is one person and one audit event -------


async def test_what_only_narrows_applies_at_once_with_one_audit(api: Api, keys: Keys) -> None:
    """R7.6 (RB32): removing a key, lowering a depth: 200, one audit event, no
    proposal, the version one up; deleting a role nobody holds: 200, one
    `platform.role.delete`; a role still held: 409 `role_in_use`."""
    t = await _tenant(api)
    solo = await _who(api, t, admin(**{keys.one: "tenant", keys.two: "tenant"}))
    role = await _plant_role(api, t, _key(), {keys.one: "tenant", keys.two: "tenant"})
    holder = await _who(api, t)
    await _assign(api, holder, role)

    for target, after in (
        ({keys.one: "tenant"}, {(keys.one, "tenant")}),
        ({keys.one: "workspace"}, {(keys.one, "workspace")}),
    ):
        version = await _version(api, role)
        audits = await _audits(api, t.tenant_id, "platform.role.permissions_set", role_id=str(role))
        narrowed = await _put_permissions(api, solo, role, target)
        assert narrowed.status_code == 200, narrowed.text
        assert narrowed.json()["proposal"] is None
        assert await _privileges(api, role) == after
        assert await _version(api, role) == version + 1
        assert narrowed.headers["ETag"] == f'"{version + 1}"'
        assert (
            await _audits(api, t.tenant_id, "platform.role.permissions_set", role_id=str(role))
            == audits + 1
        )
    assert await _proposals(api, t.tenant_id) == 0

    in_use = await _call(
        api, solo, "DELETE", f"{_ROLES}/{role}", headers={"If-Match": await _etag(api, solo, role)}
    )
    assert _reason(in_use) == (409, "role_in_use")
    assert in_use.json()["details"]["holder_count"] == 1

    unheld = await _plant_role(api, t, _key(), {keys.one: "tenant"})
    deleted = await _call(
        api,
        solo,
        "DELETE",
        f"{_ROLES}/{unheld}",
        headers={"If-Match": await _etag(api, solo, unheld)},
    )
    assert deleted.status_code == 200, deleted.text
    assert await _one(
        api, "SELECT deleted_at IS NOT NULL FROM platform.tenant_roles WHERE id = :r", r=unheld
    )
    assert await _audits(api, t.tenant_id, "platform.role.delete", role_id=str(unheld)) == 1
    assert await _proposals(api, t.tenant_id) == 0


# ---- R7.8 (RB43): once, and only as it was made ----------------------------


async def test_two_confirmations_at_once_apply_once(api: Api, keys: Keys) -> None:
    """R7.8 (RB43): one applies with one `.confirmed`, the other 409
    `proposal_closed`."""
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    first = await _who(api, t, admin())
    second = await _who(api, t, admin())
    made = await _create_role(api, maker, _key())
    request = made.json()["id"]

    answers = await asyncio.gather(_confirm(api, first, request), _confirm(api, second, request))
    assert sorted(a.status_code for a in answers) == [200, 409], [a.text for a in answers]
    loser = next(a for a in answers if a.status_code == 409)
    assert _reason(loser) == (409, "proposal_closed")
    assert (
        await _audits(api, t.tenant_id, "platform.role_change.confirmed", request_id=request) == 1
    )
    assert await _audits(api, t.tenant_id, "platform.role.create", request_id=request) == 1


async def test_a_withdrawn_proposal_or_a_suspended_proposer_opens_nothing(
    api: Api, keys: Keys
) -> None:
    """R7.8 (RB43): confirmed after it was withdrawn → `proposal_closed`; its
    proposer suspended before the confirmation → `proposal_stale`."""
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    checker = await _who(api, t, admin())
    await _who(api, t, admin())
    withdrawn = (await _create_role(api, maker, _key())).json()["id"]
    pulled = await _call(api, maker, "POST", f"{_CHANGES}/{withdrawn}/withdraw")
    assert pulled.status_code == 200, pulled.text
    assert _reason(await _confirm(api, checker, withdrawn)) == (409, "proposal_closed")

    role_key = _key()
    stale = (await _create_role(api, maker, role_key)).json()["id"]
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenant_members SET status = 'suspended' WHERE user_id = :u"),
            {"u": maker.user_id},
        )
    assert _reason(await _confirm(api, checker, stale)) == (409, "proposal_stale")
    assert await _status(api, stale) == "proposed"
    assert (
        await _one(
            api,
            "SELECT count(*) FROM platform.tenant_roles WHERE tenant_id = :t AND key = :k",
            t=t.tenant_id,
            k=role_key,
        )
        == 0
    )


async def test_a_role_changed_after_the_proposal_makes_it_stale(api: Api, keys: Keys) -> None:
    """R8.7 (RB26): a name proposal whose role moved on → `proposal_stale`; a
    key K removed (one person, 200) between a proposal still holding K and its
    confirmation → `proposal_stale`, K does not come back; no answer here says
    `stale_version`."""
    t = await _tenant(api)
    maker = await _who(api, t, admin(**dict.fromkeys((keys.one, keys.two, keys.three), "tenant")))
    checker = await _who(api, t, admin(**dict.fromkeys((keys.one, keys.two, keys.three), "tenant")))
    role = await _plant_role(api, t, _key(), {keys.one: "tenant", keys.two: "tenant"})
    seen: list[httpx.Response] = []

    renamed = await _call(
        api,
        maker,
        "PATCH",
        f"{_ROLES}/{role}",
        content=json.dumps({"name": "Tên mới"}),
        headers={
            "If-Match": await _etag(api, maker, role),
            "Content-Type": "application/merge-patch+json",
        },
    )
    assert renamed.status_code == 202, renamed.text
    keeps_k = await _put_permissions(
        api, maker, role, {keys.one: "tenant", keys.two: "tenant", keys.three: "tenant"}
    )
    assert keeps_k.status_code == 202, keeps_k.text
    narrowed = await _put_permissions(api, maker, role, {keys.two: "tenant"})
    assert narrowed.status_code == 200, narrowed.text
    seen += [renamed, keeps_k, narrowed]

    for request in (renamed.json()["proposal"]["id"], keeps_k.json()["proposal"]["id"]):
        answer = await _confirm(api, checker, request)
        seen.append(answer)
        assert _reason(answer) == (409, "proposal_stale"), answer.text
        assert await _status(api, request) == "proposed"
    assert await _privileges(api, role) == {(keys.two, "tenant")}
    assert (
        await _one(api, "SELECT name FROM platform.tenant_roles WHERE id = :r", r=role) != "Tên mới"
    )
    assert not any("stale_version" in r.text for r in seen)

    routes = Path(__file__).resolve().parents[2] / "src" / "dw_api" / "routes" / "v1"
    platform = Path(__file__).resolve().parents[4] / "packages" / "python" / "dw_platform" / "src"
    sources = [
        routes / "admin_roles.py",
        routes / "admin_members.py",
        platform / "dw_platform" / "application" / "role_admin.py",
        platform / "dw_platform" / "application" / "role_assignments.py",
        platform / "dw_platform" / "adapters" / "persistence" / "role_admin_repo.py",
        platform / "dw_platform" / "adapters" / "persistence" / "role_assignments_repo.py",
        platform / "dw_platform" / "adapters" / "persistence" / "role_refusals.py",
    ]
    assert all(p.is_file() for p in sources)
    assert [p.name for p in sources if "stale_version" in p.read_text(encoding="utf-8")] == []


# ---- R6.1, R6.3-R6.7: who may hand out what --------------------------------


async def test_nobody_hands_out_what_they_do_not_hold(api: Api, keys: Keys) -> None:
    """R6.1 (RB15): `approvals.decide` held at `workspace` and proposed at
    `tenant`; a critical role the caller does not hold revoked from someone;
    a key held at `workspace` in A added to a role assigned in B: each 403
    `rbac_escalation` naming the key, nothing changed, nothing proposed."""
    t = await _tenant(api, workspaces=2)
    ws_a, ws_b = t.workspaces
    caller = await _who(api, t, admin(**{"approvals.decide": "workspace", keys.one: "workspace"}))
    await _who(api, t, admin(**{"approvals.decide": "tenant", keys.one: "tenant"}))

    empty = await _plant_role(api, t, _key(), {})
    deeper = await _put_permissions(api, caller, empty, {"approvals.decide": "tenant"})
    assert _reason(deeper) == (403, "rbac_escalation"), deeper.text
    assert "approvals.decide:tenant" in deeper.json()["details"]["keys"]
    assert await _privileges(api, empty) == set()

    critical = await _plant_role(api, t, _key(), {keys.crit: "workspace"})
    plain = await _plant_role(api, t, _key(), {keys.one: "workspace"})
    grantee = await _who(api, t)
    await _assign(api, grantee, critical)
    await _assign(api, grantee, plain)
    revoke = await _set_memberships(
        api, caller, grantee.user_id, {ws_a: [await _role_key(api, plain)]}
    )
    assert _reason(revoke) == (403, "rbac_escalation"), revoke.text
    assert f"{keys.crit}:workspace" in revoke.json()["details"]["keys"]
    assert await _holds(api, grantee.user_id, critical) == 1

    in_b = await _plant_role(api, t, _key(), {})
    other = await _who(api, t)
    await _assign(api, other, in_b, ws_b)
    elsewhere = await _put_permissions(api, caller, in_b, {keys.one: "workspace"})
    assert _reason(elsewhere) == (403, "rbac_escalation"), elsewhere.text
    assert f"{keys.one}:workspace" in elsewhere.json()["details"]["keys"]
    assert await _privileges(api, in_b) == set()
    assert await _proposals(api, t.tenant_id) == 0


async def test_bind_assigns_what_is_not_critical(api: Api, keys: Keys) -> None:
    """R6.3 (RB16): a holder of `platform.roles.bind` proposes `member` though
    holding none of its keys (202), and is refused a role carrying a critical
    key they do not hold (403)."""
    t = await _tenant(api)
    binder = await _who(api, t, {BIND: "tenant", MEMBERS_WRITE: "tenant", MEMBERS_READ: "tenant"})
    await _who(api, t, admin())
    grantee = await _who(api, t)
    member = await _set_memberships(api, binder, grantee.user_id, {t.main: ["member"]})
    assert member.status_code == 202, member.text

    critical_key = _key()
    await _plant_role(api, t, critical_key, {keys.crit: "workspace"})
    other = await _who(api, t)
    refused = await _set_memberships(api, binder, other.user_id, {t.main: [critical_key]})
    assert _reason(refused) == (403, "rbac_escalation"), refused.text
    assert await _proposals(api, t.tenant_id) == 1


async def test_nobody_assigns_a_role_to_themselves(api: Api, keys: Keys) -> None:
    """R6.4 (RB17): proposing it → 403 `rbac_self_assignment`; confirming a
    grant proposed for oneself → 403, nothing assigned."""
    t = await _tenant(api)
    first = await _who(api, t, admin(**{keys.one: "tenant"}))
    second = await _who(api, t, admin(**{keys.one: "tenant"}))
    role = await _plant_role(api, t, _key(), {keys.one: "workspace"})
    role_key = await _role_key(api, role)

    mine = await _set_memberships(api, first, first.user_id, {t.main: [_own_role(first), role_key]})
    assert _reason(mine) == (403, "rbac_self_assignment"), mine.text
    assert await _proposals(api, t.tenant_id) == 0

    # A PUT replaces the person's roles: `second` keeps their own.
    keep = _own_role(second)
    for_second = await _set_memberships(api, first, second.user_id, {t.main: [keep, role_key]})
    assert for_second.status_code == 202, for_second.text
    [request] = for_second.json()["proposals"]
    refused = await _confirm(api, second, request)
    assert _reason(refused) == (403, "rbac_self_assignment"), refused.text
    assert await _holds(api, second.user_id, role) == 0
    assert await _status(api, request) == "proposed"


async def test_what_no_tenant_may_hold_never_enters(api: Api, keys: Keys) -> None:
    """R6.5 (RB18): `platform.admin` into a role, a role keyed `platform_admin`
    assigned or created: 422 `rbac_not_grantable`."""
    t = await _tenant(api)
    caller = await _who(api, t, admin())
    await _who(api, t, admin())
    role = await _plant_role(api, t, _key(), {})
    into_role = await _put_permissions(api, caller, role, {"platform.admin": "tenant"})
    assert _reason(into_role) == (422, "rbac_not_grantable"), into_role.text
    assert await _privileges(api, role) == set()

    await _plant_role(api, t, "platform_admin", {})
    grantee = await _who(api, t)
    assigned = await _set_memberships(api, caller, grantee.user_id, {t.main: ["platform_admin"]})
    assert _reason(assigned) == (422, "rbac_not_grantable"), assigned.text
    assert await _proposals(api, t.tenant_id) == 0


async def test_system_roles_keep_their_shape(api: Api, keys: Keys) -> None:
    """R6.6 (RB19): deleting `member` and re-privileging `tenant_owner` → 409
    `role_is_system`. A key changes through no route of the API (PATCH carries
    `name` and `description` only), so `member` keeps its key: 422 there."""
    t = await _tenant(api)
    caller = await _who(api, t, admin(**{keys.one: "tenant"}))
    await _who(api, t, admin(**{keys.one: "tenant"}))
    async with api.migrator.begin() as conn:
        member = await role_id(conn, t.tenant_id, "member")
        owner = await role_id(conn, t.tenant_id, "tenant_owner")

    deleted = await _call(
        api,
        caller,
        "DELETE",
        f"{_ROLES}/{member}",
        headers={"If-Match": await _etag(api, caller, member)},
    )
    assert _reason(deleted) == (409, "role_is_system"), deleted.text
    owners = await _put_permissions(api, caller, owner, {keys.one: "tenant"})
    assert _reason(owners) == (409, "role_is_system"), owners.text
    rekey = await _call(
        api,
        caller,
        "PATCH",
        f"{_ROLES}/{member}",
        content=json.dumps({"key": "thanh_vien"}),
        headers={
            "If-Match": await _etag(api, caller, member),
            "Content-Type": "application/merge-patch+json",
        },
    )
    assert rekey.status_code == 422, rekey.text
    assert await _role_key(api, member) == "member"
    assert (
        await _one(api, "SELECT deleted_at FROM platform.tenant_roles WHERE id = :r", r=member)
        is None
    )
    assert await _proposals(api, t.tenant_id) == 0


async def test_the_last_owner_stays(api: Api, keys: Keys) -> None:
    """R6.7 (RB20): the only active owner removing their own owner role
    (`PUT .../memberships`) or their membership (`DELETE /admin/members`) →
    409 `last_owner`, nothing changed. A `locked` company answers no route at
    all (403), so the raw-SQL test is where `locked` is held."""
    t = await _tenant(api)
    owner = await _who(api, t)
    async with api.migrator.begin() as conn:
        await assign(
            conn,
            t.tenant_id,
            t.main,
            owner.membership,
            await role_id(conn, t.tenant_id, "tenant_owner"),
        )
    owner_role = await _one(
        api,
        "SELECT id FROM platform.tenant_roles WHERE tenant_id = :t AND key = 'tenant_owner'",
        t=t.tenant_id,
    )

    dropped = await _set_memberships(api, owner, owner.user_id, {})
    assert _reason(dropped) == (409, "last_owner"), dropped.text
    removed = await _call(
        api,
        owner,
        "DELETE",
        f"{_ADMIN}/members/{owner.user_id}",
        params={"workspace_id": str(t.main)},
    )
    assert _reason(removed) == (409, "last_owner"), removed.text
    assert await _holds(api, owner.user_id, owner_role) == 1

    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'locked' WHERE id = :t"),
            {"t": t.tenant_id},
        )
    locked = await _set_memberships(api, owner, owner.user_id, {})
    assert locked.status_code == 403, locked.text
    assert await _holds(api, owner.user_id, owner_role) == 1


# ---- R5.3 (RB14): separation of duties at the confirmation ----------------


@pytest.fixture
async def rule(api: Api) -> AsyncIterator[tuple[str, str, str]]:
    suffix = uuid.uuid4().hex[:10]
    rule_key, order, pay = f"sod_test_{suffix}", f"test.s{suffix}.order", f"test.s{suffix}.pay"
    async with api.migrator.begin() as conn:
        for key in (order, pay):
            await register_key(conn, key)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.sod_rules (key, description, left_scopes, right_scopes,"
                " waivable) VALUES (:k, 'who orders does not pay', CAST(:l AS jsonb),"
                " CAST(:r AS jsonb), false)"
            ),
            {"k": rule_key, "l": f'["{order}"]', "r": f'["{pay}"]'},
        )
    yield rule_key, order, pay
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.sod_rules WHERE key = :k"), {"k": rule_key}
        )
        for key in (order, pay):
            await unregister_key(conn, key)


async def test_a_grant_making_both_sides_of_a_rule_is_refused_at_the_confirmation(
    api: Api, rule: tuple[str, str, str]
) -> None:
    """R5.3 (RB14): proposed 202; confirmed → 409 naming the rule and the
    holder, the proposal still `proposed`, no `.confirmed` audit event."""
    rule_key, order, pay = rule
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    checker = await _who(api, t, admin())
    orderer = await _plant_role(api, t, _key(), {order: "workspace"})
    payer = await _plant_role(api, t, _key(), {pay: "workspace"})
    grantee = await _who(api, t)
    await _assign(api, grantee, orderer)

    proposed = await _set_memberships(
        api,
        maker,
        grantee.user_id,
        {t.main: [await _role_key(api, orderer), await _role_key(api, payer)]},
    )
    assert proposed.status_code == 202, proposed.text
    [request] = proposed.json()["proposals"]
    refused = await _confirm(api, checker, request)
    assert _reason(refused) == (409, "ck_roles_sod_memberships"), refused.text
    assert refused.json()["details"]["rule"] == rule_key
    assert str(grantee.user_id) in refused.json()["details"]["holders"]
    assert await _status(api, request) == "proposed"
    assert await _holds(api, grantee.user_id, payer) == 0
    assert await _audits(api, t.tenant_id, "platform.role_change.confirmed") == 0


# ---- R3.3 (RB8): another tenant's ids ------------------------------------


async def test_another_tenants_ids_answer_not_found_and_change_nothing(
    api: Api, keys: Keys
) -> None:
    """R3.3 (RB8): A's administrator confirming or withdrawing B's proposal,
    reading B's role's assignments, setting B's member's memberships → 404,
    nothing changes; A's list holds none of B's proposals."""
    a = await _tenant(api)
    b = await _tenant(api)
    a_admin = await _who(api, a, admin())
    await _who(api, a, admin())
    a_open = (await _create_role(api, a_admin, _key())).json()["id"]
    b_admin = await _who(api, b, admin())
    await _who(api, b, admin())
    b_request = (await _create_role(api, b_admin, _key())).json()["id"]
    b_role = await _plant_role(api, b, _key(), {})
    b_person = await _who(api, b)
    await _assign(api, b_person, b_role)

    for answer in (
        await _confirm(api, a_admin, b_request),
        await _call(api, a_admin, "POST", f"{_CHANGES}/{b_request}/withdraw"),
        await _call(api, a_admin, "GET", f"{_ROLES}/{b_role}/assignments"),
        await _set_memberships(api, a_admin, b_person.user_id, {a.main: ["member"]}),
    ):
        assert answer.status_code == 404, answer.text
    assert await _status(api, b_request) == "proposed"
    assert await _holds(api, b_person.user_id, b_role) == 1
    assert (
        await _one(
            api, "SELECT count(*) FROM platform.memberships WHERE user_id = :u", u=b_person.user_id
        )
        == 1
    )
    assert await _proposals(api, a.tenant_id) == 1

    listed = await _call(api, a_admin, "GET", _CHANGES)
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["items"]}
    assert ids == {a_open}


# ---- R8.1-R8.5, R8.8: the routes' answers ---------------------------------


async def test_the_role_list_and_assignable_by_me(api: Api, keys: Keys) -> None:
    """R8.1: every field; `assignable_by_me` is `platform.rbac_refusals` for a
    grantee other than the caller at the caller's workspace, compared role by
    role with the function itself, for a caller with `bind` and one without."""
    t = await _tenant(api)
    binder = await _who(api, t, admin(**{keys.one: "tenant"}))
    reader = await _who(api, t, {READ: "tenant", keys.one: "workspace"})
    await _plant_role(api, t, _key(), {keys.one: "workspace"})
    await _plant_role(api, t, _key(), {keys.crit: "workspace"})
    await _plant_role(api, t, _key(), {keys.two: "tenant"})

    fields = {
        "id", "key", "name", "description", "kind", "is_system", "template_key",
        "holder_count", "version", "assignable_by_me", "updated_at",
    }  # fmt: skip
    seen: set[bool] = set()
    for caller in (binder, reader):
        listed = await _call(api, caller, "GET", _ROLES)
        assert listed.status_code == 200, listed.text
        roles = listed.json()
        assert roles and all(set(r) == fields for r in roles)
        for r in roles:
            refused = await _one(
                api,
                "SELECT EXISTS (SELECT 1 FROM platform.rbac_refusals(:t, :a,"
                " jsonb_build_object('op', 'grant', 'role_id', CAST(:r AS uuid),"
                " 'workspace_id', CAST(:w AS uuid)), false))",
                t=t.tenant_id,
                a=caller.user_id,
                r=r["id"],
                w=caller.workspace,
            )
            assert r["assignable_by_me"] is (not refused), (caller.user_id, r["key"])
            seen.add(r["assignable_by_me"])
    assert seen == {True, False}


async def test_a_route_refuses_without_its_key_and_proposes_nothing(api: Api, keys: Keys) -> None:
    """R8.2 (RB24): no `platform.roles.write` → 403 on `PUT .../permissions`
    and `POST /admin/roles`; `platform.members.write` without
    `platform.roles.bind` adding a role → 403; no proposal anywhere."""
    t = await _tenant(api)
    await _who(api, t, admin())
    await _who(api, t, admin())
    no_write = await _who(api, t, {READ: "tenant", BIND: "tenant", keys.one: "tenant"})
    no_bind = await _who(api, t, {READ: "tenant", MEMBERS_WRITE: "tenant", MEMBERS_READ: "tenant"})
    role = await _plant_role(api, t, _key(), {})
    grantee = await _who(api, t)

    assert (await _put_permissions(api, no_write, role, {keys.one: "tenant"})).status_code == 403
    assert (await _create_role(api, no_write, _key())).status_code == 403
    refused = await _set_memberships(api, no_bind, grantee.user_id, {t.main: ["member"]})
    assert refused.status_code == 403, refused.text
    assert await _proposals(api, t.tenant_id) == 0
    assert await _privileges(api, role) == set()


async def test_audit_events_are_ids_and_codes_and_a_refusal_writes_none(
    api: Api, keys: Keys
) -> None:
    """R8.3 (RB25): a proposal refused 409 writes no audit event; every event
    these routes write carries ids and codes only: no `@`, no display name."""
    t = await _tenant(api)
    email = f"{uuid.uuid4().hex[:10]}@khach.vn"
    maker = await _who(api, t, admin(**{keys.one: "tenant"}), email=email)
    lonely = await _tenant(api)
    solo = await _who(api, lonely, admin())
    before = await _all_audits(api, lonely.tenant_id)
    assert _reason(await _create_role(api, solo, _key())) == (409, "no_checker_available")
    assert await _all_audits(api, lonely.tenant_id) == before

    checker = await _who(api, t, admin(**{keys.one: "tenant"}))
    role_key = _key()
    made = (await _create_role(api, maker, role_key, body={"description": "Mô tả"})).json()
    assert (await _confirm(api, checker, made["id"])).status_code == 200
    role = uuid.UUID(made["payload"]["role_id"])
    widened = await _put_permissions(api, maker, role, {keys.one: "tenant"})
    assert (await _confirm(api, checker, widened.json()["proposal"]["id"])).status_code == 200
    invitee_email = f"{uuid.uuid4().hex[:10]}@khach.vn"
    invited = await _call(
        api,
        maker,
        "POST",
        f"{_ADMIN}/invitations",
        json={
            "display_name": "Bà Nguyễn Thị Mời",
            "email": invitee_email,
            "memberships": [{"workspace_id": str(t.main), "role_keys": [role_key]}],
        },
    )
    assert invited.status_code == 202, invited.text
    assert (await _confirm(api, checker, invited.json()["proposals"][0])).status_code == 200
    invitee = uuid.UUID(invited.json()["user_id"])
    revoked = await _set_memberships(api, maker, invitee, {t.main: []})
    assert revoked.status_code == 200, revoked.text
    pulled = (await _create_role(api, maker, _key())).json()["id"]
    assert (await _call(api, maker, "POST", f"{_CHANGES}/{pulled}/withdraw")).status_code == 200

    rows = await _rows(
        api,
        "SELECT action, details::text AS details FROM platform.audit_events WHERE tenant_id = :t",
        t=t.tenant_id,
    )
    actions = {r.action for r in rows}
    assert {
        "platform.role_change.proposed",
        "platform.role_change.confirmed",
        "platform.role_change.withdrawn",
        "platform.role.create",
        "platform.role.permissions_set",
        "platform.role_assignment.grant",
        "platform.role_assignment.revoke",
    } <= actions
    for r in rows:
        assert "@" not in r.details, r
        for name in ("Người thử", "Bà Nguyễn Thị Mời", "Vai ", "Mô tả"):
            assert name not in r.details, r


async def test_a_retry_with_its_key_answers_the_same_and_audits_once(api: Api) -> None:
    """R8.4 (RB25): the same `Idempotency-Key` and body, for a proposal and for
    its confirmation."""
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    checker = await _who(api, t, admin())
    key = {"Idempotency-Key": f"ra-{uuid.uuid4()}"}
    role_key = _key()
    first = await _create_role(api, maker, role_key, headers=key)
    again = await _create_role(api, maker, role_key, headers=key)
    assert first.status_code == again.status_code == 202, again.text
    assert first.json()["id"] == again.json()["id"]
    assert await _proposals(api, t.tenant_id) == 1
    assert await _audits(api, t.tenant_id, "platform.role_change.proposed") == 1

    confirm_key = {"Idempotency-Key": f"ra-{uuid.uuid4()}"}
    one = await _confirm(api, checker, first.json()["id"], headers=confirm_key)
    two = await _confirm(api, checker, first.json()["id"], headers=confirm_key)
    assert one.status_code == two.status_code == 200, two.text
    assert one.json() == two.json()
    assert await _audits(api, t.tenant_id, "platform.role_change.confirmed") == 1
    assert await _audits(api, t.tenant_id, "platform.role.create") == 1


async def test_a_role_write_names_the_version_it_read(api: Api, keys: Keys) -> None:
    """R8.5 (RB26): a stale `If-Match` → 412, no proposal, nothing changed;
    R8.8: a PATCH without `If-Match` → 428, nothing written."""
    t = await _tenant(api)
    maker = await _who(api, t, admin(**{keys.one: "tenant"}))
    await _who(api, t, admin(**{keys.one: "tenant"}))
    role = await _plant_role(api, t, _key(), {})
    version = await _version(api, role)
    stale = await _put_permissions(api, maker, role, {keys.one: "tenant"}, etag=f'"{version - 1}"')
    assert stale.status_code == 412, stale.text
    assert stale.json()["code"] == "precondition_failed"
    missing = await _call(
        api,
        maker,
        "PATCH",
        f"{_ROLES}/{role}",
        content=json.dumps({"name": "Không ghi"}),
        headers={"Content-Type": "application/merge-patch+json"},
    )
    assert missing.status_code == 428, missing.text
    assert missing.json()["code"] == "precondition_required"
    assert await _proposals(api, t.tenant_id) == 0
    assert await _privileges(api, role) == set()
    assert await _version(api, role) == version


# ---- R3.16 (RB42), G2: the bypass does not open role routes ----------------


async def test_platform_admin_without_a_key_is_refused_on_role_routes(api: Api, keys: Keys) -> None:
    """R3.16 (RB42): `platform_admin` in `memberships.role_keys` (planted by the
    migrator) and no key: `POST /admin/roles`, `PUT .../memberships`,
    `POST /admin/invitations` and a confirmation → 403, nothing changed. The
    role chosen carries no privilege, so only the bypass list stands between
    the caller and a proposal. G2: the same caller passes a route off the list."""
    t = await _tenant(api)
    maker = await _who(api, t, admin())
    await _who(api, t, admin())
    bypass = await _who(api, t)
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.memberships SET role_keys = role_keys || '[\"platform_admin\"]'"
                " WHERE id = :m"
            ),
            {"m": bypass.membership},
        )
    empty_key = _key()
    await _plant_role(api, t, empty_key, {})
    pending = (await _create_role(api, maker, _key())).json()["id"]
    grantee = await _who(api, t)
    proposals = await _proposals(api, t.tenant_id)
    email = f"{uuid.uuid4().hex[:10]}@khach.vn"

    answers = {
        "POST /admin/roles": await _create_role(api, bypass, _key()),
        "PUT memberships": await _set_memberships(
            api, bypass, grantee.user_id, {t.main: [empty_key]}
        ),
        "POST /admin/invitations": await _call(
            api,
            bypass,
            "POST",
            f"{_ADMIN}/invitations",
            json={
                "display_name": "Người qua cửa",
                "email": email,
                "memberships": [{"workspace_id": str(t.main), "role_keys": [empty_key]}],
            },
        ),
        "confirm": await _confirm(api, bypass, pending),
    }
    assert {name: a.status_code for name, a in answers.items()} == dict.fromkeys(answers, 403)
    assert await _proposals(api, t.tenant_id) == proposals
    assert await _status(api, pending) == "proposed"
    assert await _one(api, "SELECT count(*) FROM platform.users WHERE email = :e", e=email) == 0

    me = await _call(api, bypass, "GET", "/api/v1/me")
    assert me.json()["platform_bypass"] is True, me.text
    assert (await _call(api, bypass, "GET", "/api/v1/directory/members")).status_code == 200
    assert (await _call(api, bypass, "GET", f"{_ADMIN}/members")).status_code == 200


# ---- RB16: service accounts -------------------------------------------------


async def _service_account(api: Api, t: PlantedTenant, owner: uuid.UUID) -> uuid.UUID:
    account = uuid.uuid4()
    async with api.migrator.begin() as conn:
        for sql in (
            "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
            " VALUES (:u, :s, 'tài khoản', 'service', :t)",
            "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
            " VALUES (:t, :u, 'active')",
            "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
            " name, owner_user_id) VALUES (:u, :t, :w, :n, :o)",
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
            " VALUES (gen_random_uuid(), :t, :w, :u)",
        ):
            await conn.execute(
                sa.text(sql),
                {
                    "u": account,
                    "s": f"service:{account}",
                    "t": t.tenant_id,
                    "w": t.main,
                    "n": f"sa {account.hex[:8]}",
                    "o": owner,
                },
            )
    return account


async def test_a_service_account_never_reaches_a_critical_role(api: Api, keys: Keys) -> None:
    """R6.3 (RB16), org-and-principals R6.4: a critical role proposed for a
    service account → 422 `role_not_allowed_for_service`, no proposal; a
    non-critical one proposed, then a critical key added to it and confirmed
    first → the grant's confirmation `proposal_stale`, and proposing it again
    → 422; a critical key confirmed into a role a service account holds → 422,
    nothing changed."""
    t = await _tenant(api)
    maker = await _who(api, t, admin(**{keys.one: "tenant", keys.crit: "tenant"}))
    checker = await _who(api, t, admin(**{keys.one: "tenant", keys.crit: "tenant"}))
    account = await _service_account(api, t, maker.user_id)
    critical_key = _key()
    await _plant_role(api, t, critical_key, {keys.crit: "workspace"})
    refused = await _set_memberships(api, maker, account, {t.main: [critical_key]})
    assert _reason(refused) == (422, "role_not_allowed_for_service"), refused.text
    assert await _proposals(api, t.tenant_id) == 0

    plain_key = _key()
    plain = await _plant_role(api, t, plain_key, {keys.one: "workspace"})
    grant = await _set_memberships(api, maker, account, {t.main: [plain_key]})
    assert grant.status_code == 202, grant.text
    widen = await _put_permissions(
        api, maker, plain, {keys.one: "workspace", keys.crit: "workspace"}
    )
    assert widen.status_code == 202, widen.text
    assert (await _confirm(api, checker, widen.json()["proposal"]["id"])).status_code == 200
    stale = await _confirm(api, checker, grant.json()["proposals"][0])
    assert _reason(stale) == (409, "proposal_stale"), stale.text
    assert await _holds(api, account, plain) == 0
    proposals = await _proposals(api, t.tenant_id)
    again = await _set_memberships(api, maker, account, {t.main: [plain_key]})
    assert _reason(again) == (422, "role_not_allowed_for_service"), again.text
    assert await _proposals(api, t.tenant_id) == proposals

    held = await _plant_role(api, t, _key(), {keys.one: "workspace"})
    async with api.migrator.begin() as conn:
        membership = await conn.scalar(
            sa.text("SELECT id FROM platform.memberships WHERE user_id = :u"), {"u": account}
        )
        await assign(conn, t.tenant_id, t.main, membership, held)
    critical = await _put_permissions(
        api, maker, held, {keys.one: "workspace", keys.crit: "workspace"}
    )
    assert critical.status_code == 202, critical.text
    request = critical.json()["proposal"]["id"]
    applied = await _confirm(api, checker, request)
    assert _reason(applied) == (422, "role_not_allowed_for_service"), applied.text
    assert await _privileges(api, held) == {(keys.one, "workspace")}
    assert await _status(api, request) == "proposed"


# ---- R7.5 (RB21): a Digital Worker's principal ------------------------------


def _dw_body(role_key: str, owner: Who, technical: Who) -> dict[str, Any]:
    return {
        "key": f"dw_{uuid.uuid4().hex[:10]}",
        "name": "Chăm sóc lead",
        "mandate": "Gửi thư chào lead mới.",
        "work_kinds": ["lead.new"],
        "allowed_tools": [],
        "workflow_key": "leadcare",
        "workflow_version": "1.0.0",
        "role_keys": [role_key],
        "people": {
            "business_owner_id": str(owner.user_id),
            "technical_owner_id": str(technical.user_id),
            "work_assigner_id": str(owner.user_id),
            "validator_id": str(owner.user_id),
        },
        "decision_classes": [],
    }


_DW_PEOPLE = {"dw.manage": "tenant", "dw.read": "tenant", "approvals.decide": "tenant"}


async def test_a_dw_principal_gets_its_roles_with_the_dw_and_a_second_person_starts_it(
    dw_api: Api, keys: Keys
) -> None:
    """R7.5 (RB21): a DW made with the tenant role `approver` → 201, its
    principal holds the role, no proposal; its creator moving it to
    `operating` → 409 `second_person_required`; a second person who does not
    hold the role's key → 403 `grants_not_covered`."""
    t = await _tenant(dw_api)
    approver = await _plant_role(dw_api, t, "approver", {keys.one: "workspace"})
    creator = await _who(dw_api, t, {**_DW_PEOPLE, keys.one: "tenant"})
    second = await _who(dw_api, t, {"dw.read": "tenant", "dw.manage": "tenant"})

    made = await _call(
        dw_api,
        creator,
        "POST",
        "/api/v1/digital-workers",
        json=_dw_body("approver", creator, second),
    )
    assert made.status_code == 201, made.text
    worker = made.json()
    principal = uuid.UUID(worker["principal_user_id"])
    assert await _holds(dw_api, principal, approver) == 1
    assert await _proposals(dw_api, t.tenant_id) == 0

    path = f"/api/v1/digital-workers/{worker['id']}/state"
    own = await _call(dw_api, creator, "POST", path, json={"state": "operating"})
    assert _reason(own) == (409, "second_person_required"), own.text
    uncovered = await _call(dw_api, second, "POST", path, json={"state": "operating"})
    assert _reason(uncovered) == (403, "grants_not_covered"), uncovered.text
    assert (
        await _one(
            dw_api, "SELECT state FROM platform.digital_workers WHERE id = :d", d=worker["id"]
        )
        == "draft"
    )


async def test_a_confirmation_and_a_dw_creation_on_one_role_both_finish(
    dw_api: Api, keys: Keys
) -> None:
    """R7.8 (RB43): B confirms a `role_permissions` proposal adding a key that
    is not critical to R, statement by statement in the order of
    `SqlRoleAdminRepository.confirm`, and stops right after locking R; A
    creates a DW with R through the route until `pg_locks` shows A waiting; B
    goes on and commits: both finish, neither meets 40P01."""
    t = await _tenant(dw_api)
    maker = await _who(dw_api, t, admin(**{keys.one: "tenant", keys.two: "tenant"}))
    checker = await _who(dw_api, t, admin(**{keys.one: "tenant", keys.two: "tenant"}))
    role_key = _key()
    role = await _plant_role(dw_api, t, role_key, {keys.one: "workspace"})
    creator = await _who(dw_api, t, {**_DW_PEOPLE, keys.one: "tenant", keys.two: "tenant"})
    proposed = await _put_permissions(
        dw_api, maker, role, {keys.one: "workspace", keys.two: "workspace"}
    )
    assert proposed.status_code == 202, proposed.text
    request = uuid.UUID(proposed.json()["proposal"]["id"])

    assert dw_api.container.engine is not None
    sessions = async_sessionmaker(dw_api.container.engine, expire_on_commit=False)
    context = AccessContext(
        tenant_id=t.tenant_id,
        workspace_id=t.main,
        principal_id=checker.user_id,
        roles=frozenset(),
        plan_id="professional",
    )
    waiting = (
        # A row lock is waited for on the holder's transaction id, a lock
        # with no database: the waiter's session names it.
        "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
        " WHERE a.datname = current_database() AND NOT l.granted"
    )
    creation: asyncio.Task[httpx.Response] | None = None
    async with tenant_session(sessions, TenantScope.from_access_context(context)) as session:
        proposal = await role_admin_repo._locked_open_proposal(session, context, request)
        await role_admin_repo._check_still_true(session, context, proposal)  # locks R
        creation = asyncio.create_task(
            _call(
                dw_api,
                creator,
                "POST",
                "/api/v1/digital-workers",
                json=_dw_body(role_key, creator, creator),
            )
        )
        for _ in range(200):
            if creation.done() or int(await _one(dw_api, waiting)) > 0:
                break
            await asyncio.sleep(0.05)
        assert not creation.done(), (await creation).text
        assert int(await _one(dw_api, waiting)) > 0, "the premise: A waits for R"
        await role_admin_repo._refuse_for_confirmer(session, context, proposal)
        await session.execute(
            sa.text(
                "UPDATE platform.role_change_requests"
                " SET status = 'confirmed', confirmed_by = :c, decided_at = now() WHERE id = :r"
            ),
            {"c": checker.user_id, "r": request},
        )
        await session.execute(
            sa.text("SELECT set_config('app.role_change_id', :id, true)"), {"id": str(request)}
        )
        await role_admin_repo._apply(session, context, proposal)
    made = await asyncio.wait_for(creation, timeout=30)
    assert made.status_code == 201, made.text
    assert await _privileges(dw_api, role) == {(keys.one, "workspace"), (keys.two, "workspace")}
    assert await _holds(dw_api, uuid.UUID(made.json()["principal_user_id"]), role) == 1
