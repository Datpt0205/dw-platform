# ruff: noqa: F811  (the fixture of test_tenant_roles_api is imported by name)
"""Object privileges and field permissions in roles, through the real app on a
migrated Postgres (tenant-rbac ticket 04).

The API's half of the criteria: the generated catalogue (R9.1), a field key
proposed by one owner and confirmed by another who holds it (R9.5), what `/me`
then says (R9.6, R9.12), ids of another tenant answered as unknown ids before
any proposal (R9.13), arrays left out kept and arrays given replacing (R9.14),
a proposal gone stale and a stale `If-Match` (R9.11), `bind` over a role that
reads a sensitive field (R6.8) and a clone carrying both kinds. The raw-SQL
half is `dw_platform`'s `test_record_privileges_db.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from test_role_admin_api import (
    BIND,
    MEMBERS_READ,
    MEMBERS_WRITE,
    READ,
    WRITE,
    Who,
    _call,
    _confirm,
    _etag,
    _one,
    _proposals,
    _reason,
    _rows,
    _set_memberships,
    _tenant,
    _who,
)
from test_tenant_roles_api import Api, api  # noqa: F401  (fixture, used by name)

from dw_platform.testing.rbac import PlantedTenant, assign, plant_role, role_id
from dw_platform.testing.record_objects import Lead, add_field, plant_object

pytestmark = pytest.mark.integration

_ADMIN = "/api/v1/admin"
_ROLES = f"{_ADMIN}/roles"
_OBJ = "platform.tenant_role_object_privileges"
_FLD = "studio.field_permissions"


async def _owner(api: Api, t: PlantedTenant) -> Who:
    who = await _who(api, t)
    async with api.migrator.begin() as conn:
        owner = await role_id(conn, t.tenant_id, "tenant_owner")
        await assign(conn, t.tenant_id, t.main, who.membership, owner)
    return who


async def _lead(api: Api, t: PlantedTenant) -> Lead:
    async with api.migrator.begin() as conn:
        return await plant_object(conn, t)


async def _role(api: Api, t: PlantedTenant, key: str, holder: Who | None = None) -> uuid.UUID:
    async with api.migrator.begin() as conn:
        role = await plant_role(conn, t.tenant_id, key, {})
        if holder is not None:
            await assign(conn, t.tenant_id, t.main, holder.membership, role)
    return role


async def _put(
    api: Api, who: Who, role: uuid.UUID, body: dict[str, Any], **kw: Any
) -> httpx.Response:
    etag = kw.pop("etag", None) or await _etag(api, who, role)
    return await _call(
        api, who, "PUT", f"{_ROLES}/{role}/permissions", json=body, headers={"If-Match": etag}
    )


async def _me(api: Api, who: Who) -> dict[str, Any]:
    found = await _call(api, who, "GET", "/api/v1/me")
    assert found.status_code == 200, found.text
    body: dict[str, Any] = found.json()
    return body


def _grants(me: dict[str, Any]) -> set[tuple[str, str]]:
    return {(g["key"], g["depth"]) for g in me["grants"]}


async def _fields_of(api: Api, role: uuid.UUID) -> set[tuple[uuid.UUID, str]]:
    rows = await _rows(api, f"SELECT field_id, access FROM {_FLD} WHERE role_id = :r", r=role)
    return {(r.field_id, r.access) for r in rows}


async def _objects_of(api: Api, role: uuid.UUID) -> set[tuple[uuid.UUID, str, str]]:
    rows = await _rows(
        api, f"SELECT object_id, action, depth FROM {_OBJ} WHERE role_id = :r", r=role
    )
    return {(r.object_id, r.action, r.depth) for r in rows}


# ---- R9.1 ------------------------------------------------------------------------


async def test_r9_1_the_catalogue_lists_five_generated_keys_per_live_object(api: Api) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner = await _owner(api, t)
    listed = await _call(api, owner, "GET", f"{_ADMIN}/permissions")
    assert listed.status_code == 200, listed.text
    generated = {row["key"]: row for row in listed.json() if row["key"].startswith("obj.lead.")}
    assert set(generated) == {
        f"obj.lead.{a}" for a in ("read", "create", "update", "delete", "assign")
    }
    for key, row in generated.items():
        action = key.rsplit(".", 1)[1]
        assert row["scope_kind"] == "record" and row["area"] == "records"
        assert (row["object_id"], row["action"]) == (str(lead.object_id), action)
        assert row["risk"] == ("standard" if action == "read" else "elevated")
        assert row["allowed_depths"] == ["own", "workspace", "tenant"]
        assert row["max_grantable_depth"] == "tenant"
        assert row["label_vi"].startswith("Khách hàng tiềm năng — ")
    assert not [row for row in listed.json() if row["key"].startswith("fld.")]
    # A catalogue row carries no object.
    assert all(
        row["object_id"] is None for row in listed.json() if not row["key"].startswith("obj.")
    )


# ---- R9.5 (RB30), R9.6, R9.15 ------------------------------------------------------


async def test_r9_5_a_field_key_is_proposed_by_one_owner_and_confirmed_by_another(
    api: Api,
) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner_a, owner_b = await _owner(api, t), await _owner(api, t)
    writer = await _who(api, t, {READ: "tenant", WRITE: "tenant"})
    holder = await _who(api, t)
    marketing = await _role(api, t, "marketing", holder)
    body = {"field_permissions": [{"field_id": str(lead["phone"]), "access": "read"}]}

    proposed = await _put(api, owner_a, marketing, body)
    assert proposed.status_code == 202, proposed.text
    request = proposed.json()["proposal"]["id"]
    payload = proposed.json()["proposal"]["payload"]
    assert payload["field_permissions"] == body["field_permissions"]
    assert payload["object_privileges"] == [] and payload["permissions"] == []
    assert await _fields_of(api, marketing) == set()
    assert ("fld.lead.phone.read", "tenant") not in _grants(await _me(api, holder))

    # Someone holding `platform.roles.write` but not the key confirms nothing.
    refused = await _confirm(api, writer, request)
    assert _reason(refused) == (403, "rbac_escalation"), refused.text
    assert "fld.lead.phone.read:tenant" in refused.json()["details"]["keys"]
    assert await _fields_of(api, marketing) == set()

    confirmed = await _confirm(api, owner_b, request)
    assert confirmed.status_code == 200, confirmed.text
    assert await _fields_of(api, marketing) == {(lead["phone"], "read")}
    me = await _me(api, holder)
    assert ("fld.lead.phone.read", "tenant") in _grants(me)
    assert "fld.lead.phone.read" in me["scopes"]
    detail = await _call(api, owner_a, "GET", f"{_ROLES}/{marketing}")
    assert detail.json()["field_permissions"] == [
        {"field_id": str(lead["phone"]), "access": "read"}
    ]


async def test_r9_6_r9_15_field_keys_add_up_and_edit_gives_read(api: Api) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    holder = await _who(api, t)
    role_a, role_b = await _role(api, t, "role_a", holder), await _role(api, t, "role_b", holder)
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :a, :p, 'read'), (:t, :b, :n, 'edit')"
            ),
            {"t": t.tenant_id, "a": role_a, "b": role_b, "p": lead["phone"], "n": lead["note"]},
        )
    held = _grants(await _me(api, holder))
    assert {
        ("fld.lead.phone.read", "tenant"),
        ("fld.lead.note.read", "tenant"),
        ("fld.lead.note.edit", "tenant"),
    } <= held


# ---- R9.13 (RB47) --------------------------------------------------------------------


async def test_r9_13_another_tenants_ids_answer_as_unknown_ones_before_any_proposal(
    api: Api,
) -> None:
    t, other = await _tenant(api), await _tenant(api)
    await _lead(api, t)
    theirs = await _lead(api, other)
    owner = await _owner(api, t)
    await _owner(api, t)
    marketing = await _role(api, t, "marketing")

    def problems(response: httpx.Response) -> tuple[int, str, list[dict[str, str]]]:
        body = response.json()
        return response.status_code, body["code"], body["details"]["errors"]

    pairs = (
        (
            {"field_permissions": [{"field_id": str(theirs["phone"]), "access": "read"}]},
            {"field_permissions": [{"field_id": str(uuid.uuid4()), "access": "read"}]},
            "/field_permissions/0/field_id",
        ),
        (
            {
                "object_privileges": [
                    {"object_id": str(theirs.object_id), "action": "read", "depth": "tenant"}
                ]
            },
            {
                "object_privileges": [
                    {"object_id": str(uuid.uuid4()), "action": "read", "depth": "tenant"}
                ]
            },
            "/object_privileges/0/object_id",
        ),
    )
    for foreign, random, pointer in pairs:
        a = await _put(api, owner, marketing, foreign)
        b = await _put(api, owner, marketing, random)
        assert (
            problems(a)
            == problems(b)
            == (
                422,
                "validation_failed",
                [{"pointer": pointer, "detail": problems(a)[2][0]["detail"]}],
            )
        ), (a.text, b.text)
        assert a.json()["message"] == b.json()["message"]
    assert await _proposals(api, t.tenant_id) == 0


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        (
            lambda o, f: {
                "object_privileges": [{"object_id": o, "action": "share", "depth": "tenant"}]
            },
            "/object_privileges/0/action",
        ),
        (
            lambda o, f: {
                "object_privileges": [{"object_id": o, "action": "fly", "depth": "tenant"}]
            },
            "/object_privileges/0/action",
        ),
        (
            lambda o, f: {
                "object_privileges": [{"object_id": o, "action": "read", "depth": "team"}]
            },
            "/object_privileges/0/depth",
        ),
        (
            lambda o, f: {"field_permissions": [{"field_id": f, "access": "write"}]},
            "/field_permissions/0/access",
        ),
        (
            lambda o, f: {"permissions": [{"key": "obj.lead.read", "depth": "tenant"}]},
            "/permissions/0/key",
        ),
    ],
)
async def test_r9_13_a_bad_action_depth_access_or_record_key_is_422_with_its_pointer(
    api: Api, body: Any, pointer: str
) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner = await _owner(api, t)
    await _owner(api, t)
    marketing = await _role(api, t, "marketing")
    answer = await _put(api, owner, marketing, body(str(lead.object_id), str(lead["phone"])))
    assert answer.status_code == 422, answer.text
    assert [e["pointer"] for e in answer.json()["details"]["errors"]] == [pointer]
    assert await _proposals(api, t.tenant_id) == 0


# ---- R9.14 ----------------------------------------------------------------------------


async def test_r9_14_an_array_left_out_keeps_its_kind_and_an_empty_one_clears_it(
    api: Api,
) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner = await _owner(api, t)
    await _owner(api, t)
    marketing = await _role(api, t, "marketing")
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id,"
                " permission_key, depth) VALUES (:t, :r, :k, 'tenant')"
            ),
            {"t": t.tenant_id, "r": marketing, "k": MEMBERS_READ},
        )
        await conn.execute(
            sa.text(
                f"INSERT INTO {_OBJ} (tenant_id, role_id, object_id, action, depth)"
                " VALUES (:t, :r, :o, 'read', 'workspace')"
            ),
            {"t": t.tenant_id, "r": marketing, "o": lead.object_id},
        )
        await conn.execute(
            sa.text(
                f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :r, :f, 'edit')"
            ),
            {"t": t.tenant_id, "r": marketing, "f": lead["phone"]},
        )
    only_catalogue = await _put(api, owner, marketing, {"permissions": []})
    assert only_catalogue.status_code == 200, only_catalogue.text
    assert await _objects_of(api, marketing) == {(lead.object_id, "read", "workspace")}
    assert await _fields_of(api, marketing) == {(lead["phone"], "edit")}
    cleared = await _put(api, owner, marketing, {"field_permissions": []})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["proposal"] is None
    assert await _fields_of(api, marketing) == set()
    assert await _objects_of(api, marketing) == {(lead.object_id, "read", "workspace")}
    # edit to read and a shallower depth only narrow: one person, 200.
    narrowed = await _put(
        api,
        owner,
        marketing,
        {
            "object_privileges": [
                {"object_id": str(lead.object_id), "action": "read", "depth": "own"}
            ]
        },
    )
    assert narrowed.status_code == 200, narrowed.text
    assert await _objects_of(api, marketing) == {(lead.object_id, "read", "own")}
    assert await _proposals(api, t.tenant_id) == 0


# ---- R9.11 (RB45) -----------------------------------------------------------------------


async def test_r9_11_a_field_key_removed_between_proposal_and_confirmation_stays_removed(
    api: Api,
) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner_a, owner_b = await _owner(api, t), await _owner(api, t)
    marketing = await _role(api, t, "marketing")
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :r, :f, 'read')"
            ),
            {"t": t.tenant_id, "r": marketing, "f": lead["phone"]},
        )
    proposed = await _put(
        api,
        owner_a,
        marketing,
        {
            "object_privileges": [
                {"object_id": str(lead.object_id), "action": "read", "depth": "tenant"}
            ],
            "field_permissions": [{"field_id": str(lead["phone"]), "access": "read"}],
        },
    )
    assert proposed.status_code == 202, proposed.text
    removed = await _put(api, owner_b, marketing, {"field_permissions": []})
    assert removed.status_code == 200, removed.text
    stale = await _confirm(api, owner_b, proposed.json()["proposal"]["id"])
    assert _reason(stale) == (409, "proposal_stale"), stale.text
    assert await _fields_of(api, marketing) == set()
    assert await _objects_of(api, marketing) == set()

    etag = await _etag(api, owner_a, marketing)
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"INSERT INTO {_OBJ} (tenant_id, role_id, object_id, action, depth)"
                " VALUES (:t, :r, :o, 'update', 'own')"
            ),
            {"t": t.tenant_id, "r": marketing, "o": lead.object_id},
        )
    late = await _put(api, owner_a, marketing, {"field_permissions": []}, etag=etag)
    assert late.status_code == 412, late.text


# ---- R6.8 (RB33) ---------------------------------------------------------------------------


async def test_r6_8_bind_alone_does_not_assign_a_role_reading_a_sensitive_field(
    api: Api,
) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    await _owner(api, t)
    await _owner(api, t)
    binder = await _who(
        api, t, {READ: "tenant", BIND: "tenant", MEMBERS_READ: "tenant", MEMBERS_WRITE: "tenant"}
    )
    reads_cccd, reads_phone = _key("cccd"), _key("phone")
    for key, field in ((reads_cccd, "cccd"), (reads_phone, "phone")):
        role = await _role(api, t, key)
        async with api.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access)"
                    " VALUES (:t, :r, :f, 'read')"
                ),
                {"t": t.tenant_id, "r": role, "f": lead[field]},
            )
    grantee = await _who(api, t)
    refused = await _set_memberships(api, binder, grantee.user_id, {t.main: [reads_cccd]})
    assert _reason(refused) == (403, "rbac_escalation"), refused.text
    assert await _proposals(api, t.tenant_id) == 0
    accepted = await _set_memberships(api, binder, grantee.user_id, {t.main: [reads_phone]})
    assert accepted.status_code == 202, accepted.text


def _key(field: str) -> str:
    return f"reads_{field}_{uuid.uuid4().hex[:8]}"


# ---- R9.12 (RB46) --------------------------------------------------------------------------


async def test_r9_12_a_new_field_reaches_the_owners_cached_context(api: Api) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner = await _owner(api, t)
    before = await _me(api, owner)
    assert ("fld.lead.email.read", "tenant") not in _grants(before)
    async with api.migrator.begin() as conn:
        await add_field(conn, t.tenant_id, lead.object_id, "email", "basic", 9)
    after = await _me(api, owner)
    assert after["access_version"] > before["access_version"]
    assert {("fld.lead.email.read", "tenant"), ("fld.lead.email.edit", "tenant")} <= _grants(after)


# ---- clone_of ------------------------------------------------------------------------------


async def test_a_clone_carries_the_sources_object_privileges_and_field_permissions(
    api: Api,
) -> None:
    t = await _tenant(api)
    lead = await _lead(api, t)
    owner_a, owner_b = await _owner(api, t), await _owner(api, t)
    source = await _role(api, t, "source")
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"INSERT INTO {_OBJ} (tenant_id, role_id, object_id, action, depth)"
                " VALUES (:t, :r, :o, 'update', 'workspace')"
            ),
            {"t": t.tenant_id, "r": source, "o": lead.object_id},
        )
        await conn.execute(
            sa.text(
                f"INSERT INTO {_FLD} (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :r, :f, 'edit')"
            ),
            {"t": t.tenant_id, "r": source, "f": lead["cccd"]},
        )
    made = await _call(
        api,
        owner_a,
        "POST",
        _ROLES,
        json={"key": "clone", "name": "Bản sao", "clone_of": str(source)},
    )
    assert made.status_code == 202, made.text
    payload = made.json()["payload"]
    assert payload["object_privileges"] == [
        {"object_id": str(lead.object_id), "action": "update", "depth": "workspace"}
    ]
    assert payload["field_permissions"] == [{"field_id": str(lead["cccd"]), "access": "edit"}]
    assert (await _confirm(api, owner_b, made.json()["id"])).status_code == 200
    clone = uuid.UUID(payload["role_id"])
    assert await _objects_of(api, clone) == {(lead.object_id, "update", "workspace")}
    assert await _fields_of(api, clone) == {(lead["cccd"], "edit")}
    assert (
        await _one(api, "SELECT platform.role_is_critical(:t, :r)", t=t.tenant_id, r=clone) is True
    )
