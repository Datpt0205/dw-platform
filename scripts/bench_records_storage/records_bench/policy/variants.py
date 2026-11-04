# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""The policy variants of record-access/01 and the DDL each renders (ticket step 2).

P0 is ADR-0105 (Accepted) as written: a `uuid` access key from md5 of object and
owning workspace, one ledger row per principal (PK `(tenant_id, principal_id)`,
`epoch`, `version`, `state`, one array per action and arm, decision 4), arms that
read the arrays with `= ANY` and `&&`, and no planner hint. Each axis changes one
thing around P0:

- K: the access key is a `bigint` composed of two small per-tenant numbers, the
  object's and the owning workspace's.
- L: one ledger row per principal and action.
- E: the arms read the ledger through one correlated `EXISTS` instead of arrays
  bound once per statement.
- H: the "Của tôi" list filter `AND owner_id = (SELECT studio.acl_user())` on the
  two Của tôi profiles' pages, against the same filter as a bound parameter in
  every other variant. It is a query predicate, never a policy (gate HIGH 23).

W is the combination of the axes' winners (`run.winning_combination`).

The replacement is declared once (`declared`): the self-check compares a cell's
catalog with A1's and fails any difference outside it, so a variant that grows an
index, or is pointed at A0, is caught (step 7).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from ..ddl import SCOPE, TENANT, partitions
from ..model import KIND_AGENT, bench_uuid

KeyType = Literal["uuid", "bigint"]
Ledger = Literal["row", "action"]
ArmForm = Literal["array", "exists"]

ACTIONS = ("read", "update", "create", "delete", "assign", "share")
# The arms each action's ledger holds (ADR-0105 decisions 2 and 4): hierarchy
# and grants reach read and update only, `workspaces` bounds a create.
ARMS_OF: dict[str, tuple[str, ...]] = {
    "read": (
        "objects_tenant",
        "objects_own",
        "objects_team",
        "keys",
        "owners_team",
        "owners_subordinate",
        "grants",
    ),
    "update": (
        "objects_tenant",
        "objects_own",
        "objects_team",
        "keys",
        "owners_team",
        "owners_subordinate",
        "grants",
    ),
    "create": ("objects_tenant", "objects_own", "keys", "workspaces"),
    "delete": ("objects_tenant", "objects_own", "objects_team", "keys", "owners_team"),
    "assign": ("objects_tenant", "objects_own", "objects_team", "keys", "owners_team"),
    "share": ("objects_tenant", "objects_own", "objects_team", "keys", "owners_team"),
}
ALL_ARMS = (
    "objects_tenant",
    "objects_own",
    "objects_team",
    "keys",
    "owners_team",
    "owners_subordinate",
    "grants",
    "workspaces",
)
# The harness's arm names (seed.profiles_and_scopes) and the ledger's.
HARNESS_ARMS = {
    "objects:tenant": "objects_tenant",
    "objects:own": "objects_own",
    "keys": "keys",
    "owners:team": "owners_team",
    "owners:subordinate": "owners_subordinate",
    "grants": "grants",
    "workspaces": "workspaces",
}

KIND_BOUNDARY = 9
# An agent's boundary is one object (mkt_lead); the `workflow` writer's is every object.
AGENT_BOUNDARY = bench_uuid(KIND_BOUNDARY, 0, 1)
WRITER_BOUNDARY = bench_uuid(KIND_BOUNDARY, 0, 2)
HARNESS_AGENT = bench_uuid(KIND_AGENT, 0, 1)  # the harness's own agent principal

VALID = (
    "s.state = 'valid' AND s.epoch = (SELECT e.epoch FROM studio.access_epochs e"
    " WHERE e.tenant_id = s.tenant_id)"
)
ME = (
    "s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    " AND s.principal_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
)


@dataclass(frozen=True)
class PolicyVariant:
    name: str
    key: KeyType = "uuid"
    ledger: Ledger = "row"
    arms: ArmForm = "array"
    hint: bool = False
    base: str = "A1"  # the storage variant of custom-objects/01 it replaces parts of

    @property
    def key_sql(self) -> str:
        return "bigint" if self.key == "bigint" else "uuid"

    def options(self) -> dict[str, object]:
        return {"key": self.key, "ledger": self.ledger, "arms": self.arms, "hint": self.hint}


P0 = PolicyVariant("P0")
# One axis each around P0 (ticket step 2); the option P0 holds on each axis is P0's.
AXES: dict[str, PolicyVariant] = {
    "K": replace(P0, name="K", key="bigint"),
    "L": replace(P0, name="L", ledger="action"),
    "E": replace(P0, name="E", arms="exists"),
    "H": replace(P0, name="H", hint=True),
}
POLICY_VARIANTS: dict[str, PolicyVariant] = {"P0": P0, **AXES}
AXIS_FIELD = {"K": "key", "L": "ledger", "E": "arms", "H": "hint"}


def combination(winners: dict[str, str]) -> PolicyVariant:
    """P0 with every axis whose winner is not P0 switched to its option: W."""
    out = replace(P0, name="W")
    for axis, winner in winners.items():
        if winner != "P0":
            field = AXIS_FIELD[axis]
            out = replace(out, **{field: getattr(AXES[axis], field)})
    return out


# --------------------------------------------------------------- the ledger --
def arm_type(arm: str, variant: PolicyVariant) -> str:
    return variant.key_sql if arm == "keys" else "uuid"


