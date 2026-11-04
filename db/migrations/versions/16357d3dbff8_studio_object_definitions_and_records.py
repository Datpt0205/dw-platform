"""studio object definitions and records

Revision ID: 16357d3dbff8
Revises: 28a94cda6fdf
Create Date: 2026-11-04 07:34:35.961694+00:00

custom-objects ticket 02 (R1.1, R1.4-R1.6, R2.1-R2.6, R4.1, R4.2, R4.4, R4.6,
R9.4, R9.5; CO1-CO6, CO21; ADR-0107 decisions 1, 2, 5; ADR-0109 decision 5).
A company's objects and fields as data, applied by the `object` kind's publish
hook, and the one table their records live in:

- `studio.object_defs`: one row per `object` artifact, its key the artifact's
  through the composite key to `uq_artifacts_tenant_id_id`; `api_name` copied
  from the envelope at the first apply; `applied_version_id` (composite key to
  `uq_artifact_versions_tenant_id_id`) is the version the row says, and
  `schema_version` that version's `version_no`, no second counter.
- `studio.field_defs`: `id` is the field key; three `system` rows (`name`,
  `owner`, `workspace`) per object, every other field in a typed slot when it
  filters (`indexed` or `is_unique`), in `data` under a `field_no` never reused
  otherwise. Each storage rule is its own CHECK; the personal-data columns are
  `dw_kernel.personal_data`'s (`assert_field_tables_classified`).
- `studio.picklist_options`: keyed `(tenant_id, field_id, key)`.
- `studio.records`: `PARTITION BY HASH (tenant_id)`, modulus 4 (`records_p0` to
  `records_p3`), the provisional DDL of the spec's Data section: the A0 slot set
  of custom-objects/01 (`t01`-`t24`, `i01`-`i12`, `f01`-`f08`, `d01`-`d08`,
  `z01`-`z08`, `b01`-`b08`, `u01`-`u04`), a btree on `updated_at`, the `b`
  family indexed. Ticket 07 brings it to the D12 measurement's conclusion in a
  later revision. Only a RESTRICTIVE tenant policy, on the parent and on each
  partition: until record-access/03 adds the PERMISSIVE `record_access_*`
  policies (ADR-0105), no role but the migrator reads or writes a row.
- `studio.dependencies.to_field_id`: composite key to `studio.field_defs`,
  RESTRICT (ADR-0109 decision 5).
- `studio.refuse_object_artifact_delete()`: an `object` artifact that has a
  definition, or a version past `draft`, is not soft-deleted
  (`ck_artifacts_not_in_use`, which the store already reads as 409
  `artifact_in_use`); deleting an object is W2's.
- The `object` row of `studio.artifact_kinds` (no quality gate) and the
  permission `studio.objects.manage` (tenant depth, standard risk).

The three definition tables are tenant-wide (ADR-0107 decision 1, DO-01).
`dw_app` holds SELECT, INSERT and DELETE on the four tables (the DELETE is the
offboarding lane's; its default step deletes them in the order the RESTRICT
keys give), UPDATE only of the columns the hook and RecordService change, and
nothing on a partition: the schema's default SELECT is revoked from each, so
rows are reached only through the parent (DO-02.2).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "16357d3dbff8"
down_revision = "28a94cda6fdf"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_API_NAME = "'^[a-z][a-z0-9_]{1,39}$'"
_LABELS = "jsonb_typeof(labels) = 'object' AND btrim(coalesce(labels ->> 'vi', '')) <> ''"
_TEXT_LIKE = "('text', 'email', 'phone', 'url')"

# The provisional slot set (A0 of custom-objects/01 step 2), written here as
# literals because a migration imports no package; `test_object_definitions_db`
# holds it equal to `dw_studio.records.domain.field_types.SLOTS`.
_FAMILIES = (
    ("t", 'text COLLATE "vi-VN-x-icu"', 24),
    ("i", "bigint", 12),
    ("f", "double precision", 8),
    ("d", "date", 8),
    ("z", "timestamp with time zone", 8),
    ("b", "boolean", 8),
    ("u", "text", 4),
)
_SLOTS = tuple(
    (f"{family}{n:02d}", family, sql_type)
    for family, sql_type, count in _FAMILIES
    for n in range(1, count + 1)
)
_PARTITIONS = tuple(f"records_p{remainder}" for remainder in range(4))

_SLOT_COLUMNS = ",\n        ".join(f"{slot} {sql_type}" for slot, _, sql_type in _SLOTS)
_SLOT_CHECKS = ",\n        ".join(
    f"CONSTRAINT ck_records_{slot} CHECK (octet_length({slot}) <= 1024)"
    for slot, family, _ in _SLOTS
    if family in ("t", "u")
)

_TABLES = (
    f"""
    CREATE TABLE studio.object_defs (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        api_name text NOT NULL,
        labels jsonb NOT NULL,
        default_access text DEFAULT 'private' NOT NULL,
        ai_description text,
        applied_version_id uuid NOT NULL,
        schema_version integer NOT NULL,
        next_field_no integer DEFAULT 1 NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        created_by uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_by uuid NOT NULL,
        CONSTRAINT pk_object_defs PRIMARY KEY (tenant_id, id),
        CONSTRAINT uq_object_defs_tenant_id_api_name UNIQUE (tenant_id, api_name),
        CONSTRAINT fk_object_defs_id_artifacts FOREIGN KEY (id, tenant_id)
            REFERENCES studio.artifacts (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT fk_object_defs_applied_version_id_artifact_versions
            FOREIGN KEY (applied_version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT ck_object_defs_api_name CHECK (api_name ~ {_API_NAME}),
        CONSTRAINT ck_object_defs_labels CHECK ({_LABELS}),
        CONSTRAINT ck_object_defs_default_access
            CHECK (default_access IN ('private', 'public_read', 'public_read_write')),
        CONSTRAINT ck_object_defs_ai_description CHECK (char_length(ai_description) <= 500),
        CONSTRAINT ck_object_defs_schema_version CHECK (schema_version >= 1),
        CONSTRAINT ck_object_defs_next_field_no CHECK (next_field_no >= 1)
    )
    """,
    "CREATE INDEX ix_object_defs_tenant_id_applied_version_id"
    " ON studio.object_defs (tenant_id, applied_version_id)",
    f"""
    CREATE TABLE studio.field_defs (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        object_id uuid NOT NULL,
        api_name text NOT NULL,
        labels jsonb NOT NULL,
        ai_description text,
        type text NOT NULL,
        number_mode text,
        scale integer,
        currency_code text,
        max_length integer,
        required boolean NOT NULL,
        is_unique boolean NOT NULL,
        indexed boolean NOT NULL,
        pd_category text NOT NULL,
        sensitive_type text,
        subject_identifier text,
        storage_kind text NOT NULL,
        slot text,
        field_no integer,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        created_by uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_by uuid NOT NULL,
        CONSTRAINT pk_field_defs PRIMARY KEY (tenant_id, id),
        CONSTRAINT uq_field_defs_tenant_id_object_id_api_name
            UNIQUE (tenant_id, object_id, api_name),
        CONSTRAINT uq_field_defs_tenant_id_object_id_field_no
            UNIQUE (tenant_id, object_id, field_no),
        CONSTRAINT fk_field_defs_object_id_object_defs FOREIGN KEY (object_id, tenant_id)
            REFERENCES studio.object_defs (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT ck_field_defs_api_name CHECK (api_name ~ {_API_NAME}),
        CONSTRAINT ck_field_defs_labels CHECK ({_LABELS}),
        CONSTRAINT ck_field_defs_ai_description CHECK (char_length(ai_description) <= 500),
        CONSTRAINT ck_field_defs_type CHECK (type IN ('text', 'number', 'currency', 'date',
            'datetime', 'boolean', 'picklist', 'email', 'phone', 'url', 'owner', 'workspace')),
        CONSTRAINT ck_field_defs_pd_category
            CHECK (pd_category IN ('none', 'basic', 'sensitive')),
        CONSTRAINT ck_field_defs_sensitive_type CHECK (sensitive_type IN (
            'racial_ethnic_origin', 'political_religious_views', 'private_life', 'health',
            'biometric_genetic', 'sex_life_orientation', 'crime_violation', 'location',
            'identity_credentials', 'financial', 'behaviour_tracking', 'legally_confidential')),
        CONSTRAINT ck_field_defs_subject_identifier CHECK (subject_identifier IN (
            'email', 'phone', 'national_id', 'zalo_user_id', 'facebook_psid', 'tax_code',
            'bank_account')),
        CONSTRAINT ck_field_defs_pd_sensitive_type
            CHECK ((pd_category = 'sensitive') = (sensitive_type IS NOT NULL)),
        CONSTRAINT ck_field_defs_pd_subject_identifier
            CHECK (pd_category <> 'none' OR subject_identifier IS NULL),
        CONSTRAINT ck_field_defs_number_mode CHECK (number_mode IN ('exact', 'float')),
        CONSTRAINT ck_field_defs_number_mode_type
            CHECK ((type = 'number') = (number_mode IS NOT NULL)),
        CONSTRAINT ck_field_defs_scale CHECK (scale BETWEEN 0 AND 6),
        CONSTRAINT ck_field_defs_scale_type CHECK ((scale IS NOT NULL)
            = (type = 'currency' OR (type = 'number' AND number_mode = 'exact'))),
        CONSTRAINT ck_field_defs_currency_code CHECK (currency_code ~ '^[A-Z]{{3}}$'),
        CONSTRAINT ck_field_defs_currency_code_type
            CHECK ((type = 'currency') = (currency_code IS NOT NULL)),
        CONSTRAINT ck_field_defs_max_length CHECK (max_length BETWEEN 1 AND 255),
        CONSTRAINT ck_field_defs_max_length_type
            CHECK ((max_length IS NOT NULL) = (type IN {_TEXT_LIKE})),
        CONSTRAINT ck_field_defs_storage_kind
            CHECK (storage_kind IN ('system', 'slot', 'data')),
        CONSTRAINT ck_field_defs_slot CHECK (slot ~ '^(t|u|i|f|d|z|b)[0-9]{{2}}$'),
        CONSTRAINT ck_field_defs_field_no CHECK (field_no >= 1),
        -- The storage rules, one CHECK each (ticket 02 step 1).
        CONSTRAINT ck_field_defs_slot_storage
            CHECK ((storage_kind = 'slot') = (slot IS NOT NULL)),
        CONSTRAINT ck_field_defs_data_storage
            CHECK ((storage_kind = 'data') = (field_no IS NOT NULL)),
        CONSTRAINT ck_field_defs_system_rows
            CHECK ((storage_kind = 'system') = (api_name IN ('name', 'owner', 'workspace'))),
        CONSTRAINT ck_field_defs_system_types CHECK (storage_kind <> 'system'
            OR (api_name = 'name' AND type = 'text')
            OR (api_name = 'owner' AND type = 'owner')
            OR (api_name = 'workspace' AND type = 'workspace')),
        CONSTRAINT ck_field_defs_system_only_types
            CHECK (type NOT IN ('owner', 'workspace') OR storage_kind = 'system'),
        CONSTRAINT ck_field_defs_unique_types CHECK (NOT is_unique OR type IN {_TEXT_LIKE}),
        CONSTRAINT ck_field_defs_unique_slot
            CHECK ((coalesce(left(slot, 1), '') = 'u') = is_unique),
        CONSTRAINT ck_field_defs_filter_storage CHECK (storage_kind = 'system'
            OR (storage_kind = 'slot') = (indexed OR is_unique)),
        CONSTRAINT ck_field_defs_slot_family CHECK (slot IS NULL OR CASE left(slot, 1)
            WHEN 't' THEN type IN ('text', 'email', 'phone', 'url', 'picklist')
            WHEN 'u' THEN type IN {_TEXT_LIKE}
            WHEN 'i' THEN type = 'currency' OR (type = 'number' AND number_mode = 'exact')
            WHEN 'f' THEN type = 'number' AND number_mode = 'float'
            WHEN 'd' THEN type = 'date'
            WHEN 'z' THEN type = 'datetime'
            WHEN 'b' THEN type = 'boolean'
            ELSE false END)
    )
    """,
    # Two filtering fields of one object never share a slot (R1.5, CO4).
    "CREATE UNIQUE INDEX uq_field_defs_tenant_id_object_id_slot"
    " ON studio.field_defs (tenant_id, object_id, slot) WHERE slot IS NOT NULL",
    f"""
    CREATE TABLE studio.picklist_options (
        tenant_id uuid NOT NULL,
        field_id uuid NOT NULL,
        key text NOT NULL,
        labels jsonb NOT NULL,
        position integer NOT NULL,
        active boolean NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        created_by uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_by uuid NOT NULL,
        CONSTRAINT pk_picklist_options PRIMARY KEY (tenant_id, field_id, key),
        CONSTRAINT fk_picklist_options_field_id_field_defs FOREIGN KEY (field_id, tenant_id)
            REFERENCES studio.field_defs (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT ck_picklist_options_key CHECK (key ~ '^[a-z0-9_]{{1,40}}$'),
        CONSTRAINT ck_picklist_options_labels CHECK ({_LABELS}),
        CONSTRAINT ck_picklist_options_position CHECK (position >= 0)
    )
    """,
    f"""
    CREATE TABLE studio.records (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        object_id uuid NOT NULL,
        workspace_id uuid NOT NULL,
        owner_kind text NOT NULL,
        owner_id uuid NOT NULL,
        name text COLLATE "vi-VN-x-icu" NOT NULL,
        version integer DEFAULT 1 NOT NULL,
        create_key text,
        data jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        {_SLOT_COLUMNS},
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        created_by uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_by uuid NOT NULL,
        deleted_at timestamp with time zone,
        deleted_by uuid,
        CONSTRAINT pk_records PRIMARY KEY (tenant_id, id),
        CONSTRAINT fk_records_object_id_object_defs FOREIGN KEY (object_id, tenant_id)
            REFERENCES studio.object_defs (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT fk_records_workspace_id_workspaces FOREIGN KEY (workspace_id, tenant_id)
            REFERENCES platform.workspaces (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT ck_records_owner_kind CHECK (owner_kind IN ('user', 'team')),
        CONSTRAINT ck_records_name CHECK (char_length(name) BETWEEN 1 AND 255),
        CONSTRAINT ck_records_version CHECK (version >= 1),
        CONSTRAINT ck_records_create_key CHECK (octet_length(create_key) <= 255),
        CONSTRAINT ck_records_data
            CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 32768),
        {_SLOT_CHECKS}
    ) PARTITION BY HASH (tenant_id)
    """,
    *(
        f"CREATE TABLE studio.{part} PARTITION OF studio.records"
        f" FOR VALUES WITH (MODULUS 4, REMAINDER {remainder})"
        for remainder, part in enumerate(_PARTITIONS)
    ),
    "CREATE UNIQUE INDEX uq_records_tenant_id_object_id_create_key"
    " ON studio.records (tenant_id, object_id, create_key) WHERE create_key IS NOT NULL",
    "CREATE INDEX ix_records_tenant_id_object_id_created_at_id"
    " ON studio.records (tenant_id, object_id, created_at DESC, id DESC)",
    "CREATE INDEX ix_records_tenant_id_object_id_updated_at_id"
    " ON studio.records (tenant_id, object_id, updated_at DESC, id DESC)",
    "CREATE INDEX ix_records_tenant_id_object_id_name_id"
    " ON studio.records (tenant_id, object_id, name, id)",
    "CREATE INDEX ix_records_tenant_id_workspace_id ON studio.records (tenant_id, workspace_id)",
    # R9.4: one partial index per slot, the shape the query compiler plans on.
    *(
        f"CREATE INDEX ix_records_tenant_id_object_id_{slot}_id"
        f" ON studio.records (tenant_id, object_id, {slot}, id)"
        f" WHERE {slot} IS NOT NULL AND deleted_at IS NULL"
        for slot, _, _ in _SLOTS
    ),
    *(
        f"CREATE UNIQUE INDEX uq_records_tenant_id_object_id_{slot}"
        f" ON studio.records (tenant_id, object_id, {slot})"
        f" WHERE {slot} IS NOT NULL AND deleted_at IS NULL"
        for slot, family, _ in _SLOTS
        if family == "u"
    ),
    # ADR-0109 decision 5: a dependency on a field holds it.
    "ALTER TABLE studio.dependencies ADD COLUMN to_field_id uuid",
    "ALTER TABLE studio.dependencies ADD CONSTRAINT fk_dependencies_to_field_id_field_defs"
    " FOREIGN KEY (to_field_id, tenant_id) REFERENCES studio.field_defs (id, tenant_id)"
    " ON DELETE RESTRICT",
    "CREATE INDEX ix_dependencies_tenant_id_to_field_id"
    " ON studio.dependencies (tenant_id, to_field_id)",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
# Tenant-only: definitions of the whole company (ADR-0107 decision 1). The
# records policy is RESTRICTIVE: it narrows whatever PERMISSIVE policy
# record-access/03 adds (ADR-0105 decision 1), and alone it admits nothing.
_RLS = (
    "ALTER TABLE studio.object_defs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.object_defs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_object_defs ON studio.object_defs"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.field_defs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.field_defs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_field_defs ON studio.field_defs"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.picklist_options ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.picklist_options FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_picklist_options ON studio.picklist_options"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.records ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.records FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_records ON studio.records AS RESTRICTIVE"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    # Row security is not inherited: each partition carries the parent's.
    *(
        statement
        for part in _PARTITIONS
        for statement in (
            f"ALTER TABLE studio.{part} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE studio.{part} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation_records ON studio.{part} AS RESTRICTIVE"
            f" USING {_TENANT} WITH CHECK {_TENANT}",
        )
    ),
)

# R1.1 (HIGH 8 of the gate): the object's API name has one owner, the
# envelope, and a definition names it; an object is deleted in W2.
_REFUSE_OBJECT_ARTIFACT_DELETE = """
    CREATE FUNCTION studio.refuse_object_artifact_delete() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.kind = 'object' AND OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
           AND (EXISTS (SELECT 1 FROM studio.object_defs o
                        WHERE o.tenant_id = OLD.tenant_id AND o.id = OLD.id)
                OR EXISTS (SELECT 1 FROM studio.artifact_versions v
                           WHERE v.tenant_id = OLD.tenant_id AND v.artifact_id = OLD.id
                             AND v.stage <> 'draft')) THEN
            RAISE EXCEPTION 'an object with a definition or a candidate is not deleted'
                USING ERRCODE = '23503', CONSTRAINT = 'ck_artifacts_not_in_use';
        END IF;
        RETURN NEW;
    END
    $$
    """

_TRIGGERS = (
    "CREATE TRIGGER refuse_object_artifact_delete BEFORE UPDATE OF deleted_at"
    " ON studio.artifacts"
    " FOR EACH ROW EXECUTE FUNCTION studio.refuse_object_artifact_delete()",
    # On the parent of `records`, the trigger runs for a row in any partition.
    *(
        f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON studio.{table}"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
        for table in ("object_defs", "field_defs", "picklist_options", "records")
    ),
)

_RECORD_UPDATES = ", ".join(
    (
        "name",
        "data",
        *(slot for slot, _, _ in _SLOTS),
        "version",
        "updated_at",
        "updated_by",
        "deleted_at",
        "deleted_by",
    )
)

# What `dw_app` holds beyond the schema's default SELECT (ADR 0100 point 4).
_APP_GRANTS = (
    "GRANT INSERT, DELETE ON studio.object_defs TO dw_app;",
    "GRANT UPDATE (labels, default_access, ai_description, applied_version_id,"
    " schema_version, next_field_no, updated_at, updated_by) ON studio.object_defs TO dw_app;",
    "GRANT INSERT, DELETE ON studio.field_defs TO dw_app;",
    "GRANT UPDATE (labels, ai_description, required, max_length, pd_category, sensitive_type,"
    " subject_identifier, updated_at, updated_by) ON studio.field_defs TO dw_app;",
    "GRANT INSERT, DELETE ON studio.picklist_options TO dw_app;",
    "GRANT UPDATE (labels, position, active, updated_at, updated_by)"
    " ON studio.picklist_options TO dw_app;",
    "GRANT INSERT, DELETE ON studio.records TO dw_app;",
    f"GRANT UPDATE ({_RECORD_UPDATES}) ON studio.records TO dw_app;",
    # The schema's default SELECT reaches a partition too (DO-02.2).
    *(f"REVOKE ALL ON studio.{part} FROM dw_app;" for part in _PARTITIONS),
)

OBJECTS_MANAGE = "studio.objects.manage"


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
    op.execute(_REFUSE_OBJECT_ARTIFACT_DELETE)
    # Called by its trigger and by no role.
    op.execute("REVOKE ALL ON FUNCTION studio.refuse_object_artifact_delete() FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))
    # OPS-b: the kind's row beside its registry entry; no quality gate (R2.14).
    op.execute(
        "INSERT INTO studio.artifact_kinds (kind, has_quality_gate) VALUES ('object', false)"
    )
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    op.execute(
        sa.text(
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'studio', :l, 'tenant', 'standard', 'active', NULL,"
            " 'dw_studio', true)"
            " ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=OBJECTS_MANAGE, l="Quản trị đối tượng và trường của công ty")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
        ).bindparams(k=OBJECTS_MANAGE)
    )
    op.execute(
        sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=OBJECTS_MANAGE)
    )
    op.execute("DELETE FROM studio.artifact_kinds WHERE kind = 'object'")
    op.execute("DROP TRIGGER refuse_object_artifact_delete ON studio.artifacts")
    op.execute("DROP FUNCTION studio.refuse_object_artifact_delete()")
    op.execute("DROP INDEX studio.ix_dependencies_tenant_id_to_field_id")
    op.execute("ALTER TABLE studio.dependencies DROP COLUMN to_field_id")
    for table in ("records", "picklist_options", "field_defs", "object_defs"):
        op.execute(f"DROP TABLE studio.{table}")
