"""The record policy template: the one owner of the text of every policy on a
record table and of each command's reach (record-access ticket 03; ADR-0105
decision 1, its 2026-11-04 refinement; CLAUDE.md, Tenancy and authorization).

A record table and each of its partitions carry exactly five policies: the
RESTRICTIVE `tenant_isolation_<t>` and the PERMISSIVE `record_access_<t>_select`,
`_insert`, `_update`, `_delete`, each `tenant AND (scope OR (actor_ok AND reach))`.
Settings are read in sub-SELECTs and the ledger's arrays as `(SELECT f())::uuid[]`,
so each is an InitPlan computed once per statement.

`reach_sql(command)` is each command's reach over the record's own columns, and
`actor_sql(command)` which actor kinds a command admits: `user`, or `agent` and
`workflow` for an object their run's boundary allows the command on
(record-access ticket 04; ADR-0105 decision 6). The policies, RecordService's
`permissions` (custom-objects/03) and the assignment function
(record-access/05) all read them from here, never from a second copy (gate (l);
failure-modes #2). A revision does not import this module: it copies
the text rendered here when it was written, and the catalog test
(`test_record_policies.py`) compares what PostgreSQL holds with what this module
renders, so a change here needs a revision that applies it.

P0 of ADR-0105 as written: the `uuid` access key and one array per action and
arm. Provisional until record-access/07 applies ticket 06's D12 winner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Command = Literal["select", "insert", "update", "delete", "assign", "soft_delete"]
# The commands a data boundary carries a flag for (`studio.acl_boundary_objects`).
BoundaryCommand = Literal["select", "insert", "update", "delete", "assign"]

# The record commands and the ledger action each reads (ADR-0104 decision 3).
_ACTION: dict[str, str] = {
    "select": "read",
    "update": "update",
    "delete": "delete",
    "assign": "assign",
}

TENANT = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
SCOPE = "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'"
USER_OK = "(SELECT studio.acl_actor_kind()) = 'user'"


def actor_sql(command: BoundaryCommand) -> str:
    """Which actor kinds ``command`` admits, parenthesised: `user` on its reach
    alone; `agent` and `workflow` only for an object every boundary of the
    run's chain allows ``command`` on (R6.4, R6.5, R6.13). Any other kind, or
    none, is admitted by neither arm (R6.1)."""
    return (
        f"({USER_OK} OR ((SELECT studio.acl_actor_kind()) IN ('agent', 'workflow')"
        f" AND object_id = ANY ((SELECT studio.acl_boundary_objects('{command}'))::uuid[])))"
    )


def reach_sql(command: Command) -> str:
    """The reach of one command over a record row, parenthesised.

    `select`, `update`, `delete`, `assign`: the object held tenant-wide, the
    record's (object, owning workspace) key held at workspace depth, or the
    caller owning it with the object held at own depth or deeper. `insert`: the
    same for `create`, the own arm keyed by (object, anchor workspace) so a
    create grant on one object never opens another's workspace. `soft_delete`:
    update and delete reach both, since a soft delete is an UPDATE of
    `deleted_at` (custom-objects:R5.5; gate (b), (o)).
    """
    if command == "soft_delete":
        return f"({reach_sql('update')} AND {reach_sql('delete')})"
    if command == "insert":
        return (
            "(object_id = ANY ((SELECT studio.acl_objects('create', 'tenant'))::uuid[])"
            " OR access_key = ANY ((SELECT studio.acl_keys('create'))::uuid[])"
            " OR (owner_id = (SELECT studio.acl_user())"
            " AND access_key = ANY ((SELECT studio.acl_create_own_keys())::uuid[])))"
        )
    action = _ACTION[command]
    return (
        f"(object_id = ANY ((SELECT studio.acl_objects('{action}', 'tenant'))::uuid[])"
        f" OR access_key = ANY ((SELECT studio.acl_keys('{action}'))::uuid[])"
        f" OR (owner_id = (SELECT studio.acl_user())"
        f" AND object_id = ANY ((SELECT studio.acl_objects('{action}', 'own'))::uuid[])))"
    )


def may_sql(command: Literal["update", "soft_delete"]) -> str:
    """Whether the bound actor may run ``command`` on a record row, from the
    same arms its policy reads: `update` is `_update`'s USING, `soft_delete`
    its WITH CHECK on a row whose `deleted_at` is set. RecordService's
    `permissions` (custom-objects/03, gate (l)) selects it beside the row, so
    what a reader is told and what the policy enforces are one text."""
    update = f"{actor_sql('update')} AND {reach_sql('update')}"
    if command == "update":
        return f"({SCOPE} OR ({update}))"
    return f"({SCOPE} OR ({update} AND {actor_sql('delete')} AND {reach_sql('delete')}))"


def _guarded(command: BoundaryCommand, reach: str) -> str:
    return f"({TENANT}) AND ({SCOPE} OR ({actor_sql(command)} AND {reach}))"


@dataclass(frozen=True)
class RecordPolicy:
    name: str
    permissive: bool
    command: Literal["ALL", "SELECT", "INSERT", "UPDATE", "DELETE"]
    using: str | None
    with_check: str | None

    def create_sql(self, table: str) -> str:
        """`CREATE POLICY` of this policy on ``table`` (schema-qualified)."""
        parts = [f"CREATE POLICY {self.name} ON {table}"]
        if not self.permissive:
            parts.append("AS RESTRICTIVE")
        if self.command != "ALL":
            parts.append(f"FOR {self.command}")
        if self.using is not None:
            parts.append(f"USING ({self.using})")
        if self.with_check is not None:
            parts.append(f"WITH CHECK ({self.with_check})")
        return " ".join(parts)


def record_policies(short: str) -> tuple[RecordPolicy, ...]:
    """The five policies of record table ``short`` (`records` for
    `studio.records`), the same on the parent and each partition."""
    # A soft delete sets `deleted_at`: the new row then needs delete reach too,
    # so tenant-wide default access and update depth never delete (R2.7), and an
    # agent's or a workflow's boundary must allow `delete` (ticket 04, step 6).
    update_check = (
        f"({TENANT}) AND ({SCOPE} OR ({actor_sql('update')} AND {reach_sql('update')}"
        f" AND (deleted_at IS NULL OR ({actor_sql('delete')} AND {reach_sql('delete')}))))"
    )
    return (
        RecordPolicy(f"tenant_isolation_{short}", False, "ALL", f"({TENANT})", f"({TENANT})"),
        RecordPolicy(
            f"record_access_{short}_select",
            True,
            "SELECT",
            _guarded("select", reach_sql("select")),
            None,
        ),
        RecordPolicy(
            f"record_access_{short}_insert",
            True,
            "INSERT",
            None,
            _guarded("insert", reach_sql("insert")),
        ),
        RecordPolicy(
            f"record_access_{short}_update",
            True,
            "UPDATE",
            _guarded("update", reach_sql("update")),
            update_check,
        ),
        RecordPolicy(
            f"record_access_{short}_delete",
            True,
            "DELETE",
            _guarded("delete", reach_sql("delete")),
            None,
        ),
    )
