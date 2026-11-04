"""record reach ledger

Revision ID: f6ea6e818d0c
Revises: d66d6913b249
Create Date: 2026-11-05 09:00:00.000000+00:00

record-access ticket 02 (R5.1-R5.7; RA12-RA16; ADR-0105 decision 4 as written,
P0, with its 2026-11-04 refinements). Which records a principal reaches is
computed in one SQL function from `platform.effective_grants`, kept in one row
per principal, read by the `studio.acl_*` functions the record policies of
ticket 03 call, and invalidated in the transaction of every change to its
inputs, so a revocation holds from the next statement. Provisional until
ticket 07 applies the D12 winner in a later revision.

- `studio.access_epochs`: one counter per tenant, bumped by structural changes
  (roles, object privileges, the company's status, workspaces, objects).
- `studio.principal_scopes`: one row per principal, `valid` or `stale`, the
  epoch it was computed at, `valid_until` (the earliest expiry of the role
  assignments behind it), `workspace_ids`, and one `uuid[]` per action and arm:
  `own` (objects held at own depth or deeper), `keys` (`studio.access_key` of an
  object and the anchor of a workspace-depth grant), `tenant`; plus
  `create_own_keys`, the (object, anchor) keys of own-depth `create`. Private
  to its principal: the tenant policy plus a RESTRICTIVE
  `tenant AND (principal OR scope)` (ADR-0117 shape). The composite key to
  `platform.tenant_members` refuses a row for someone who is not a member of
  that company and cascades the row away with the membership (R5.6, R5.7).
- `studio.access_input_tables`: which tables feed reach and which trigger
  function each carries, the triggers made from its rows; a later revision
  that hangs `platform.bump_access_version()` on a new table adds its row here.
- `studio.v_principal_grants`, `studio.v_principal_workspaces`: the inputs, the
  tenant and principal read from the settings in each view and nowhere else;
  `studio.compute_principal_scope()` reads only them. All three are the
  migrator's; nobody else may read or call them.
- `studio.ensure_principal_scope()`: the door. Does nothing for a connection
  with no principal or one who is not a member of the bound company; otherwise
  recomputes a missing, stale, out-of-epoch or expired row with a
  compare-and-set on `version`, so a computation begun before a revocation
  never publishes after it.
- `studio.mark_principal_stale()`, `studio.bump_access_epoch()`: the trigger
  functions; neither takes a table name from a caller.
- `studio.purge_access_epoch(tenant)`: the offboarding lane's step for the
  epoch row, as `platform.purge_tenant_access_version` is for its own.
"""

from __future__ import annotations

from alembic import op

revision = "f6ea6e818d0c"
down_revision = "d66d6913b249"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires: every setting read once, in a sub-SELECT.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_USER = "(SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"

ACTIONS = ("read", "create", "update", "delete", "assign")
ARMS = ("own", "keys", "tenant")
# The ledger's reach columns, in one order for the table, the computation and the door.
REACH_COLUMNS = (*(f"{action}_{arm}" for action in ACTIONS for arm in ARMS), "create_own_keys")
_REACH_DDL = ",\n        ".join(f"{c} uuid[] NOT NULL DEFAULT '{{}}'" for c in REACH_COLUMNS)

# -- the tables -----------------------------------------------------------------