def ledger_ddl(variant: PolicyVariant) -> list[str]:
    head = (
        "tenant_id uuid NOT NULL, principal_id uuid NOT NULL,"
        + (" action text NOT NULL," if variant.ledger == "action" else "")
        + " epoch bigint NOT NULL, version bigint NOT NULL, state text NOT NULL"
    )
    if variant.ledger == "row":
        cols = [
            f"{a}_{arm} {arm_type(arm, variant)}[] NOT NULL DEFAULT '{{}}'"
            for a in ACTIONS
            for arm in ARMS_OF[a]
        ]
        pk = "(tenant_id, principal_id)"
        checks = []
    else:
        cols = [f"{arm} {arm_type(arm, variant)}[] NOT NULL DEFAULT '{{}}'" for arm in ALL_ARMS]
        pk = "(tenant_id, principal_id, action)"
        actions = ", ".join(f"'{a}'" for a in ACTIONS)
        checks = [f"CONSTRAINT ck_principal_scopes_action CHECK (action IN ({actions}))"]
    body = ",\n    ".join(
        [
            head,
            *cols,
            f"CONSTRAINT pk_principal_scopes PRIMARY KEY {pk}",
            "CONSTRAINT ck_principal_scopes_state CHECK (state IN ('valid', 'stale'))",
            *checks,
        ]
    )
    return [
        f"CREATE TABLE studio.principal_scopes (\n    {body})",
        "ALTER TABLE studio.principal_scopes ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE studio.principal_scopes FORCE ROW LEVEL SECURITY",
        "CREATE POLICY tenant_isolation_principal_scopes ON studio.principal_scopes USING"
        " (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid) AND"
        " principal_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid))",
        "REVOKE ALL ON studio.principal_scopes FROM dw_app",
        "GRANT SELECT ON studio.principal_scopes TO dw_app",
    ]


SUPPORT_TABLES = f"""
CREATE TABLE studio.access_epochs (
    tenant_id uuid NOT NULL, epoch bigint NOT NULL DEFAULT 1,
    CONSTRAINT pk_access_epochs PRIMARY KEY (tenant_id));
ALTER TABLE studio.access_epochs ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio.access_epochs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_access_epochs ON studio.access_epochs USING ({TENANT});
REVOKE ALL ON studio.access_epochs FROM dw_app;
GRANT SELECT ON studio.access_epochs TO dw_app;
-- STAND-IN for ADR-0103's studio.actor_boundaries: the objects a boundary admits.
CREATE TABLE studio.actor_boundaries (
    tenant_id uuid NOT NULL, boundary_id uuid NOT NULL, object_ids uuid[] NOT NULL,
    CONSTRAINT pk_actor_boundaries PRIMARY KEY (tenant_id, boundary_id));
ALTER TABLE studio.actor_boundaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio.actor_boundaries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_actor_boundaries ON studio.actor_boundaries USING ({TENANT});
REVOKE ALL ON studio.actor_boundaries FROM dw_app;
GRANT SELECT ON studio.actor_boundaries TO dw_app;
-- STAND-IN for platform.effective_grants (ADR-0104 decision 5): one row per
-- (principal, obj.<api_name>.<action>, depth, anchor), read only by the door.
CREATE TABLE studio.bench_effective_grants (
    tenant_id uuid NOT NULL, principal_id uuid NOT NULL, permission_key text NOT NULL,
    depth text NOT NULL, anchor_workspace_id uuid NOT NULL,
    CONSTRAINT pk_bench_effective_grants
        PRIMARY KEY (tenant_id, principal_id, permission_key, depth, anchor_workspace_id),
    CONSTRAINT ck_bench_effective_grants_depth
        CHECK (depth IN ('own', 'team', 'workspace', 'workspace_subtree', 'tenant')));
REVOKE ALL ON studio.bench_effective_grants FROM dw_app;
"""


# -------------------------------------------------------- the acl functions --
def _pick(variant: PolicyVariant, action_sql: str, arm_sql: str, arms: tuple[str, ...]) -> str:
    """The ledger column of (action, arm), as a CASE over the caller's arguments."""
    if variant.ledger == "row":
        whens = " ".join(
            f"WHEN '{a}:{arm}' THEN s.{a}_{arm}"
            for a in ACTIONS
            for arm in ARMS_OF[a]
            if arm in arms
        )
        return f"CASE {action_sql} || ':' || {arm_sql} {whens} END"
    whens = " ".join(f"WHEN '{arm}' THEN s.{arm}" for arm in arms)
    return f"CASE {arm_sql} {whens} END"


def _acl(variant: PolicyVariant, name: str, args: str, returns: str, pick: str) -> str:
    action = " AND s.action = p_action" if variant.ledger == "action" else ""
    return (
        f"CREATE FUNCTION studio.{name}({args}) RETURNS {returns}\n"
        "    LANGUAGE sql STABLE SET search_path = pg_catalog\n"
        f"    AS $$ SELECT coalesce((SELECT {pick} FROM studio.principal_scopes s\n"
        f"             WHERE {ME}{action}\n"
        f"               AND {VALID}), '{{}}'::{returns}) $$"
    )


