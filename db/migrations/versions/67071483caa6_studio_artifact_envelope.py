"""studio artifact envelope

Revision ID: 67071483caa6
Revises: 555dad01f629
Create Date: 2026-11-03

The versioned envelope every Studio kind shares (tenant-config ticket 02;
ADR-0109 decisions 1-2, 4-5; ADR-0120 decision 1), the first tenant tables of
schema `studio`:

- `studio.artifact_kinds`: the platform's catalogue of kinds, no `tenant_id`.
  `has_quality_gate` has no DEFAULT, so a kind registered without saying
  whether it is gated is refused (R2.14). Empty here: each kind's spec inserts
  its row in its own revision, with its registry entry (OPS-b).
- `studio.artifacts`: one row per artifact, owned by one workspace through the
  composite key to `uq_workspaces_tenant_id_id` (R2.18); the API name is unique
  among live artifacts of one kind (R2.3) and fixed once a version was live
  (R2.10); the owning workspace never changes (R2.19, ADR-0115 decision 1).
- `studio.artifact_versions`: at most one unreleased version per artifact
  (R2.20); a sealed version's content never changes (R2.9).
- `studio.definition_manifests`: content-addressed, written once per hash.
- `studio.dependencies`: where each sealed version uses what (R3.1); a soft
  delete of an artifact an in-use version depends on is refused (R3.3).

Every reference to an artifact, a version or a workspace is a composite key
`(tenant_id, <column>)`, listed with its column first so its name follows
`NAMING_CONVENTION`, so no row points into another tenant even from a role
that bypasses RLS (R2.18). RLS is tenant-only: these are definitions of the
whole company (ADR-0100 decision 5). `dw_app` holds column UPDATEs only
(studio-skeleton R2.7) and DELETE, which outside the offboarding lane's pass
`platform.refuse_delete_outside_offboarding()` refuses (R3.8), but on
`studio.dependencies`, whose rows a reseal replaces.
"""

from __future__ import annotations

from alembic import op

revision = "67071483caa6"
down_revision = "555dad01f629"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_HASH = "~ '^sha256:[0-9a-f]{64}$'"
_MIB = 1048576

