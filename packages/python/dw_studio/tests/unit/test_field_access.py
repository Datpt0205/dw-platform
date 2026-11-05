"""`resolve_field_access`, `visible_fields`, `reads_all` and the service that
feeds them (field-security ticket 01, R2.1-R2.8; FS1, FS7, FS8).

Examples first, one per criterion of the ticket, on a `lead` with the pilot's
fields; then a property run of 1 500 generated cases over R2.1-R2.7; then
`FieldAccessService` over a fake port that records what it was asked. The
database half (the inputs read live under the bound company) is
`tests/integration/test_field_access_db.py`.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from dw_kernel.personal_data import PdCategory
from dw_studio.core.application.field_access import (
    BoundActor,
    FieldAccessService,
    PrincipalGrants,
)
from dw_studio.core.domain.field_access import (
    BoundaryLink,
    FieldAccess,
    FieldAction,
    FieldLevel,
    FieldSecurity,
    ObjectSecurity,
    reads_all,
    resolve_field_access,
    visible_fields,
)

pytestmark = pytest.mark.unit

_RANK = {"hidden": 0, "read": 1, "edit": 2}


def _field(
    api_name: str, pd: str = "none", mode: str | None = None, *, unique: bool = False
) -> FieldSecurity:
    category = PdCategory(pd)
    return FieldSecurity(
        field_id=uuid.uuid5(uuid.NAMESPACE_OID, api_name),
        api_name=api_name,
        access_mode=mode or ("open" if category is PdCategory.NONE else "secured"),  # type: ignore[arg-type]
        pd_category=category,
        is_unique=unique,
    )


NAME = _field("name", "basic")
PHONE = _field("phone", "basic", unique=True)
EMAIL = _field("email", "basic")
STATUS = _field("status")
CCCD = _field("cccd", "sensitive")
LEAD = ObjectSecurity("lead", 7, (NAME, PHONE, EMAIL, STATUS, CCCD))


def keys(*names: str) -> frozenset[str]:
    return frozenset(names)


def levels(
    grants: frozenset[str],
    boundary: Sequence[BoundaryLink] | None = None,
    action: FieldAction = "update",
    *,
    security: ObjectSecurity = LEAD,
    service: bool = False,
) -> dict[str, FieldLevel]:
    access = resolve_field_access(grants, security, boundary, action, service_account=service)
    return {name: access.levels[f] for f, name in access.api_names.items()}


# ---- examples, one per criterion ------------------------------------------------


def test_r2_1_one_level_per_field_and_the_schema_version_it_used() -> None:
    access = resolve_field_access(keys("obj.lead.read"), LEAD, None, service_account=False)
    assert set(access.levels) == {f.field_id for f in LEAD.fields}
    assert set(access.levels.values()) <= {"hidden", "read", "edit"}
    assert access.fls_version == 7
    assert access.object_api_name == "lead"


def test_r2_2_an_open_field_is_read_for_a_reader_and_edit_for_an_updater() -> None:
    assert levels(keys("obj.lead.read"))["status"] == "read"
    assert levels(keys("obj.lead.read", "obj.lead.update"))["status"] == "edit"


def test_r2_2_without_object_read_every_field_is_hidden() -> None:
    found = levels(keys("obj.lead.update", "obj.lead.create", "fld.lead.phone.read"))
    assert set(found.values()) == {"hidden"}


def test_r2_2_a_field_edit_without_object_update_is_read() -> None:
    grants = keys("obj.lead.read", "fld.lead.phone.read", "fld.lead.phone.edit")
    assert levels(grants)["phone"] == "read"
    assert levels(grants | {"obj.lead.update"})["phone"] == "edit"


def test_r2_3_fs1_a_secured_field_not_granted_is_hidden_and_not_visible() -> None:
    grants = keys("obj.lead.read")
    access = resolve_field_access(grants, LEAD, None, service_account=False)
    found = levels(grants)
    assert found["email"] == "hidden"
    assert found["name"] == "hidden"
    assert EMAIL.field_id not in visible_fields(access)
    assert STATUS.field_id in visible_fields(access)


def test_r2_4_read_from_one_role_and_edit_from_another_add_up_to_edit() -> None:
    # `platform.field_permission_keys` gives an `edit` row both keys; two roles
    # held by one person arrive as one set of keys.
    role_a = keys("fld.lead.phone.read")
    role_b = keys("fld.lead.phone.read", "fld.lead.phone.edit")
    held = role_a | role_b | {"obj.lead.read", "obj.lead.update"}
    assert levels(held)["phone"] == "edit"


def test_r2_4_an_edit_key_alone_reads_nothing() -> None:
    """The function never derives read from edit; the database's keys do."""
    assert levels(keys("obj.lead.read", "obj.lead.update", "fld.lead.email.edit"))["email"] == (
        "hidden"
    )


