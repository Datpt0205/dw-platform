"""Field security's one decision: which fields of an object a caller sees or
edits (field-security ticket 01, R2; ADR-0106 decisions 2-4).

`resolve_field_access` is pure and is the only place that turns grants, a
field's `access_mode` and the run's data boundary into `hidden`, `read` or
`edit`. Every path that emits a record value takes a `FieldAccess` from
`FieldAccessService` (`dw_studio.core.application.field_access`), which reads
these inputs live in the caller's transaction and calls this function; no path
decides a field itself (R5.1).

What it reads, and from whom:

- `principal_grants`: the keys `platform.effective_grants` gives the principal
  in the bound company, every assignment and depth together: `obj.<object>.<action>`
  and `fld.<object>.<field>.read|edit` (tenant-rbac/04). "Edit gives read" is
  `platform.field_permission_keys`'s, so this function never derives a read
  from an edit: a secured field needs its `.read` key for any level.
- `object_security`: the object's fields as `studio.field_defs` holds them now,
  and its `schema_version`, which is the `fls_version` (ADR-0106 decision 4).
  `owner` and `workspace` are not here: they are system columns any reader of
  the record sees (ADR-0105).
- `boundary`: None only for the actor `user`; for `agent` and `workflow`, one
  mapping per link of `studio.boundary_chain` (record-access/04), field id to
  the link's `read` or `edit`. An empty chain hides everything (R2.8).

Here because every capability calls it (records, workflows, tools and run
history): Studio's capabilities never import one another, so a decision they
share lives in the core, as `ActorBoundaryPort` does.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from dw_kernel.personal_data import PdCategory

# A field's mode in its object's `dw.object/v1` version (ADR-0106 decision 2);
# `ck_field_defs_access_mode` holds the column to the same two values.
AccessMode = Literal["open", "secured"]
FieldLevel = Literal["hidden", "read", "edit"]
FieldAction = Literal["read", "update", "create"]
# What one boundary link allows on a field (`ck_actor_boundary_fields_access`).
BoundaryLevel = Literal["read", "edit"]
BoundaryLink = Mapping[uuid.UUID, BoundaryLevel]

HIDDEN: Final = "hidden"
READ: Final = "read"
EDIT: Final = "edit"
_RANK: Final[Mapping[str, int]] = {HIDDEN: 0, READ: 1, EDIT: 2}


@dataclass(frozen=True, slots=True)
class FieldSecurity:
    """One field of the object, as its live definition row says now."""

    field_id: uuid.UUID
    api_name: str
    access_mode: AccessMode
    pd_category: PdCategory
    is_unique: bool


@dataclass(frozen=True, slots=True)
class ObjectSecurity:
    """An object's fields with their security attributes, at `schema_version`."""

    api_name: str
    schema_version: int
    fields: tuple[FieldSecurity, ...]


@dataclass(frozen=True, slots=True)
class FieldAccess:
    """`hidden`, `read` or `edit` for every field of one object, and the
    `fls_version` (the object's `schema_version`) it was decided at (R2.1)."""

    object_api_name: str
    fls_version: int
    levels: Mapping[uuid.UUID, FieldLevel]
    api_names: Mapping[uuid.UUID, str]

    def level_of(self, api_name: str) -> FieldLevel | None:
        """The level of the field named ``api_name``; None for a name the
        object does not have."""
        for field_id, name in self.api_names.items():
            if name == api_name:
                return self.levels[field_id]
        return None


def _at_most(level: FieldLevel, cap: FieldLevel) -> FieldLevel:
    return level if _RANK[level] <= _RANK[cap] else cap


def _secured(field: FieldSecurity) -> bool:
    # A sensitive field is secured whatever its row says (R1.3 holds the row to
    # it too): an unreadable or unknown mode is secured, never open.
    return field.access_mode != "open" or field.pd_category is PdCategory.SENSITIVE


