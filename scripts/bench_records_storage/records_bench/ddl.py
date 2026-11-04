"""DDL of every variant the ticket measures, rendered from one place.

Not an Alembic revision: it runs on the scratch database `dw_bench` after the
migration head (ticket 01 step 2). `studio.artifacts` is the head's own
(tenant-config/02, revision 67071483caa6); the `object` row of
`studio.artifact_kinds` that custom-objects/02 registers, groups, the manager
tree, shares, sharing rules, `studio.principal_scopes` and the `studio.acl_*`
functions of record-access are not at the head yet and are minimal stand-ins,
marked `STAND-IN`; each principal's reach arrays are computed by the seeder in the
shape of ADR-0105 decision 4, so the cost of computing reach stays
record-access/01's (MEDIUM (b) of the gate).

Variants (ticket 01 step 2):
- A0: the W1 DDL of the spec's Data section, three policy arms.
- A1: A0 plus W2's known part (GIN `read_grants`, `name_key`, slots `l`, `m` with
  composite FKs) and the six-arm policy. A1 decides the modulus.
- A2: A1 with a BRIN index on `updated_at` instead of the btree.
- A3: A1 without the indexes of family `b`.
- C: a narrow typed pivot, each pivot row carrying the record's reach; write
  path and maintenance only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .model import W1_FAMILIES, W2_FAMILIES, slots_of

UpdatedAtIndex = Literal["btree", "brin", "none"]


@dataclass(frozen=True)
class Variant:
    name: str
    w2: bool  # W2's known part: name_key, grants, l/m slots, six arms
    updated_at_index: UpdatedAtIndex = "btree"
    b_indexes: bool = True
    pivot: bool = False
    reads: bool = True  # in the read matrix (R9.1, R9.2, R9.8, R9.9, HOT)
    writes: bool = False  # in the write and maintenance matrix (R9.6, R9.7, R9.10-R9.12)

    @property
    def families(self) -> dict[str, tuple[str, int]]:
        return {**W1_FAMILIES, **W2_FAMILIES} if self.w2 else dict(W1_FAMILIES)

    @property
    def slots(self) -> list[tuple[str, str, str]]:
        return [] if self.pivot else slots_of(self.families)

    @property
    def indexed_slots(self) -> list[str]:
        return [s for s, fam, _t in self.slots if self.b_indexes or fam != "b"]


VARIANTS: dict[str, Variant] = {
    "A0": Variant("A0", w2=False),
    "A1": Variant("A1", w2=True, writes=True),
    "A2": Variant("A2", w2=True, updated_at_index="brin"),
    "A3": Variant("A3", w2=True, b_indexes=False),
    "C": Variant("C", w2=True, pivot=True, reads=False, writes=True),
}
MODULI = (8, 4)
PIVOT_FAMILIES = ("t", "u", "i", "f", "d", "z", "b", "l", "m")

TENANT = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
# The per-row form of db/migrations/sql/0001_platform_baseline.sql, kept for the
# InitPlan comparison of step 5 ("giữ các phép đo cũ").
TENANT_PER_ROW = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
SCOPE = "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'"


@dataclass
class Ddl:
    schema: list[str] = field(default_factory=list)  # before the seed
    post_load: list[str] = field(default_factory=list)  # indexes, keys, ANALYZE
    indexes: list[str] = field(default_factory=list)  # names, for R9.4's count


def partitions(table: str, modulus: int) -> list[str]:
    return [f"{table}_p{r}" for r in range(modulus)]


# ------------------------------------------------------------ stand-ins (SQL) --
STUB_FUNCTIONS = """
CREATE FUNCTION studio.bench_uuid(kind integer, tenant_idx integer, n bigint) RETURNS uuid
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT (lpad(to_hex(kind), 4, '0') || lpad(to_hex(tenant_idx), 12, '0')
                  || lpad(to_hex(n), 16, '0'))::uuid $$;