def test_r2_5_the_boundary_caps_what_the_principal_holds() -> None:
    grants = keys("obj.lead.read", "fld.lead.name.read", "fld.lead.email.read")
    only_name: BoundaryLink = {NAME.field_id: "read"}
    found = levels(grants, [only_name])
    assert (found["name"], found["email"], found["status"]) == ("read", "hidden", "hidden")
    widened: BoundaryLink = {NAME.field_id: "read", EMAIL.field_id: "read"}
    assert levels(grants, [widened])["email"] == "read"


def test_r2_5_every_link_caps_and_read_caps_edit() -> None:
    grants = keys("obj.lead.read", "obj.lead.update")
    root: BoundaryLink = {STATUS.field_id: "edit"}
    child: BoundaryLink = {STATUS.field_id: "read"}
    assert levels(grants, [root])["status"] == "edit"
    assert levels(grants, [root, child])["status"] == "read"
    assert levels(grants, [root, {}])["status"] == "hidden"


def test_r2_6_fs7_a_unique_field_is_read_for_a_creator_but_not_past_the_boundary() -> None:
    grants = keys("obj.lead.read", "obj.lead.create")
    assert levels(grants)["phone"] == "read"
    assert levels(keys("obj.lead.read", "obj.lead.update"))["phone"] == "read"
    assert levels(keys("obj.lead.read"))["phone"] == "hidden"
    assert levels(grants, [{NAME.field_id: "read"}])["phone"] == "hidden"


def test_r2_6_a_unique_sensitive_field_stays_hidden_from_a_service_account() -> None:
    """tenant-rbac R9.9: no service account reads a sensitive field, the unique
    exception included; a person in the same role reads it (ADR-0106)."""
    national = _field("cccd_so", "sensitive", unique=True)
    security = ObjectSecurity("lead", 1, (national, PHONE))
    grants = keys("obj.lead.read", "obj.lead.create")
    assert levels(grants, security=security)["cccd_so"] == "read"
    as_service = levels(grants, security=security, service=True)
    assert as_service["cccd_so"] == "hidden"
    assert as_service["phone"] == "read"
    assert levels(grants, action="create", security=security, service=True)["cccd_so"] == "hidden"


def test_r2_7_create_uses_the_create_key_and_needs_no_object_read() -> None:
    edit = keys("obj.lead.read", "obj.lead.create", "fld.lead.phone.read", "fld.lead.phone.edit")
    assert levels(edit, action="create")["phone"] == "edit"
    assert levels(edit, action="update")["phone"] == "read"
    assert levels(edit, action="create")["status"] == "edit"
    create_only = levels(keys("obj.lead.create"), action="create")
    assert create_only["status"] == "edit"
    assert create_only["email"] == "hidden"
    assert create_only["phone"] == "read"
    assert create_only["cccd"] == "hidden"


def test_r2_7_read_never_answers_edit() -> None:
    every = keys("obj.lead.read", "obj.lead.create", "obj.lead.update", "fld.lead.phone.read")
    assert "edit" not in levels(every | {"fld.lead.phone.edit"}, action="read").values()


def test_r2_8_an_empty_chain_hides_every_field_the_open_ones_included() -> None:
    grants = keys("obj.lead.read", "obj.lead.create", "obj.lead.update")
    assert set(levels(grants, []).values()) == {"hidden"}
    assert set(levels(grants, [], action="create").values()) == {"hidden"}


def test_fs11_a_sensitive_field_is_secured_whatever_its_row_says() -> None:
    opened = ObjectSecurity("lead", 1, (_field("cccd", "sensitive", "open"),))
    assert levels(keys("obj.lead.read", "obj.lead.update"), security=opened)["cccd"] == "hidden"


def test_another_object_s_keys_give_nothing() -> None:
    grants = keys("obj.lead.read", "fld.contact.phone.read", "fld.contact.phone.edit")
    assert levels(grants)["phone"] == "hidden"


# ---- reads_all -------------------------------------------------------------------


def _access(**by_name: FieldLevel) -> FieldAccess:
    ids = {name: uuid.uuid4() for name in by_name}
    return FieldAccess(
        "lead", 1, {ids[n]: level for n, level in by_name.items()}, {v: k for k, v in ids.items()}
    )


def test_r2_1_reads_all_over_the_stamped_fields() -> None:
    assert reads_all({"lead": _access(phone="hidden")}, ["lead.phone"]) is False
    assert reads_all({"lead": _access(phone="read")}, ["lead.phone"]) is True
    assert reads_all({"lead": _access(phone="edit")}, ["lead.phone"]) is True
    assert reads_all({"lead": _access(phone="read")}, ["contact.phone"]) is False
    assert reads_all({"lead": _access(phone="read")}, ["lead.email"]) is False
    assert reads_all({"lead": _access(phone="read")}, ["lead"]) is False
    assert reads_all({}, []) is True