_TABLES = (
    """
    CREATE TABLE studio.artifact_kinds (
        kind text NOT NULL,
        has_quality_gate boolean NOT NULL,
        CONSTRAINT pk_artifact_kinds PRIMARY KEY (kind),
        CONSTRAINT ck_artifact_kinds_kind CHECK (kind ~ '^[a-z][a-z0-9_]{1,39}$')
    )
    """,
    """
    CREATE TABLE studio.artifacts (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        kind text NOT NULL,
        api_name text NOT NULL,
        owning_workspace_id uuid NOT NULL,
        labels text[] DEFAULT '{}' NOT NULL,
        origin jsonb,
        last_version_no integer DEFAULT 0 NOT NULL,
        row_version integer NOT NULL,
        deleted_at timestamp with time zone,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_artifacts PRIMARY KEY (id),
        CONSTRAINT uq_artifacts_tenant_id_id UNIQUE (tenant_id, id),
        CONSTRAINT fk_artifacts_kind_artifact_kinds FOREIGN KEY (kind)
            REFERENCES studio.artifact_kinds (kind) ON DELETE RESTRICT,
        CONSTRAINT fk_artifacts_owning_workspace_id_workspaces
            FOREIGN KEY (owning_workspace_id, tenant_id)
            REFERENCES platform.workspaces (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT ck_artifacts_api_name CHECK (api_name ~ '^[a-z][a-z0-9_]{1,39}$'),
        CONSTRAINT ck_artifacts_last_version_no CHECK (last_version_no >= 0),
        CONSTRAINT ck_artifacts_row_version CHECK (row_version >= 1),
        CONSTRAINT ck_artifacts_origin CHECK (origin IS NULL OR jsonb_typeof(origin) = 'object')
    )
    """,
    "CREATE INDEX ix_artifacts_kind ON studio.artifacts (kind)",
    "CREATE INDEX ix_artifacts_tenant_id_owning_workspace_id"
    " ON studio.artifacts (tenant_id, owning_workspace_id)",
    "CREATE UNIQUE INDEX uq_artifacts_tenant_id_kind_api_name"
    " ON studio.artifacts (tenant_id, kind, api_name) WHERE deleted_at IS NULL",
    # The two orders `GET /api/v1/studio/artifacts` pages in (app-standards R6).
    "CREATE INDEX ix_artifacts_tenant_id_kind_updated_at_id"
    " ON studio.artifacts (tenant_id, kind, updated_at DESC, id DESC)",
    "CREATE INDEX ix_artifacts_tenant_id_updated_at_id"
    " ON studio.artifacts (tenant_id, updated_at DESC, id DESC)",
    f"""
    CREATE TABLE studio.artifact_versions (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        artifact_id uuid NOT NULL,
        stage text NOT NULL,
        version_no integer,
        document_schema text NOT NULL,
        document jsonb NOT NULL,
        content_hash text,
        definition_hash text,
        row_version integer NOT NULL,
        based_on_version_id uuid,
        change_note text,
        CONSTRAINT pk_artifact_versions PRIMARY KEY (id),
        CONSTRAINT uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id),
        CONSTRAINT uq_artifact_versions_artifact_id_version_no UNIQUE (artifact_id, version_no),
        CONSTRAINT fk_artifact_versions_artifact_id_artifacts
            FOREIGN KEY (artifact_id, tenant_id)
            REFERENCES studio.artifacts (id, tenant_id) ON DELETE CASCADE,
        -- Only the column: `tenant_id` is NOT NULL (measured 24/10/2026, PG 16).
        CONSTRAINT fk_artifact_versions_based_on_version_id_artifact_versions
            FOREIGN KEY (based_on_version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id)
            ON DELETE SET NULL (based_on_version_id),
        CONSTRAINT ck_artifact_versions_stage
            CHECK (stage IN ('draft', 'evaluating', 'awaiting_approval', 'live', 'retired')),
        CONSTRAINT ck_artifact_versions_version_no
            CHECK ((version_no IS NULL OR version_no >= 1)
                   AND (version_no IS NOT NULL OR stage = 'draft')),
        CONSTRAINT ck_artifact_versions_document_schema
            CHECK (document_schema ~ '^dw\\.[a-z_]+/v[0-9]+$'),
        CONSTRAINT ck_artifact_versions_document
            CHECK (jsonb_typeof(document) = 'object' AND octet_length(document::text) <= {_MIB}),
        CONSTRAINT ck_artifact_versions_document_nfc CHECK (document::text IS NFC NORMALIZED),
        CONSTRAINT ck_artifact_versions_content_hash
            CHECK (content_hash IS NULL OR content_hash {_HASH}),
        CONSTRAINT ck_artifact_versions_definition_hash
            CHECK (definition_hash IS NULL OR definition_hash {_HASH}),
        CONSTRAINT ck_artifact_versions_sealed
            CHECK (stage = 'draft' OR (content_hash IS NOT NULL AND definition_hash IS NOT NULL)),
        CONSTRAINT ck_artifact_versions_row_version CHECK (row_version >= 1)
    )
    """,
    "CREATE INDEX ix_artifact_versions_tenant_id_artifact_id"
    " ON studio.artifact_versions (tenant_id, artifact_id)",
    "CREATE INDEX ix_artifact_versions_tenant_id_based_on_version_id"
    " ON studio.artifact_versions (tenant_id, based_on_version_id)",
    # R2.20: one draft or candidate per artifact. The one-live index is
    # agent-lifecycle's (agent-lifecycle R1.2).
    "CREATE UNIQUE INDEX uq_artifact_versions_unreleased ON studio.artifact_versions"
    " (artifact_id) WHERE stage IN ('draft', 'evaluating', 'awaiting_approval')",
    f"""
    CREATE TABLE studio.definition_manifests (
        tenant_id uuid NOT NULL,
        hash text NOT NULL,
        body jsonb NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_definition_manifests PRIMARY KEY (tenant_id, hash),
        CONSTRAINT fk_definition_manifests_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE RESTRICT,
        CONSTRAINT ck_definition_manifests_hash CHECK (hash {_HASH}),
        CONSTRAINT ck_definition_manifests_body
            CHECK (jsonb_typeof(body) = 'object' AND octet_length(body::text) <= {_MIB}),
        CONSTRAINT ck_definition_manifests_body_nfc CHECK (body::text IS NFC NORMALIZED)
    )
    """,
    f"""
    CREATE TABLE studio.dependencies (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        from_artifact_id uuid NOT NULL,
        from_version_id uuid NOT NULL,
        to_kind text NOT NULL,
        to_key text NOT NULL,
        to_version integer,
        to_hash text,
        to_artifact_id uuid,
        to_version_id uuid,
        usage text NOT NULL,
        path text NOT NULL,
        CONSTRAINT pk_dependencies PRIMARY KEY (id),
        CONSTRAINT fk_dependencies_from_artifact_id_artifacts
            FOREIGN KEY (from_artifact_id, tenant_id)
            REFERENCES studio.artifacts (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_dependencies_from_version_id_artifact_versions
            FOREIGN KEY (from_version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_dependencies_to_artifact_id_artifacts
            FOREIGN KEY (to_artifact_id, tenant_id)
            REFERENCES studio.artifacts (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT fk_dependencies_to_version_id_artifact_versions
            FOREIGN KEY (to_version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT ck_dependencies_to_kind CHECK (to_kind IN ('artifact', 'field',
            'picklist_value', 'platform_artifact', 'connector', 'mcp_tool', 'binding',
            'node_type')),
        CONSTRAINT ck_dependencies_usage
            CHECK (usage IN ('read', 'write', 'compare', 'invoke', 'bind', 'display')),
        CONSTRAINT ck_dependencies_to_hash CHECK (to_hash IS NULL OR to_hash {_HASH}),
        CONSTRAINT ck_dependencies_path CHECK (path = '' OR path LIKE '/%'),
        -- The soft-delete trigger finds a dependent by `to_artifact_id`
        -- (failure-modes #7): an `artifact` row without it would hide one.
        CONSTRAINT ck_dependencies_artifact_target CHECK (
            to_kind <> 'artifact'
            OR (to_artifact_id IS NOT NULL AND to_version_id IS NOT NULL
                AND to_key = to_artifact_id::text)
        )
    )
    """,
    "CREATE INDEX ix_dependencies_tenant_id_from_artifact_id"
    " ON studio.dependencies (tenant_id, from_artifact_id)",
    "CREATE INDEX ix_dependencies_tenant_id_from_version_id"
    " ON studio.dependencies (tenant_id, from_version_id)",
    "CREATE INDEX ix_dependencies_tenant_id_to_artifact_id"
    " ON studio.dependencies (tenant_id, to_artifact_id)",
    "CREATE INDEX ix_dependencies_tenant_id_to_version_id"
    " ON studio.dependencies (tenant_id, to_version_id)",
    "CREATE INDEX ix_dependencies_tenant_id_to_kind_to_key"
    " ON studio.dependencies (tenant_id, to_kind, to_key)",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
# Tenant-only: definitions of the whole company (ADR-0100 decision 5).
_RLS = (
    "ALTER TABLE studio.artifacts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.artifacts FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_artifacts ON studio.artifacts"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.artifact_versions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.artifact_versions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_artifact_versions ON studio.artifact_versions"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.definition_manifests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.definition_manifests FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_definition_manifests ON studio.definition_manifests"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.dependencies ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.dependencies FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_dependencies ON studio.dependencies"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

_FUNCTIONS = (
    # R2.9 (TC1): a sealed version's content is fixed, from any role.
    """
    CREATE FUNCTION studio.refuse_sealed_content_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.stage <> 'draft' AND (
            NEW.document IS DISTINCT FROM OLD.document
            OR NEW.document_schema IS DISTINCT FROM OLD.document_schema
            OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
            OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash
            OR NEW.version_no IS DISTINCT FROM OLD.version_no
            OR NEW.artifact_id IS DISTINCT FROM OLD.artifact_id
        ) THEN
            RAISE EXCEPTION 'the content of a sealed version does not change'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_artifact_versions_sealed_content';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R2.10 (TC4): the API name is fixed once a version has been live.
    """
    CREATE FUNCTION studio.refuse_api_name_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.api_name IS DISTINCT FROM OLD.api_name AND EXISTS (
            SELECT 1 FROM studio.artifact_versions v
            WHERE v.tenant_id = OLD.tenant_id AND v.artifact_id = OLD.id
              AND v.stage IN ('live', 'retired')
        ) THEN
            RAISE EXCEPTION 'the API name is fixed once a version has been live'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_artifacts_api_name_immutable';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R2.19 (TC30): a secret's AAD binds the owning workspace (ADR-0115 decision 1).
    """
    CREATE FUNCTION studio.refuse_owning_workspace_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.owning_workspace_id IS DISTINCT FROM OLD.owning_workspace_id THEN
            RAISE EXCEPTION 'an artifact''s owning workspace does not change'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_artifacts_owning_workspace_fixed';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R3.3 (TC5): no soft delete under an in-use dependent. Its query takes a
    # fresh snapshot after the row lock, so a seal that read this row FOR SHARE
    # and committed is seen. DETAIL counts the dependent versions by stage.
    """
    CREATE FUNCTION studio.refuse_soft_delete_in_use() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        v_counts text;
    BEGIN
        IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
            SELECT string_agg(s.stage || '=' || s.n, ',' ORDER BY s.stage) INTO v_counts
            FROM (
                SELECT v.stage, count(DISTINCT d.from_version_id) AS n
                FROM studio.dependencies d
                JOIN studio.artifact_versions v
                  ON v.tenant_id = d.tenant_id AND v.id = d.from_version_id
                WHERE d.tenant_id = OLD.tenant_id AND d.to_artifact_id = OLD.id
                  AND d.from_artifact_id <> OLD.id
                  AND v.stage IN ('evaluating', 'awaiting_approval', 'live')
                GROUP BY v.stage
            ) s;
            IF v_counts IS NOT NULL THEN
                RAISE EXCEPTION 'another version uses this artifact'
                    USING ERRCODE = '23503', CONSTRAINT = 'ck_artifacts_not_in_use',
                          DETAIL = v_counts;
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R3.8 (TC31): only the offboarding lane's pass deletes these rows. A
    # definer, so the tenant's status is read whatever the caller's scope
    # (gate MEDIUM (f), as `platform.guard_contact_suppression()`).
    """
    CREATE FUNCTION platform.refuse_delete_outside_offboarding() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF (SELECT t.status FROM platform.tenants t WHERE t.id = OLD.tenant_id)
           IS DISTINCT FROM 'offboarding' THEN
            RAISE EXCEPTION 'only the offboarding lane deletes this row'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_delete_outside_offboarding';
        END IF;
        RETURN OLD;
    END
    $$
    """,
)

_FUNCTION_NAMES = (
    "studio.refuse_sealed_content_change()",
    "studio.refuse_api_name_change()",
    "studio.refuse_owning_workspace_change()",
    "studio.refuse_soft_delete_in_use()",
    "platform.refuse_delete_outside_offboarding()",
)

_TRIGGERS = (
    "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON studio.artifacts"
    " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
    "CREATE TRIGGER refuse_sealed_content_change BEFORE UPDATE ON studio.artifact_versions"
    " FOR EACH ROW EXECUTE FUNCTION studio.refuse_sealed_content_change()",
    "CREATE TRIGGER refuse_api_name_change BEFORE UPDATE OF api_name ON studio.artifacts"
    " FOR EACH ROW EXECUTE FUNCTION studio.refuse_api_name_change()",
    "CREATE TRIGGER refuse_owning_workspace_change BEFORE UPDATE OF owning_workspace_id"
    " ON studio.artifacts FOR EACH ROW EXECUTE FUNCTION studio.refuse_owning_workspace_change()",
    "CREATE TRIGGER refuse_soft_delete_in_use BEFORE UPDATE OF deleted_at ON studio.artifacts"
    " FOR EACH ROW EXECUTE FUNCTION studio.refuse_soft_delete_in_use()",
    *(
        f"CREATE TRIGGER refuse_delete_outside_offboarding BEFORE DELETE ON studio.{table}"
        " FOR EACH ROW EXECUTE FUNCTION platform.refuse_delete_outside_offboarding()"
        for table in ("artifacts", "artifact_versions", "definition_manifests")
    ),
)

# What `dw_app` holds beyond the schema's default SELECT (ADR 0100 point 4).
_APP_GRANTS = (
    "GRANT INSERT, DELETE ON studio.artifacts TO dw_app;",
    "GRANT UPDATE (api_name, labels, last_version_no, row_version, deleted_at, updated_at)"
    " ON studio.artifacts TO dw_app;",
    "GRANT INSERT, DELETE ON studio.artifact_versions TO dw_app;",
    "GRANT UPDATE (stage, document_schema, document, version_no, content_hash,"
    " definition_hash, row_version, change_note) ON studio.artifact_versions TO dw_app;",
    "GRANT INSERT, DELETE ON studio.definition_manifests TO dw_app;",
    "GRANT INSERT, DELETE ON studio.dependencies TO dw_app;",
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
    # Every function of this revision is called by its trigger and by no role.
    for function in _FUNCTION_NAMES:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))


def downgrade() -> None:
    for table in ("dependencies", "definition_manifests", "artifact_versions", "artifacts"):
        op.execute(f"DROP TABLE studio.{table}")
    op.execute("DROP TABLE studio.artifact_kinds")
    for function in _FUNCTION_NAMES:
        op.execute(f"DROP FUNCTION {function}")