CREATE FUNCTION studio.bench_record_id(tenant_idx integer, n bigint, created timestamptz)
    RETURNS uuid
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT (lpad(to_hex((extract(epoch FROM created) * 1000)::bigint), 12, '0') || '7'
                  || lpad(to_hex(tenant_idx), 3, '0') || '8' || lpad(to_hex(n), 15, '0'))::uuid $$;
"""

ORG_STUBS = """
-- STAND-IN for org-and-principals and record-access tables the six-arm policy
-- reads through the closure; the seeder fills them so record-access/01 seeds
-- nothing of its own (ticket 01 step 3).
CREATE TABLE studio.bench_people (
    tenant_id uuid NOT NULL, id uuid NOT NULL, person_no integer NOT NULL,
    manager_id uuid, home_workspace_id uuid NOT NULL, depth integer NOT NULL,
    CONSTRAINT pk_bench_people PRIMARY KEY (tenant_id, id));
CREATE TABLE studio.bench_workspace_tree (
    tenant_id uuid NOT NULL, workspace_id uuid NOT NULL, parent_id uuid, depth integer NOT NULL,
    CONSTRAINT pk_bench_workspace_tree PRIMARY KEY (tenant_id, workspace_id));
CREATE TABLE studio.bench_teams (
    tenant_id uuid NOT NULL, id uuid NOT NULL, workspace_id uuid NOT NULL,
    CONSTRAINT pk_bench_teams PRIMARY KEY (tenant_id, id));
CREATE TABLE studio.bench_team_members (
    tenant_id uuid NOT NULL, team_id uuid NOT NULL, person_id uuid NOT NULL,
    CONSTRAINT pk_bench_team_members PRIMARY KEY (tenant_id, team_id, person_id));
CREATE TABLE studio.record_shares (
    tenant_id uuid NOT NULL, record_id uuid NOT NULL, principal_id uuid NOT NULL,
    access text NOT NULL CHECK (access IN ('read', 'edit')), expires_at timestamptz,
    CONSTRAINT pk_record_shares PRIMARY KEY (tenant_id, record_id, principal_id));
CREATE TABLE studio.sharing_rule_versions (
    tenant_id uuid NOT NULL, id uuid NOT NULL, object_id uuid NOT NULL, condition text NOT NULL,
    target_id uuid NOT NULL, access text NOT NULL,
    CONSTRAINT pk_sharing_rule_versions PRIMARY KEY (tenant_id, id));
REVOKE ALL ON studio.bench_people, studio.bench_workspace_tree, studio.bench_teams,
    studio.bench_team_members, studio.record_shares, studio.sharing_rule_versions FROM dw_app;
"""

DEFINITIONS = """
-- STAND-IN for the kind row custom-objects/02 registers; studio.artifacts itself
-- is the head's (tenant-config/02).
INSERT INTO studio.artifact_kinds (kind, has_quality_gate) VALUES ('object', false)
    ON CONFLICT (kind) DO NOTHING;