_TABLES = (
    """
    CREATE TABLE studio.access_epochs (
        tenant_id uuid NOT NULL,
        epoch bigint NOT NULL DEFAULT 0,
        changed_at timestamp with time zone NOT NULL DEFAULT now(),
        CONSTRAINT pk_access_epochs PRIMARY KEY (tenant_id),
        CONSTRAINT fk_access_epochs_tenant_id_tenants
            FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id) ON DELETE CASCADE,
        CONSTRAINT ck_access_epochs_epoch CHECK (epoch >= 0)
    )
    """,
    f"""
    CREATE TABLE studio.principal_scopes (
        tenant_id uuid NOT NULL,
        principal_id uuid NOT NULL,
        epoch bigint NOT NULL,
        version bigint NOT NULL,
        state text NOT NULL,
        computed_at timestamp with time zone NOT NULL,
        valid_until timestamp with time zone,
        workspace_ids uuid[] NOT NULL,
        {_REACH_DDL},
        CONSTRAINT pk_principal_scopes PRIMARY KEY (tenant_id, principal_id),
        CONSTRAINT fk_principal_scopes_tenant_id_tenant_members
            FOREIGN KEY (tenant_id, principal_id)
            REFERENCES platform.tenant_members (tenant_id, user_id) ON DELETE CASCADE,
        CONSTRAINT ck_principal_scopes_state CHECK (state IN ('valid', 'stale'))
    )
    """,
    # The platform's catalogue of reach inputs: no tenant's rows, `dw_app` reads.
    # `events` is spelled as `pg_get_triggerdef` prints it, so the catalog test
    # compares one string.
    """
    CREATE TABLE studio.access_input_tables (
        table_name text NOT NULL,
        trigger_function text NOT NULL,
        events text,
        reason text NOT NULL,
        CONSTRAINT pk_access_input_tables PRIMARY KEY (table_name),
        CONSTRAINT ck_access_input_tables_table_name
            CHECK (table_name ~ '^(platform|studio)\\.[a-z_][a-z0-9_]*$'),
        CONSTRAINT ck_access_input_tables_trigger_function
            CHECK (trigger_function IN ('mark_principal_stale', 'bump_access_epoch', 'none')),
        CONSTRAINT ck_access_input_tables_events CHECK (events IN (
            'INSERT OR DELETE OR UPDATE', 'INSERT OR DELETE', 'UPDATE OF status',
            'DELETE OR UPDATE OF archived_at')),
        CONSTRAINT ck_access_input_tables_events_needs_function
            CHECK ((trigger_function = 'none') = (events IS NULL)),
        CONSTRAINT ck_access_input_tables_reason CHECK (btrim(reason) <> '')
    )
    """,
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
_RLS = (
    "ALTER TABLE studio.access_epochs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.access_epochs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_access_epochs ON studio.access_epochs"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.principal_scopes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.principal_scopes FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_principal_scopes ON studio.principal_scopes"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    # A row private to one person (CLAUDE.md, Tenancy; ADR-0117): RESTRICTIVE, so
    # no PERMISSIVE policy added later reopens another person's row.
    "CREATE POLICY owner_or_scope_principal_scopes ON studio.principal_scopes AS RESTRICTIVE"
    f" USING ({_TENANT} AND (principal_id = {_USER} OR {_SCOPE}))",
)

# (table, trigger function, events, reason). Every table carrying
# `platform.bump_access_version()` has a row, `none` included (ADR-0104 decision 7).
ACCESS_INPUTS = (
    (
        "platform.role_assignments",
        "mark_principal_stale",
        "INSERT OR DELETE OR UPDATE",
        "lần gán vai trò của một người: thêm, gỡ, đổi hạn",
    ),
    (
        "platform.memberships",
        "mark_principal_stale",
        "INSERT OR DELETE OR UPDATE",
        "thành viên workspace: workspace_ids và neo của lần gán",
    ),
    (
        "platform.tenant_members",
        "mark_principal_stale",
        "UPDATE OF status",
        "trạng thái thành viên công ty; xóa thì dòng sổ tầm đi theo khóa ngoại",
    ),
    (
        "platform.tenant_role_permissions",
        "bump_access_epoch",
        "INSERT OR DELETE OR UPDATE",
        "quyền nền tảng của vai trò, đầu vào của platform.effective_grants",
    ),
    (
        "platform.tenant_role_object_privileges",
        "bump_access_epoch",
        "INSERT OR DELETE OR UPDATE",
        "quyền đối tượng ở một độ sâu, đầu vào chính của tầm bản ghi (tenant-rbac/04)",
    ),
    (
        "platform.tenant_roles",
        "bump_access_epoch",
        "INSERT OR DELETE OR UPDATE",
        "vai trò của công ty: xóa mềm, tenant_owner",
    ),
    ("platform.tenants", "bump_access_epoch", "UPDATE OF status", "khóa, mở, offboard công ty"),
    (
        "platform.entitlements",
        "bump_access_epoch",
        "INSERT OR DELETE OR UPDATE",
        "gói của công ty, theo ADR-0104 quyết 7",
    ),
    (
        "platform.workspaces",
        "bump_access_epoch",
        "DELETE OR UPDATE OF archived_at",
        "lưu trữ hay xóa workspace: neo của lần gán và workspace_ids",
    ),
    (
        "studio.object_defs",
        "bump_access_epoch",
        "INSERT OR DELETE",
        "đối tượng mới hay mất đổi khóa obj.* sinh ra (tenant-rbac/04);"
        " default_access là của ticket 03",
    ),
    (
        "studio.field_defs",
        "none",
        None,
        "không phải đầu vào của tầm bản ghi: trường thuộc bảo mật trường (ADR-0106)",
    ),
    (
        "studio.field_permissions",
        "none",
        None,
        "không phải đầu vào của tầm bản ghi: quyền trường (tenant-rbac/04, ADR-0106)",
    ),
)

# -- the functions ----------------------------------------------------------------

_ACCESS_KEY = """
    CREATE FUNCTION studio.access_key(p_object_id uuid, p_workspace_id uuid) RETURNS uuid
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path = pg_catalog
    AS $$ SELECT md5(p_object_id::text || '/' || p_workspace_id::text)::uuid $$
"""

# The tenant and principal come from the settings here, in each view, and
# nowhere else; every join below names `ctx` (gate (h)). The key-to-object map is
# `platform.object_permission_keys`, the one owner of an `obj.*` key.
_CTX = """
        WITH ctx AS (
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid AS tenant_id,
                   NULLIF(current_setting('app.user_id', true), '')::uuid AS user_id
        )"""

_V_GRANTS = f"""
    CREATE VIEW studio.v_principal_grants WITH (security_invoker = true) AS{_CTX}
        SELECT k.object_id, k.action, g.depth, g.anchor_workspace_id, a.expires_at
        FROM ctx
        CROSS JOIN LATERAL platform.effective_grants(ctx.tenant_id, ctx.user_id) g
        JOIN LATERAL platform.object_permission_keys(ctx.tenant_id) k
          ON k.key = g.permission_key
        JOIN platform.workspaces w
          ON w.tenant_id = ctx.tenant_id AND w.id = g.anchor_workspace_id
         AND w.archived_at IS NULL
        JOIN platform.memberships m
          ON m.tenant_id = ctx.tenant_id AND m.workspace_id = g.anchor_workspace_id
         AND m.user_id = ctx.user_id
        JOIN platform.role_assignments a
          ON a.tenant_id = ctx.tenant_id AND a.workspace_id = m.workspace_id
         AND a.membership_id = m.id AND a.role_id = g.role_id
        WHERE k.action IN ('read', 'create', 'update', 'delete', 'assign')
"""

_V_WORKSPACES = f"""
    CREATE VIEW studio.v_principal_workspaces WITH (security_invoker = true) AS{_CTX}
        SELECT m.workspace_id
        FROM ctx
        JOIN platform.tenants t ON t.id = ctx.tenant_id AND t.status = 'active'
        JOIN platform.tenant_members tm
          ON tm.tenant_id = ctx.tenant_id AND tm.user_id = ctx.user_id AND tm.status = 'active'
        JOIN platform.memberships m ON m.tenant_id = ctx.tenant_id AND m.user_id = ctx.user_id
        JOIN platform.workspaces w
          ON w.tenant_id = ctx.tenant_id AND w.id = m.workspace_id AND w.archived_at IS NULL
"""

_W1_DEPTHS = "('own', 'workspace', 'tenant')"


def _arm(action: str, arm: str) -> str:
    """One reach column: the depths an arm admits in W1 (ADR-0104 decision 3)."""
    if arm == "own":
        value, where = "g.object_id", f"g.depth IN {_W1_DEPTHS}"
    elif arm == "keys":
        value, where = (
            "studio.access_key(g.object_id, g.anchor_workspace_id)",
            "g.depth = 'workspace'",
        )
    else:
        value, where = "g.object_id", "g.depth = 'tenant'"
    return (
        f"coalesce(array_agg(DISTINCT {value})"
        f" FILTER (WHERE g.action = '{action}' AND {where}), '{{}}')"
    )


_COMPUTE_COLUMNS = ",\n            ".join(
    [
        *(_arm(action, arm) for action in ACTIONS for arm in ARMS),
        "coalesce(array_agg(DISTINCT studio.access_key(g.object_id, g.anchor_workspace_id))"
        " FILTER (WHERE g.action = 'create' AND g.depth = 'own'), '{}')",
    ]
)
_RETURNS = ", ".join(f"{c} uuid[]" for c in REACH_COLUMNS)

_COMPUTE = f"""
    CREATE FUNCTION studio.compute_principal_scope()
    RETURNS TABLE (workspace_ids uuid[], valid_until timestamp with time zone, {_RETURNS})
    LANGUAGE sql STABLE
    SET search_path = pg_catalog
    AS $$
        SELECT
            (SELECT coalesce(array_agg(DISTINCT w.workspace_id), '{{}}')
             FROM studio.v_principal_workspaces w),
            min(g.expires_at) FILTER (WHERE g.depth IN {_W1_DEPTHS}),
            {_COMPUTE_COLUMNS}
        FROM studio.v_principal_grants g
    $$
"""

_SET_COMPUTED = ",\n                ".join(
    f"{c} = c.{c}" for c in ("workspace_ids", "valid_until", *REACH_COLUMNS)
)
_INSERT_COLUMNS = ", ".join(("workspace_ids", "valid_until", *REACH_COLUMNS))
_SELECT_COMPUTED = ", ".join(f"c.{c}" for c in ("workspace_ids", "valid_until", *REACH_COLUMNS))

_ENSURE = f"""
    CREATE FUNCTION studio.ensure_principal_scope() RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $$
    DECLARE
        v_tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        v_user uuid := NULLIF(current_setting('app.user_id', true), '')::uuid;
        v_epoch bigint;
        v_version bigint;
        v_state text;
        v_row_epoch bigint;
        v_valid_until timestamp with time zone;
    BEGIN
        -- Support staff, a lane, a connection without a principal: nothing to
        -- compute, and the readers answer '{{}}' (R4.4; gate (i)).
        IF v_tenant IS NULL OR v_user IS NULL OR NOT EXISTS (
            SELECT 1 FROM platform.tenant_members m
            WHERE m.tenant_id = v_tenant AND m.user_id = v_user
        ) THEN
            RETURN;
        END IF;
        -- The epoch is read before the computation's snapshot, so an epoch bump
        -- committed in between leaves this row out of date, never wrong.
        v_epoch := coalesce(
            (SELECT e.epoch FROM studio.access_epochs e WHERE e.tenant_id = v_tenant), 0);
        SELECT s.version, s.state, s.epoch, s.valid_until
        INTO v_version, v_state, v_row_epoch, v_valid_until
        FROM studio.principal_scopes s
        WHERE s.tenant_id = v_tenant AND s.principal_id = v_user;
        IF NOT FOUND THEN
            -- A row a revocation upserted meanwhile wins (gate (g)).
            INSERT INTO studio.principal_scopes
                (tenant_id, principal_id, epoch, version, state, computed_at, {_INSERT_COLUMNS})
            SELECT v_tenant, v_user, v_epoch, 1, 'valid', now(), {_SELECT_COMPUTED}
            FROM studio.compute_principal_scope() c
            ON CONFLICT (tenant_id, principal_id) DO NOTHING;
            RETURN;
        END IF;
        IF v_state = 'valid' AND v_row_epoch = v_epoch
           AND (v_valid_until IS NULL OR v_valid_until > now()) THEN
            RETURN;
        END IF;
        -- Compare-and-set: a change committed after the version was read moved
        -- it, and this computation, begun before that change, writes nothing.
        UPDATE studio.principal_scopes s
        SET state = 'valid', epoch = v_epoch, version = s.version + 1, computed_at = now(),
            {_SET_COMPUTED}
        FROM studio.compute_principal_scope() c
        WHERE s.tenant_id = v_tenant AND s.principal_id = v_user AND s.version = v_version;
    END
    $$
"""

# The caller's own row, read only while it is valid for the tenant's epoch and
# its earliest assignment expiry (R5.3).
_VALID = """s.tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
               AND s.principal_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
               AND s.state = 'valid'
               AND s.epoch = coalesce(
                   (SELECT e.epoch FROM studio.access_epochs e WHERE e.tenant_id = s.tenant_id), 0)
               AND (s.valid_until IS NULL OR s.valid_until > now())"""


def _reader(name: str, args: str, returns: str, pick: str, empty: str) -> str:
    return f"""
    CREATE FUNCTION studio.{name}({args}) RETURNS {returns}
    LANGUAGE sql STABLE
    SET search_path = pg_catalog
    AS $$
        SELECT coalesce((SELECT {pick} FROM studio.principal_scopes s
                         WHERE {_VALID}), {empty})
    $$
"""


def _case(subject: str, columns: dict[str, str]) -> str:
    whens = " ".join(f"WHEN '{when}' THEN s.{column}" for when, column in columns.items())
    return f"CASE {subject} {whens} END"


_READERS = (
    _reader("acl_user", "", "uuid", "s.principal_id", "NULL"),
    _reader(
        "acl_objects",
        "p_action text, p_arm text",
        "uuid[]",
        _case(
            "p_action || ':' || p_arm",
            {f"{a}:{arm}": f"{a}_{arm}" for a in ACTIONS for arm in ("own", "tenant")},
        ),
        "'{}'::uuid[]",
    ),
    _reader(
        "acl_keys",
        "p_action text",
        "uuid[]",
        _case("p_action", {a: f"{a}_keys" for a in ACTIONS}),
        "'{}'::uuid[]",
    ),
    _reader("acl_create_own_keys", "", "uuid[]", "s.create_own_keys", "'{}'::uuid[]"),
)

_MARK_STALE = """
    CREATE FUNCTION studio.mark_principal_stale() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $$
    DECLARE
        v_rec record;
        v_user uuid;
        v_pass integer;
    BEGIN
        FOR v_pass IN 1..2 LOOP
            IF v_pass = 1 THEN
                CONTINUE WHEN TG_OP = 'INSERT';
                v_rec := OLD;
            ELSE
                CONTINUE WHEN TG_OP = 'DELETE';
                v_rec := NEW;
            END IF;
            IF TG_TABLE_NAME = 'role_assignments' THEN
                SELECT m.user_id INTO v_user FROM platform.memberships m
                WHERE m.tenant_id = v_rec.tenant_id AND m.workspace_id = v_rec.workspace_id
                  AND m.id = v_rec.membership_id;
            ELSE
                v_user := v_rec.user_id;
            END IF;
            -- Only for a member the company still has: a removal cascades the
            -- ledger row away and no row is made again for them (gate (k)).
            -- An upsert, so a computation that found no row loses to it (gate (g)).
            INSERT INTO studio.principal_scopes AS s
                (tenant_id, principal_id, epoch, version, state, computed_at, workspace_ids)
            SELECT tm.tenant_id, tm.user_id, 0, 1, 'stale', now(), '{}'
            FROM platform.tenant_members tm
            WHERE tm.tenant_id = v_rec.tenant_id AND tm.user_id = v_user
            ON CONFLICT (tenant_id, principal_id)
            DO UPDATE SET state = 'stale', version = s.version + 1;
        END LOOP;
        RETURN NULL;
    END
    $$
"""

_BUMP_EPOCH = """
    CREATE FUNCTION studio.bump_access_epoch() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $$
    DECLARE
        v_rec record;
        v_tenant uuid;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            v_rec := OLD;
        ELSE
            v_rec := NEW;
        END IF;
        IF TG_TABLE_NAME = 'tenants' THEN
            -- The move into offboarding bumps; nothing after it does (gate (l)).
            IF TG_OP = 'UPDATE' AND OLD.status IN ('offboarding', 'offboarded') THEN
                RETURN NULL;
            END IF;
            v_tenant := v_rec.id;
        ELSE
            v_tenant := v_rec.tenant_id;
        END IF;
        -- An upsert, so no bump is lost when the row is missing (gate (g)); none
        -- for a company gone or leaving, so the lane's deletes after
        -- `studio.purge_access_epoch` make no row again (gate (l)).
        INSERT INTO studio.access_epochs AS e (tenant_id, epoch, changed_at)
        SELECT t.id, 1, now() FROM platform.tenants t
        WHERE t.id = v_tenant
          AND (TG_TABLE_NAME = 'tenants' OR t.status NOT IN ('offboarding', 'offboarded'))
        ON CONFLICT (tenant_id) DO UPDATE SET epoch = e.epoch + 1, changed_at = now();
        RETURN NULL;
    END
    $$
"""

_PURGE_EPOCH = """
    CREATE FUNCTION studio.purge_access_epoch(p_tenant_id uuid) RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $$
    BEGIN
        IF p_tenant_id IS DISTINCT FROM
            NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
            RAISE EXCEPTION 'purge_access_epoch runs for the transaction''s own tenant'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_access_epochs_purge';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = p_tenant_id AND status = 'offboarding'
        ) THEN
            RAISE EXCEPTION 'purge_access_epoch runs only for a tenant offboarding'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_access_epochs_purge';
        END IF;
        DELETE FROM studio.access_epochs WHERE tenant_id = p_tenant_id;
    END
    $$
"""

# Made from the declaration's rows, never written out a second time (gate (j)).
_ATTACH = """
    DO $$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT table_name, trigger_function, events FROM studio.access_input_tables
                 WHERE trigger_function <> 'none' LOOP
            EXECUTE format(
                'CREATE TRIGGER trg_studio_access_input AFTER %s ON %I.%I'
                ' FOR EACH ROW EXECUTE FUNCTION studio.%I()',
                r.events, split_part(r.table_name, '.', 1), split_part(r.table_name, '.', 2),
                r.trigger_function);
        END LOOP;
    END
    $$
"""

_DETACH = """
    DO $$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT table_name FROM studio.access_input_tables
                 WHERE trigger_function <> 'none' LOOP
            EXECUTE format('DROP TRIGGER IF EXISTS trg_studio_access_input ON %I.%I',
                           split_part(r.table_name, '.', 1), split_part(r.table_name, '.', 2));
        END LOOP;
    END
    $$
"""

# `dw_app` calls the door, the readers and the offboarding step; the rest is no one's.
_APP_FUNCTIONS = (
    "studio.ensure_principal_scope()",
    "studio.acl_user()",
    "studio.acl_objects(text, text)",
    "studio.acl_keys(text)",
    "studio.acl_create_own_keys()",
    "studio.purge_access_epoch(uuid)",
)
_PRIVATE_FUNCTIONS = (
    "studio.access_key(uuid, uuid)",
    "studio.compute_principal_scope()",
    "studio.mark_principal_stale()",
    "studio.bump_access_epoch()",
)
_TABLE_NAMES = ("studio.access_epochs", "studio.principal_scopes", "studio.access_input_tables")
_VIEW_NAMES = ("studio.v_principal_grants", "studio.v_principal_workspaces")


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


def _quoted(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    # 1. The tables, their row security and privileges.
    for statement in _TABLES:
        op.execute(statement)
    for statement in _RLS:
        op.execute(statement)
    for table in _TABLE_NAMES:
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
    tables = ", ".join(_TABLE_NAMES)
    # The schema's defaults hand `dw_app` SELECT; written out so the grant does
    # not rest on them, and nothing else, for the provisioner or the agent role.
    op.execute(_for_role("dw_app", f"REVOKE ALL ON {tables} FROM dw_app;"))
    op.execute(_for_role("dw_app", f"GRANT SELECT ON {tables} TO dw_app;"))
    for role in ("dw_provisioner", "dw_agent_ro"):
        op.execute(_for_role(role, f"REVOKE ALL ON {tables} FROM {role};"))

    # 2. The declaration of the inputs.
    for table, function, events, reason in ACCESS_INPUTS:
        op.execute(
            "INSERT INTO studio.access_input_tables (table_name, trigger_function, events, reason)"
            f" VALUES ({_quoted(table)}, {_quoted(function)}, {_quoted(events)}, {_quoted(reason)})"
        )

    # 3. The key, the inputs, the computation, the door and the readers.
    for statement in (_ACCESS_KEY, _V_GRANTS, _V_WORKSPACES, _COMPUTE, _ENSURE, *_READERS):
        op.execute(statement)
    for statement in (_MARK_STALE, _BUMP_EPOCH, _PURGE_EPOCH):
        op.execute(statement)
    views = ", ".join(_VIEW_NAMES)
    op.execute(f"REVOKE ALL ON {views} FROM PUBLIC")
    for role in ("dw_app", "dw_provisioner", "dw_agent_ro"):
        op.execute(_for_role(role, f"REVOKE ALL ON {views} FROM {role};"))
    for function in (*_APP_FUNCTIONS, *_PRIVATE_FUNCTIONS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in _APP_FUNCTIONS:
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))

    # 4. The triggers, from the declaration.
    op.execute(_ATTACH)


def downgrade() -> None:
    op.execute(_DETACH)
    for function in (
        "studio.purge_access_epoch(uuid)",
        "studio.bump_access_epoch()",
        "studio.mark_principal_stale()",
        "studio.acl_create_own_keys()",
        "studio.acl_keys(text)",
        "studio.acl_objects(text, text)",
        "studio.acl_user()",
        "studio.ensure_principal_scope()",
        "studio.compute_principal_scope()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP VIEW IF EXISTS studio.v_principal_workspaces")
    op.execute("DROP VIEW IF EXISTS studio.v_principal_grants")
    op.execute("DROP FUNCTION IF EXISTS studio.access_key(uuid, uuid)")
    op.execute("DROP TABLE IF EXISTS studio.access_input_tables")
    op.execute("DROP TABLE IF EXISTS studio.principal_scopes")
    op.execute("DROP TABLE IF EXISTS studio.access_epochs")