# ---- 1 500 generated cases -------------------------------------------------------

_ACTIONS: tuple[FieldAction, ...] = ("read", "update", "create")


def _case(rng: random.Random) -> tuple[ObjectSecurity, frozenset[str], bool]:
    fields = []
    for n in range(rng.randint(1, 6)):
        pd = rng.choice(["none", "basic", "sensitive"])
        mode = rng.choice(["open", "secured"])
        fields.append(_field(f"f{n}", pd, mode, unique=rng.random() < 0.3))
    service = rng.random() < 0.25
    grants = {f"obj.lead.{a}" for a in ("read", "create", "update") if rng.random() < 0.6}
    for f in fields:
        if service and f.pd_category is PdCategory.SENSITIVE:
            continue  # tenant-rbac R9.9: never granted to a service account
        given = rng.choice([None, "read", "edit"])
        if given:
            # `platform.field_permission_keys`: an edit row gives both keys.
            grants.add(f"fld.lead.{f.api_name}.read")
            if given == "edit":
                grants.add(f"fld.lead.{f.api_name}.edit")
    return ObjectSecurity("lead", rng.randint(1, 99), tuple(fields)), frozenset(grants), service


def _boundary(rng: random.Random, security: ObjectSecurity) -> list[BoundaryLink] | None:
    if rng.random() < 0.3:
        return None
    return [
        {f.field_id: rng.choice(["read", "edit"]) for f in security.fields if rng.random() < 0.7}
        for _ in range(rng.randint(0, 3))
    ]


def _by_id(
    grants: frozenset[str],
    security: ObjectSecurity,
    boundary: Sequence[BoundaryLink] | None,
    action: FieldAction,
    service: bool,
) -> Mapping[uuid.UUID, FieldLevel]:
    return resolve_field_access(grants, security, boundary, action, service_account=service).levels


def test_r2_1_to_r2_7_hold_over_1500_generated_cases() -> None:
    rng = random.Random(20261105)
    checked = 0
    for _ in range(1500):
        security, grants, service = _case(rng)
        boundary = _boundary(rng, security)
        action = rng.choice(_ACTIONS)
        access = resolve_field_access(grants, security, boundary, action, service_account=service)
        principal = _by_id(grants, security, None, action, service)
        holds = {a: f"obj.lead.{a}" in grants for a in ("read", "create", "update")}

        # R2.1: one level per field, and the version used.
        assert set(access.levels) == {f.field_id for f in security.fields}
        assert access.fls_version == security.schema_version
        for f in security.fields:
            level = access.levels[f.field_id]
            assert level in _RANK
            # R2.5, R2.8: never wider than the principal, nor than any link.
            assert _RANK[level] <= _RANK[principal[f.field_id]]
            if boundary is not None:
                assert boundary or level == "hidden"
                for link in boundary:
                    assert _RANK[level] <= _RANK[link.get(f.field_id, "hidden")]
            # Edit only with the write key of the action; `read` never edits.
            if level == "edit":
                assert action != "read" and holds[action]
            # R2.2: reading or updating needs object read.
            if action != "create" and not holds["read"]:
                assert level == "hidden"
            secured = f.access_mode == "secured" or f.pd_category is PdCategory.SENSITIVE
            granted = f"fld.lead.{f.api_name}.read" in grants
            creates = (
                holds["create"]
                if action == "create"
                else (holds["read"] and (holds["create"] or holds["update"]))
            )
            excepted = (
                f.is_unique and creates and not (service and f.pd_category is PdCategory.SENSITIVE)
            )
            # R1.2, R2.3: a secured field not granted is hidden, unless unique.
            if secured and not granted and not excepted:
                assert principal[f.field_id] == "hidden"
            # R2.6: a unique field reads for whoever creates or updates.
            if excepted:
                assert principal[f.field_id] != "hidden"
            # tenant-rbac R9.9: a service account reads no sensitive field.
            if service and f.pd_category is PdCategory.SENSITIVE:
                assert principal[f.field_id] == "hidden"
            checked += 1

        # FS11: a sensitive field's row saying `open` changes nothing.
        reopened = ObjectSecurity(
            security.api_name,
            security.schema_version,
            tuple(
                FieldSecurity(f.field_id, f.api_name, "open", f.pd_category, f.is_unique)
                if f.pd_category is PdCategory.SENSITIVE
                else f
                for f in security.fields
            ),
        )
        assert _by_id(grants, reopened, boundary, action, service) == access.levels

        # R2.4: grants add up; more keys never lower a level.
        extra = set(grants)
        for f in security.fields:
            if rng.random() < 0.5 and not (service and f.pd_category is PdCategory.SENSITIVE):
                extra |= {f"fld.lead.{f.api_name}.read", f"fld.lead.{f.api_name}.edit"}
        for a in ("read", "create", "update"):
            if rng.random() < 0.3:
                extra.add(f"obj.lead.{a}")
        more = _by_id(frozenset(extra), security, boundary, action, service)
        assert all(_RANK[more[f]] >= _RANK[access.levels[f]] for f in access.levels)

        # Another object's keys change nothing.
        other = {k.replace("lead", "contact", 1) for k in extra}
        assert _by_id(grants | other, security, boundary, action, service) == access.levels
    assert checked >= 1500


