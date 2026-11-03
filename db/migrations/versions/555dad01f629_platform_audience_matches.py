"""platform audience matches

Revision ID: 555dad01f629
Revises: b5677d345bc1
Create Date: 2026-11-02 09:46:10.116868+00:00

org-and-principals ticket 04 (R8.3, R8.4; OP13; ADR-0102 decision 7): one
function answers whether a person is in a `dw.audience/v1` document's audience,
per call, never materialised. No table, no cached result.

`platform.audience_matches(p_tenant_id, p_user_id, p_audience)` is true when
and only when the person is an `active` member of the company and one group of
`any_of` has a non-empty `all_of` whose every condition is a
`workspace_subtree` naming a workspace where the person has a membership (the
W1 tree is flat, so a workspace's subtree is the workspace itself; W2 moves the
condition onto `platform.workspace_subtree` when the tree arrives).

It closes when anything is wrong and never raises: another `schema`, an
`any_of` or `all_of` that is not an array, an empty group, an unknown kind of
condition or a value that is not a uuid (tested by pattern before the cast,
inside CASE, which is what orders evaluation in SQL) make that group false, so
a stored document that went bad hides an agent instead of breaking a list.

Both tables are filtered by `p_tenant_id` in the statement, and the answer is
false when `p_tenant_id` is not the transaction's `app.tenant_id` (unset
included): `tenant_members_self_select` and `memberships_self_select` show a
connection whose `app.principal_id` is set that person's rows in every tenant,
so RLS alone would let tenant A's transaction match B's audience.

SECURITY INVOKER, so RLS still applies to the caller; `SET search_path` keeps a
caller's path out of name resolution (and keeps the planner from inlining it,
which the call sites accept: ticket 04 M6). EXECUTE is revoked from PUBLIC and
granted to `dw_app` only.
"""

from __future__ import annotations

from alembic import op

revision = "555dad01f629"
down_revision = "b5677d345bc1"
branch_labels = None
depends_on = None

SIGNATURE = "platform.audience_matches(uuid, uuid, jsonb)"

_UUID = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

_FUNCTION = f"""
CREATE FUNCTION platform.audience_matches(p_tenant_id uuid, p_user_id uuid, p_audience jsonb)
RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT COALESCE(
        NOT (p_tenant_id IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        AND EXISTS (
            SELECT 1 FROM platform.tenant_members tm
            WHERE tm.tenant_id = p_tenant_id
              AND tm.user_id = p_user_id
              AND tm.status = 'active'
        )
        -- Each WHEN is tested in order, so no array function sees a non-array,
        -- and no cast sees a value that is not a uuid.
        AND CASE
            WHEN jsonb_typeof(p_audience) IS DISTINCT FROM 'object' THEN false
            WHEN p_audience -> 'schema' IS DISTINCT FROM to_jsonb('dw.audience/v1'::text) THEN false
            WHEN jsonb_typeof(p_audience -> 'any_of') IS DISTINCT FROM 'array' THEN false
            ELSE EXISTS (
                SELECT 1
                FROM jsonb_array_elements(p_audience -> 'any_of') AS g(grp)
                WHERE CASE
                    WHEN jsonb_typeof(g.grp) <> 'object' THEN false
                    WHEN jsonb_typeof(g.grp -> 'all_of') IS DISTINCT FROM 'array' THEN false
                    -- An empty group would be true for everyone.
                    WHEN jsonb_array_length(g.grp -> 'all_of') = 0 THEN false
                    ELSE NOT EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(g.grp -> 'all_of') AS c(cond)
                        WHERE NOT CASE
                            WHEN jsonb_typeof(c.cond) <> 'object' THEN false
                            WHEN (SELECT count(*) FROM jsonb_object_keys(c.cond)) <> 1 THEN false
                            WHEN jsonb_typeof(c.cond -> 'workspace_subtree')
                                IS DISTINCT FROM 'string' THEN false
                            WHEN (c.cond ->> 'workspace_subtree') !~ '{_UUID}' THEN false
                            ELSE EXISTS (
                                SELECT 1 FROM platform.memberships m
                                WHERE m.tenant_id = p_tenant_id
                                  AND m.user_id = p_user_id
                                  AND m.workspace_id = (c.cond ->> 'workspace_subtree')::uuid
                            )
                        END
                    )
                END
            )
        END,
        false
    )
$$
"""


def _for_role(role: str, statement: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                {statement}
            END IF;
        END
        $$
        """


def upgrade() -> None:
    op.execute(_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO dw_app;"))


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