CREATE TABLE studio.object_defs (
    tenant_id uuid NOT NULL, id uuid NOT NULL, api_name text NOT NULL,
    labels jsonb NOT NULL, default_access text NOT NULL DEFAULT 'private',
    ai_description text, schema_version integer NOT NULL DEFAULT 1,
    next_field_no integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(), created_by uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(), updated_by uuid NOT NULL,
    CONSTRAINT pk_object_defs PRIMARY KEY (tenant_id, id),
    CONSTRAINT uq_object_defs_tenant_id_api_name UNIQUE (tenant_id, api_name),
    CONSTRAINT fk_object_defs_tenant_id_artifacts FOREIGN KEY (tenant_id, id)
        REFERENCES studio.artifacts (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_object_defs_api_name CHECK (api_name ~ '^[a-z][a-z0-9_]{1,39}$'),
    CONSTRAINT ck_object_defs_labels CHECK (coalesce(labels ->> 'vi', '') <> ''),
    CONSTRAINT ck_object_defs_default_access
        CHECK (default_access IN ('private', 'public_read', 'public_read_write')),
    CONSTRAINT ck_object_defs_ai_description CHECK (char_length(ai_description) <= 500),
    CONSTRAINT ck_object_defs_schema_version CHECK (schema_version >= 1),
    CONSTRAINT ck_object_defs_next_field_no CHECK (next_field_no >= 1));
CREATE TABLE studio.field_defs (
    tenant_id uuid NOT NULL, id uuid NOT NULL, object_id uuid NOT NULL, api_name text NOT NULL,
    type text NOT NULL, pd_category text NOT NULL DEFAULT 'none', storage_kind text NOT NULL,
    slot text, field_no integer NOT NULL, required boolean NOT NULL DEFAULT false,
    is_unique boolean NOT NULL DEFAULT false, indexed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(), created_by uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(), updated_by uuid NOT NULL,
    CONSTRAINT pk_field_defs PRIMARY KEY (tenant_id, id),
    CONSTRAINT fk_field_defs_tenant_id_object_defs FOREIGN KEY (tenant_id, object_id)
        REFERENCES studio.object_defs (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT uq_field_defs_tenant_id_object_id_api_name UNIQUE (tenant_id, object_id, api_name),
    CONSTRAINT uq_field_defs_tenant_id_object_id_field_no UNIQUE (tenant_id, object_id, field_no),
    CONSTRAINT ck_field_defs_storage_kind CHECK (storage_kind IN ('system', 'slot', 'data')),
    CONSTRAINT ck_field_defs_slot CHECK (slot ~ '^(t|u|i|f|d|z|b|l|m)[0-9]{2}$'));
CREATE UNIQUE INDEX uq_field_defs_tenant_id_object_id_slot
    ON studio.field_defs (tenant_id, object_id, slot) WHERE slot IS NOT NULL;
CREATE INDEX ix_field_defs_tenant_id_object_id ON studio.field_defs (tenant_id, object_id);
"""

PRINCIPAL_SCOPES = """
-- STAND-IN for record-access's studio.principal_scopes: one row per principal,
-- action and arm here (ADR-0105 decision 4 keeps one row per principal with one
-- array per action and arm; same arrays, read the same way, once per statement).
CREATE TABLE studio.principal_scopes (
    tenant_id uuid NOT NULL, principal_id uuid NOT NULL, action text NOT NULL, arm text NOT NULL,
    ids uuid[] NOT NULL,
    CONSTRAINT pk_principal_scopes PRIMARY KEY (tenant_id, principal_id, action, arm));
CREATE FUNCTION studio.acl_tenant() RETURNS uuid LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;
CREATE FUNCTION studio.acl_user() RETURNS uuid LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
CREATE FUNCTION studio.acl_actor_kind() RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT CASE WHEN current_setting('app.actor_kind', true) IN ('user', 'agent', 'workflow')
                 THEN current_setting('app.actor_kind', true) ELSE '' END $$;
-- One level each, settings read inline: a LANGUAGE sql function with SET
-- search_path is not inlined and is planned again at every call in PostgreSQL
-- 16, so a stand-in calling a stand-in would charge reach its own nesting
-- (measured 2026-11-02: 0.9 ms a call nested, 0.16 ms flat).
CREATE FUNCTION studio.acl_objects(p_action text, p_depth text) RETURNS uuid[]
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT coalesce((SELECT s.ids FROM studio.principal_scopes s
             WHERE s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
               AND s.principal_id = NULLIF(current_setting('app.user_id', true), '')::uuid
               AND s.action = p_action AND s.arm = 'objects:' || p_depth), '{}'::uuid[]) $$;
CREATE FUNCTION studio.acl_keys(p_action text) RETURNS uuid[]
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT coalesce((SELECT s.ids FROM studio.principal_scopes s
             WHERE s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
               AND s.principal_id = NULLIF(current_setting('app.user_id', true), '')::uuid
               AND s.action = p_action AND s.arm = 'keys'), '{}'::uuid[]) $$;
CREATE FUNCTION studio.acl_owners(p_action text, p_kind text) RETURNS uuid[]
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT coalesce((SELECT s.ids FROM studio.principal_scopes s
             WHERE s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
               AND s.principal_id = NULLIF(current_setting('app.user_id', true), '')::uuid
               AND s.action = p_action AND s.arm = 'owners:' || p_kind), '{}'::uuid[]) $$;
CREATE FUNCTION studio.acl_grant_keys(p_action text) RETURNS uuid[]
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT coalesce((SELECT s.ids FROM studio.principal_scopes s
             WHERE s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
               AND s.principal_id = NULLIF(current_setting('app.user_id', true), '')::uuid
               AND s.action = p_action AND s.arm = 'grants'), '{}'::uuid[]) $$;
CREATE FUNCTION studio.acl_workspaces(p_action text) RETURNS uuid[]
    LANGUAGE sql STABLE SET search_path = pg_catalog
    AS $$ SELECT coalesce((SELECT s.ids FROM studio.principal_scopes s
             WHERE s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
               AND s.principal_id = NULLIF(current_setting('app.user_id', true), '')::uuid
               AND s.action = p_action AND s.arm = 'workspaces'), '{}'::uuid[]) $$;
ALTER TABLE studio.principal_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio.principal_scopes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_principal_scopes ON studio.principal_scopes
    USING (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
           AND principal_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid));
GRANT SELECT ON studio.principal_scopes TO dw_app;
"""

ACL_FUNCTIONS = (
    "studio.acl_tenant()",
    "studio.acl_user()",
    "studio.acl_actor_kind()",
    "studio.acl_objects(text, text)",
    "studio.acl_keys(text)",
    "studio.acl_owners(text, text)",
    "studio.acl_grant_keys(text)",
    "studio.acl_workspaces(text)",
)

SEARCH_KEY = """
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE FUNCTION studio.search_key(t text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, t COLLATE "C")) $$;
"""

WRITE_KEYS = f"""
CREATE TABLE studio.record_write_keys (
    tenant_id uuid NOT NULL, write_key text NOT NULL, record_id uuid NOT NULL, op text NOT NULL,
    version integer NOT NULL, created boolean NOT NULL DEFAULT false,
    owner_kind text, owner_id uuid, workspace_id uuid, actor_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_record_write_keys PRIMARY KEY (tenant_id, write_key),
    CONSTRAINT ck_record_write_keys_write_key
        CHECK (octet_length(write_key) BETWEEN 1 AND 255 AND write_key LIKE 'wf:%'),
    CONSTRAINT ck_record_write_keys_op CHECK (op IN ('update', 'upsert', 'assign')),
    CONSTRAINT ck_record_write_keys_version CHECK (version >= 1),
    CONSTRAINT ck_record_write_keys_assign CHECK (
        op <> 'assign'
        OR (owner_kind IS NOT NULL AND owner_id IS NOT NULL AND workspace_id IS NOT NULL)));