def acl_functions(variant: PolicyVariant) -> list[str]:
    """STABLE, invoker, fixed search_path, empty when anything is missing (ADR-0105 decision 1).

    One level each, settings read inline: a LANGUAGE sql function with SET
    search_path is not inlined and is planned at every call (the harness's
    measurement of 2026-11-02), so nesting would charge reach its own depth.
    """
    k = variant.key_sql
    obj_arms = ("objects_tenant", "objects_own", "objects_team")
    owner_arms = ("owners_team", "owners_subordinate")
    return [
        _acl(
            variant,
            "acl_objects",
            "p_action text, p_depth text",
            "uuid[]",
            _pick(variant, "p_action", "'objects_' || p_depth", obj_arms),
        ),
        _acl(
            variant,
            "acl_keys",
            "p_action text",
            f"{k}[]",
            _pick(variant, "p_action", "'keys'", ("keys",)),
        ),
        _acl(
            variant,
            "acl_owners",
            "p_action text, p_kind text",
            "uuid[]",
            _pick(variant, "p_action", "'owners_' || p_kind", owner_arms),
        ),
        _acl(
            variant,
            "acl_grant_keys",
            "p_action text",
            "uuid[]",
            _pick(variant, "p_action", "'grants'", ("grants",)),
        ),
        _acl(
            variant,
            "acl_workspaces",
            "p_action text",
            "uuid[]",
            _pick(variant, "p_action", "'workspaces'", ("workspaces",)),
        ),
        "CREATE FUNCTION studio.acl_boundary() RETURNS uuid[]\n"
        "    LANGUAGE sql STABLE SET search_path = pg_catalog\n"
        "    AS $$ SELECT coalesce((SELECT b.object_ids FROM studio.actor_boundaries b\n"
        "             WHERE b.tenant_id = NULLIF(current_setting('app.tenant_id', true),"
        " '')::uuid\n"
        "               AND b.boundary_id = NULLIF(current_setting('app.boundary_id', true),"
        " '')::uuid), '{}'::uuid[]) $$",
    ]


ACL_FUNCTION_NAMES = (
    "acl_objects",
    "acl_keys",
    "acl_owners",
    "acl_grant_keys",
    "acl_workspaces",
    "acl_boundary",
)


# ------------------------------------------------------------ the policies --
ACTOR_OK = (
    "((SELECT studio.acl_actor_kind()) = 'user'"
    " OR ((SELECT studio.acl_actor_kind()) IN ('agent', 'workflow')"
    " AND object_id = ANY ((SELECT studio.acl_boundary())::uuid[])))"
)
# ADR-0105 decision 3: expiry is enforced at read time, early, never late.
NOT_EXPIRED = "(grants_valid_until IS NULL OR grants_valid_until > now())"


def _array_arms(action: str, variant: PolicyVariant) -> list[str]:
    k = variant.key_sql
    arms = ARMS_OF[action]
    out = [
        f"object_id = ANY ((SELECT studio.acl_objects('{action}', 'tenant'))::uuid[])",
        f"access_key = ANY ((SELECT studio.acl_keys('{action}'))::{k}[])",
    ]
    own = (
        f"(owner_id = (SELECT studio.acl_user())"
        f" AND object_id = ANY ((SELECT studio.acl_objects('{action}', 'own'))::uuid[])"
    )
    if action == "create":
        own += f" AND workspace_id = ANY ((SELECT studio.acl_workspaces('{action}'))::uuid[])"
    out.append(own + ")")
    if "owners_team" in arms:
        out.append(
            f"(owner_id = ANY ((SELECT studio.acl_owners('{action}', 'team'))::uuid[])"
            f" AND object_id = ANY ((SELECT studio.acl_objects('{action}', 'team'))::uuid[]))"
        )
    if "owners_subordinate" in arms:
        out.append(
            f"(owner_id = ANY ((SELECT studio.acl_owners('{action}', 'subordinate'))::uuid[])"
            f" AND object_id = ANY ((SELECT studio.acl_objects('{action}', 'own'))::uuid[]))"
        )
    if "grants" in arms:
        column = "read_grants" if action == "read" else "edit_grants"
        out.append(
            f"({column} && (SELECT studio.acl_grant_keys('{action}'))::uuid[] AND {NOT_EXPIRED})"
        )
    return out


def _exists_arms(action: str, variant: PolicyVariant) -> list[str]:
    """The ledger joined per row: one correlated EXISTS holding every arm."""
    arms = ARMS_OF[action]

    def col(arm: str) -> str:
        return f"s.{action}_{arm}" if variant.ledger == "row" else f"s.{arm}"

    inner = [
        f"object_id = ANY ({col('objects_tenant')})",
        f"access_key = ANY ({col('keys')})",
    ]
    own = f"(owner_id = s.principal_id AND object_id = ANY ({col('objects_own')})"
    if action == "create":
        own += f" AND workspace_id = ANY ({col('workspaces')})"
    inner.append(own + ")")
    if "owners_team" in arms:
        inner.append(
            f"(owner_id = ANY ({col('owners_team')}) AND object_id = ANY ({col('objects_team')}))"
        )
    if "owners_subordinate" in arms:
        inner.append(
            f"(owner_id = ANY ({col('owners_subordinate')})"
            f" AND object_id = ANY ({col('objects_own')}))"
        )
    if "grants" in arms:
        column = "read_grants" if action == "read" else "edit_grants"
        inner.append(f"({column} && {col('grants')} AND {NOT_EXPIRED})")
    action_clause = f" AND s.action = '{action}'" if variant.ledger == "action" else ""
    body = "\n                OR ".join(inner)
    return [
        "EXISTS (SELECT 1 FROM studio.principal_scopes s"
        " WHERE s.tenant_id = (SELECT studio.acl_tenant())"
        f" AND s.principal_id = (SELECT studio.acl_user()){action_clause} AND {VALID}"
        f"\n            AND ({body}))"
    ]


