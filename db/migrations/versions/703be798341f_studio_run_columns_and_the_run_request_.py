"""studio run columns and the run request door

Revision ID: 703be798341f
Revises: 9b97696ff72f
Create Date: 2026-11-04 13:38:02.697634+00:00

workflow-engine ticket 02 (R3.1, R3.2, R3.3, R3.5-R3.8, R3.12, R3.18, R3.19;
WE1, WE18, WE21, WE50; ADR-0113 decision 1). What `platform.worker_runs`
needs to hold a Studio run, which `RunRequestService` writes `queued` and
nothing else does:

- fifteen columns, named as the spec's Data section names them; the queue's
  are ADR-0113's (`priority`, `available_at`, `lease_owner`, `lease_until`,
  `attempt`, `deadline_at`; a dead letter is `status = 'dead_lettered'`, no
  column). `definition_hash` (wf-lite, `16ac88642439`) and
  `run_as_principal_id` (digital-worker, `cfbd906be98b`) are there already.
- `root_run_id` NOT NULL: every existing row becomes its own root (with the
  `updated_at` trigger off, so no row looks touched today), and
  `platform.default_root_run_id()` fills it on any insert that names none (a
  code-defined worker's run, a test fixture), one owner instead of ten insert
  sites.
- `artifact_version_id` and `parent_run_id` each by a composite key that
  carries `tenant_id`, RESTRICT: a foreign key is checked past RLS, so a key
  on the id alone would let tenant A name tenant B's version or run (R3.12).
  The self key's target is `uq_worker_runs_tenant_id_id`, made first.
  Offboarding gains no step: its order comes from the RESTRICT edges, which
  put `platform.worker_runs` before `studio.artifact_versions`, and one
  `DELETE ... WHERE tenant_id` takes a parent and its children together.
- CHECKs on what a Studio row must carry (trigger kind, manifest, run-as
  principal, request key, its artifact) and on the shape of the run tree;
  `ck_worker_runs_definition_hash` read by its owner: bare hex for wf-lite,
  `sha256:` for Studio, as `studio.artifact_versions` holds it.
- `uq_worker_runs_active_thread` rebuilt with `dead_lettered` among the
  finished statuses, the set `TERMINAL_STATUSES` names in `run_store.py`.
- the indexes the queue, the reaper, the run list and the two keys read.

`ck_worker_runs_status` is runtime-hardening/03's, untouched. Grants do not
change: `dw_app` already holds SELECT, INSERT, UPDATE and DELETE on the table
and no column grant narrows it; the new trigger function is callable by no
role.
"""

from __future__ import annotations

from alembic import op

revision = "703be798341f"
down_revision = "9b97696ff72f"
branch_labels = None
depends_on = None

_FINISHED = "'completed', 'failed', 'cancelled', 'dead_lettered'"
_FINISHED_BEFORE = "'completed', 'failed', 'cancelled'"
_UNFINISHED = "'queued', 'running', 'waiting', 'blocked'"

_COLUMNS = """
    ALTER TABLE platform.worker_runs
        ADD COLUMN root_run_id uuid,
        ADD COLUMN parent_run_id uuid,
        ADD COLUMN chain_depth smallint DEFAULT 0 NOT NULL,
        ADD COLUMN artifact_kind text,
        ADD COLUMN artifact_id uuid,
        ADD COLUMN artifact_version_id uuid,
        ADD COLUMN trigger_kind text,
        ADD COLUMN inbound_event_id uuid,
        ADD COLUMN request_key text,
        ADD COLUMN priority smallint DEFAULT 0 NOT NULL,
        ADD COLUMN available_at timestamp with time zone DEFAULT now() NOT NULL,
        ADD COLUMN lease_owner text,
        ADD COLUMN lease_until timestamp with time zone,
        ADD COLUMN attempt smallint DEFAULT 0 NOT NULL,
        ADD COLUMN deadline_at timestamp with time zone
    """

