"""connections and secret envelopes

Revision ID: 70d8a4564454
Revises: 557e6907195e
Create Date: 2026-11-03 05:25:26.228257+00:00

connections-and-vault ticket 02 (spec R1.1, R1.3-R1.10, R1.14; CV1-CV3, CV23,
CV24; ADR-0115 decision 1). Every tenant secret is an AES-256-GCM envelope that
only the credential broker opens, behind a one-way database door.

- `platform.connections`: the columns of the spec but `compromised_at`, `name`,
  `disabled_at` and `uq_connections_account_live`, which ticket 04 adds with
  their readers. `uq_connections_tenant_id_id` is the target of the envelopes'
  composite key. The owning workspace never changes
  (`platform.guard_connection_owning_workspace()`, R1.7): the AAD of every
  envelope of the connection binds it. Tenant-wide on purpose: a connection is
  used across the workspaces of its company (D1). `dw_app` holds SELECT, INSERT
  and DELETE on the table, so the offboarding catalog sees it, and UPDATE of six
  named columns only, so a column a later ticket adds has none until a
  migration grants it.
- `platform.secret_envelopes`: one row per (subject, field, secret version);
  a subject is a nullable column with a composite key `(tenant_id, <subject>_id)`
  to its table, `ON DELETE CASCADE`, exactly one per row (`num_nonnulls`); a
  later subject adds its column, its key and its UNIQUE, and widens the CHECK
  (ADR-0115 decision 1). No AAD hint column: the AAD is built from the caller's
  tenant, the subject's owning workspace, the subject, `field` and
  `secret_version`. `dw_app` holds nothing on it (R1.3).
- The door, four SECURITY DEFINER functions narrowing by `app.tenant_id` and
  taking no tenant argument, each on a fixed `search_path`, revoked from PUBLIC
  and executable by `dw_app` alone (CV2): `platform.put_secret` writes a new
  version and, in the same statement, stamps every earlier version whose
  `revoked_at` is NULL with `replaced_at = now()` and `revoked_at = now()`, or
  `now() + 24 hours` for a `signing_secret` (R1.9, V4.20);
  `platform.open_secret` returns the latest version, or the one named, only
  while it is not revoked (R1.10, R1.14: closed while missing, never falling
  back to an older version); `platform.secret_status` returns the versions'
  dates, never a value; `platform.delete_secret` removes every version of a
  field. The subject column is found from the catalog
  (`platform.secret_subject_column`), so a later subject changes none of them.
"""

from __future__ import annotations

from alembic import op

revision = "70d8a4564454"
down_revision = "557e6907195e"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_KIB_64 = 65536