# ---- the service, over a fake port ----------------------------------------------


@dataclass
class FakeInputs:
    """`FieldSecurityInputsPort` as a table of answers, recording each read."""

    bound: BoundActor
    security: ObjectSecurity
    held: dict[uuid.UUID, PrincipalGrants]
    links: dict[uuid.UUID, BoundaryLink]
    asked: list[tuple[str, Any]] = field(default_factory=list)

    async def actor(self, tx: Any) -> BoundActor:
        self.asked.append(("actor", tx))
        return self.bound

    async def object_security(self, tx: Any, object_id: uuid.UUID) -> ObjectSecurity:
        self.asked.append(("object", object_id))
        return self.security

    async def principal(self, tx: Any, principal_id: uuid.UUID) -> PrincipalGrants:
        self.asked.append(("principal", principal_id))
        return self.held.get(principal_id, PrincipalGrants(frozenset(), True))

    async def boundary(
        self, tx: Any, boundary_ids: Sequence[uuid.UUID], object_id: uuid.UUID
    ) -> tuple[BoundaryLink, ...]:
        self.asked.append(("boundary", tuple(boundary_ids)))
        return tuple(self.links.get(b, {}) for b in boundary_ids)


PERSON, OTHER, LINK = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
READER = PrincipalGrants(keys("obj.lead.read", "fld.lead.email.read"), False)


def _inputs(kind: str, chain: tuple[uuid.UUID, ...] = ()) -> FakeInputs:
    return FakeInputs(
        bound=BoundActor(kind, PERSON, chain),  # type: ignore[arg-type]
        security=LEAD,
        held={PERSON: READER, OTHER: PrincipalGrants(keys("obj.lead.read"), False)},
        links={LINK: {STATUS.field_id: "read"}},
    )


async def test_a_user_request_reads_its_own_grants_and_no_boundary() -> None:
    inputs = _inputs("user")
    access = await FieldAccessService(inputs).for_object("tx", uuid.uuid4())
    assert access.level_of("email") == "read"
    assert [kind for kind, _ in inputs.asked] == ["actor", "principal", "object"]


async def test_a_caller_read_once_decides_every_action_of_its_transaction() -> None:
    """custom-objects/03: RecordService reads the caller once, asks the
    object key from its grants, then the field decision of each action from
    the same grants: the actor and the keys are not read again."""
    inputs = _inputs("user")
    service = FieldAccessService(inputs)
    caller = await service.caller("tx")
    assert caller.holds("obj.lead.read") and not caller.holds("obj.lead.update")
    decided = await service.for_actions("tx", uuid.uuid4(), ("read", "create"), caller=caller)
    assert decided["read"].level_of("email") == "read"
    assert decided["create"].level_of("email") == "read"
    assert set(decided) == {"read", "create"}
    assert [kind for kind, _ in inputs.asked] == ["actor", "principal", "object"]


async def test_r2_5_a_run_reads_its_chain_and_r2_8_an_empty_one_hides_all() -> None:
    inputs = _inputs("agent", (LINK,))
    access = await FieldAccessService(inputs).for_object("tx", uuid.uuid4())
    assert (access.level_of("email"), access.level_of("status")) == ("hidden", "read")
    assert ("boundary", (LINK,)) in inputs.asked
    empty = await FieldAccessService(_inputs("workflow")).for_object("tx", uuid.uuid4())
    assert set(empty.levels.values()) == {"hidden"}


async def test_r2_9_nothing_is_kept_between_two_calls() -> None:
    inputs = _inputs("user")
    service = FieldAccessService(inputs)
    await service.for_object("tx1", uuid.uuid4())
    inputs.held[PERSON] = PrincipalGrants(keys("obj.lead.read"), False)
    again = await service.for_object("tx2", uuid.uuid4())
    assert again.level_of("email") == "hidden"
    assert [kind for kind, _ in inputs.asked].count("principal") == 2


async def test_for_person_reads_that_person_without_a_boundary() -> None:
    inputs = _inputs("agent", (LINK,))
    access = await FieldAccessService(inputs).for_person("tx", OTHER, uuid.uuid4())
    assert access.level_of("status") == "read"
    assert access.level_of("email") == "hidden"
    assert ("principal", OTHER) in inputs.asked
    assert not any(kind in ("actor", "boundary") for kind, _ in inputs.asked)
