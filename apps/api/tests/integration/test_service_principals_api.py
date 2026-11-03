# ruff: noqa: F811  (the fixture of test_tenant_roles_api is imported by name)
"""A company's service accounts through the real app on a migrated Postgres
(org-and-principals ticket 03).

R6.1 (one transaction, nothing left by a refusal, an `Idempotency-Key`),
R6.4 (the role-assignment route answers 422 `role_not_allowed_for_service`),
R6.12 (the list: the caller's tenant, never a DW's principal, only what the
caller reaches), R6.13, R6.14 (PATCH: 404 for what is not this company's
account, 403 without `.manage`), R6.16, R6.17 (the accountable owner).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import sqlalchemy as sa
from test_tenant_roles_api import SECRET, Api, api  # noqa: F401  (fixture, used by name)

from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.service_principals import (
    SERVICE_PRINCIPALS_MANAGE_SCOPE,
    SERVICE_PRINCIPALS_USE_SCOPE,
)
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    unregister_key,
)

_BASE = "/api/v1/admin/service-principals"
_BOTH = {SERVICE_PRINCIPALS_MANAGE_SCOPE: "tenant", SERVICE_PRINCIPALS_USE_SCOPE: "tenant"}


@dataclass(frozen=True)
class Caller:
    subject: str
    user_id: uuid.UUID
    tenant: PlantedTenant
    workspace: uuid.UUID


async def _call(api: Api, caller: Caller, method: str, path: str, **kw: Any) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue(caller.subject)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(caller.tenant.tenant_id),
        "X-Workspace-Id": str(caller.workspace),
        **kw.pop("headers", {}),
    }
    return await api.client.request(method, path, headers=headers, **kw)


async def _caller(
    api: Api,
    tenant: PlantedTenant,
    privileges: dict[str, str] | None = None,
    *,
    anchor: uuid.UUID | None = None,
) -> Caller:
    """A person with a membership in `main` and, when given, a role carrying
    `privileges`, assigned where `anchor` says (the main workspace otherwise)."""
    anchor = anchor or tenant.main
    async with api.migrator.begin() as conn:
        person = await plant_person(conn, tenant.tenant_id)
        subject = f"sp-api-{person}"
        await conn.execute(
            sa.text("UPDATE platform.users SET subject = :s WHERE id = :u"),
            {"s": subject, "u": person},
        )
        here = await plant_membership(conn, tenant.tenant_id, tenant.main, person)
        there = (
            here
            if anchor == tenant.main
            else await plant_membership(conn, tenant.tenant_id, anchor, person)
        )
        if privileges:
            role = await plant_role(conn, tenant.tenant_id, f"r_{person.hex[:12]}", privileges)
            await assign(conn, tenant.tenant_id, anchor, there, role)
    return Caller(subject, person, tenant, tenant.main)


async def _create(
    api: Api, caller: Caller, owner: uuid.UUID, *, name: str | None = None, **kw: Any
) -> httpx.Response:
    body = {
        "name": name or f"Tài khoản {uuid.uuid4().hex[:8]}",
        "description": "Chạy theo lịch",
        "owning_workspace_id": str(caller.tenant.main),
        "owner_user_id": str(owner),
        **kw.pop("body", {}),
    }
    return await _call(api, caller, "POST", _BASE, json=body, **kw)


async def _rows(api: Api, sql: str, **values: object) -> list[Any]:
    async with api.migrator.connect() as conn:
        return list((await conn.execute(sa.text(sql), values)).all())


async def test_creating_an_account_writes_its_user_member_row_membership_and_audit(
    api: Api,
) -> None:
    """R6.1 (OP17's happy path): one transaction, the tenant the context's."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
    admin = await _caller(api, t, _BOTH)
    answer = await _create(api, admin, admin.user_id)
    assert answer.status_code == 201, answer.text
    view = answer.json()
    account = uuid.UUID(view["id"])
    assert view["status"] == "active" and view["owner_missing"] is False
    assert view["owning_workspace_id"] == str(t.main)

    [user] = await _rows(
        api,
        "SELECT subject, email, kind, owner_tenant_id FROM platform.users WHERE id = :u",
        u=account,
    )
    assert tuple(user) == (f"service:{account}", None, "service", t.tenant_id)
    assert await _rows(
        api, "SELECT status FROM platform.tenant_members WHERE user_id = :u", u=account
    ) == [("active",)]
    [membership] = await _rows(
        api,
        "SELECT m.workspace_id, count(a.id) FROM platform.memberships m"
        " LEFT JOIN platform.role_assignments a ON a.membership_id = m.id"
        " WHERE m.user_id = :u GROUP BY m.workspace_id",
        u=account,
    )
    assert tuple(membership) == (t.main, 0)
    [principal] = await _rows(
        api,
        "SELECT owner_user_id, created_by FROM platform.service_principals WHERE user_id = :u",
        u=account,
    )
    assert tuple(principal) == (admin.user_id, admin.user_id)
    [audit] = await _rows(
        api,
        "SELECT action, actor_id, details FROM platform.audit_events WHERE resource_id = :r",
        r=str(account),
    )
    assert (audit.action, audit.actor_id) == ("platform.service_principal.created", admin.user_id)
    assert audit.details == {
        "owning_workspace_id": str(t.main),
        "owner_user_id": str(admin.user_id),
    }


async def test_a_refused_create_writes_nothing(api: Api) -> None:
    """R6.1: without `.manage` 403; a workspace of another tenant and an
    unknown one the same 422 at `/owning_workspace_id`; a name taken 409; an
    owner who is not `active` 422 `owner_not_member`, refused after the user
    and the company row were written, which roll back with it."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
        other = await plant_tenant(conn)
        suspended = await plant_person(conn, t.tenant_id, status="suspended")
    admin = await _caller(api, t, _BOTH)
    nobody = await _caller(api, t, {SERVICE_PRINCIPALS_USE_SCOPE: "tenant"})
    services = "SELECT count(*) FROM platform.users WHERE kind = 'service' AND owner_tenant_id = :t"
    taken = await _create(api, admin, admin.user_id, name="Lịch đêm")
    assert taken.status_code == 201
    [(before,)] = await _rows(api, services, t=t.tenant_id)

    forbidden = await _create(api, nobody, admin.user_id)
    assert forbidden.status_code == 403
    for workspace in (other.main, uuid.uuid4()):
        wrong = await _create(
            api, admin, admin.user_id, body={"owning_workspace_id": str(workspace)}
        )
        assert wrong.status_code == 422, wrong.text
        problem = wrong.json()
        assert problem["code"] == "validation_failed"
        assert [e["pointer"] for e in problem["errors"]] == ["/owning_workspace_id"]
    twice = await _create(api, admin, admin.user_id, name="Lịch đêm")
    assert (twice.status_code, twice.json()["details"]["reason_code"]) == (
        409,
        "service_principal_name_taken",
    )
    absent = await _create(api, admin, suspended)
    assert (absent.status_code, absent.json()["details"]["reason_code"]) == (
        422,
        "owner_not_member",
    )
    assert await _rows(api, services, t=t.tenant_id) == [(before,)]


async def test_a_create_retried_with_its_key_makes_one_account(api: Api) -> None:
    """R6.1, ADR-0108 decision 4: the `Idempotency-Key` is optional and, sent,
    answers a retry with the account the first attempt made."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
    admin = await _caller(api, t, _BOTH)
    key = {"Idempotency-Key": f"sp-{uuid.uuid4()}"}
    first = await _create(api, admin, admin.user_id, name="Một lần", headers=key)
    again = await _create(api, admin, admin.user_id, name="Một lần", headers=key)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert await _rows(
        api,
        "SELECT count(*) FROM platform.service_principals WHERE tenant_id = :t",
        t=t.tenant_id,
    ) == [(1,)]


async def _plant_dw(
    api: Api, t: PlantedTenant, workspace: uuid.UUID, owner: uuid.UUID
) -> uuid.UUID:
    principal = uuid.uuid4()
    async with api.migrator.begin() as conn:
        for sql in (
            "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
            " VALUES (:u, :s, 'dw', 'service', :t)",
            "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
            " VALUES (:t, :u, 'active')",
            "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
            " name, owner_user_id) VALUES (:u, :t, :w, :n, :o)",
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
            " VALUES (gen_random_uuid(), :t, :w, :u)",
            "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
            " principal_user_id, key, name, mandate, work_kinds, allowed_tools,"
            " workflow_key, workflow_version, technical_owner_id, work_assigner_id,"
            " validator_id, created_by) VALUES (gen_random_uuid(), :t, :w, :u, :k, 'dw',"
            " 'dw', ARRAY['lead'], ARRAY[]::text[], 'wf', '1.0.0', :o, :o, :o, :o)",
        ):
            await conn.execute(
                sa.text(sql),
                {
                    "u": principal,
                    "s": f"service:{principal}",
                    "t": t.tenant_id,
                    "w": workspace,
                    "n": f"dw {principal.hex[:8]}",
                    "o": owner,
                    "k": f"dw_{principal.hex[:12]}",
                },
            )
    return principal


async def _listed(api: Api, caller: Caller) -> dict[uuid.UUID, dict[str, Any]]:
    answer = await _call(api, caller, "GET", _BASE)
    assert answer.status_code == 200, answer.text
    return {uuid.UUID(item["id"]): item for item in answer.json()["items"]}


async def test_the_list_holds_what_the_caller_reaches_in_their_own_company(api: Api) -> None:
    """R6.12 (OP17): B's admin sees none of A's; a holder of `.use` only in
    another workspace does not see it; a `.manage` holder at tenant depth
    standing in W1 does not see the principal of a DW in W2 (nor in W1)."""
    async with api.migrator.begin() as conn:
        a = await plant_tenant(conn, workspaces=2)
        b = await plant_tenant(conn)
    admin = await _caller(api, a, _BOTH)
    b_admin = await _caller(api, b, _BOTH)
    elsewhere = await _caller(
        api, a, {SERVICE_PRINCIPALS_USE_SCOPE: "workspace"}, anchor=a.workspaces[1]
    )
    account = uuid.UUID((await _create(api, admin, admin.user_id)).json()["id"])
    dw_here = await _plant_dw(api, a, a.main, admin.user_id)
    dw_there = await _plant_dw(api, a, a.workspaces[1], admin.user_id)

    mine = await _listed(api, admin)
    assert account in mine and mine[account]["bindable_by_me"] is True
    assert dw_here not in mine and dw_there not in mine
    assert account not in await _listed(api, b_admin)
    assert account not in await _listed(api, elsewhere)


async def test_a_patch_of_what_is_not_this_companys_account_is_not_found(api: Api) -> None:
    """R6.13 (OP17): A's account named by B's admin, a DW's principal in the
    caller's workspace and in another, a person, an unknown id: one 404, and
    nothing changes."""
    async with api.migrator.begin() as conn:
        a = await plant_tenant(conn, workspaces=2)
        b = await plant_tenant(conn)
    admin = await _caller(api, a, _BOTH)
    b_admin = await _caller(api, b, _BOTH)
    account = uuid.UUID((await _create(api, admin, admin.user_id, name="Giữ tên")).json()["id"])
    dw_here = await _plant_dw(api, a, a.main, admin.user_id)
    dw_there = await _plant_dw(api, a, a.workspaces[1], admin.user_id)
    rename = {"name": "Đổi tên"}
    for caller, target in (
        (b_admin, account),
        (admin, dw_here),
        (admin, dw_there),
        (admin, admin.user_id),
        (admin, uuid.uuid4()),
    ):
        answer = await _call(api, caller, "PATCH", f"{_BASE}/{target}", json=rename)
        assert (answer.status_code, answer.json()["code"]) == (404, "not_found"), target
    names = await _rows(
        api,
        "SELECT name FROM platform.service_principals WHERE user_id = ANY(:ids) ORDER BY name",
        ids=[account, dw_here, dw_there],
    )
    assert "Đổi tên" not in {n for (n,) in names}


async def test_a_patch_takes_manage_reaching_the_owning_workspace(api: Api) -> None:
    """R6.14 (OP17): `.manage` anchored in another workspace is not enough."""
    async with api.migrator.begin() as conn:
        a = await plant_tenant(conn, workspaces=2)
    admin = await _caller(api, a, _BOTH)
    other = await _caller(
        api, a, {SERVICE_PRINCIPALS_MANAGE_SCOPE: "workspace"}, anchor=a.workspaces[1]
    )
    account = uuid.UUID((await _create(api, admin, admin.user_id, name="Không đổi")).json()["id"])
    answer = await _call(api, other, "PATCH", f"{_BASE}/{account}", json={"name": "Đã đổi"})
    assert answer.status_code == 403
    assert await _rows(
        api, "SELECT name FROM platform.service_principals WHERE user_id = :u", u=account
    ) == [("Không đổi",)]

    changed = await _call(
        api, admin, "PATCH", f"{_BASE}/{account}", json={"name": "Đã đổi", "description": None}
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["name"], changed.json()["description"]) == ("Đã đổi", None)


async def test_the_accountable_owner_through_the_routes(api: Api) -> None:
    """R6.16, R6.17 (OP18): an owner who is not `active` is refused 422
    `owner_not_member`, an owner of `null` 422 `validation_failed`; a new
    owner is audited with both ids; the owner suspended shows `owner_missing`."""
    async with api.migrator.begin() as conn:
        a = await plant_tenant(conn)
        suspended = await plant_person(conn, a.tenant_id, status="suspended")
    admin = await _caller(api, a, _BOTH)
    successor = await _caller(api, a)
    account = uuid.UUID((await _create(api, admin, admin.user_id)).json()["id"])
    path = f"{_BASE}/{account}"

    refused = await _call(api, admin, "PATCH", path, json={"owner_user_id": str(suspended)})
    assert (refused.status_code, refused.json()["details"]["reason_code"]) == (
        422,
        "owner_not_member",
    )
    emptied = await _call(api, admin, "PATCH", path, json={"owner_user_id": None})
    assert (emptied.status_code, emptied.json()["code"]) == (422, "validation_failed")

    moved = await _call(api, admin, "PATCH", path, json={"owner_user_id": str(successor.user_id)})
    assert moved.status_code == 200, moved.text
    [audit] = await _rows(
        api,
        "SELECT details FROM platform.audit_events"
        " WHERE resource_id = :r AND action = 'platform.service_principal.updated'",
        r=str(account),
    )
    assert audit.details["owner_user_id"] == {
        "from": str(admin.user_id),
        "to": str(successor.user_id),
    }

    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenant_members SET status = 'suspended' WHERE user_id = :u"),
            {"u": successor.user_id},
        )
    listed = await _listed(api, admin)
    assert listed[account]["owner_missing"] is True
    assert listed[account]["bindable_by_me"] is False


