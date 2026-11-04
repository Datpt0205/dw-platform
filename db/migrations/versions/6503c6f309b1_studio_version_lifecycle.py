"""studio version lifecycle

Revision ID: 6503c6f309b1
Revises: 8efd60e59d32
Create Date: 2026-11-04 12:21:49.507479+00:00

agent-lifecycle ticket 03 (R1.1-R1.9, R2.1-R2.7, R2.10; AL1-AL3, AL19, AL21;
ADR-0120 decision 1). The stage machine of the shared version envelope
(`studio.artifact_versions`, tenant-config ticket 02), held by the database:

- Lifecycle columns. `publish_approval_id` is a composite key to
  `uq_approval_requests_tenant_id_id` (ticket 01), since a foreign key check
  does not pass through RLS; `gate_run_id` gets its key with
  `studio.gate_runs` in ticket 06. `compared_live_hash` is the
  `definition_hash` of the version live at submit; `tighten_only` is ticket
  04's comparator result; `contributor_ids` is everyone who created or saved
  the draft, backfilled here from the `studio.artifact.*` audit of the row's
  artifact, and never empty: a row with no such audit stops the revision,
  naming it, rather than be given an arbitrary person.
- `studio.guard_version_stage()`, BEFORE INSERT OR UPDATE: inserted as
  `draft`; `draft -> evaluating` (gated kinds), `draft -> awaiting_approval`
  (kinds without a gate), `evaluating | awaiting_approval -> draft` (cleared),
  `awaiting_approval -> live` (kinds without a gate in this revision: the
  approved `studio.publish.<kind>` request of this very version, decided by
  someone neither a contributor nor the submitter, and `compared_live_hash`
  still the hash of the version this publish retires as `superseded` in the
  same transaction, both NULL when none), `draft -> live` (the `object`
  kind's tighten-only branch), `live -> retired`. `evaluating ->
  awaiting_approval` is refused for every kind until ticket 06 replaces the
  function with its gate check, so a gated kind fails closed until then. Each
  lifecycle column changes only at its own step, the stage moved or not.
  Invoker's rights: RLS of the two approval tables narrows by tenant alone,
  so `dw_app` reads its own company's rows and no other's. Every refusal is
  SQLSTATE 23514 `ck_artifact_versions_stage_transition`. Content is not
  checked here: `studio.refuse_sealed_content_change()` already holds it.
- `uq_artifact_versions_live`: one live version per artifact. One unreleased
  version is tenant-config's `uq_artifact_versions_unreleased`.
- `studio.artifact_display_stage` (`security_invoker`): the displayed stage,
  killed first, computed and never stored.
- The permissions `studio.versions.submit` and `studio.versions.retire`.

`dw_app` holds UPDATE of exactly the new columns (column UPDATEs only on this
table, revision 67071483caa6) and SELECT on the view, the schema's default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "6503c6f309b1"
down_revision = "8efd60e59d32"
branch_labels = None
depends_on = None

_HASH = "~ '^sha256:[0-9a-f]{64}$'"

_COLUMNS = (
    "ALTER TABLE studio.artifact_versions"
    " ADD COLUMN gate_run_id uuid,"
    " ADD COLUMN publish_approval_id uuid,"
    " ADD COLUMN tighten_only boolean DEFAULT false NOT NULL,"
    " ADD COLUMN compared_live_hash text,"
    " ADD COLUMN contributor_ids uuid[],"
    " ADD COLUMN submitted_by uuid,"
    " ADD COLUMN submitted_at timestamp with time zone,"
    " ADD COLUMN published_by uuid,"
    " ADD COLUMN published_at timestamp with time zone,"
    " ADD COLUMN retired_by uuid,"
    " ADD COLUMN retired_at timestamp with time zone,"
    " ADD COLUMN retire_reason_code text",
)

# Everyone who created or saved the row's draft, first appearance first: the
# envelope's own audit (`ArtifactService`) is the only record of who did.
_BACKFILL = """
    UPDATE studio.artifact_versions v
    SET contributor_ids = coalesce(
        (
            SELECT array_agg(f.actor_id ORDER BY f.first_at, f.actor_id)
            FROM (
                SELECT e.actor_id, min(e.occurred_at) AS first_at
                FROM platform.audit_events e
                WHERE e.tenant_id = v.tenant_id
                  AND e.resource_id = v.artifact_id::text
                  AND e.action LIKE 'studio.artifact.%'
                GROUP BY e.actor_id
            ) f
        ),
        ARRAY[]::uuid[]
    )
    """

_NO_CONTRIBUTOR = """
    DO $$
    DECLARE
        v_rows text;
    BEGIN
        SELECT string_agg(
                   format('version %s of artifact %s (tenant %s)', id, artifact_id, tenant_id),
                   '; ' ORDER BY tenant_id, artifact_id, id)
          INTO v_rows
          FROM studio.artifact_versions
         WHERE cardinality(contributor_ids) = 0;
        IF v_rows IS NOT NULL THEN
            RAISE EXCEPTION 'no studio.artifact.* audit names a contributor of: %', v_rows
                USING ERRCODE = '23514', CONSTRAINT = 'ck_artifact_versions_contributor_ids';
        END IF;
    END
    $$
    """

_CONSTRAINTS = (
    "ALTER TABLE studio.artifact_versions ALTER COLUMN contributor_ids SET NOT NULL",
    "ALTER TABLE studio.artifact_versions"
    " ADD CONSTRAINT ck_artifact_versions_contributor_ids"
    " CHECK (cardinality(contributor_ids) >= 1 AND array_position(contributor_ids, NULL) IS NULL),"
    " ADD CONSTRAINT ck_artifact_versions_tighten_only_compared"
    " CHECK (NOT tighten_only OR compared_live_hash IS NOT NULL),"
    f" ADD CONSTRAINT ck_artifact_versions_compared_live_hash"
    f" CHECK (compared_live_hash IS NULL OR compared_live_hash {_HASH}),"
    " ADD CONSTRAINT ck_artifact_versions_retire_reason_code"
    " CHECK (retire_reason_code IN ('superseded', 'explicit')),"
    " ADD CONSTRAINT ck_artifact_versions_submitted"
    " CHECK ((submitted_by IS NULL) = (submitted_at IS NULL)),"
    " ADD CONSTRAINT ck_artifact_versions_published"
    " CHECK ((published_by IS NULL) = (published_at IS NULL)),"
    " ADD CONSTRAINT ck_artifact_versions_retired"
    " CHECK ((retired_by IS NULL) = (retired_at IS NULL)"
    " AND (retired_at IS NULL) = (retire_reason_code IS NULL)),"
    # Composite, since a foreign key check does not pass through RLS (R1.9).
    " ADD CONSTRAINT fk_artifact_versions_publish_approval_id_approval_requests"
    " FOREIGN KEY (publish_approval_id, tenant_id)"
    " REFERENCES platform.approval_requests (id, tenant_id) ON DELETE RESTRICT",
    "CREATE INDEX ix_artifact_versions_tenant_id_publish_approval_id"
    " ON studio.artifact_versions (tenant_id, publish_approval_id)",
    # R1.2: one live version per artifact.
    "CREATE UNIQUE INDEX uq_artifact_versions_live ON studio.artifact_versions (artifact_id)"
    " WHERE stage = 'live'",
)

_GUARD = """
    CREATE FUNCTION studio.guard_version_stage() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_kind text;
        v_gated boolean;
        v_moved boolean;
        v_replaced text;
        v_ok boolean := false;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.stage <> 'draft'
               OR NEW.gate_run_id IS NOT NULL OR NEW.publish_approval_id IS NOT NULL
               OR NEW.tighten_only OR NEW.compared_live_hash IS NOT NULL
               OR NEW.submitted_by IS NOT NULL OR NEW.submitted_at IS NOT NULL
               OR NEW.published_by IS NOT NULL OR NEW.published_at IS NOT NULL
               OR NEW.retired_by IS NOT NULL OR NEW.retired_at IS NOT NULL
               OR NEW.retire_reason_code IS NOT NULL THEN
                RAISE EXCEPTION 'a version is inserted as a draft'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_artifact_versions_stage_transition';
            END IF;
            RETURN NEW;
        END IF;

        v_moved := NEW.stage <> OLD.stage;
        SELECT a.kind, k.has_quality_gate INTO v_kind, v_gated
          FROM studio.artifacts a
          JOIN studio.artifact_kinds k ON k.kind = a.kind
         WHERE a.tenant_id = NEW.tenant_id AND a.id = NEW.artifact_id;

        -- Each lifecycle column at its own step, whether the stage moved or not.
        IF NOT FOUND
           OR (NOT v_gated AND NEW.gate_run_id IS NOT NULL)
           OR (NEW.contributor_ids IS DISTINCT FROM OLD.contributor_ids
               AND NOT (OLD.stage = 'draft' AND NEW.stage = 'draft'))
           OR ((NEW.submitted_by, NEW.submitted_at, NEW.compared_live_hash, NEW.tighten_only)
               IS DISTINCT FROM
               (OLD.submitted_by, OLD.submitted_at, OLD.compared_live_hash, OLD.tighten_only)
               AND NOT (v_moved AND 'draft' IN (OLD.stage, NEW.stage)))
           OR (NEW.publish_approval_id IS DISTINCT FROM OLD.publish_approval_id
               AND NOT (v_moved AND NEW.stage IN ('awaiting_approval', 'draft')))
           OR (NEW.gate_run_id IS DISTINCT FROM OLD.gate_run_id
               AND NOT (OLD.stage = 'evaluating'
                        OR (v_moved AND 'draft' IN (OLD.stage, NEW.stage))))
           OR ((NEW.published_by, NEW.published_at)
               IS DISTINCT FROM (OLD.published_by, OLD.published_at)
               AND NOT (v_moved AND NEW.stage = 'live'))
           OR ((NEW.retired_by, NEW.retired_at, NEW.retire_reason_code)
               IS DISTINCT FROM (OLD.retired_by, OLD.retired_at, OLD.retire_reason_code)
               AND NOT (OLD.stage = 'live' AND NEW.stage = 'retired')) THEN
            RAISE EXCEPTION 'version %: a lifecycle column changes only at its own step', NEW.id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_artifact_versions_stage_transition';
        END IF;
        IF NOT v_moved THEN
            RETURN NEW;
        END IF;

        IF NEW.stage = 'draft' THEN
            -- Back to the draft: everything the submit wrote is cleared.
            v_ok := OLD.stage IN ('evaluating', 'awaiting_approval')
                AND NEW.gate_run_id IS NULL AND NEW.publish_approval_id IS NULL
                AND NEW.submitted_by IS NULL AND NEW.submitted_at IS NULL
                AND NEW.compared_live_hash IS NULL AND NOT NEW.tighten_only;
        ELSIF OLD.stage = 'draft' AND NEW.stage = 'evaluating' THEN
            v_ok := v_gated AND NEW.submitted_by IS NOT NULL;
        ELSIF OLD.stage = 'draft' AND NEW.stage = 'awaiting_approval' THEN
            v_ok := NOT v_gated AND NEW.submitted_by IS NOT NULL
                AND NEW.publish_approval_id IS NOT NULL;
        ELSIF OLD.stage = 'evaluating' AND NEW.stage = 'awaiting_approval' THEN
            -- The gate's evidence lives in `studio.gate_runs` (ticket 06), which
            -- replaces this function with that branch; until then, closed.
            v_ok := false;
        ELSIF NEW.stage = 'live' AND OLD.stage IN ('awaiting_approval', 'draft') THEN
            -- The version this publish replaces: the one retired as superseded
            -- in this same transaction, since one live version per artifact
            -- makes `LifecycleService` retire it first.
            SELECT r.definition_hash INTO v_replaced
              FROM studio.artifact_versions r
             WHERE r.tenant_id = NEW.tenant_id AND r.artifact_id = NEW.artifact_id
               AND r.id <> NEW.id AND r.stage = 'retired'
               AND r.retire_reason_code = 'superseded'
               AND r.xmin = pg_current_xact_id()::xid
             ORDER BY r.retired_at DESC
             LIMIT 1;
            IF OLD.stage = 'awaiting_approval' THEN
                -- A gated kind adds its gate check here in ticket 06.
                v_ok := NOT v_gated
                    AND NEW.published_by IS NOT NULL
                    AND NEW.compared_live_hash IS NOT DISTINCT FROM v_replaced
                    AND EXISTS (
                        SELECT 1
                          FROM platform.approval_requests a
                          JOIN platform.approval_decisions d
                            ON d.tenant_id = a.tenant_id AND d.request_id = a.id
                         WHERE a.tenant_id = NEW.tenant_id
                           AND a.id = NEW.publish_approval_id
                           AND a.approval_type = 'studio.publish.' || v_kind
                           AND a.payload->>'version_id' = NEW.id::text
                           AND a.status = 'approved'
                           AND d.outcome = 'approved'
                           AND d.decided_by <> ALL (NEW.contributor_ids)
                           AND d.decided_by IS DISTINCT FROM NEW.submitted_by
                    );
            ELSE
                -- The tighten-only branch: an object definition alone (R1.7).
                v_ok := v_kind = 'object' AND NOT v_gated AND NEW.tighten_only
                    AND NEW.published_by IS NOT NULL AND NEW.submitted_by IS NOT NULL
                    AND v_replaced IS NOT NULL AND NEW.compared_live_hash = v_replaced;
            END IF;
        ELSIF OLD.stage = 'live' AND NEW.stage = 'retired' THEN
            v_ok := NEW.retired_by IS NOT NULL;
        END IF;

        IF NOT v_ok THEN
            RAISE EXCEPTION 'version % may not move from % to %', NEW.id, OLD.stage, NEW.stage
                USING ERRCODE = '23514', CONSTRAINT = 'ck_artifact_versions_stage_transition';
        END IF;
        RETURN NEW;
    END
    $$
    """

_TRIGGER = (
    "CREATE TRIGGER guard_version_stage BEFORE INSERT OR UPDATE ON studio.artifact_versions"
    " FOR EACH ROW EXECUTE FUNCTION studio.guard_version_stage()"
)

# R1.5: killed, live, awaiting approval, evaluating, draft, retired; computed
# under the reader's own RLS (`security_invoker`), never stored.
_VIEW = """
    CREATE VIEW studio.artifact_display_stage WITH (security_invoker = true) AS
    SELECT a.tenant_id,
           a.id AS artifact_id,
           CASE
               WHEN EXISTS (
                   SELECT 1 FROM platform.control_switches s
                    WHERE s.tenant_id = a.tenant_id AND s.target_id = a.id
                      AND s.action = 'kill' AND s.lifted_at IS NULL
               ) THEN 'killed'
               WHEN EXISTS (
                   SELECT 1 FROM studio.artifact_versions v
                    WHERE v.tenant_id = a.tenant_id AND v.artifact_id = a.id AND v.stage = 'live'
               ) THEN 'live'
               WHEN EXISTS (
                   SELECT 1 FROM studio.artifact_versions v
                    WHERE v.tenant_id = a.tenant_id AND v.artifact_id = a.id
                      AND v.stage = 'awaiting_approval'
               ) THEN 'awaiting_approval'
               WHEN EXISTS (
                   SELECT 1 FROM studio.artifact_versions v
                    WHERE v.tenant_id = a.tenant_id AND v.artifact_id = a.id
                      AND v.stage = 'evaluating'
               ) THEN 'evaluating'
               WHEN EXISTS (
                   SELECT 1 FROM studio.artifact_versions v
                    WHERE v.tenant_id = a.tenant_id AND v.artifact_id = a.id AND v.stage = 'draft'
               ) THEN 'draft'
               WHEN EXISTS (
                   SELECT 1 FROM studio.artifact_versions v
                    WHERE v.tenant_id = a.tenant_id AND v.artifact_id = a.id
                      AND v.stage = 'retired'
               ) THEN 'retired'
           END AS display_stage
    FROM studio.artifacts a
    """

_APP_GRANTS = (
    "GRANT UPDATE (gate_run_id, publish_approval_id, tighten_only, compared_live_hash,"
    " contributor_ids, submitted_by, submitted_at, published_by, published_at, retired_by,"
    " retired_at, retire_reason_code) ON studio.artifact_versions TO dw_app;",
)

# (key, label): workspace depth, standard risk (tenant-rbac/01's classes).
PERMISSIONS = (
    ("studio.versions.submit", "Gửi kiểm định phiên bản agent và quy trình"),
    ("studio.versions.retire", "Gỡ phiên bản đang dùng của agent và quy trình"),
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
    op.execute(_BACKFILL)
    op.execute(_NO_CONTRIBUTOR)
    for statement in _CONSTRAINTS:
        op.execute(statement)
    op.execute(_GUARD)
    # Called by its trigger and by no role.
    op.execute("REVOKE ALL ON FUNCTION studio.guard_version_stage() FROM PUBLIC")
    op.execute(_TRIGGER)
    op.execute(_VIEW)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    for key, label in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
                " 'dw_studio', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label)
        )


def downgrade() -> None:
    for key, _label in PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
            ).bindparams(k=key)
        )
        op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=key))
    op.execute("DROP VIEW studio.artifact_display_stage")
    op.execute("DROP TRIGGER guard_version_stage ON studio.artifact_versions")
    op.execute("DROP FUNCTION studio.guard_version_stage()")
    op.execute("DROP INDEX studio.uq_artifact_versions_live")
    op.execute("DROP INDEX studio.ix_artifact_versions_tenant_id_publish_approval_id")
    op.execute(
        "ALTER TABLE studio.artifact_versions"
        " DROP CONSTRAINT fk_artifact_versions_publish_approval_id_approval_requests,"
        " DROP COLUMN gate_run_id, DROP COLUMN publish_approval_id, DROP COLUMN tighten_only,"
        " DROP COLUMN compared_live_hash, DROP COLUMN contributor_ids,"
        " DROP COLUMN submitted_by, DROP COLUMN submitted_at, DROP COLUMN published_by,"
        " DROP COLUMN published_at, DROP COLUMN retired_by, DROP COLUMN retired_at,"
        " DROP COLUMN retire_reason_code"
    )