ALTER TABLE studio.record_write_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio.record_write_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_record_write_keys ON studio.record_write_keys
    USING ({TENANT}) WITH CHECK ({TENANT});
CREATE POLICY owner_record_write_keys ON studio.record_write_keys AS RESTRICTIVE
    USING ({TENANT} AND (actor_id = (SELECT studio.acl_user()) OR {SCOPE}))
    WITH CHECK ({TENANT} AND (actor_id = (SELECT studio.acl_user()) OR {SCOPE}));
REVOKE ALL ON studio.record_write_keys FROM dw_app;
GRANT SELECT, INSERT, DELETE ON studio.record_write_keys TO dw_app;
"""

WRITE_KEYS_POST_LOAD = [
    "ALTER TABLE studio.record_write_keys ADD CONSTRAINT fk_record_write_keys_tenant_id_records"
    " FOREIGN KEY (tenant_id, record_id) REFERENCES studio.records (tenant_id, id) ON DELETE"
    " CASCADE",
    "CREATE INDEX ix_record_write_keys_tenant_id_record_id ON studio.record_write_keys (tenant_id,"
    " record_id)",
]


# ------------------------------------------------------------------ policies --
def _arms(action: str, w2: bool, grants_column: str) -> list[str]:
    arms = [
        f"object_id = ANY ((SELECT studio.acl_objects('{action}', 'tenant'))::uuid[])",
        f"access_key = ANY ((SELECT studio.acl_keys('{action}'))::uuid[])",
        f"(owner_id = (SELECT studio.acl_user())"
        f" AND object_id = ANY ((SELECT studio.acl_objects('{action}', 'own'))::uuid[]))",
    ]
    if w2 and action in ("read", "update"):
        own = f"object_id = ANY ((SELECT studio.acl_objects('{action}', 'own'))::uuid[])"
        arms += [
            f"(owner_id = ANY ((SELECT studio.acl_owners('{action}', 'team'))::uuid[]) AND {own})",
            f"(owner_id = ANY ((SELECT studio.acl_owners('{action}', 'subordinate'))::uuid[]) AND"
            f" {own})",
            f"{grants_column} && (SELECT studio.acl_grant_keys('{action}'))::uuid[]",
        ]
    return arms


def _insert_arms() -> list[str]:
    return [
        "object_id = ANY ((SELECT studio.acl_objects('create', 'tenant'))::uuid[])",
        "access_key = ANY ((SELECT studio.acl_keys('create'))::uuid[])",
        "(owner_id = (SELECT studio.acl_user())"
        " AND object_id = ANY ((SELECT studio.acl_objects('create', 'own'))::uuid[])"
        " AND workspace_id = ANY ((SELECT studio.acl_workspaces('create'))::uuid[]))",
    ]


def actor_ok(w2: bool) -> str:
    # W1 admits people only (record-access/03 step 4); W2 adds agents and
    # workflows, whose boundary is already folded into their own arrays here.
    if w2:
        return "(SELECT studio.acl_actor_kind()) IN ('user', 'agent', 'workflow')"
    return "(SELECT studio.acl_actor_kind()) = 'user'"


def access_expr(arms: list[str], w2: bool) -> str:
    reach = "\n            OR ".join(arms)
    return f"{TENANT} AND ({SCOPE} OR ({actor_ok(w2)} AND (\n            {reach})))"


def record_policies(table: str, short: str, w2: bool) -> list[str]:
    """The template of ADR-0105 decision 1 for one table or partition."""
    select = access_expr(_arms("read", w2, "read_grants"), w2)
    update = access_expr(_arms("update", w2, "edit_grants"), w2)
    delete = access_expr(_arms("delete", w2, "read_grants"), w2)
    insert = access_expr(_insert_arms(), w2)
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{short} ON {table} AS RESTRICTIVE"
        f" USING ({TENANT}) WITH CHECK ({TENANT})",
        f"CREATE POLICY record_access_{short}_select ON {table} FOR SELECT USING ({select})",
        f"CREATE POLICY record_access_{short}_insert ON {table} FOR INSERT WITH CHECK ({insert})",
        f"CREATE POLICY record_access_{short}_update ON {table} FOR UPDATE"
        f" USING ({update}) WITH CHECK ({update})",
        f"CREATE POLICY record_access_{short}_delete ON {table} FOR DELETE USING ({delete})",
    ]


# ------------------------------------------------------------------- records --
def _system_columns(w2: bool) -> list[str]:
    cols = [
        "id uuid NOT NULL",
        "tenant_id uuid NOT NULL",
        "object_id uuid NOT NULL",
        "workspace_id uuid NOT NULL",
        "owner_kind text NOT NULL",
        "owner_id uuid NOT NULL",
        'name text COLLATE "vi-VN-x-icu" NOT NULL',
    ]
    if w2:
        cols.append(
            'name_key text COLLATE "C" GENERATED ALWAYS AS (studio.search_key(name)) STORED'
        )
    cols += [
        "version integer NOT NULL DEFAULT 1",
        "create_key text",
        "data jsonb NOT NULL DEFAULT '{}'::jsonb",
    ]
    return cols


def _tail_columns(w2: bool) -> list[str]:
    cols = []
    if w2:
        cols += [
            "read_grants uuid[] NOT NULL DEFAULT '{}'::uuid[]",
            "edit_grants uuid[] NOT NULL DEFAULT '{}'::uuid[]",
            "grants_valid_until timestamptz",
        ]
    cols += [
        "access_key uuid GENERATED ALWAYS AS (md5(object_id::text || '/' ||"
        " workspace_id::text)::uuid) STORED",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "created_by uuid NOT NULL",
        "updated_at timestamptz NOT NULL DEFAULT now()",
        "updated_by uuid NOT NULL",
        "deleted_at timestamptz",
        "deleted_by uuid",
    ]
    return cols


def _record_checks(variant: Variant) -> list[str]:
    checks = [
        "CONSTRAINT ck_records_owner_kind CHECK (owner_kind IN ('user', 'team'))",
        "CONSTRAINT ck_records_name CHECK (char_length(name) BETWEEN 1 AND 255)",
        "CONSTRAINT ck_records_version CHECK (version >= 1)",
        "CONSTRAINT ck_records_create_key CHECK (octet_length(create_key) <= 255)",
        "CONSTRAINT ck_records_data CHECK (jsonb_typeof(data) = 'object' AND pg_column_size(data)"
        " <= 32768)",
    ]
    checks += [
        f"CONSTRAINT ck_records_{slot} CHECK (octet_length({slot}) <= 1024)"
        for slot, family, _t in variant.slots
        if family in ("t", "u")
    ]
    if variant.w2:
        checks.append(
            "CONSTRAINT ck_records_grants_bounded CHECK"
            " (cardinality(read_grants) <= 200 AND edit_grants <@ read_grants)"
        )
    return checks


def updatable_columns(variant: Variant) -> list[str]:
    """What `dw_app` may UPDATE (spec, Data: name, data, slots, version, updated_*, deleted_*)."""
    return [
        "name",
        "data",
        *[s for s, _f, _t in variant.slots],
        "version",
        "updated_at",
        "updated_by",
        "deleted_at",
        "deleted_by",
    ]


def records_ddl(variant: Variant, modulus: int) -> Ddl:
    out = Ddl()
    cols = _system_columns(variant.w2)
    cols += [f"{slot} {sql_type}" for slot, _f, sql_type in variant.slots]
    cols += _tail_columns(variant.w2)
    body = ",\n    ".join(cols + _record_checks(variant))
    out.schema.append(f"CREATE TABLE studio.records (\n    {body}\n) PARTITION BY HASH (tenant_id)")
    for r, part in enumerate(partitions("studio.records", modulus)):
        out.schema.append(
            f"CREATE TABLE {part} PARTITION OF studio.records FOR VALUES WITH (MODULUS {modulus},"
            f" REMAINDER {r})"
        )
    for table in ["studio.records", *partitions("studio.records", modulus)]:
        out.schema += record_policies(table, table.split(".")[1], variant.w2)
    out.schema += [
        "REVOKE ALL ON studio.records FROM dw_app",
        "GRANT SELECT, INSERT, DELETE ON studio.records TO dw_app",
        f"GRANT UPDATE ({', '.join(updatable_columns(variant))}) ON studio.records TO dw_app",
        *[f"REVOKE ALL ON {p} FROM dw_app" for p in partitions("studio.records", modulus)],
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON studio.records"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
    ]

    def index(name: str, sql: str) -> None:
        out.indexes.append(name)
        out.post_load.append(sql.format(name=name))

    out.post_load.append(
        "ALTER TABLE studio.records ADD CONSTRAINT pk_records PRIMARY KEY (tenant_id, id)"
    )
    out.indexes.append("pk_records")
    index(
        "uq_records_tenant_id_object_id_create_key",
        "CREATE UNIQUE INDEX {name} ON studio.records (tenant_id, object_id, create_key)"
        " WHERE create_key IS NOT NULL",
    )
    index(
        "ix_records_tenant_id_object_id_created_at",
        "CREATE INDEX {name} ON studio.records (tenant_id, object_id, created_at DESC, id DESC)",
    )
    if variant.updated_at_index == "btree":
        index(
            "ix_records_tenant_id_object_id_updated_at",
            "CREATE INDEX {name} ON studio.records (tenant_id, object_id, updated_at DESC, id"
            " DESC)",
        )
    elif variant.updated_at_index == "brin":
        index(
            "ix_records_updated_at", "CREATE INDEX {name} ON studio.records USING brin (updated_at)"
        )
    index(
        "ix_records_tenant_id_object_id_name",
        "CREATE INDEX {name} ON studio.records (tenant_id, object_id, name, id)",
    )
    index(
        "ix_records_tenant_id_workspace_id",
        "CREATE INDEX {name} ON studio.records (tenant_id, workspace_id)",
    )
    index(
        "ix_records_tenant_id_access_key",
        "CREATE INDEX {name} ON studio.records (tenant_id, access_key, created_at DESC, id DESC)",
    )
    index(
        "ix_records_tenant_id_owner_id",
        "CREATE INDEX {name} ON studio.records (tenant_id, owner_id, object_id, created_at DESC,"
        " id DESC)",
    )
    for slot in variant.indexed_slots:
        index(
            f"ix_records_{slot}",
            f"CREATE INDEX {{name}} ON studio.records (tenant_id, object_id, {slot}, id)"
            f" WHERE {slot} IS NOT NULL AND deleted_at IS NULL",
        )
    for slot, family, _t in variant.slots:
        if family == "u":
            index(
                f"uq_records_tenant_id_object_id_{slot}",
                f"CREATE UNIQUE INDEX {{name}} ON studio.records (tenant_id, object_id, {slot})"
                f" WHERE {slot} IS NOT NULL AND deleted_at IS NULL",
            )
    if variant.w2:
        index(
            "ix_records_read_grants",
            "CREATE INDEX {name} ON studio.records USING gin (read_grants)",
        )
        index(
            "ix_records_tenant_id_object_id_name_key",
            "CREATE INDEX {name} ON studio.records (tenant_id, object_id, name_key, id)",
        )
        for slot, family, _t in variant.slots:
            if family in ("l", "m"):
                # The slot index leads with object_id, so the FK's own-side index
                # is its own (CLAUDE.md, every FK indexed on its own side).
                index(
                    f"ix_records_tenant_id_{slot}",
                    f"CREATE INDEX {{name}} ON studio.records (tenant_id, {slot}) WHERE {slot} IS"
                    " NOT NULL",
                )
    out.post_load += [
        "ALTER TABLE studio.records ADD CONSTRAINT fk_records_tenant_id_object_defs"
        " FOREIGN KEY (tenant_id, object_id) REFERENCES studio.object_defs (tenant_id, id) ON"
        " DELETE RESTRICT",
        "ALTER TABLE studio.records ADD CONSTRAINT fk_records_tenant_id_workspaces"
        " FOREIGN KEY (tenant_id, workspace_id) REFERENCES platform.workspaces (tenant_id, id) ON"
        " DELETE RESTRICT",
    ]
    for slot, family, _t in variant.slots:
        if family in ("l", "m"):
            on_delete = f"SET NULL ({slot})" if family == "l" else "CASCADE"
            out.post_load.append(
                f"ALTER TABLE studio.records ADD CONSTRAINT fk_records_{slot}_records"
                f" FOREIGN KEY (tenant_id, {slot}) REFERENCES studio.records (tenant_id, id) ON"
                f" DELETE {on_delete}"
            )
    if variant.pivot:
        _pivot_ddl(out, variant, modulus)
    return out


def _pivot_ddl(out: Ddl, variant: Variant, modulus: int) -> None:
    """C: one typed table per family, each row carrying the record's reach."""
    families = variant.families
    for fam in PIVOT_FAMILIES:
        sql_type = families[fam][0]
        table = f"studio.record_values_{fam}"
        out.schema.append(
            f"CREATE TABLE {table} (\n"
            "    tenant_id uuid NOT NULL, object_id uuid NOT NULL, record_id uuid NOT NULL,"
            " field_id uuid NOT NULL,\n"
            f"    value {sql_type} NOT NULL, workspace_id uuid NOT NULL, owner_kind text NOT NULL,"
            " owner_id uuid NOT NULL,\n"
            "    access_key uuid NOT NULL, read_grants uuid[] NOT NULL DEFAULT '{}'::uuid[],"
            " edit_grants uuid[] NOT NULL DEFAULT '{}'::uuid[]\n"
            ") PARTITION BY HASH (tenant_id)"
        )
        for r, part in enumerate(partitions(table, modulus)):
            out.schema.append(
                f"CREATE TABLE {part} PARTITION OF {table} FOR VALUES WITH (MODULUS {modulus},"
                f" REMAINDER {r})"
            )
        for t in [table, *partitions(table, modulus)]:
            out.schema += record_policies(t, t.split(".")[1], True)
        out.schema += [
            f"REVOKE ALL ON {table} FROM dw_app",
            f"GRANT SELECT, INSERT, UPDATE (value), DELETE ON {table} TO dw_app",
            *[f"REVOKE ALL ON {p} FROM dw_app" for p in partitions(table, modulus)],
        ]
        short = f"record_values_{fam}"
        out.post_load.append(
            f"ALTER TABLE {table} ADD CONSTRAINT pk_{short} PRIMARY KEY (tenant_id, record_id,"
            " field_id)"
        )
        out.indexes.append(f"pk_{short}")
        if fam == "u":
            name = f"uq_{short}_tenant_id_object_id_field_id_value"
            out.post_load.append(
                f"CREATE UNIQUE INDEX {name} ON {table} (tenant_id, object_id, field_id, value)"
            )
        else:
            name = f"ix_{short}_tenant_id_object_id_field_id_value"
            out.post_load.append(
                f"CREATE INDEX {name} ON {table} (tenant_id, object_id, field_id, value, record_id)"
            )
        out.indexes.append(name)
        out.post_load.append(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{short}_tenant_id_records FOREIGN KEY"
            " (tenant_id, record_id)"
            " REFERENCES studio.records (tenant_id, id) ON DELETE CASCADE"
        )
        if fam in ("l", "m"):
            name = f"ix_{short}_tenant_id_value"
            out.post_load.append(f"CREATE INDEX {name} ON {table} (tenant_id, value)")
            out.indexes.append(name)
            on_delete = "CASCADE"  # a pivot row of a deleted target goes with it
            out.post_load.append(
                f"ALTER TABLE {table} ADD CONSTRAINT fk_{short}_value_records FOREIGN KEY"
                " (tenant_id, value)"
                f" REFERENCES studio.records (tenant_id, id) ON DELETE {on_delete}"
            )


def cell_ddl(variant: Variant, modulus: int) -> Ddl:
    """Everything one (variant, modulus) cell runs, in order."""
    out = Ddl()
    out.schema += [STUB_FUNCTIONS, ORG_STUBS, DEFINITIONS, PRINCIPAL_SCOPES]
    if variant.w2:
        out.schema.append(SEARCH_KEY)
    out.schema += [
        "ALTER TABLE studio.object_defs ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE studio.object_defs FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_object_defs ON studio.object_defs USING ({TENANT}) WITH"
        f" CHECK ({TENANT})",
        "ALTER TABLE studio.field_defs ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE studio.field_defs FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_field_defs ON studio.field_defs USING ({TENANT}) WITH"
        f" CHECK ({TENANT})",
    ]
    records = records_ddl(variant, modulus)
    out.schema += records.schema
    out.schema.append(WRITE_KEYS)
    out.post_load += records.post_load + WRITE_KEYS_POST_LOAD
    out.indexes += records.indexes
    return out