def reach(action: str, variant: PolicyVariant) -> str:
    arms = (
        _array_arms(action, variant) if variant.arms == "array" else _exists_arms(action, variant)
    )
    joined = "\n            OR ".join(arms)
    return f"{TENANT} AND ({SCOPE} OR ({ACTOR_OK} AND (\n            {joined})))"


def record_policies(table: str, short: str, variant: PolicyVariant) -> list[str]:
    """ADR-0105 decision 1 for one record table or partition: RESTRICTIVE tenant, PERMISSIVE."""
    return [
        f"CREATE POLICY tenant_isolation_{short} ON {table} AS RESTRICTIVE"
        f" USING ({TENANT}) WITH CHECK ({TENANT})",
        f"CREATE POLICY record_access_{short}_select ON {table} FOR SELECT"
        f" USING ({reach('read', variant)})",
        f"CREATE POLICY record_access_{short}_insert ON {table} FOR INSERT"
        f" WITH CHECK ({reach('create', variant)})",
        f"CREATE POLICY record_access_{short}_update ON {table} FOR UPDATE"
        f" USING ({reach('update', variant)}) WITH CHECK ({reach('update', variant)})",
        f"CREATE POLICY record_access_{short}_delete ON {table} FOR DELETE"
        f" USING ({reach('delete', variant)})",
    ]


def _drop_harness_policies(modulus: int) -> list[str]:
    out = []
    for table in ["studio.records", *partitions("studio.records", modulus)]:
        short = table.split(".")[1]
        out.append(f"DROP POLICY tenant_isolation_{short} ON {table}")
        for cmd in ("select", "insert", "update", "delete"):
            out.append(f"DROP POLICY record_access_{short}_{cmd} ON {table}")
    return out


# ----------------------------------------------- compute, door and triggers --
def _key_expr(variant: PolicyVariant, object_id: str, workspace_id: str) -> str:
    if variant.key == "uuid":
        return f"md5({object_id}::text || '/' || {workspace_id}::text)::uuid"
    return (
        f"((SELECT o.object_no FROM studio.object_defs o WHERE o.tenant_id = (SELECT t FROM me)"
        f" AND o.id = {object_id})::bigint << 32) | (SELECT w.workspace_no FROM platform.workspaces"
        f" w WHERE w.tenant_id = (SELECT t FROM me) AND w.id = {workspace_id})"
    )