_TABLES = (
    """
    CREATE TABLE platform.connections (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        owning_workspace_id uuid NOT NULL,
        connector_key text NOT NULL,
        connector_major integer NOT NULL,
        share_scope text NOT NULL,
        external_account text,
        status text NOT NULL,
        scopes text[] DEFAULT '{}' NOT NULL,
        last_used_at timestamp with time zone,
        created_by uuid,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_connections PRIMARY KEY (id),
        CONSTRAINT uq_connections_tenant_id_id UNIQUE (tenant_id, id),
        CONSTRAINT fk_connections_owning_workspace_id_workspaces
            FOREIGN KEY (owning_workspace_id, tenant_id)
            REFERENCES platform.workspaces (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT fk_connections_created_by_users
            FOREIGN KEY (created_by) REFERENCES platform.users (id) ON DELETE SET NULL,
        CONSTRAINT ck_connections_connector_major CHECK (connector_major >= 0),
        CONSTRAINT ck_connections_share_scope
            CHECK (share_scope IN ('owner', 'workspace', 'workspace_subtree')),
        CONSTRAINT ck_connections_status
            CHECK (status IN ('pending', 'active', 'needs_reauth', 'disabled', 'revoked'))
    )
    """,
    "CREATE INDEX ix_connections_tenant_id_owning_workspace_id"
    " ON platform.connections (tenant_id, owning_workspace_id)",
    "CREATE INDEX ix_connections_created_by ON platform.connections (created_by)",
    # The order ticket 04's list pages in, led by the column RLS supplies.
    "CREATE INDEX ix_connections_tenant_id_created_at_id"
    " ON platform.connections (tenant_id, created_at DESC, id DESC)",
    f"""
    CREATE TABLE platform.secret_envelopes (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        connection_id uuid,
        field text NOT NULL,
        secret_version integer NOT NULL,
        alg text NOT NULL,
        nonce bytea NOT NULL,
        kek_ref text NOT NULL,
        kek_version integer NOT NULL,
        wrapped_data_key bytea NOT NULL,
        ciphertext bytea NOT NULL,
        revoked_at timestamp with time zone,
        replaced_at timestamp with time zone,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_secret_envelopes PRIMARY KEY (id),
        -- Led by the two columns of the composite key: also its index, and the
        -- index of the key to the tenant. Named `..._field_version`, not after
        -- every column: the convention's 64 characters would be truncated to
        -- Postgres's 63 and match no lookup by name (the adapter's conflict).
        -- A later subject's UNIQUE follows suit (`inbound_endpoint_id`: 63).
        CONSTRAINT uq_secret_envelopes_tenant_id_connection_id_field_version
            UNIQUE (tenant_id, connection_id, field, secret_version),
        CONSTRAINT fk_secret_envelopes_tenant_id_tenants
            FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id) ON DELETE CASCADE,
        -- Composite: a foreign key check does not pass through RLS (R1.8).
        CONSTRAINT fk_secret_envelopes_connection_id_connections
            FOREIGN KEY (connection_id, tenant_id)
            REFERENCES platform.connections (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT ck_secret_envelopes_subject CHECK (num_nonnulls(connection_id) = 1),
        CONSTRAINT ck_secret_envelopes_field CHECK (field ~ '^[a-z][a-z0-9_]{{0,62}}$'),
        CONSTRAINT ck_secret_envelopes_secret_version CHECK (secret_version >= 1),
        CONSTRAINT ck_secret_envelopes_alg CHECK (alg = 'aes-256-gcm'),
        CONSTRAINT ck_secret_envelopes_nonce CHECK (octet_length(nonce) = 12),
        CONSTRAINT ck_secret_envelopes_kek_version CHECK (kek_version >= 1),
        CONSTRAINT ck_secret_envelopes_ciphertext CHECK (octet_length(ciphertext) <= {_KIB_64}),
        -- Only a rotation stamps `replaced_at`, and always with `revoked_at`.
        CONSTRAINT ck_secret_envelopes_replaced_revoked
            CHECK (replaced_at IS NULL OR revoked_at IS NOT NULL)
    )
    """,
)

