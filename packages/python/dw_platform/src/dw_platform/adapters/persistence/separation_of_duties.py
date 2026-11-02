"""The database's separation-of-duties refusal, read back as a domain error.

The rule has one owner: `platform.enforce_role_separation_of_duties`, the AFTER
trigger on `platform.role_assignments` and `platform.tenant_role_permissions`
(migration `b5677d345bc1`, tenant-rbac R5.1). It raises SQLSTATE 23514 with
the constraint `ck_roles_sod_memberships`, the broken rule's key (always
`sod_…`) in HINT, the rule's description as the message and up to 20 user ids
in DETAIL. A membership write through the legacy `role_keys` columns reaches it
through the trigger that copies those columns into assignments, so its routes
keep answering 409 `{rule, reason}`. This module only recognizes that refusal;
it never re-derives which scopes conflict, so nothing here can drift from the
catalogue.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from dw_kernel.errors import ConflictError

_RULE_PREFIX = "sod_"
_ROLE_SOD = "ck_roles_sod_memberships"


def refusal(error: IntegrityError) -> tuple[str, str] | None:
    """The constraint a refusal names and its detail, or None when the driver
    reported no constraint."""
    # asyncpg's own exception carries the trigger's CONSTRAINT and DETAIL;
    # SQLAlchemy wraps it as the DBAPI error's cause.
    cause = getattr(error.orig, "__cause__", None)
    constraint = getattr(cause, "constraint_name", None)
    if not isinstance(constraint, str):
        return None
    return constraint, getattr(cause, "detail", None) or ""


def separation_of_duties_conflict(error: IntegrityError) -> ConflictError | None:
    """The conflict `error` stands for, or None when it is some other
    integrity failure the caller must handle (or re-raise) itself."""
    refused = refusal(error)
    if refused is None or refused[0] != _ROLE_SOD:
        return None
    cause = getattr(error.orig, "__cause__", None)
    rule = getattr(cause, "hint", None)
    if not isinstance(rule, str) or not rule.startswith(_RULE_PREFIX):
        return None
    return ConflictError(
        "these roles cannot be held together (separation of duties)",
        details={
            "rule": rule,
            "reason": getattr(cause, "message", None) or "",
            "holders": [held for held in refused[1].split(", ") if held],
        },
    )