def compute_function(variant: PolicyVariant) -> str:
    """`studio.compute_principal_scope()`: a principal's reach, from the settings only.

    ADR-0105 decision 2 in full: tenant depth and the object's `default_access`
    give the tenant arm, workspace and sub-tree depth the keys, team depth the
    team's closure, own or more the transitive subordinates (every object keeps
    `grant_hierarchy` on), and the grant keys are the person, their teams, their
    home workspace, the sub-tree markers above it and the rule versions aimed at
    their teams. One row per (action, arm); keys go in `nums` when they are bigint.
    """
    key = _key_expr(variant, "k.object_id", "k.ws")
    if variant.key == "bigint":
        keys_row = (
            "SELECT a.action, 'keys', NULL::uuid[],"
            f" ARRAY(SELECT DISTINCT {key} FROM keyset k WHERE k.action = a.action ORDER BY 1)"
            " FROM actions a"
        )
    else:
        keys_row = (
            f"SELECT a.action, 'keys', ARRAY(SELECT DISTINCT {key} FROM keyset k"
            " WHERE k.action = a.action ORDER BY 1), NULL::bigint[] FROM actions a"
        )
    return f"""
CREATE FUNCTION studio.compute_principal_scope()
    RETURNS TABLE (action text, arm text, ids uuid[], nums bigint[])
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$
WITH RECURSIVE me AS (
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid AS t,
           NULLIF(current_setting('app.user_id', true), '')::uuid AS u),
g AS (
    SELECT o.id AS object_id, split_part(eg.permission_key, '.', 3) AS action, eg.depth,
           eg.anchor_workspace_id AS anchor, o.default_access
    FROM me
    JOIN studio.bench_effective_grants eg ON eg.tenant_id = me.t AND eg.principal_id = me.u
    JOIN studio.object_defs o
      ON o.tenant_id = me.t AND o.api_name = split_part(eg.permission_key, '.', 2)),
actions AS (SELECT DISTINCT g.action FROM g),
sub(anchor, ws) AS (
    SELECT DISTINCT g.anchor, g.anchor FROM g WHERE g.depth = 'workspace_subtree'
    UNION
    SELECT sub.anchor, w.workspace_id FROM sub JOIN studio.bench_workspace_tree w
      ON w.tenant_id = (SELECT t FROM me) AND w.parent_id = sub.ws),
keyset AS (
    SELECT g.action, g.object_id, g.anchor AS ws FROM g WHERE g.depth = 'workspace'
    UNION
    SELECT g.action, g.object_id, sub.ws FROM g JOIN sub ON sub.anchor = g.anchor
    WHERE g.depth = 'workspace_subtree'),
teams AS (
    SELECT m.team_id FROM me JOIN studio.bench_team_members m
      ON m.tenant_id = me.t AND m.person_id = me.u),
team_closure AS (
    SELECT teams.team_id AS id FROM teams
    UNION
    SELECT m.person_id FROM teams JOIN studio.bench_team_members m
      ON m.tenant_id = (SELECT t FROM me) AND m.team_id = teams.team_id),
subs(id) AS (
    SELECT p.id FROM me JOIN studio.bench_people p ON p.tenant_id = me.t AND p.manager_id = me.u
    UNION
    SELECT p.id FROM subs JOIN studio.bench_people p
      ON p.tenant_id = (SELECT t FROM me) AND p.manager_id = subs.id),
home AS (
    SELECT p.home_workspace_id AS ws FROM me JOIN studio.bench_people p
      ON p.tenant_id = me.t AND p.id = me.u),
ancestors(ws) AS (
    SELECT home.ws FROM home
    UNION
    SELECT w.parent_id FROM ancestors JOIN studio.bench_workspace_tree w
      ON w.tenant_id = (SELECT t FROM me) AND w.workspace_id = ancestors.ws
    WHERE w.parent_id IS NOT NULL),
grant_keys AS (
    SELECT me.u AS k FROM me
    UNION SELECT teams.team_id FROM teams
    UNION SELECT home.ws FROM home
    UNION SELECT md5('subtree:' || ancestors.ws::text)::uuid FROM ancestors
    UNION SELECT r.id FROM studio.sharing_rule_versions r
          WHERE r.tenant_id = (SELECT t FROM me) AND r.target_id IN (SELECT team_id FROM teams)),
create_ws AS (
    SELECT g.anchor AS ws FROM g
     WHERE g.action = 'create' AND g.depth IN ('own', 'team', 'workspace')
    UNION SELECT sub.ws FROM g JOIN sub ON sub.anchor = g.anchor
          WHERE g.action = 'create' AND g.depth = 'workspace_subtree'
    UNION SELECT w.id FROM platform.workspaces w
          WHERE w.tenant_id = (SELECT t FROM me)
            AND EXISTS (SELECT 1 FROM g WHERE g.action = 'create' AND g.depth = 'tenant'))
SELECT a.action, 'objects_tenant', ARRAY(SELECT DISTINCT g.object_id FROM g
         WHERE g.action = a.action AND (g.depth = 'tenant'
            OR (a.action = 'read' AND g.default_access IN ('public_read', 'public_read_write'))
            OR (a.action = 'update' AND g.default_access = 'public_read_write')) ORDER BY 1),
       NULL::bigint[] FROM actions a
UNION ALL
SELECT a.action, 'objects_own', ARRAY(SELECT DISTINCT g.object_id FROM g
         WHERE g.action = a.action ORDER BY 1), NULL FROM actions a
UNION ALL
SELECT a.action, 'objects_team', ARRAY(SELECT DISTINCT g.object_id FROM g
         WHERE g.action = a.action AND g.depth <> 'own' ORDER BY 1), NULL FROM actions a
UNION ALL
{keys_row}
UNION ALL
SELECT a.action, 'owners_team', ARRAY(SELECT c.id FROM team_closure c
         WHERE EXISTS (SELECT 1 FROM g WHERE g.action = a.action AND g.depth <> 'own') ORDER BY 1),
       NULL FROM actions a
UNION ALL
SELECT a.action, 'owners_subordinate', ARRAY(SELECT subs.id FROM subs
         WHERE a.action IN ('read', 'update') ORDER BY 1), NULL FROM actions a
UNION ALL
SELECT a.action, 'grants', ARRAY(SELECT gk.k FROM grant_keys gk
         WHERE a.action IN ('read', 'update') ORDER BY 1), NULL FROM actions a
UNION ALL
SELECT a.action, 'workspaces', ARRAY(SELECT DISTINCT c.ws FROM create_ws c
         WHERE a.action = 'create' ORDER BY 1), NULL FROM actions a
$$"""


def _arm_value(variant: PolicyVariant, action_sql: str, arm: str) -> str:
    column = "nums" if arm == "keys" and variant.key == "bigint" else "ids"
    return (
        f"coalesce((SELECT c.{column} FROM c WHERE c.action = {action_sql} AND c.arm = '{arm}'),"
        f" '{{}}'::{arm_type(arm, variant)}[])"
    )