async def test_the_role_route_refuses_a_critical_role_for_a_service_account(api: Api) -> None:
    """R6.4 (OP9): the members route's write meets the guard and answers 422
    `role_not_allowed_for_service`; nothing is assigned."""
    key = f"test.spapi{uuid.uuid4().hex[:8]}.crit"
    template = f"crit_{uuid.uuid4().hex[:8]}"
    async with api.migrator.begin() as conn:
        await register_key(conn, key, risk="critical")
        await conn.execute(
            sa.text("INSERT INTO platform.roles (key, name, scopes) VALUES (:k, :k, :s)"),
            {"k": template, "s": f'["{key}"]'},
        )
        a = await plant_tenant(conn, workspaces=2)
    try:
        admin = await _caller(api, a, {**_BOTH, "platform.members.write": "tenant"})
        account = uuid.UUID((await _create(api, admin, admin.user_id)).json()["id"])
        answer = await _call(
            api,
            admin,
            "PUT",
            f"/api/v1/admin/members/{account}/memberships",
            json={"memberships": [{"workspace_id": str(a.workspaces[1]), "role_keys": [template]}]},
        )
        assert answer.status_code == 422, answer.text
        assert answer.json()["details"]["reason_code"] == "role_not_allowed_for_service"
        assert await _rows(
            api,
            "SELECT count(*) FROM platform.role_assignments a"
            " JOIN platform.memberships m ON m.id = a.membership_id WHERE m.user_id = :u",
            u=account,
        ) == [(0,)]
    finally:
        async with api.migrator.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM platform.tenant_roles WHERE key = :k"), {"k": template}
            )
            await conn.execute(
                sa.text("DELETE FROM platform.roles WHERE key = :k"), {"k": template}
            )
            await unregister_key(conn, key)