_RLS = (
    "ALTER TABLE platform.connections ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.connections FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_connections ON platform.connections"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE platform.secret_envelopes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.secret_envelopes FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_secret_envelopes ON platform.secret_envelopes"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# The tenant every door function narrows by, never an argument.
_CALLER_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_FUNCTIONS = (
    # R1.7 (CV1): the AAD of every envelope binds the owning workspace.
    """
    CREATE FUNCTION platform.guard_connection_owning_workspace() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.owning_workspace_id IS DISTINCT FROM OLD.owning_workspace_id THEN
            RAISE EXCEPTION 'a connection''s owning workspace does not change'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_connections_owning_workspace_fixed';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # A subject is a column of `platform.secret_envelopes` holding a composite
    # key `(tenant_id, <kind>_id)` to its table (ADR-0115 decision 1): read from
    # the catalog, so a later subject changes no door function, and a kind that
    # is not one is refused before any SQL is built from it.
    """
    CREATE FUNCTION platform.secret_subject_column(p_subject_kind text) RETURNS text
    LANGUAGE plpgsql STABLE
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_column text := p_subject_kind || '_id';
    BEGIN
        IF p_subject_kind IS NULL OR NOT EXISTS (
            SELECT 1
            FROM pg_constraint k
            JOIN pg_attribute s ON s.attrelid = k.conrelid AND s.attname = v_column
            JOIN pg_attribute t ON t.attrelid = k.conrelid AND t.attname = 'tenant_id'
            WHERE k.conrelid = 'platform.secret_envelopes'::regclass
              AND k.contype = 'f'
              AND cardinality(k.conkey) = 2
              AND k.conkey @> ARRAY[s.attnum, t.attnum]
        ) THEN
            RAISE EXCEPTION 'not a secret subject: %', p_subject_kind USING ERRCODE = '22023';
        END IF;
        RETURN v_column;
    END
    $$
    """,
    # R1.1, R1.9 (CV24): a new value is a new row; every earlier version not
    # yet revoked is replaced in the same statement, a signing secret after a
    # 24-hour overlap, and a `revoked_at` already set is never moved.
    f"""
    CREATE FUNCTION platform.put_secret(
        p_subject_kind text,
        p_subject_id uuid,
        p_field text,
        p_secret_version integer,
        p_alg text,
        p_nonce bytea,
        p_kek_ref text,
        p_kek_version integer,
        p_wrapped_data_key bytea,
        p_ciphertext bytea
    ) RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid := {_CALLER_TENANT};
        v_column text := platform.secret_subject_column(p_subject_kind);
    BEGIN
        IF v_tenant IS NULL THEN
            RAISE EXCEPTION 'app.tenant_id is not set' USING ERRCODE = '42501';
        END IF;
        EXECUTE format(
            'UPDATE platform.secret_envelopes'
            ' SET replaced_at = now(),'
            '     revoked_at = CASE WHEN field = ''signing_secret'''
            '                       THEN now() + interval ''24 hours'' ELSE now() END'
            ' WHERE tenant_id = $1 AND %I = $2 AND field = $3 AND revoked_at IS NULL',
            v_column
        ) USING v_tenant, p_subject_id, p_field;
        EXECUTE format(
            'INSERT INTO platform.secret_envelopes'
            ' (id, tenant_id, %I, field, secret_version, alg, nonce, kek_ref, kek_version,'
            '  wrapped_data_key, ciphertext)'
            ' VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10)',
            v_column
        ) USING v_tenant, p_subject_id, p_field, p_secret_version, p_alg, p_nonce, p_kek_ref,
                p_kek_version, p_wrapped_data_key, p_ciphertext;
    END
    $$
    """,
    # R1.10, R1.14 (CV24): the version named, or else the latest; returned only
    # while it is not revoked. A revoked latest version answers nothing rather
    # than the version it replaced.
    f"""
    CREATE FUNCTION platform.open_secret(
        p_subject_kind text, p_subject_id uuid, p_field text, p_secret_version integer
    ) RETURNS TABLE (
        secret_version integer,
        alg text,
        nonce bytea,
        kek_ref text,
        kek_version integer,
        wrapped_data_key bytea,
        ciphertext bytea
    )
    LANGUAGE plpgsql STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid := {_CALLER_TENANT};
        v_column text := platform.secret_subject_column(p_subject_kind);
    BEGIN
        RETURN QUERY EXECUTE format(
            'SELECT c.secret_version, c.alg, c.nonce, c.kek_ref, c.kek_version,'
            '       c.wrapped_data_key, c.ciphertext'
            ' FROM ('
            '   SELECT e.* FROM platform.secret_envelopes e'
            '   WHERE e.tenant_id = $1 AND e.%I = $2 AND e.field = $3'
            '     AND ($4 IS NULL OR e.secret_version = $4)'
            '   ORDER BY e.secret_version DESC LIMIT 1'
            ' ) c'
            ' WHERE c.revoked_at IS NULL OR c.revoked_at > now()',
            v_column
        ) USING v_tenant, p_subject_id, p_field, p_secret_version;
    END
    $$
    """,
    # What `connection_usable` (ticket 04) reads: the dates of every version
    # still held, never a value.
    f"""
    CREATE FUNCTION platform.secret_status(
        p_subject_kind text, p_subject_id uuid, p_field text
    ) RETURNS TABLE (
        secret_version integer, revoked_at timestamp with time zone,
        replaced_at timestamp with time zone
    )
    LANGUAGE plpgsql STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid := {_CALLER_TENANT};
        v_column text := platform.secret_subject_column(p_subject_kind);
    BEGIN
        RETURN QUERY EXECUTE format(
            'SELECT e.secret_version, e.revoked_at, e.replaced_at'
            ' FROM platform.secret_envelopes e'
            ' WHERE e.tenant_id = $1 AND e.%I = $2 AND e.field = $3'
            ' ORDER BY e.secret_version',
            v_column
        ) USING v_tenant, p_subject_id, p_field;
    END
    $$
    """,
    # Every version of one field of one subject; a version with no row is read
    # as revoked (closed while missing).
    f"""
    CREATE FUNCTION platform.delete_secret(
        p_subject_kind text, p_subject_id uuid, p_field text
    ) RETURNS integer
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid := {_CALLER_TENANT};
        v_column text := platform.secret_subject_column(p_subject_kind);
        v_deleted integer;
    BEGIN
        EXECUTE format(
            'DELETE FROM platform.secret_envelopes'
            ' WHERE tenant_id = $1 AND %I = $2 AND field = $3',
            v_column
        ) USING v_tenant, p_subject_id, p_field;
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        RETURN v_deleted;
    END
    $$
    """,
)

# The one database door to the envelopes (R1.3, CV2).
DOORS = (
    "platform.put_secret(text, uuid, text, integer, text, bytea, text, integer, bytea, bytea)",
    "platform.open_secret(text, uuid, text, integer)",
    "platform.secret_status(text, uuid, text)",
    "platform.delete_secret(text, uuid, text)",
)

_INTERNAL = (
    "platform.guard_connection_owning_workspace()",
    "platform.secret_subject_column(text)",
)

_TRIGGERS = (
    "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.connections"
    " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
    "CREATE TRIGGER guard_connection_owning_workspace BEFORE UPDATE ON platform.connections"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_connection_owning_workspace()",
    "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.secret_envelopes"
    " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
)

# `0001_platform_grants.sql`'s default privileges hand `dw_app` SELECT, INSERT,
# UPDATE and DELETE on every new table of `platform`; these narrow them.
_APP_GRANTS = (
    "REVOKE ALL ON platform.secret_envelopes FROM dw_app;",
    "REVOKE UPDATE ON platform.connections FROM dw_app;",
    "GRANT SELECT, INSERT, DELETE ON platform.connections TO dw_app;",
    "GRANT UPDATE (share_scope, external_account, status, scopes, last_used_at, updated_at)"
    " ON platform.connections TO dw_app;",
    *(f"GRANT EXECUTE ON FUNCTION {door} TO dw_app;" for door in DOORS),
)

_AGENT_RO_REVOKES = (
    "REVOKE ALL ON platform.connections FROM dw_agent_ro;",
    "REVOKE ALL ON platform.secret_envelopes FROM dw_agent_ro;",
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
    for statement in _TABLES:
        op.execute(statement)
    for statement in _RLS:
        op.execute(statement)
    for statement in _FUNCTIONS:
        op.execute(statement)
    # A new function is executable by PUBLIC: every role with USAGE on
    # `platform` (`dw_provisioner`) would reach the door (CV2).
    for function in (*_INTERNAL, *DOORS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))
    for statement in _AGENT_RO_REVOKES:
        op.execute(_for_role("dw_agent_ro", statement))


def downgrade() -> None:
    for function in DOORS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TABLE IF EXISTS platform.secret_envelopes")
    op.execute("DROP TABLE IF EXISTS platform.connections")
    for function in _INTERNAL:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
