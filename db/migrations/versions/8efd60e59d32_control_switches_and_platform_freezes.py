"""control switches and platform freezes

Revision ID: 8efd60e59d32
Revises: 16357d3dbff8
Create Date: 2026-11-04 10:40:10.686166+00:00

agent-lifecycle ticket 01 (R7.1-R7.6, R7.10, R7.11, R10.1; AL11, AL12, AL16,
AL18; ADR-0120 decisions 5-7, amended 2026-11-04). A freeze and a kill are
switches every door of the runtime asks about, never stages:

- `platform.control_switches`: one row per switch a company or an operator
  sets. Tenant-wide (a switch is the whole company's, or a component's whose
  workspace is `owning_workspace_id`, which RLS never reads). A freeze is of
  the company and a kill of a component, `ck_control_switches_scope_action`;
  one open switch per target and origin, `uq_control_switches_open`, so a
  company's freeze and an operator's freeze of the same company are both open
  and each side lifts only its own row. `lift_approval_id` is a composite key
  to `uq_approval_requests_tenant_id_id`, added here (the earliest ticket that
  needs it; ticket 03 reuses it), since a foreign key check does not pass
  through RLS. Its index leads with `tenant_id`, so it is the tenant key's
  index too: the partial open index does not cover a lifted row.
  `owning_workspace_id` is held by the RESTRICT composite key to
  `platform.workspaces`, as every tenant-wide table's is.
- `platform.guard_control_switch()`: a row is inserted open; one with origin
  `platform` only by `dw_provisioner`; a row is lifted once and nothing else
  changes; a `platform` row is lifted by `dw_provisioner` alone, without an
  approval; a `tenant` row only with `lift_approval_id` naming an approved
  `studio.lifecycle.unfreeze` (a freeze) or `studio.lifecycle.revive` (a kill,
  ticket 05) request whose payload names this row's id and whose approving
  decision is not its requester's, so `dw_app` cannot lift one with a direct
  UPDATE that skips the second person (R7.5, D11); a DELETE only while the
  company is `offboarding` (R10.1). Every refusal is SQLSTATE 23514.
- `pg_notify('dw_control_switch', ...)` on every change: `{"tenant_id", "id"}`
  for a switch, so a listener drops that company's snapshot alone, and
  `{"platform": true}` for a platform freeze, which drops every snapshot.
- `platform.platform_freezes`: the identity plane, no `tenant_id`; at most one
  open row; written by `dw_provisioner` (audited in
  `platform.provisioning_audit`), read by `dw_app`.
- `uq_approval_requests_control_lift_pending`: one pending lift request per
  switch, as `uq_approval_requests_dw_autonomy_raise_pending` does, so two
  concurrent requests give one approval and one 409 `lift_pending`.
- The permission `studio.lifecycle.freeze` (tenant depth, standard risk), and
  the `org_admin` template carries it for a company cloned from it later; a
  role already cloned is not touched (tenant-rbac R3.2).

`dw_app` holds SELECT, INSERT, UPDATE of the lift columns and DELETE (the
offboarding lane's, which the trigger allows only there) on the switches and
SELECT on the platform freezes; `dw_agent_ro` holds neither.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8efd60e59d32"
down_revision = "16357d3dbff8"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_REASON_CODES = "('incident', 'maintenance', 'abuse', 'test', 'other')"
_NIL = "'00000000-0000-0000-0000-000000000000'::uuid"

# What `dw_provisioner` holds here, beside the tuples of the same name in
# 0fdd32a39d87, 349080a62e41 and b5677d345bc1; mirrored by
# scripts/create_provisioner_role.py, all held to the catalog by
# test_privileges.py. It sets and lifts the operator's switches only.
PROVISIONER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("platform.control_switches", "SELECT, INSERT", ("lifted_at", "lifted_by", "lift_reason")),
    ("platform.platform_freezes", "SELECT, INSERT", ("lifted_at", "lifted_by")),
)

_TABLES = (
    # The target of every composite key that names an approval of a tenant-wide
    # row (ADR-0120 decision 1): the existing unique carries `workspace_id`.
    "ALTER TABLE platform.approval_requests"
    " ADD CONSTRAINT uq_approval_requests_tenant_id_id UNIQUE (tenant_id, id)",
    f"""
    CREATE TABLE platform.control_switches (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        scope_type text NOT NULL,
        owning_workspace_id uuid,
        target_id uuid,
        action text NOT NULL,
        origin text NOT NULL,
        reason_code text NOT NULL,
        reason text NOT NULL,
        set_by uuid NOT NULL,
        set_at timestamp with time zone DEFAULT now() NOT NULL,
        lift_approval_id uuid,
        lifted_by uuid,
        lifted_at timestamp with time zone,
        lift_reason text,
        CONSTRAINT pk_control_switches PRIMARY KEY (id),
        CONSTRAINT fk_control_switches_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE CASCADE,
        CONSTRAINT fk_control_switches_lift_approval_id_approval_requests
            FOREIGN KEY (lift_approval_id, tenant_id)
            REFERENCES platform.approval_requests (id, tenant_id) ON DELETE RESTRICT,
        -- A component's workspace, never deleted with a switch on it open or not.
        CONSTRAINT fk_control_switches_owning_workspace_id_workspaces
            FOREIGN KEY (owning_workspace_id, tenant_id)
            REFERENCES platform.workspaces (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT ck_control_switches_scope_type
            CHECK (scope_type IN ('tenant', 'agent', 'workflow')),
        CONSTRAINT ck_control_switches_action CHECK (action IN ('freeze', 'kill')),
        CONSTRAINT ck_control_switches_origin CHECK (origin IN ('tenant', 'platform')),
        CONSTRAINT ck_control_switches_reason_code CHECK (reason_code IN {_REASON_CODES}),
        CONSTRAINT ck_control_switches_reason CHECK (char_length(reason) BETWEEN 1 AND 500),
        CONSTRAINT ck_control_switches_lift_reason
            CHECK (lift_reason IS NULL OR char_length(lift_reason) BETWEEN 1 AND 500),
        -- A freeze is of the whole company, a kill of one component.
        CONSTRAINT ck_control_switches_scope_action
            CHECK ((scope_type = 'tenant') = (action = 'freeze')),
        CONSTRAINT ck_control_switches_target
            CHECK ((target_id IS NULL) = (scope_type = 'tenant')),
        CONSTRAINT ck_control_switches_owning_workspace
            CHECK ((owning_workspace_id IS NULL) = (scope_type = 'tenant')),
        CONSTRAINT ck_control_switches_lifted CHECK ((lifted_at IS NULL) = (lifted_by IS NULL))
    )
    """,
    # The composite key's index, and the tenant key's: both lead with tenant_id.
    "CREATE INDEX ix_control_switches_tenant_id_lift_approval_id"
    " ON platform.control_switches (tenant_id, lift_approval_id)",
    "CREATE INDEX ix_control_switches_tenant_id_owning_workspace_id"
    " ON platform.control_switches (tenant_id, owning_workspace_id)",
    # One open switch per target and origin (ADR-0120 decision 5, amended 2026-11-04).
    "CREATE UNIQUE INDEX uq_control_switches_open ON platform.control_switches"
    f" (tenant_id, scope_type, origin, coalesce(target_id, {_NIL})) WHERE lifted_at IS NULL",
    f"""
    CREATE TABLE platform.platform_freezes (
        id uuid NOT NULL,
        reason_code text NOT NULL,
        reason text NOT NULL,
        set_by uuid NOT NULL,
        set_at timestamp with time zone DEFAULT now() NOT NULL,
        lifted_by uuid,
        lifted_at timestamp with time zone,
        CONSTRAINT pk_platform_freezes PRIMARY KEY (id),
        CONSTRAINT ck_platform_freezes_reason_code CHECK (reason_code IN {_REASON_CODES}),
        CONSTRAINT ck_platform_freezes_reason CHECK (char_length(reason) BETWEEN 1 AND 500),
        CONSTRAINT ck_platform_freezes_lifted CHECK ((lifted_at IS NULL) = (lifted_by IS NULL))
    )
    """,
    "CREATE UNIQUE INDEX uq_platform_freezes_open ON platform.platform_freezes ((true))"
    " WHERE lifted_at IS NULL",
    # R7.10: one pending lift per switch; the repository reads this name as 409.
    "CREATE UNIQUE INDEX uq_approval_requests_control_lift_pending"
    " ON platform.approval_requests (tenant_id, (payload->>'switch_id'))"
    " WHERE approval_type IN ('studio.lifecycle.unfreeze', 'studio.lifecycle.revive')"
    " AND status = 'pending'",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
# Tenant-only: a switch is the company's, or a component's of any workspace.
_RLS = (
    "ALTER TABLE platform.control_switches ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.control_switches FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_control_switches ON platform.control_switches"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# Not a definer: `current_user` is the role that writes, and the approval is
# read under the writer's RLS, so only its own company's request can lift it.
# A company row missing on DELETE is the cascade from the company row itself.
_GUARD = """
    CREATE FUNCTION platform.guard_control_switch() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_status text;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            SELECT t.status INTO v_status FROM platform.tenants t WHERE t.id = OLD.tenant_id;
            IF FOUND AND v_status IS DISTINCT FROM 'offboarding' THEN
                RAISE EXCEPTION 'a control switch is deleted only by the offboarding lane'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_control_switches_delete';
            END IF;
            RETURN OLD;
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.lifted_at IS NOT NULL OR NEW.lifted_by IS NOT NULL
               OR NEW.lift_reason IS NOT NULL OR NEW.lift_approval_id IS NOT NULL THEN
                RAISE EXCEPTION 'a control switch is inserted open'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_control_switches_insert_open';
            END IF;
            IF NEW.origin = 'platform' AND current_user <> 'dw_provisioner' THEN
                RAISE EXCEPTION 'only the provisioner sets an operator''s switch'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_control_switches_platform_origin';
            END IF;
            RETURN NEW;
        END IF;
        IF OLD.lifted_at IS NOT NULL OR NEW.lifted_at IS NULL
           OR (NEW.id, NEW.tenant_id, NEW.scope_type, NEW.owning_workspace_id, NEW.target_id,
               NEW.action, NEW.origin, NEW.reason_code, NEW.reason, NEW.set_by, NEW.set_at)
              IS DISTINCT FROM
              (OLD.id, OLD.tenant_id, OLD.scope_type, OLD.owning_workspace_id, OLD.target_id,
               OLD.action, OLD.origin, OLD.reason_code, OLD.reason, OLD.set_by, OLD.set_at) THEN
            RAISE EXCEPTION 'a control switch is lifted once, and nothing else changes'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_control_switches_lift_once';
        END IF;
        IF OLD.origin = 'platform' THEN
            IF current_user <> 'dw_provisioner' OR NEW.lift_approval_id IS NOT NULL THEN
                RAISE EXCEPTION 'an operator''s switch is lifted by the provisioner alone'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_control_switches_platform_lift';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.lift_approval_id IS NULL OR NOT EXISTS (
            SELECT 1
            FROM platform.approval_requests a
            JOIN platform.approval_decisions d
              ON d.request_id = a.id AND d.tenant_id = a.tenant_id
            WHERE a.tenant_id = NEW.tenant_id
              AND a.id = NEW.lift_approval_id
              AND a.status = 'approved'
              AND a.approval_type = CASE NEW.action
                                       WHEN 'freeze' THEN 'studio.lifecycle.unfreeze'
                                       ELSE 'studio.lifecycle.revive' END
              AND a.payload->>'switch_id' = NEW.id::text
              AND d.outcome = 'approved'
              AND d.decided_by <> a.requested_by
        ) THEN
            RAISE EXCEPTION 'a company''s switch is lifted only by its approved lift request'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_control_switches_lift_approval';
        END IF;
        RETURN NEW;
    END
    $$
    """

# R7.1: identifiers only, after the write; Postgres holds a NOTIFY until the
# transaction commits and drops it if it does not.
_NOTIFY_SWITCH = """
    CREATE FUNCTION platform.notify_control_switch() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_row platform.control_switches%ROWTYPE;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            v_row := OLD;
        ELSE
            v_row := NEW;
        END IF;
        PERFORM pg_notify(
            'dw_control_switch',
            json_build_object('tenant_id', v_row.tenant_id, 'id', v_row.id)::text
        );
        RETURN NULL;
    END
    $$
    """

_NOTIFY_PLATFORM = """
    CREATE FUNCTION platform.notify_platform_freeze() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        PERFORM pg_notify('dw_control_switch', '{"platform": true}');
        RETURN NULL;
    END
    $$
    """

_FUNCTIONS = (
    "platform.guard_control_switch()",
    "platform.notify_control_switch()",
    "platform.notify_platform_freeze()",
)

_TRIGGERS = (
    "CREATE TRIGGER guard_control_switch BEFORE INSERT OR UPDATE OR DELETE"
    " ON platform.control_switches FOR EACH ROW EXECUTE FUNCTION platform.guard_control_switch()",
    "CREATE TRIGGER notify_control_switch AFTER INSERT OR UPDATE OR DELETE"
    " ON platform.control_switches FOR EACH ROW EXECUTE FUNCTION platform.notify_control_switch()",
    "CREATE TRIGGER notify_platform_freeze AFTER INSERT OR UPDATE"
    " ON platform.platform_freezes FOR EACH ROW EXECUTE FUNCTION platform.notify_platform_freeze()",
)

# `ALTER DEFAULT PRIVILEGES` (0001_platform_grants.sql) hands `dw_app` every
# verb and `dw_agent_ro` SELECT on a new platform table; these hold exactly
# what the code runs.
_GRANTS = (
    ("dw_app", "REVOKE ALL ON platform.control_switches FROM dw_app;"),
    ("dw_app", "GRANT SELECT, INSERT, DELETE ON platform.control_switches TO dw_app;"),
    (
        "dw_app",
        "GRANT UPDATE (lifted_by, lifted_at, lift_reason, lift_approval_id)"
        " ON platform.control_switches TO dw_app;",
    ),
    ("dw_app", "REVOKE ALL ON platform.platform_freezes FROM dw_app;"),
    ("dw_app", "GRANT SELECT ON platform.platform_freezes TO dw_app;"),
    ("dw_agent_ro", "REVOKE ALL ON platform.control_switches FROM dw_agent_ro;"),
    ("dw_agent_ro", "REVOKE ALL ON platform.platform_freezes FROM dw_agent_ro;"),
    ("dw_provisioner", "GRANT SELECT, INSERT ON platform.control_switches TO dw_provisioner;"),
    (
        "dw_provisioner",
        "GRANT UPDATE (lifted_at, lifted_by, lift_reason)"
        " ON platform.control_switches TO dw_provisioner;",
    ),
    ("dw_provisioner", "GRANT SELECT, INSERT ON platform.platform_freezes TO dw_provisioner;"),
    (
        "dw_provisioner",
        "GRANT UPDATE (lifted_at, lifted_by) ON platform.platform_freezes TO dw_provisioner;",
    ),
)

FREEZE = "studio.lifecycle.freeze"


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
    for statement in _TABLES:
        op.execute(statement)
    for statement in _RLS:
        op.execute(statement)
    for function in (_GUARD, _NOTIFY_SWITCH, _NOTIFY_PLATFORM):
        op.execute(function)
    # Called by their triggers and by no role.
    for signature in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for role, statement in _GRANTS:
        op.execute(_for_role(role, statement))
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    op.execute(
        sa.text(
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'studio', :l, 'tenant', 'standard', 'active', NULL,"
            " 'dw_platform', true)"
            " ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=FREEZE, l="Đóng băng công ty")
    )
    # The template a company cloned later starts from; cloned roles keep theirs.
    op.execute(
        sa.text(
            "UPDATE platform.roles SET scopes = scopes || jsonb_build_array(CAST(:k AS text))"
            " WHERE key = 'org_admin' AND NOT scopes @> jsonb_build_array(CAST(:k AS text))"
        ).bindparams(k=FREEZE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE platform.roles SET scopes = scopes - :k WHERE key = 'org_admin'"
        ).bindparams(k=FREEZE)
    )
    op.execute(
        sa.text(
            "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
        ).bindparams(k=FREEZE)
    )
    op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=FREEZE))
    op.execute("DROP INDEX platform.uq_approval_requests_control_lift_pending")
    op.execute("DROP TABLE platform.platform_freezes")
    op.execute("DROP TABLE platform.control_switches")
    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(
        "ALTER TABLE platform.approval_requests DROP CONSTRAINT uq_approval_requests_tenant_id_id"
    )