def ensure_function(variant: PolicyVariant) -> str:
    """`studio.ensure_principal_scope()`: the door every Studio transaction calls.

    A valid row at the tenant's epoch returns at once (R9.8). Otherwise the reach
    is computed and published only if the row's version is still the one read
    before computing: a stale mark (a revocation) bumps the version, so a
    computation begun before it never publishes after it (ADR-0105 decision 4).
    """
    if variant.ledger == "row":
        cols = [f"{a}_{arm}" for a in ACTIONS for arm in ARMS_OF[a]]
        values = [_arm_value(variant, f"'{a}'", arm) for a in ACTIONS for arm in ARMS_OF[a]]
        fast = (
            "SELECT s.version, s.state = 'valid' AND s.epoch = e INTO v0, ok"
            " FROM studio.principal_scopes s WHERE s.tenant_id = t AND s.principal_id = u;\n"
            "    IF ok THEN RETURN; END IF;"
        )
        insert = (
            "WITH c AS MATERIALIZED (SELECT * FROM studio.compute_principal_scope())\n"
            "    INSERT INTO studio.principal_scopes AS s (tenant_id, principal_id, epoch,"
            f" version, state, {', '.join(cols)})\n"
            f"    SELECT t, u, e, coalesce(v0, 0) + 1, 'valid', {', '.join(values)}\n"
            "    ON CONFLICT (tenant_id, principal_id) DO UPDATE SET epoch = EXCLUDED.epoch,"
            " version = EXCLUDED.version, state = 'valid', "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
            + "\n    WHERE s.version = v0;"
        )
    else:
        cols = list(ALL_ARMS)
        values = [_arm_value(variant, "a.action", arm) for arm in ALL_ARMS]
        actions = ", ".join(f"'{a}'" for a in ACTIONS)
        fast = (
            "SELECT max(s.version), count(*) = 6 AND bool_and(s.state = 'valid' AND s.epoch = e)"
            " INTO v0, ok FROM studio.principal_scopes s WHERE s.tenant_id = t AND s.principal_id"
            " = u;\n"
            "    IF ok THEN RETURN; END IF;"
        )
        insert = (
            "WITH c AS MATERIALIZED (SELECT * FROM studio.compute_principal_scope())\n"
            "    INSERT INTO studio.principal_scopes AS s (tenant_id, principal_id, action, epoch,"
            f" version, state, {', '.join(cols)})\n"
            f"    SELECT t, u, a.action, e, coalesce(v0, 0) + 1, 'valid', {', '.join(values)}\n"
            f"    FROM unnest(ARRAY[{actions}]) AS a(action)\n"
            "    ON CONFLICT (tenant_id, principal_id, action) DO UPDATE SET epoch ="
            " EXCLUDED.epoch, version = EXCLUDED.version, state = 'valid', "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
            + "\n    WHERE s.version = v0;"
        )
    return f"""
CREATE FUNCTION studio.ensure_principal_scope() RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
    AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    u uuid := NULLIF(current_setting('app.user_id', true), '')::uuid;
    e bigint;
    v0 bigint;
    ok boolean := false;
BEGIN
    IF t IS NULL OR u IS NULL THEN RETURN; END IF;
    SELECT x.epoch INTO e FROM studio.access_epochs x WHERE x.tenant_id = t;
    IF e IS NULL THEN RETURN; END IF;
    {fast}
    {insert}
END $$"""


TRIGGERS = """
CREATE FUNCTION studio.bench_mark_scope_stale() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
    AS $$
BEGIN
    -- Every row of the principal moves to one new version together, so the
    -- door's version check holds for the per-action ledger too.
    IF TG_OP <> 'INSERT' THEN
        UPDATE studio.principal_scopes SET state = 'stale', version = version + 1
         WHERE tenant_id = OLD.tenant_id AND principal_id = OLD.principal_id;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        UPDATE studio.principal_scopes SET state = 'stale', version = version + 1
         WHERE tenant_id = NEW.tenant_id AND principal_id = NEW.principal_id;
    END IF;
    RETURN NULL;
END $$;
CREATE FUNCTION studio.bench_bump_access_epoch() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
    AS $$
BEGIN
    UPDATE studio.access_epochs SET epoch = epoch + 1
     WHERE tenant_id = CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
    RETURN NULL;
END $$;
CREATE TRIGGER bench_mark_scope_stale AFTER INSERT OR UPDATE OR DELETE
    ON studio.bench_effective_grants FOR EACH ROW EXECUTE FUNCTION studio.bench_mark_scope_stale();
CREATE TRIGGER bench_bump_access_epoch AFTER UPDATE OF default_access ON studio.object_defs
    FOR EACH ROW WHEN (OLD.default_access IS DISTINCT FROM NEW.default_access)
    EXECUTE FUNCTION studio.bench_bump_access_epoch();
CREATE TRIGGER bench_bump_access_epoch AFTER INSERT OR UPDATE OR DELETE
    ON studio.bench_team_members FOR EACH ROW EXECUTE FUNCTION studio.bench_bump_access_epoch();
CREATE TRIGGER bench_bump_access_epoch AFTER INSERT OR UPDATE OR DELETE
    ON studio.bench_people FOR EACH ROW EXECUTE FUNCTION studio.bench_bump_access_epoch();
CREATE TRIGGER bench_bump_access_epoch AFTER INSERT OR UPDATE OR DELETE
    ON studio.bench_workspace_tree FOR EACH ROW EXECUTE FUNCTION studio.bench_bump_access_epoch();
CREATE TRIGGER bench_bump_access_epoch AFTER INSERT OR UPDATE OR DELETE
    ON studio.sharing_rule_versions FOR EACH ROW EXECUTE FUNCTION studio.bench_bump_access_epoch();
"""
TRIGGERED_TABLES = (
    "studio.bench_effective_grants",
    "studio.object_defs",
    "studio.bench_team_members",
    "studio.bench_people",
    "studio.bench_workspace_tree",
    "studio.sharing_rule_versions",
)


def _definer_reach(action: str, variant: PolicyVariant) -> str:
    """The reach of an action a definer function enforces itself: it bypasses RLS."""
    return reach(action, variant)


