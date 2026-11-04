"""Unit: a role's grants as `PUT /admin/roles/{id}/permissions` sets them
(tenant-rbac ticket 04, R9.13-R9.15). The keys come from the database's one
owner (`platform.record_privilege_keys`); here they are given."""

from __future__ import annotations

import uuid

import pytest

from dw_kernel.errors import DomainError
from dw_platform.application.role_admin import (
    FieldPermission,
    ObjectPrivilege,
    Privilege,
    RecordKeys,
    RoleGrants,
    _checked_fields,
    _checked_objects,
    diff_privileges,
)

LEAD = uuid.uuid4()
PHONE = uuid.uuid4()
ACTIONS = {"read": True, "update": True, "share": False}


def _keys() -> RecordKeys:
    return RecordKeys(
        keys={
            ObjectPrivilege(LEAD, "read", "workspace"): (Privilege("obj.lead.read", "workspace"),),
            ObjectPrivilege(LEAD, "read", "tenant"): (Privilege("obj.lead.read", "tenant"),),
            FieldPermission(PHONE, "read"): (Privilege("fld.lead.phone.read", "tenant"),),
            FieldPermission(PHONE, "edit"): (
                Privilege("fld.lead.phone.edit", "tenant"),
                Privilege("fld.lead.phone.read", "tenant"),
            ),
        },
        actions=ACTIONS,
    )


def test_a_payload_without_a_kind_keeps_the_current_one() -> None:
    """R9.14: a proposal written before tenant-rbac/04 carries `permissions`
    only, and its confirmation leaves the record grants as they are."""
    current = RoleGrants(
        (Privilege("a.b.c", "tenant"),),
        (ObjectPrivilege(LEAD, "read", "own"),),
        (FieldPermission(PHONE, "read"),),
    )
    old = RoleGrants.from_payload({"permissions": []}, current=current)
    assert old == RoleGrants((), current.object_privileges, current.field_permissions)
    full = RoleGrants.from_payload(current.as_payload(), current=RoleGrants())
    assert full == current


def test_edit_to_read_narrows_and_read_to_edit_widens() -> None:
    keys = _keys()
    read = RoleGrants(field_permissions=(FieldPermission(PHONE, "read"),))
    edit = RoleGrants(field_permissions=(FieldPermission(PHONE, "edit"),))
    up = diff_privileges(keys.keyed(read), keys.keyed(edit))
    assert up.widens and up.added == (Privilege("fld.lead.phone.edit", "tenant"),)
    down = diff_privileges(keys.keyed(edit), keys.keyed(read))
    assert not down.widens and down.removed == (Privilege("fld.lead.phone.edit", "tenant"),)
    deeper = diff_privileges(
        keys.keyed(RoleGrants(object_privileges=(ObjectPrivilege(LEAD, "read", "workspace"),))),
        keys.keyed(RoleGrants(object_privileges=(ObjectPrivilege(LEAD, "read", "tenant"),))),
    )
    assert deeper.raised == (Privilege("obj.lead.read", "tenant"),)


@pytest.mark.parametrize(
    ("row", "pointer"),
    [
        (ObjectPrivilege(LEAD, "share", "tenant"), "/object_privileges/0/action"),
        (ObjectPrivilege(LEAD, "fly", "tenant"), "/object_privileges/0/action"),
        (ObjectPrivilege(LEAD, "read", "team"), "/object_privileges/0/depth"),
        (ObjectPrivilege(uuid.uuid4(), "read", "tenant"), "/object_privileges/0/object_id"),
    ],
)
def test_an_object_privilege_that_cannot_be_set_is_refused_with_its_pointer(
    row: ObjectPrivilege, pointer: str
) -> None:
    with pytest.raises(DomainError) as caught:
        _checked_objects([row], _keys())
    errors: list[dict[str, str]] = caught.value.details["errors"]  # type: ignore[assignment]
    assert [e["pointer"] for e in errors] == [pointer]


@pytest.mark.parametrize(
    ("rows", "pointer"),
    [
        ([FieldPermission(PHONE, "write")], "/field_permissions/0/access"),
        ([FieldPermission(uuid.uuid4(), "read")], "/field_permissions/0/field_id"),
        ([FieldPermission(PHONE, "read"), FieldPermission(PHONE, "edit")], "/field_permissions/1"),
    ],
)
def test_a_field_permission_that_cannot_be_set_is_refused_with_its_pointer(
    rows: list[FieldPermission], pointer: str
) -> None:
    with pytest.raises(DomainError) as caught:
        _checked_fields(rows, _keys())
    errors: list[dict[str, str]] = caught.value.details["errors"]  # type: ignore[assignment]
    assert [e["pointer"] for e in errors] == [pointer]


def test_rows_that_can_be_set_come_back_sorted() -> None:
    rows = [ObjectPrivilege(LEAD, "read", "tenant")]
    assert _checked_objects(rows, _keys()) == tuple(rows)
    assert _checked_fields([FieldPermission(PHONE, "edit")], _keys()) == (
        FieldPermission(PHONE, "edit"),
    )