def resolve_field_access(
    principal_grants: frozenset[str],
    object_security: ObjectSecurity,
    boundary: Sequence[BoundaryLink] | None,
    action: FieldAction = "update",
    *,
    service_account: bool,
) -> FieldAccess:
    """The level of every field of ``object_security`` for ``action``.

    On the principal's side, in this order (R2.2-R2.4, R2.6, R2.7):

    - `read` and `update` need `obj.<object>.read`; without it every field is
      `hidden`. `create` does not, so a create-only role can create a record.
    - `edit` needs the write key of ``action``: `obj.<object>.update`, or
      `obj.<object>.create` for `create`; `read` writes nothing, so it never
      answers `edit`.
    - An open field is `edit` with the write key, else `read` with
      `obj.<object>.read`. A secured field needs `fld.<object>.<field>.read`
      for `read` and also `.edit` for `edit`, added up over every role because
      the keys already are.
    - A unique field is at least `read` for a principal who creates or updates
      the object: holding `obj.<object>.create` for `create`, or
      `obj.<object>.read` with `.create` or `.update` otherwise (ADR-0106
      decision 4). Not a sensitive field for a service account
      (``service_account``): no service account reads a sensitive field
      (tenant-rbac R9.9), this exception included.

    Then, for an `agent` or `workflow` run (``boundary`` not None), the level
    is capped by every link: a field a link has no row for, or an empty chain,
    is `hidden`, an open or unique field included (R2.5, R2.8).
    """
    name = object_security.api_name
    holds_read = f"obj.{name}.read" in principal_grants
    holds_create = f"obj.{name}.create" in principal_grants
    holds_update = f"obj.{name}.update" in principal_grants
    writes = {"create": holds_create, "update": holds_update, "read": False}[action]
    creates_or_updates = (
        holds_create if action == "create" else holds_read and (holds_create or holds_update)
    )
    sees = action == "create" or holds_read

    levels: dict[uuid.UUID, FieldLevel] = {}
    for field in object_security.fields:
        level: FieldLevel = HIDDEN
        if sees:
            if not _secured(field):
                level = EDIT if writes else READ if holds_read else HIDDEN
            elif f"fld.{name}.{field.api_name}.read" in principal_grants:
                edits = f"fld.{name}.{field.api_name}.edit" in principal_grants
                level = EDIT if edits and writes else READ if holds_read else HIDDEN
            if (
                level == HIDDEN
                and field.is_unique
                and creates_or_updates
                and not (service_account and field.pd_category is PdCategory.SENSITIVE)
            ):
                level = READ
        if boundary is not None:
            if not boundary:
                level = HIDDEN
            for link in boundary:
                level = _at_most(level, link.get(field.field_id, HIDDEN))
        levels[field.field_id] = level
    return FieldAccess(
        object_api_name=name,
        fls_version=object_security.schema_version,
        levels=levels,
        api_names={f.field_id: f.api_name for f in object_security.fields},
    )


def visible_fields(access: FieldAccess) -> frozenset[uuid.UUID]:
    """The fields at `read` or above: what an adapter may select (R3.1)."""
    return frozenset(f for f, level in access.levels.items() if level != HIDDEN)


def reads_all(accesses: Mapping[str, FieldAccess], stamped_fields: Iterable[str]) -> bool:
    """True when every `<object>.<field>` of ``stamped_fields`` is `read` or
    `edit` in the `FieldAccess` of its object in ``accesses`` (by object
    `api_name`); False for an object or a field ``accesses`` does not hold, or
    a name not of that shape. The approver rule of R4.5 and R4.7, which
    workflow-nodes/06's guards and ticket 02's candidate filter call."""
    for stamped in stamped_fields:
        object_name, dot, field_name = stamped.partition(".")
        access = accesses.get(object_name)
        if not dot or access is None:
            return False
        if access.level_of(field_name) not in (READ, EDIT):
            return False
    return True