def assign_share_functions(variant: PolicyVariant) -> list[str]:
    """STAND-INs for studio.assign_record and studio.share_record (ADR-0105 decision 3)."""
    assign = f"""
CREATE FUNCTION studio.assign_record(p_record_id uuid, p_owner_id uuid, p_workspace_id uuid)
    RETURNS TABLE (new_version integer, new_workspace_id uuid)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
    AS $$
DECLARE
    -- A variable, not the function: plpgsql binds it as a parameter, so the plan
    -- prunes to the tenant's partition instead of locking every one.
    t uuid := studio.acl_tenant();
BEGIN
    RETURN QUERY
    UPDATE studio.records r SET owner_kind = 'user', owner_id = p_owner_id,
           workspace_id = coalesce(p_workspace_id, r.workspace_id), version = r.version + 1,
           updated_by = studio.acl_user()
     WHERE r.tenant_id = t AND r.id = p_record_id AND r.deleted_at IS NULL
       AND r.id IN (SELECT x.id FROM studio.records x WHERE x.tenant_id = t
                     AND x.id = p_record_id AND {_definer_reach("assign", variant)})
    RETURNING r.version, r.workspace_id;
END $$"""
    share = f"""
CREATE FUNCTION studio.share_record(p_record_id uuid, p_principal_id uuid, p_access text,
                                    p_until timestamptz)
    RETURNS TABLE (new_version integer, new_workspace_id uuid)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
    AS $$
DECLARE
    t uuid := studio.acl_tenant();
BEGIN
    IF p_access NOT IN ('read', 'edit') THEN
        RAISE EXCEPTION 'share access must be read or edit' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH target AS (
        SELECT x.id FROM studio.records x WHERE x.tenant_id = t
           AND x.id = p_record_id AND x.deleted_at IS NULL AND {_definer_reach("share", variant)}
    ), shared AS (
        INSERT INTO studio.record_shares AS rs (tenant_id, record_id, principal_id, access,
                                                expires_at)
        SELECT t, target.id, p_principal_id, p_access, p_until FROM target
        ON CONFLICT (tenant_id, record_id, principal_id)
        DO UPDATE SET access = EXCLUDED.access, expires_at = EXCLUDED.expires_at
        RETURNING rs.record_id
    )
    UPDATE studio.records r SET
           read_grants = CASE WHEN p_principal_id = ANY (r.read_grants) THEN r.read_grants
                              ELSE r.read_grants || p_principal_id END,
           edit_grants = CASE WHEN p_access = 'edit' AND NOT p_principal_id = ANY (r.edit_grants)
                              THEN r.edit_grants || p_principal_id ELSE r.edit_grants END,
           grants_valid_until = CASE WHEN p_until IS NULL THEN r.grants_valid_until
                                     ELSE least(r.grants_valid_until, p_until) END,
           version = r.version + 1
      FROM shared WHERE r.tenant_id = t AND r.id = shared.record_id
    RETURNING r.version, r.workspace_id;
END $$"""
    return [assign, share]


def _key_axis_schema() -> list[str]:
    """K: the bigint key, the per-tenant numbers it is composed of, and what keeps it.

    A generated column cannot read another table, so the key is kept by a
    BEFORE trigger from the object's and the owning workspace's numbers, which
    are assigned per tenant on insert.
    """
    return [
        "ALTER TABLE studio.object_defs ADD COLUMN object_no integer",
        "ALTER TABLE platform.workspaces ADD COLUMN workspace_no integer",
        """
CREATE FUNCTION studio.bench_number_object() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog
    AS $$
BEGIN
    IF NEW.object_no IS NULL THEN
        NEW.object_no := coalesce((SELECT max(o.object_no) FROM studio.object_defs o
                                    WHERE o.tenant_id = NEW.tenant_id), 0) + 1;
    END IF;
    RETURN NEW;
END $$""",
        """
CREATE FUNCTION studio.bench_number_workspace() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog
    AS $$
BEGIN
    IF NEW.workspace_no IS NULL THEN
        NEW.workspace_no := coalesce((SELECT max(w.workspace_no) FROM platform.workspaces w
                                       WHERE w.tenant_id = NEW.tenant_id), 0) + 1;
    END IF;
    RETURN NEW;
END $$""",
        "CREATE TRIGGER bench_number_object BEFORE INSERT ON studio.object_defs"
        " FOR EACH ROW EXECUTE FUNCTION studio.bench_number_object()",
        "CREATE TRIGGER bench_number_workspace BEFORE INSERT ON platform.workspaces"
        " FOR EACH ROW EXECUTE FUNCTION studio.bench_number_workspace()",
        "ALTER TABLE studio.records DROP COLUMN access_key",
        "ALTER TABLE studio.records ADD COLUMN access_key bigint",
        """
CREATE FUNCTION studio.bench_access_key() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
    AS $$
BEGIN
    NEW.access_key := ((SELECT o.object_no FROM studio.object_defs o
                         WHERE o.tenant_id = NEW.tenant_id AND o.id = NEW.object_id)::bigint << 32)
                      | (SELECT w.workspace_no FROM platform.workspaces w
                          WHERE w.tenant_id = NEW.tenant_id AND w.id = NEW.workspace_id);
    RETURN NEW;
END $$""",
        "CREATE TRIGGER bench_access_key BEFORE INSERT OR UPDATE OF object_id, workspace_id"
        " ON studio.records FOR EACH ROW EXECUTE FUNCTION studio.bench_access_key()",
    ]


