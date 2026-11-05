"""actor boundaries and the run's actor at every door

Revision ID: 996c234cfde3
Revises: 2c2095fbb4c7
Create Date: 2026-11-05 14:00:00.000000+00:00

record-access ticket 04 (R6.3-R6.15; RA18-RA21, RA27; ADR-0103 decisions 4
and 5, ADR-0105 decision 6 with its 2026-11-04 refinement, ADR-0109 decision
6). An agent or a workflow reads and writes records with its principal's live
reach, intersected with the data boundary its version fixed at publish, or,
for a `simulate` run whose root is not live yet, with the provisional boundary
its run door recorded for that run alone:

- `studio.actor_boundaries`, `studio.actor_boundary_objects`,
  `studio.actor_boundary_fields`: one boundary per published (kind, version,
  definition hash), or one per `simulate` run (`run_id` set); its objects with
  a flag per command, its fields with `read` or `edit`. Tenant-wide rows (no
  `workspace_id`, DO-01). `dw_app` holds SELECT and DELETE and no INSERT or
  UPDATE: every write is `studio.record_actor_boundary`'s (gate (i)).
- `refuse_boundary_change` on the three tables, raising
  `ck_actor_boundaries_frozen`: UPDATE always, the owner included; DELETE of a
  published boundary's row unless the company is `offboarding`. A provisional
  boundary is deleted at any time, its rows by cascade (R6.8, R6.15). SECURITY
  DEFINER, so the company's status and the parent row are read whatever the
  caller's settings; a company already gone (its own row's cascade) is let
  through, as `platform.guard_control_switch()` does.
- `ck_actor_boundaries_provisional_run`: a provisional boundary names a
  `simulate` run of its own company, read with `tenant_id = NEW.tenant_id`
  stated, since the insert runs inside the definer (R6.14).
- `studio.record_actor_boundary(kind, source_id, source_version, run_id,
  objects, fields)`: SECURITY DEFINER, the tenant from `app.tenant_id`; the
  version is one of the tenant's, and a published boundary's hash is the
  version's `definition_hash`; each `api_name` becomes an id, an unknown one
  refused for a published boundary (23503) and left out of a provisional one
  (a draft's object not applied yet, gate (o)).
- `studio.boundary_chain(run_id)`: the run and every parent, root first, each
  link's provisional boundary or else the published one of its (kind,
  version, hash); `'{}'` when a link has none or the chain does not reach a
  root (R6.5; gate (b), (f), (l)). Invoker, under the bound tenant.
- `studio.acl_boundary_objects(cmd)`: the objects whose flag for `cmd` every
  boundary of `app.boundary_id` holds; `'{}'` for an empty or malformed list,
  an id that is no boundary of the bound tenant, or a provisional boundary
  outside `app.run_mode = 'simulate'` (R6.4, R6.5, R6.13; gate (j)).
- The four PERMISSIVE record policies on `studio.records` and each partition
  (from `pg_inherits`), altered in place: `actor_ok` admits `user`, or `agent`
  and `workflow` for an object in the boundary for the policy's command; the
  soft delete in `_update`'s WITH CHECK asks `delete`. The text is copied from
  `dw_studio.records.adapters.record_policy` as it renders now;
  `test_record_policies.py` compares the catalog with the module.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "996c234cfde3"
down_revision = "2c2095fbb4c7"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT_POLICY = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"

# -- the tables -----------------------------------------------------------------

_TABLES = (
    """
    CREATE TABLE studio.actor_boundaries (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        kind text NOT NULL,
        source_id uuid NOT NULL,
        source_version text NOT NULL,
        run_id uuid,
        created_at timestamp with time zone NOT NULL DEFAULT now(),
        CONSTRAINT pk_actor_boundaries PRIMARY KEY (tenant_id, id),
        CONSTRAINT fk_actor_boundaries_tenant_id_tenants
            FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id) ON DELETE CASCADE,
        CONSTRAINT ck_actor_boundaries_kind CHECK (kind IN ('agent', 'workflow')),
        CONSTRAINT ck_actor_boundaries_source_version CHECK (btrim(source_version) <> '')
    )
    """,
    """
    CREATE TABLE studio.actor_boundary_objects (
        tenant_id uuid NOT NULL,
        boundary_id uuid NOT NULL,
        object_id uuid NOT NULL,
        can_read boolean NOT NULL,
        can_create boolean NOT NULL,
        can_update boolean NOT NULL,
        can_delete boolean NOT NULL,
        can_assign boolean NOT NULL,
        CONSTRAINT pk_actor_boundary_objects PRIMARY KEY (tenant_id, boundary_id, object_id),
        CONSTRAINT fk_actor_boundary_objects_boundary_id_actor_boundaries
            FOREIGN KEY (tenant_id, boundary_id)
            REFERENCES studio.actor_boundaries (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_actor_boundary_objects_object_id_object_defs
            FOREIGN KEY (tenant_id, object_id)
            REFERENCES studio.object_defs (tenant_id, id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE studio.actor_boundary_fields (
        tenant_id uuid NOT NULL,
        boundary_id uuid NOT NULL,
        field_id uuid NOT NULL,
        access text NOT NULL,
        CONSTRAINT pk_actor_boundary_fields PRIMARY KEY (tenant_id, boundary_id, field_id),
        CONSTRAINT fk_actor_boundary_fields_boundary_id_actor_boundaries
            FOREIGN KEY (tenant_id, boundary_id)
            REFERENCES studio.actor_boundaries (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_actor_boundary_fields_field_id_field_defs
            FOREIGN KEY (tenant_id, field_id)
            REFERENCES studio.field_defs (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_actor_boundary_fields_access CHECK (access IN ('read', 'edit'))
    )
    """,
)

_INDEXES = (
    # One boundary per published (kind, version, hash), the lookup of
    # `studio.boundary_chain`; one provisional boundary per run, its lookup.
    "CREATE UNIQUE INDEX uq_actor_boundaries_tenant_id_kind_source_id_source_version"
    " ON studio.actor_boundaries (tenant_id, kind, source_id, source_version)"
    " WHERE run_id IS NULL",
    "CREATE UNIQUE INDEX uq_actor_boundaries_tenant_id_run_id"
    " ON studio.actor_boundaries (tenant_id, run_id) WHERE run_id IS NOT NULL",
    # The RESTRICT keys' own side (CLAUDE.md, Data model rules).
    "CREATE INDEX ix_actor_boundary_objects_tenant_id_object_id"
    " ON studio.actor_boundary_objects (tenant_id, object_id)",
    "CREATE INDEX ix_actor_boundary_fields_tenant_id_field_id"
    " ON studio.actor_boundary_fields (tenant_id, field_id)",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
_RLS = (
    "ALTER TABLE studio.actor_boundaries ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.actor_boundaries FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_actor_boundaries ON studio.actor_boundaries"
    f" USING {_TENANT_POLICY} WITH CHECK {_TENANT_POLICY}",
    "ALTER TABLE studio.actor_boundary_objects ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.actor_boundary_objects FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_actor_boundary_objects ON studio.actor_boundary_objects"
    f" USING {_TENANT_POLICY} WITH CHECK {_TENANT_POLICY}",
    "ALTER TABLE studio.actor_boundary_fields ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.actor_boundary_fields FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_actor_boundary_fields ON studio.actor_boundary_fields"
    f" USING {_TENANT_POLICY} WITH CHECK {_TENANT_POLICY}",
)

_TABLE_NAMES = (
    "studio.actor_boundaries",
    "studio.actor_boundary_objects",
    "studio.actor_boundary_fields",
)

# -- the triggers ---------------------------------------------------------------

_FROZEN = """
    CREATE FUNCTION studio.refuse_boundary_change() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_status text;
        v_run uuid;
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'a data boundary never changes once recorded'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_actor_boundaries_frozen';
        END IF;
        SELECT t.status INTO v_status FROM platform.tenants t WHERE t.id = OLD.tenant_id;
        -- The company leaving, or already gone (its own row's cascade).
        IF NOT FOUND OR v_status = 'offboarding' THEN
            RETURN OLD;
        END IF;
        IF TG_TABLE_NAME = 'actor_boundaries' THEN
            -- A provisional boundary goes at any time (R6.15).
            IF OLD.run_id IS NOT NULL THEN
                RETURN OLD;
            END IF;
        ELSE
            -- A row of a provisional boundary, or the cascade of a parent's
            -- delete that the parent's own trigger let through.
            SELECT b.run_id INTO v_run FROM studio.actor_boundaries b
            WHERE b.tenant_id = OLD.tenant_id AND b.id = OLD.boundary_id;
            IF NOT FOUND OR v_run IS NOT NULL THEN
                RETURN OLD;
            END IF;
        END IF;
        RAISE EXCEPTION 'a published data boundary is deleted only by the offboarding lane'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_actor_boundaries_frozen';
    END
    $$
"""
_FROZEN_TRIGGERS = tuple(
    f"CREATE TRIGGER refuse_boundary_change BEFORE UPDATE OR DELETE ON {table}"
    " FOR EACH ROW EXECUTE FUNCTION studio.refuse_boundary_change()"
    for table in _TABLE_NAMES
)

# Runs inside `studio.record_actor_boundary` as its owner, past RLS: the run is
# read under the row's own tenant, stated (R6.14).
_PROVISIONAL_RUN = """
    CREATE FUNCTION studio.check_provisional_run() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        IF NEW.run_id IS NULL THEN
            RETURN NEW;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform.worker_runs r
            WHERE r.tenant_id = NEW.tenant_id AND r.id = NEW.run_id AND r.run_mode = 'simulate'
        ) THEN
            RAISE EXCEPTION 'a provisional boundary names a simulate run of its own company'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_actor_boundaries_provisional_run';
        END IF;
        RETURN NEW;
    END
    $$
"""
_PROVISIONAL_TRIGGER = (
    "CREATE TRIGGER ck_actor_boundaries_provisional_run BEFORE INSERT ON studio.actor_boundaries"
    " FOR EACH ROW EXECUTE FUNCTION studio.check_provisional_run()"
)

# -- the writer -------------------------------------------------------------------

_RECORD = """
    CREATE FUNCTION studio.record_actor_boundary(
        p_kind text, p_source_id uuid, p_source_version text, p_run_id uuid,
        p_objects jsonb, p_fields jsonb
    ) RETURNS uuid
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        v_id uuid := gen_random_uuid();
        v_missing text;
    BEGIN
        IF v_tenant IS NULL THEN
            RAISE EXCEPTION 'a data boundary is recorded under a bound company'
                USING ERRCODE = '42501';
        END IF;
        IF jsonb_typeof(p_objects) IS DISTINCT FROM 'array'
           OR jsonb_typeof(p_fields) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'objects and fields are JSON arrays' USING ERRCODE = '22023';
        END IF;
        -- One of the company's versions; a published boundary under its hash.
        IF NOT EXISTS (
            SELECT 1 FROM studio.artifact_versions v
            WHERE v.tenant_id = v_tenant AND v.id = p_source_id
              AND (p_run_id IS NOT NULL OR v.definition_hash = p_source_version)
        ) THEN
            RAISE EXCEPTION 'the boundary''s version is not one of this company''s under that hash'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_actor_boundaries_source';
        END IF;
        -- A published boundary names only what is applied; a provisional one
        -- leaves out what a draft has not applied yet (gate (o)).
        IF p_run_id IS NULL THEN
            SELECT o->>'api_name' INTO v_missing
            FROM jsonb_array_elements(p_objects) o
            WHERE NOT EXISTS (SELECT 1 FROM studio.object_defs d
                              WHERE d.tenant_id = v_tenant AND d.api_name = o->>'api_name')
            LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'no object % in this company', v_missing
                    USING ERRCODE = '23503',
                          CONSTRAINT = 'fk_actor_boundary_objects_object_id_object_defs';
            END IF;
            SELECT (x->>'object_api_name') || '.' || (x->>'field_api_name') INTO v_missing
            FROM jsonb_array_elements(p_fields) x
            WHERE NOT EXISTS (SELECT 1 FROM studio.object_defs d
                              JOIN studio.field_defs f
                                ON f.tenant_id = d.tenant_id AND f.object_id = d.id
                              WHERE d.tenant_id = v_tenant
                                AND d.api_name = x->>'object_api_name'
                                AND f.api_name = x->>'field_api_name')
            LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'no field % in this company', v_missing
                    USING ERRCODE = '23503',
                          CONSTRAINT = 'fk_actor_boundary_fields_field_id_field_defs';
            END IF;
        END IF;
        INSERT INTO studio.actor_boundaries (tenant_id, id, kind, source_id, source_version, run_id)
        VALUES (v_tenant, v_id, p_kind, p_source_id, p_source_version, p_run_id);
        INSERT INTO studio.actor_boundary_objects
            (tenant_id, boundary_id, object_id, can_read, can_create, can_update, can_delete,
             can_assign)
        SELECT v_tenant, v_id, d.id, (o->>'can_read')::boolean, (o->>'can_create')::boolean,
               (o->>'can_update')::boolean, (o->>'can_delete')::boolean,
               (o->>'can_assign')::boolean
        FROM jsonb_array_elements(p_objects) o
        JOIN studio.object_defs d ON d.tenant_id = v_tenant AND d.api_name = o->>'api_name';
        INSERT INTO studio.actor_boundary_fields (tenant_id, boundary_id, field_id, access)
        SELECT v_tenant, v_id, f.id, x->>'access'
        FROM jsonb_array_elements(p_fields) x
        JOIN studio.object_defs d ON d.tenant_id = v_tenant AND d.api_name = x->>'object_api_name'
        JOIN studio.field_defs f
          ON f.tenant_id = v_tenant AND f.object_id = d.id AND f.api_name = x->>'field_api_name';
        RETURN v_id;
    END
    $$
"""

# -- the readers --------------------------------------------------------------------

# The one answer to "which boundaries does this run read under" (gate (b), (k)).
_CHAIN = """
    CREATE FUNCTION studio.boundary_chain(p_run_id uuid) RETURNS uuid[]
    LANGUAGE sql STABLE
    SET search_path = pg_catalog
    AS $$
        WITH RECURSIVE ctx AS (
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid AS tenant_id
        ), chain AS (
            SELECT r.id, r.parent_run_id, r.chain_depth, r.artifact_kind,
                   r.artifact_version_id, r.definition_hash
            FROM platform.worker_runs r, ctx
            WHERE r.tenant_id = ctx.tenant_id AND r.id = p_run_id
            UNION ALL
            -- Each step strictly nearer the root, so a bent row cannot loop.
            SELECT p.id, p.parent_run_id, p.chain_depth, p.artifact_kind,
                   p.artifact_version_id, p.definition_hash
            FROM chain c
            JOIN platform.worker_runs p ON p.id = c.parent_run_id AND p.chain_depth < c.chain_depth
            CROSS JOIN ctx
            WHERE p.tenant_id = ctx.tenant_id
        ), links AS (
            SELECT c.chain_depth, c.parent_run_id,
                   coalesce(
                       (SELECT b.id FROM studio.actor_boundaries b, ctx
                        WHERE b.tenant_id = ctx.tenant_id AND b.run_id = c.id),
                       (SELECT b.id FROM studio.actor_boundaries b, ctx
                        WHERE b.tenant_id = ctx.tenant_id AND b.run_id IS NULL
                          AND b.kind = c.artifact_kind AND b.source_id = c.artifact_version_id
                          AND b.source_version = c.definition_hash)) AS boundary_id
            FROM chain c
        )
        SELECT CASE WHEN count(*) FILTER (WHERE parent_run_id IS NULL) = 1
                         AND bool_and(boundary_id IS NOT NULL)
                    THEN array_agg(boundary_id ORDER BY chain_depth)
                    ELSE '{}'::uuid[] END
        FROM links
    $$
"""

# What every boundary of `app.boundary_id` allows for one command (R6.4, R6.13).
_ACL_BOUNDARY = """
    CREATE FUNCTION studio.acl_boundary_objects(p_cmd text) RETURNS uuid[]
    LANGUAGE sql STABLE
    SET search_path = pg_catalog
    AS $$
        WITH ctx AS (
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid AS tenant_id,
                   coalesce(current_setting('app.boundary_id', true), '') AS raw,
                   current_setting('app.run_mode', true) IS NOT DISTINCT FROM 'simulate'
                       AS simulate
        ), ids AS (
            SELECT DISTINCT u::uuid AS id
            FROM ctx, unnest(string_to_array(ctx.raw, ',')) u
            WHERE ctx.raw ~* '^<UUID>(,<UUID>)*$'
        ), admitted AS (
            SELECT count(*) AS listed,
                   count(b.id) FILTER (WHERE b.run_id IS NULL OR ctx.simulate) AS usable
            FROM ids
            CROSS JOIN ctx
            LEFT JOIN studio.actor_boundaries b ON b.tenant_id = ctx.tenant_id AND b.id = ids.id
        )
        SELECT coalesce(array_agg(o.object_id), '{}'::uuid[])
        FROM (
            SELECT o.object_id
            FROM studio.actor_boundary_objects o, ctx, admitted
            WHERE admitted.listed > 0 AND admitted.usable = admitted.listed
              AND o.tenant_id = ctx.tenant_id AND o.boundary_id IN (SELECT id FROM ids)
              AND CASE p_cmd
                      WHEN 'select' THEN o.can_read
                      WHEN 'insert' THEN o.can_create
                      WHEN 'update' THEN o.can_update
                      WHEN 'delete' THEN o.can_delete
                      WHEN 'assign' THEN o.can_assign
                      ELSE false
                  END
            GROUP BY o.object_id
            HAVING count(*) = (SELECT listed FROM admitted)
        ) o
    $$
""".replace("<UUID>", "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# -- the record policies, copied from `dw_studio.records.adapters.record_policy` --

_TENANT = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
_SCOPE = "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'"
_USER_OK = "(SELECT studio.acl_actor_kind()) = 'user'"


def _actor_ok(command: str) -> str:
    return (
        f"({_USER_OK} OR ((SELECT studio.acl_actor_kind()) IN ('agent', 'workflow')"
        f" AND object_id = ANY ((SELECT studio.acl_boundary_objects('{command}'))::uuid[])))"
    )


def _reach(action: str) -> str:
    if action == "create":
        return (
            "(object_id = ANY ((SELECT studio.acl_objects('create', 'tenant'))::uuid[])"
            " OR access_key = ANY ((SELECT studio.acl_keys('create'))::uuid[])"
            " OR (owner_id = (SELECT studio.acl_user())"
            " AND access_key = ANY ((SELECT studio.acl_create_own_keys())::uuid[])))"
        )
    return (
        f"(object_id = ANY ((SELECT studio.acl_objects('{action}', 'tenant'))::uuid[])"
        f" OR access_key = ANY ((SELECT studio.acl_keys('{action}'))::uuid[])"
        f" OR (owner_id = (SELECT studio.acl_user())"
        f" AND object_id = ANY ((SELECT studio.acl_objects('{action}', 'own'))::uuid[])))"
    )


def _guarded(actor: str, reach: str) -> str:
    return f"({_TENANT}) AND ({_SCOPE} OR ({actor} AND {reach}))"


def _policies(*, boundary: bool) -> tuple[tuple[str, str], ...]:
    """(name, the `ALTER POLICY` clauses) of the four PERMISSIVE policies: with
    the boundary (this revision) or the `user`-only arm of 2c2095fbb4c7."""

    def actor(command: str) -> str:
        return _actor_ok(command) if boundary else _USER_OK

    update_check = f"({_TENANT}) AND ({_SCOPE} OR ({actor('update')} AND {_reach('update')}" + (
        f" AND (deleted_at IS NULL OR ({actor('delete')} AND {_reach('delete')}))))"
        if boundary
        else f" AND (deleted_at IS NULL OR {_reach('delete')})))"
    )
    return (
        ("record_access_records_select", f"USING ({_guarded(actor('select'), _reach('read'))})"),
        (
            "record_access_records_insert",
            f"WITH CHECK ({_guarded(actor('insert'), _reach('create'))})",
        ),
        (
            "record_access_records_update",
            f"USING ({_guarded(actor('update'), _reach('update'))}) WITH CHECK ({update_check})",
        ),
        ("record_access_records_delete", f"USING ({_guarded(actor('delete'), _reach('delete'))})"),
    )


_PARTITIONS = sa.text(
    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
    " WHERE i.inhparent = 'studio.records'::regclass ORDER BY c.relname"
)

# `dw_app` calls the writer and the readers; the trigger functions are no one's.
_APP_FUNCTIONS = (
    "studio.record_actor_boundary(text, uuid, text, uuid, jsonb, jsonb)",
    "studio.boundary_chain(uuid)",
    "studio.acl_boundary_objects(text)",
)
_PRIVATE_FUNCTIONS = (
    "studio.refuse_boundary_change()",
    "studio.check_provisional_run()",
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


def _record_tables() -> list[str]:
    return ["records", *op.get_bind().execute(_PARTITIONS).scalars()]


def _alter_policies(*, boundary: bool) -> None:
    for table in _record_tables():
        for name, clauses in _policies(boundary=boundary):
            op.execute(f"ALTER POLICY {name} ON studio.{table} {clauses}")


def upgrade() -> None:
    # 1. The tables, their row security and privileges: SELECT and DELETE only.
    for statement in (*_TABLES, *_INDEXES, *_RLS):
        op.execute(statement)
    tables = ", ".join(_TABLE_NAMES)
    op.execute(f"REVOKE ALL ON {tables} FROM PUBLIC")
    op.execute(_for_role("dw_app", f"REVOKE ALL ON {tables} FROM dw_app;"))
    op.execute(_for_role("dw_app", f"GRANT SELECT, DELETE ON {tables} TO dw_app;"))
    for role in ("dw_provisioner", "dw_agent_ro"):
        op.execute(_for_role(role, f"REVOKE ALL ON {tables} FROM {role};"))

    # 2. The triggers.
    for statement in (_FROZEN, *_FROZEN_TRIGGERS, _PROVISIONAL_RUN, _PROVISIONAL_TRIGGER):
        op.execute(statement)

    # 3. The writer and the readers.
    for statement in (_RECORD, _CHAIN, _ACL_BOUNDARY):
        op.execute(statement)
    for function in (*_APP_FUNCTIONS, *_PRIVATE_FUNCTIONS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in _APP_FUNCTIONS:
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))

    # 4. The record policies admit an agent or a workflow within its boundary.
    _alter_policies(boundary=True)


def downgrade() -> None:
    _alter_policies(boundary=False)
    for function in (
        "studio.acl_boundary_objects(text)",
        "studio.boundary_chain(uuid)",
        "studio.record_actor_boundary(text, uuid, text, uuid, jsonb, jsonb)",
    ):
        op.execute(f"DROP FUNCTION {function}")
    for table in reversed(_TABLE_NAMES):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION studio.check_provisional_run()")
    op.execute("DROP FUNCTION studio.refuse_boundary_change()")
