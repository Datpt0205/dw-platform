"""connections status rules and revocation for compromise

Revision ID: 388a31c46bdf
Revises: 20bb9a2210cf
Create Date: 2026-11-04 03:23:35.127169+00:00

connections-and-vault ticket 04 (spec R1.15, R5.6, R5.16, R5.19, R5.21; CV15,
CV21, CV28; ADR-0115 decision 2): what the shared connections of a workspace
need before a route writes one.

- `name`, the label the list shows (`btrim(name) <> ''`, at most 200
  characters); `dw_app` may UPDATE it (`PATCH`). NOT NULL at once: no command
  wrote a connection before this revision, and the backfill below names any
  row a test left behind after its connector.
- `platform.guard_connection_status()`, BEFORE INSERT OR UPDATE OF `status`:
  the one transition table for every writer, the migrator included. INSERT
  only `pending` or `active`; `pending -> active | disabled`; `active ->
  disabled | needs_reauth | revoked`; `needs_reauth -> active | disabled |
  revoked`; `disabled -> active | revoked`; `revoked` is final; an unchanged
  status always passes. `disabled -> active` only while the transaction set
  `app.connection_enable_approval` to an approved `connections.enable`
  request of the same company and the same connection, opened after the row's
  `disabled_at` (D11). Every refusal is 23514, the row unchanged.
- `disabled_at`, written by that trigger alone, at every move into
  `disabled`; `dw_app` holds no UPDATE of it and an INSERT naming it is
  refused.
- `compromised_at`, written by `platform.revoke_connection_secrets` alone (no
  `dw_app` UPDATE); `platform.guard_connection_compromised_at()` refuses an
  UPDATE that clears it or moves it back, and an INSERT naming it, so the mark
  outlives the material the purge lane deletes (R1.16, H-28).
- `platform.revoke_connection_secrets(uuid)`, SECURITY DEFINER on a fixed
  `search_path`, revoked from PUBLIC, executable by `dw_app`: the company is
  the transaction's `app.tenant_id`, never an argument. It locks the
  connection, stamps `revoked_at = now()` on every envelope of it not yet
  revoked (NULL or in the future, `replaced_at` untouched), then
  `compromised_at = now()`; a connection the company cannot see writes nothing
  and returns no row (R1.15).
- `uq_connections_account_live`: one row not `revoked` per (company,
  connector, lower(external account)), so a disabled connection comes back only
  through the two-person enable (R5.21). A NULL account never collides.
- `connections.read`, `connections.manage`, `connections.use` in the
  catalogue, workspace-depth, grantable by the tenant; no system role is given
  them here (`tenant_owner` holds every key by computation, ADR-0104 decision 2).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "388a31c46bdf"
down_revision = "20bb9a2210cf"
branch_labels = None
depends_on = None

_COLUMNS = (
    "ALTER TABLE platform.connections ADD COLUMN name text",
    "UPDATE platform.connections SET name = connector_key WHERE name IS NULL",
    "ALTER TABLE platform.connections ALTER COLUMN name SET NOT NULL",
    "ALTER TABLE platform.connections ADD CONSTRAINT ck_connections_name"
    " CHECK (btrim(name) <> '' AND char_length(name) <= 200)",
    "ALTER TABLE platform.connections ADD COLUMN disabled_at timestamp with time zone",
    "ALTER TABLE platform.connections ADD COLUMN compromised_at timestamp with time zone",
    # Not only `active`: a disabled row blocks a new one for the same account.
    "CREATE UNIQUE INDEX uq_connections_account_live ON platform.connections"
    " (tenant_id, connector_key, lower(external_account)) WHERE status <> 'revoked'",
)

# The constraint names each refusal carries, for the adapter's mapping by name.
STATUS_TRANSITION = "ck_connections_status_transition"
ENABLE_APPROVED = "ck_connections_enable_approved"
DISABLED_AT_TRIGGER_ONLY = "ck_connections_disabled_at_trigger_only"
COMPROMISED_AT_FORWARD = "ck_connections_compromised_at_forward"

_UUID = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

_FUNCTIONS = (
    f"""
    CREATE FUNCTION platform.guard_connection_status() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_approval text;
        v_approved boolean := false;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.status NOT IN ('pending', 'active') THEN
                RAISE EXCEPTION 'a connection starts pending or active, not %', NEW.status
                    USING ERRCODE = '23514', CONSTRAINT = '{STATUS_TRANSITION}';
            END IF;
            IF NEW.disabled_at IS NOT NULL THEN
                RAISE EXCEPTION 'disabled_at is written by the status trigger alone'
                    USING ERRCODE = '23514', CONSTRAINT = '{DISABLED_AT_TRIGGER_ONLY}';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.status = OLD.status THEN
            RETURN NEW;
        END IF;
        IF NOT (
            (OLD.status = 'pending' AND NEW.status IN ('active', 'disabled'))
            OR (OLD.status = 'active' AND NEW.status IN ('disabled', 'needs_reauth', 'revoked'))
            OR (OLD.status = 'needs_reauth' AND NEW.status IN ('active', 'disabled', 'revoked'))
            OR (OLD.status = 'disabled' AND NEW.status IN ('active', 'revoked'))
        ) THEN
            RAISE EXCEPTION 'a connection does not move from % to %', OLD.status, NEW.status
                USING ERRCODE = '23514', CONSTRAINT = '{STATUS_TRANSITION}';
        END IF;
        -- D11: enabling again takes the approved request of a second person,
        -- opened after the row last went disabled (R5.19).
        IF OLD.status = 'disabled' AND NEW.status = 'active' THEN
            v_approval := lower(
                NULLIF(current_setting('app.connection_enable_approval', true), '')
            );
            -- Nested, not one OR: SQL does not promise to skip the cast of a
            -- setting that is not a uuid.
            IF v_approval IS NOT NULL AND v_approval ~ '{_UUID}' THEN
                v_approved := EXISTS (
                    SELECT 1 FROM platform.approval_requests r
                    WHERE r.id = v_approval::uuid
                      AND r.tenant_id = NEW.tenant_id
                      AND r.approval_type = 'connections.enable'
                      AND r.status = 'approved'
                      AND r.payload ->> 'connection_id' = NEW.id::text
                      AND r.created_at > OLD.disabled_at
                );
            END IF;
            IF NOT v_approved THEN
                RAISE EXCEPTION 'a disabled connection is enabled only by its approved request'
                    USING ERRCODE = '23514', CONSTRAINT = '{ENABLE_APPROVED}';
            END IF;
        END IF;
        IF NEW.status = 'disabled' THEN
            NEW.disabled_at := now();
        END IF;
        RETURN NEW;
    END
    $$
    """,
    f"""
    CREATE FUNCTION platform.guard_connection_compromised_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.compromised_at IS NOT NULL THEN
                RAISE EXCEPTION 'compromised_at is written by revoke_connection_secrets alone'
                    USING ERRCODE = '23514', CONSTRAINT = '{COMPROMISED_AT_FORWARD}';
            END IF;
            RETURN NEW;
        END IF;
        IF OLD.compromised_at IS NOT NULL
           AND (NEW.compromised_at IS NULL OR NEW.compromised_at < OLD.compromised_at) THEN
            RAISE EXCEPTION 'a revocation for compromise is neither cleared nor moved back'
                USING ERRCODE = '23514', CONSTRAINT = '{COMPROMISED_AT_FORWARD}';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R1.15 (CV28): one transaction, the connection locked first so a second
    # revocation waits; the company is the caller's, never the row's.
    """
    CREATE FUNCTION platform.revoke_connection_secrets(p_connection_id uuid)
    RETURNS TABLE (compromised_on timestamp with time zone, versions integer)
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        v_found uuid;
        v_versions integer;
    BEGIN
        IF v_tenant IS NULL THEN
            RAISE EXCEPTION 'app.tenant_id is not set' USING ERRCODE = '42501';
        END IF;
        SELECT c.id INTO v_found FROM platform.connections c
        WHERE c.tenant_id = v_tenant AND c.id = p_connection_id
        FOR UPDATE;
        IF v_found IS NULL THEN
            RETURN;
        END IF;
        UPDATE platform.secret_envelopes e SET revoked_at = now()
        WHERE e.tenant_id = v_tenant AND e.connection_id = p_connection_id
          AND (e.revoked_at IS NULL OR e.revoked_at > now());
        GET DIAGNOSTICS v_versions = ROW_COUNT;
        UPDATE platform.connections c SET compromised_at = now()
        WHERE c.tenant_id = v_tenant AND c.id = p_connection_id;
        RETURN QUERY SELECT now(), v_versions;
    END
    $$
    """,
)