# Every existing row is a root. The `updated_at` trigger is off for the
# backfill, so a row's last change keeps its real time (a running row is aged
# by it, `run_store._reap_stale_thread`).
_BACKFILL = (
    "ALTER TABLE platform.worker_runs DISABLE TRIGGER touch_updated_at",
    "UPDATE platform.worker_runs SET root_run_id = id",
    "ALTER TABLE platform.worker_runs ENABLE TRIGGER touch_updated_at",
    "ALTER TABLE platform.worker_runs ALTER COLUMN root_run_id SET NOT NULL",
)

# One owner for "a run that names no root is its own".
_DEFAULT_ROOT = """
    CREATE FUNCTION platform.default_root_run_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.root_run_id := COALESCE(NEW.root_run_id, NEW.id);
        RETURN NEW;
    END
    $$
    """

_HEX = "'^[0-9a-f]{64}$'"
_SHA256 = "'^sha256:[0-9a-f]{64}$'"

_CONSTRAINTS = f"""
    ALTER TABLE platform.worker_runs
        ADD CONSTRAINT uq_worker_runs_tenant_id_id UNIQUE (tenant_id, id),
        ADD CONSTRAINT fk_worker_runs_artifact_version_id_artifact_versions
            FOREIGN KEY (artifact_version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id) ON DELETE RESTRICT,
        ADD CONSTRAINT fk_worker_runs_parent_run_id_worker_runs
            FOREIGN KEY (parent_run_id, tenant_id)
            REFERENCES platform.worker_runs (id, tenant_id) ON DELETE RESTRICT,
        ADD CONSTRAINT ck_worker_runs_trigger_kind
            CHECK (trigger_kind IN ('chat', 'manual', 'test', 'eval', 'datahub')),
        ADD CONSTRAINT ck_worker_runs_studio_trigger_kind
            CHECK (artifact_kind IS NULL OR trigger_kind IS NOT NULL),
        ADD CONSTRAINT ck_worker_runs_priority CHECK (priority IN (0, 1, 2)),
        ADD CONSTRAINT ck_worker_runs_studio_manifest
            CHECK (artifact_kind IS NULL OR run_manifest_hash IS NOT NULL),
        ADD CONSTRAINT ck_worker_runs_studio_run_as
            CHECK (artifact_kind IS NULL OR run_as_principal_id IS NOT NULL),
        ADD CONSTRAINT ck_worker_runs_studio_request_key
            CHECK (artifact_kind IS NULL OR request_key IS NOT NULL),
        ADD CONSTRAINT ck_worker_runs_studio_artifact
            CHECK ((artifact_kind IS NULL) = (artifact_id IS NULL)
                   AND (artifact_kind IS NULL) = (artifact_version_id IS NULL)),
        ADD CONSTRAINT ck_worker_runs_root_run
            CHECK ((parent_run_id IS NULL AND root_run_id = id AND chain_depth = 0)
                   OR (parent_run_id IS NOT NULL AND chain_depth > 0)),
        DROP CONSTRAINT ck_worker_runs_definition_hash,
        ADD CONSTRAINT ck_worker_runs_definition_hash
            CHECK (definition_hash IS NULL
                   OR (artifact_kind IS NULL AND definition_hash ~ {_HEX})
                   OR (artifact_kind IS NOT NULL AND definition_hash ~ {_SHA256}))
    """