def schema(variant: PolicyVariant, modulus: int) -> list[str]:
    """Run after A1's DDL and before the seed: the replacement, in dependency order."""
    out = _drop_harness_policies(modulus)
    out += [
        "DROP FUNCTION studio.acl_objects(text, text), studio.acl_keys(text),"
        " studio.acl_owners(text, text), studio.acl_grant_keys(text),"
        " studio.acl_workspaces(text)",
        "DROP TABLE studio.principal_scopes",
    ]
    if variant.key == "bigint":
        out += _key_axis_schema()
    out += ledger_ddl(variant)
    out.append(SUPPORT_TABLES)
    out += acl_functions(variant)
    for table in ["studio.records", *partitions("studio.records", modulus)]:
        out += record_policies(table, table.split(".")[1], variant)
    out.append(compute_function(variant))
    out.append(ensure_function(variant))
    out += assign_share_functions(variant)
    out += [
        "REVOKE ALL ON FUNCTION studio.compute_principal_scope() FROM PUBLIC",
        "REVOKE ALL ON FUNCTION studio.ensure_principal_scope() FROM PUBLIC",
        "REVOKE ALL ON FUNCTION studio.assign_record(uuid, uuid, uuid) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION studio.share_record(uuid, uuid, text, timestamptz) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION studio.ensure_principal_scope() TO dw_app",
        "GRANT EXECUTE ON FUNCTION studio.assign_record(uuid, uuid, uuid) TO dw_app",
        "GRANT EXECUTE ON FUNCTION studio.share_record(uuid, uuid, text, timestamptz) TO dw_app",
    ]
    return out


def post_load(variant: PolicyVariant) -> list[str]:
    """After the seed: the triggers that mark a principal stale or bump the tenant's epoch."""
    del variant
    return [TRIGGERS]


# ------------------------------------------------------ the declared replacement --
REPLACED_TABLES = (
    "studio.principal_scopes",
    "studio.access_epochs",
    "studio.actor_boundaries",
    "studio.bench_effective_grants",
)
REPLACED_FUNCTIONS = (
    *ACL_FUNCTION_NAMES,
    "compute_principal_scope",
    "ensure_principal_scope",
    "assign_record",
    "share_record",
    "bench_mark_scope_stale",
    "bench_bump_access_epoch",
)
KEY_AXIS_FUNCTIONS = ("bench_number_object", "bench_number_workspace", "bench_access_key")


def declared(variant: PolicyVariant, modulus: int) -> set[tuple[str, ...]]:
    """Every catalog key this variant may differ from A1 in (ticket step 2).

    The RESTRICTIVE tenant policy is not here: every variant renders it from the
    harness's own TENANT expression, so a variant that loses the tenant clause
    differs from A1 where it may not.
    """
    out: set[tuple[str, ...]] = set()
    for table in REPLACED_TABLES:
        out.add(("table", table))
    for table in ["studio.records", *partitions("studio.records", modulus)]:
        for cmd in ("select", "insert", "update", "delete"):
            out.add(("policy", table, f"record_access_{table.split('.')[1]}_{cmd}"))
    for fn in REPLACED_FUNCTIONS:
        out.add(("function", fn))
    for table in TRIGGERED_TABLES:
        name = (
            "bench_mark_scope_stale"
            if table == "studio.bench_effective_grants"
            else ("bench_bump_access_epoch")
        )
        out.add(("trigger", table, name))
    if variant.key == "bigint":
        out |= {
            ("column", "studio.records", "access_key"),
            ("column", "studio.object_defs", "object_no"),
            ("column", "platform.workspaces", "workspace_no"),
            ("trigger", "studio.records", "bench_access_key"),
            ("trigger", "studio.object_defs", "bench_number_object"),
            ("trigger", "platform.workspaces", "bench_number_workspace"),
            *(("function", fn) for fn in KEY_AXIS_FUNCTIONS),
        }
    return out


def is_declared(key: tuple[str, ...], allowed: set[tuple[str, ...]]) -> bool:
    """A catalog key is declared when it, or the replaced table it belongs to, is."""
    if key in allowed:
        return True
    return len(key) >= 2 and ("table", key[1]) in allowed


# ------------------------------------------------------------- the door call --
def door_sql() -> str:
    """Runs after every scoped transaction's settings (`Endpoint.after_scope`).

    The boundary a runtime binds for its actor (ADR-0105 decision 6): the harness
    has one agent and one workflow writer, so the actor kind names it here.
    """
    return (
        "SELECT set_config('app.boundary_id', CASE current_setting('app.actor_kind', true)"
        f" WHEN 'agent' THEN '{AGENT_BOUNDARY}' WHEN 'workflow' THEN '{WRITER_BOUNDARY}'"
        " ELSE '' END, true), studio.ensure_principal_scope()"
    )


def own_filter(variant: PolicyVariant, placeholder: int) -> str:
    """The "Của tôi" list filter: a bound parameter, or the planner hint of axis H."""
    if variant.hint:
        return " AND owner_id = (SELECT studio.acl_user())"
    return f" AND owner_id = ${placeholder}"
