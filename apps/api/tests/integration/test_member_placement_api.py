# ruff: noqa: F811  (the fixture of test_tenant_roles_api is imported by name)
"""Placing a person in a workspace with no role, and no proposal only its
assignee could confirm (tenant-rbac ticket 16: R3.3, R6.4, R7.1, R7.3, R7.6,
R8.2; RB8, RB17, RB21, RB22, RB24, RB32).

`PUT /api/v1/admin/members/{user_id}/memberships` in the running app, over
PostgreSQL: each workspace of the body is a membership the person has
afterwards, `role_keys: []` a membership with no role (one person, one audit,
no proposal), and a role proposed for someone whom nobody but the caller and
that person could confirm is refused before anything is written. People are
planted as `dw_migrator` with the helpers of `test_role_admin_api.py`.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
import sqlalchemy as sa
from test_role_admin_api import (
    BIND,
    MEMBERS_READ,
    MEMBERS_WRITE,
    READ,
    Who,
    _audits,
    _call,
    _confirm,
    _one,
    _proposals,
    _reason,
    _rows,
    _set_memberships,
    _tenant,
    _who,
    admin,
)
from test_service_principals_api import _plant_dw
from test_tenant_roles_api import Api, api  # noqa: F401  (fixture, used by name)

from dw_platform.testing.rbac import PlantedTenant, assign, plant_membership, plant_role, role_id

pytestmark = pytest.mark.integration

_ADMIN = "/api/v1/admin"
GRANT = "platform.membership.grant"


async def _owner(api: Api, t: PlantedTenant) -> Who:
    who = await _who(api, t)
    async with api.migrator.begin() as conn:
        owner = await role_id(conn, t.tenant_id, "tenant_owner")
        await assign(conn, t.tenant_id, t.main, who.membership, owner)
    return who


async def _role(api: Api, t: PlantedTenant, *, kind: str = "role") -> str:
    """A role of no critical key; its key."""
    key = f"r_{uuid.uuid4().hex[:12]}"
    async with api.migrator.begin() as conn:
        await plant_role(conn, t.tenant_id, key, {}, kind=kind)
    return key


async def _workspaces_of(api: Api, t: PlantedTenant, user: uuid.UUID) -> set[uuid.UUID]:
    rows = await _rows(
        api,
        "SELECT workspace_id FROM platform.memberships WHERE tenant_id = :t AND user_id = :u",
        t=t.tenant_id,
        u=user,
    )
    return {r.workspace_id for r in rows}


async def _binders(api: Api, t: PlantedTenant) -> set[uuid.UUID]:
    rows = await _rows(
        api,
        "SELECT c FROM platform.checker_candidates(CAST(:t AS uuid), :k, NULL) AS c",
        t=t.tenant_id,
        k=BIND,
    )
    return {r.c for r in rows}


async def _grants(api: Api, t: PlantedTenant, user: uuid.UUID) -> set[tuple[str, str]]:
    rows = await _rows(
        api,
        "SELECT permission_key, depth FROM platform.effective_grants(CAST(:t AS uuid),"
        " CAST(:u AS uuid))",
        t=t.tenant_id,
        u=user,
    )
    return {(r.permission_key, r.depth) for r in rows}


def _in(who: Who, workspace: uuid.UUID) -> Who:
    return dataclasses.replace(who, workspace=workspace)


def _second(t: PlantedTenant) -> uuid.UUID:
    return next(w for w in t.workspaces if w != t.main)


# ---- R7.1 (RB21): a membership with no role is one person and one audit --------------


async def test_r7_1_role_keys_empty_places_the_person_with_no_role_and_no_proposal(
    api: Api,
) -> None:
    t = await _tenant(api, workspaces=3)
    w, w2 = (ws for ws in t.workspaces if ws != t.main)
    writer = await _who(api, t, {MEMBERS_WRITE: "tenant", MEMBERS_READ: "tenant"})
    person = await _who(api, t)
    grants = await _grants(api, t, person.user_id)
    assignments = "SELECT count(*) FROM platform.role_assignments WHERE tenant_id = :t"
    before = (await _proposals(api, t.tenant_id), int(await _one(api, assignments, t=t.tenant_id)))

    placed = await _set_memberships(api, writer, person.user_id, {t.main: [], w: []})

    assert placed.status_code == 200, placed.text
    body = placed.json()
    assert {m["workspace_id"]: m["role_keys"] for m in body["memberships"]} == {
        str(t.main): [],
        str(w): [],
    }
    assert body["proposals"] == []
    assert await _workspaces_of(api, t, person.user_id) == {t.main, w}
    assert await _audits(api, t.tenant_id, GRANT) == 1
    after = (await _proposals(api, t.tenant_id), int(await _one(api, assignments, t=t.tenant_id)))
    assert after == before
    assert await _grants(api, t, person.user_id) == grants

    # Two people: a role added is a proposal, in force once a third confirms.
    caller = await _who(api, t, admin())
    await _who(api, t, admin())
    role = await _role(api, t)
    proposed = await _set_memberships(api, caller, person.user_id, {t.main: [], w: [], w2: [role]})
    assert proposed.status_code == 202, proposed.text
    assert len(proposed.json()["proposals"]) == 1


async def test_r7_1_two_owners_place_each_other_and_work_there(api: Api) -> None:
    """marketing-pilot/02's case: a company of two owners and no one else
    holding `platform.roles.bind`."""
    t = await _tenant(api, workspaces=2)
    w = _second(t)
    o1, o2 = await _owner(api, t), await _owner(api, t)
    assert await _binders(api, t) == {o1.user_id, o2.user_id}
    for caller, other in ((o1, o2), (o2, o1)):
        placed = await _set_memberships(
            api, caller, other.user_id, {t.main: ["tenant_owner"], w: []}
        )
        assert placed.status_code == 200, placed.text
    for owner in (o1, o2):
        me = await _call(api, _in(owner, w), "GET", "/api/v1/me")
        assert me.status_code == 200, me.text


# ---- K5 (digital-worker R1.17): a DW principal gets no new membership ---------------


async def test_r7_1_k5_a_digital_workers_principal_gets_no_new_membership(api: Api) -> None:
    t = await _tenant(api, workspaces=2)
    owner = await _owner(api, t)
    principal = await _plant_dw(api, t, t.main, owner.user_id)
    refused = await _set_memberships(api, owner, principal, {t.main: [], _second(t): []})
    assert _reason(refused) == (409, "dw_principal_roles_fixed"), refused.text
    assert await _workspaces_of(api, t, principal) == {t.main}


# ---- K1 (R8.2): only `platform.members.write` places a person ----------------------


async def test_r8_2_k1_a_binder_without_members_write_places_nobody(api: Api) -> None:
    t = await _tenant(api, workspaces=2)
    binder = await _who(api, t, {BIND: "tenant", READ: "tenant", MEMBERS_READ: "tenant"})
    person = await _who(api, t)
    refused = await _set_memberships(api, binder, person.user_id, {t.main: [], _second(t): []})
    assert refused.status_code == 403, refused.text
    assert await _workspaces_of(api, t, person.user_id) == {t.main}
    assert await _audits(api, t.tenant_id, GRANT) == 0


# ---- K2 (R3.3): nobody of another company, no workspace of another company -----------


async def test_r3_3_k2_another_companys_person_or_workspace_is_not_found(api: Api) -> None:
    a, b = await _tenant(api), await _tenant(api)
    owner = await _owner(api, a)
    person = await _who(api, a)
    stranger = await _who(api, b)
    foreign = await _set_memberships(api, owner, stranger.user_id, {a.main: []})
    assert foreign.status_code == 404, foreign.text
    elsewhere = await _set_memberships(api, owner, person.user_id, {a.main: [], b.main: []})
    assert elsewhere.status_code == 404, elsewhere.text
    assert await _workspaces_of(api, a, person.user_id) == {a.main}
    assert await _workspaces_of(api, b, stranger.user_id) == {b.main}
    assert await _audits(api, a.tenant_id, GRANT) == 0
    assert await _audits(api, b.tenant_id, GRANT) == 0


# ---- K3 (R6.4): nobody places themself in a new workspace ---------------------------


async def test_r6_4_k3_nobody_places_themself_in_a_new_workspace(api: Api) -> None:
    t = await _tenant(api, workspaces=2)
    w = _second(t)
    o1, o2 = await _owner(api, t), await _owner(api, t)
    body = {t.main: ["tenant_owner"], w: []}
    refused = await _set_memberships(api, o1, o1.user_id, body)
    assert _reason(refused) == (403, "rbac_self_assignment"), refused.text
    assert await _workspaces_of(api, t, o1.user_id) == {t.main}
    assert await _audits(api, t.tenant_id, GRANT) == 0
    placed = await _set_memberships(api, o1, o2.user_id, body)
    assert placed.status_code == 200, placed.text


# ---- K4 (R7.3): no proposal only its assignee could confirm -------------------------


async def test_r7_3_k4_a_grant_only_its_assignee_could_confirm_is_refused(api: Api) -> None:
    t = await _tenant(api, workspaces=2)
    w = _second(t)
    o1, o2 = await _owner(api, t), await _owner(api, t)
    assert await _binders(api, t) == {o1.user_id, o2.user_id}
    role = await _role(api, t)
    body = {t.main: ["tenant_owner"], w: [role]}
    refused = await _set_memberships(api, o1, o2.user_id, body)
    assert _reason(refused) == (409, "no_checker_available"), refused.text
    assert await _proposals(api, t.tenant_id) == 0
    assert await _workspaces_of(api, t, o2.user_id) == {t.main}
    permission_set = await _role(api, t, kind="permission_set")
    sets = await _call(
        api,
        o1,
        "PUT",
        f"{_ADMIN}/members/{o2.user_id}/permission-sets",
        json={"permission_set_keys": [permission_set]},
    )
    assert _reason(sets) == (409, "no_checker_available"), sets.text
    assert await _proposals(api, t.tenant_id) == 0

    # A third holder: the proposal is written, and confirmed by them; the
    # assignee confirming their own is refused at the confirmation too.
    checker = await _who(api, t, admin())
    proposed = await _set_memberships(api, o1, o2.user_id, body)
    assert proposed.status_code == 202, proposed.text
    request = proposed.json()["proposals"][0]
    own = await _confirm(api, o2, request)
    assert _reason(own) == (403, "rbac_self_assignment"), own.text
    confirmed = await _confirm(api, checker, request)
    assert confirmed.status_code == 200, confirmed.text


# ---- K6 (R7.6, R8.2): `[]` on a membership with roles keeps it --------------------


async def _placed_person(api: Api, t: PlantedTenant, role: str) -> tuple[Who, uuid.UUID]:
    """P: `member` in main, ``role`` in W, a membership with no role in Y."""
    w, y, _x = (ws for ws in t.workspaces if ws != t.main)
    person = await _who(api, t)
    async with api.migrator.begin() as conn:
        member = await role_id(conn, t.tenant_id, "member")
        await assign(conn, t.tenant_id, t.main, person.membership, member)
        there = await plant_membership(conn, t.tenant_id, w, person.user_id)
        await assign(conn, t.tenant_id, w, there, await role_id(conn, t.tenant_id, role))
        await plant_membership(conn, t.tenant_id, y, person.user_id)
        assignment = await conn.scalar(
            sa.text(
                "SELECT a.id FROM platform.role_assignments a"
                " JOIN platform.tenant_roles r ON r.id = a.role_id"
                " WHERE a.membership_id = :m AND r.key = :k"
            ),
            {"m": there, "k": role},
        )
    return person, assignment


async def test_r7_6_k6_an_empty_list_keeps_the_membership_and_revokes_its_roles(
    api: Api,
) -> None:
    t = await _tenant(api, workspaces=4)
    w, y, x = (ws for ws in t.workspaces if ws != t.main)
    role = await _role(api, t)
    person, assignment = await _placed_person(api, t, role)
    body = {t.main: ["member"], w: [], y: []}
    still = "SELECT count(*) FROM platform.role_assignments WHERE id = :a"

    writer = await _who(api, t, {MEMBERS_WRITE: "tenant", MEMBERS_READ: "tenant"})
    refused = await _set_memberships(api, writer, person.user_id, body)
    assert refused.status_code == 403, refused.text
    assert await _one(api, still, a=assignment) == 1

    caller = await _who(api, t, admin())
    await _who(api, t, admin())
    revoked = await _set_memberships(api, caller, person.user_id, body)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["proposals"] == []
    assert await _one(api, still, a=assignment) == 0
    assert await _audits(api, t.tenant_id, "platform.role_assignment.revoke") == 1
    assert await _workspaces_of(api, t, person.user_id) == {t.main, w, y}

    # The web's save of a role elsewhere sends the empty memberships back.
    saved = await _set_memberships(
        api, caller, person.user_id, {t.main: ["member"], w: [], y: [], x: []}
    )
    assert saved.status_code == 200, saved.text
    assert await _workspaces_of(api, t, person.user_id) == {t.main, w, y, x}