_INDEXES = (
    "DROP INDEX platform.uq_worker_runs_active_thread",
    "CREATE UNIQUE INDEX uq_worker_runs_active_thread ON platform.worker_runs"
    f" (tenant_id, thread_id) WHERE status NOT IN ({_FINISHED})",
    # The door's `ON CONFLICT` target (R3.6, R3.20).
    "CREATE UNIQUE INDEX uq_worker_runs_tenant_id_request_key ON platform.worker_runs"
    " (tenant_id, request_key) WHERE request_key IS NOT NULL",
    # The `studio_runs` lane's fair take (ticket 04).
    "CREATE INDEX ix_worker_runs_tenant_id_priority_available_at ON platform.worker_runs"
    " (tenant_id, priority, available_at) WHERE status = 'queued'",
    "CREATE INDEX ix_worker_runs_tenant_id_artifact_id_created_at ON platform.worker_runs"
    " (tenant_id, artifact_id, created_at DESC, id DESC)",
    "CREATE INDEX ix_worker_runs_tenant_id_root_run_id ON platform.worker_runs"
    " (tenant_id, root_run_id)",
    "CREATE INDEX ix_worker_runs_tenant_id_inbound_event_id ON platform.worker_runs"
    " (tenant_id, inbound_event_id) WHERE inbound_event_id IS NOT NULL",
    # The two composite keys' own indexes.
    "CREATE INDEX ix_worker_runs_tenant_id_artifact_version_id ON platform.worker_runs"
    " (tenant_id, artifact_version_id)",
    "CREATE INDEX ix_worker_runs_tenant_id_parent_run_id ON platform.worker_runs"
    " (tenant_id, parent_run_id) WHERE parent_run_id IS NOT NULL",
    # The `studio_run_reaper` lane's deadline sweep (ticket 04).
    "CREATE INDEX ix_worker_runs_tenant_id_deadline_at ON platform.worker_runs"
    f" (tenant_id, deadline_at) WHERE status IN ({_UNFINISHED})",
    # `GET /api/v1/runs` pages on it (telemetry-and-audit R4.1; H-20).
    "CREATE INDEX ix_worker_runs_page ON platform.worker_runs"
    " (tenant_id, workspace_id, created_at DESC, id DESC)",
)


def upgrade() -> None:
    op.execute(_COLUMNS)
    for statement in _BACKFILL:
        op.execute(statement)
    op.execute(_DEFAULT_ROOT)
    # Called by its trigger and by no role.
    op.execute("REVOKE ALL ON FUNCTION platform.default_root_run_id() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER default_root_run_id BEFORE INSERT ON platform.worker_runs"
        " FOR EACH ROW EXECUTE FUNCTION platform.default_root_run_id()"
    )
    op.execute(_CONSTRAINTS)
    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        "DROP INDEX platform.ix_worker_runs_page",
        "DROP INDEX platform.ix_worker_runs_tenant_id_deadline_at",
        "DROP INDEX platform.ix_worker_runs_tenant_id_parent_run_id",
        "DROP INDEX platform.ix_worker_runs_tenant_id_artifact_version_id",
        "DROP INDEX platform.ix_worker_runs_tenant_id_inbound_event_id",
        "DROP INDEX platform.ix_worker_runs_tenant_id_root_run_id",
        "DROP INDEX platform.ix_worker_runs_tenant_id_artifact_id_created_at",
        "DROP INDEX platform.ix_worker_runs_tenant_id_priority_available_at",
        "DROP INDEX platform.uq_worker_runs_tenant_id_request_key",
        "DROP INDEX platform.uq_worker_runs_active_thread",
        "CREATE UNIQUE INDEX uq_worker_runs_active_thread ON platform.worker_runs"
        f" (tenant_id, thread_id) WHERE status NOT IN ({_FINISHED_BEFORE})",
        "ALTER TABLE platform.worker_runs DROP CONSTRAINT ck_worker_runs_definition_hash,"
        f" ADD CONSTRAINT ck_worker_runs_definition_hash CHECK (definition_hash IS NULL"
        f" OR definition_hash ~ {_HEX})",
        "DROP TRIGGER default_root_run_id ON platform.worker_runs",
        "DROP FUNCTION platform.default_root_run_id()",
        # The columns take their constraints, keys and indexes with them.
        "ALTER TABLE platform.worker_runs"
        " DROP COLUMN deadline_at, DROP COLUMN attempt, DROP COLUMN lease_until,"
        " DROP COLUMN lease_owner, DROP COLUMN available_at, DROP COLUMN priority,"
        " DROP COLUMN request_key, DROP COLUMN inbound_event_id, DROP COLUMN trigger_kind,"
        " DROP COLUMN artifact_version_id, DROP COLUMN artifact_id, DROP COLUMN artifact_kind,"
        " DROP COLUMN chain_depth, DROP COLUMN parent_run_id, DROP COLUMN root_run_id",
        "ALTER TABLE platform.worker_runs DROP CONSTRAINT uq_worker_runs_tenant_id_id",
    ):
        op.execute(statement)