REVOKE_DOOR = "platform.revoke_connection_secrets(uuid)"
_INTERNAL = (
    "platform.guard_connection_status()",
    "platform.guard_connection_compromised_at()",
)

_TRIGGERS = (
    "CREATE TRIGGER guard_connection_status"
    " BEFORE INSERT OR UPDATE OF status ON platform.connections"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_connection_status()",
    "CREATE TRIGGER guard_connection_compromised_at"
    " BEFORE INSERT OR UPDATE OF compromised_at ON platform.connections"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_connection_compromised_at()",
)

# `name` is renamed through `PATCH`; `disabled_at` and `compromised_at` have
# no `dw_app` UPDATE (ticket 02 granted UPDATE by named column only).
_APP_GRANTS = (
    "GRANT UPDATE (name) ON platform.connections TO dw_app;",
    f"GRANT EXECUTE ON FUNCTION {REVOKE_DOOR} TO dw_app;",
)

# key, Vietnamese label, risk.
PERMISSIONS = (
    ("connections.read", "Xem kết nối của workspace", "standard"),
    ("connections.manage", "Quản trị kết nối của workspace", "elevated"),
    ("connections.use", "Dùng kết nối của workspace trong lượt chạy", "standard"),
)


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
    for statement in _COLUMNS:
        op.execute(statement)
    for statement in _FUNCTIONS:
        op.execute(statement)
    # A new function is executable by PUBLIC: every role with USAGE on
    # `platform` (`dw_provisioner`) would reach the door (CV2).
    for function in (*_INTERNAL, REVOKE_DOOR):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))
    for key, label, risk in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'connections', :l, 'workspace', :r, 'active', NULL,"
                " 'dw_platform', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label, r=risk)
        )


def downgrade() -> None:
    for key, _label, _risk in PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
            ).bindparams(k=key)
        )
        op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=key))
    op.execute("DROP TRIGGER IF EXISTS guard_connection_compromised_at ON platform.connections")
    op.execute("DROP TRIGGER IF EXISTS guard_connection_status ON platform.connections")
    op.execute(f"DROP FUNCTION IF EXISTS {REVOKE_DOOR}")
    for function in _INTERNAL:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP INDEX IF EXISTS platform.uq_connections_account_live")
    for column in ("compromised_at", "disabled_at", "name"):
        op.execute(f"ALTER TABLE platform.connections DROP COLUMN IF EXISTS {column}")
