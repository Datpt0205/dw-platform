"""The database's refusals of a role write, read back as domain errors
(tenant-rbac ticket 03, step 7).

Every writer of the role tables meets the same triggers, so every adapter that
writes them reads a refusal here and nowhere else: one constraint, one answer.
The rules stay the database's (`platform.rbac_guard`, `platform.rbac_refusals`
and the guards beside them); this module only names what they said.

- `rbac_refusals_<table>`: the reason code in DETAIL, the keys `key:depth` in
  HINT, answered by `rbac_refusal_error`, the service's own mapping; the two
  refusals no service path should meet (no confirmed proposal, no actor) as 409
  `second_person_required` and 403.
- `ck_role_assignments_service_not_critical` 422, `ck_roles_sod_memberships`,
  `role_limit_reached`, `ck_role_assignments_last_owner`,
  `ck_memberships_dw_principal_roles_fixed`, `ck_tenant_roles_in_use` and a
  unique key (two proposals of one change, M1) 409 by name; any other check
  violation 409 `constraint_violation` naming it, never a 500.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from dw_kernel.errors import ConflictError, DWError, PermissionDeniedError
from dw_platform.adapters.persistence.separation_of_duties import (
    refusal,
    separation_of_duties_conflict,
)
from dw_platform.adapters.persistence.service_principals_repo import service_principal_refusal
from dw_platform.adapters.persistence.support_grants import support_staff_conflict
from dw_platform.application.role_admin import Refusal, conflict, rbac_refusal_error

_GUARD_PREFIX = "rbac_refusals_"
_BY_NAME = {
    "role_limit_reached": ("a company holds at most 200 roles", "role_limit_reached"),
    "ck_role_assignments_last_owner": (
        "the company keeps at least one active owner",
        "last_owner",
    ),
    "ck_tenant_roles_in_use": ("this role is still assigned", "role_in_use"),
    "ck_memberships_dw_principal_roles_fixed": (
        "the roles of a digital worker's principal are fixed when it is made",
        "dw_principal_roles_fixed",
    ),
    "uq_tenant_roles_tenant_id_key": (
        "this company already has a role with that key",
        "role_key_taken",
    ),
}
_UNIQUE_SQLSTATE = "23505"
_CHECK_SQLSTATE = "23514"
_FOREIGN_KEY_SQLSTATE = "23503"


def _cause(error: IntegrityError) -> object:
    return getattr(error.orig, "__cause__", None)


def _guard_refusal(detail: str, hint: str) -> DWError:
    if detail == "rbac_two_people":
        return conflict(
            "a change that widens takes a second person's confirmation", "second_person_required"
        )
    if detail == "rbac_actor_missing":
        return PermissionDeniedError(
            "a role change names who makes it", details={"reason_code": "rbac_actor_missing"}
        )
    refusals = [Refusal(detail, *key.split(":", 1)) for key in hint.split(",") if ":" in key] or [
        Refusal(detail)
    ]
    return rbac_refusal_error(refusals) or PermissionDeniedError("refused")


def role_write_refusal(error: IntegrityError) -> DWError | None:
    """The domain error a refused role write stands for, or None when the
    error carries no constraint (the caller re-raises)."""
    refused = refusal(error)
    if refused is None:
        return None
    name, detail = refused
    cause = _cause(error)
    if name.startswith(_GUARD_PREFIX):
        return _guard_refusal(detail, getattr(cause, "hint", None) or "")
    known = (
        separation_of_duties_conflict(error)
        or service_principal_refusal(error)
        or support_staff_conflict(error)
    )
    if known is not None:
        return known
    if name in _BY_NAME:
        message, reason_code = _BY_NAME[name]
        return conflict(message, reason_code)
    sqlstate = getattr(cause, "sqlstate", None)
    if sqlstate == _UNIQUE_SQLSTATE:
        return ConflictError(
            "this change is already in place", details={"reason_code": "already_applied"}
        )
    if sqlstate == _FOREIGN_KEY_SQLSTATE:
        return conflict("what this change names is gone", "proposal_stale")
    if sqlstate == _CHECK_SQLSTATE:
        return conflict("the database refused this change", "constraint_violation", constraint=name)
    return None
