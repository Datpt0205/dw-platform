"""run manifests

Revision ID: 28a94cda6fdf
Revises: 2354ad4d2e3c
Create Date: 2026-11-04 06:19:42.563338+00:00

tenant-config ticket 04 (R6.1-R6.9, R2.18, R3.6, R3.8; TC15, TC21, TC28,
TC29, TC31, TC32; ADR-0109 decisions 6-8). What a Studio run pinned, stored
once per content:

- `platform.run_manifests`: a `dw.run_manifest/v1` body keyed
  `(tenant_id, hash)`, written `INSERT ... ON CONFLICT DO NOTHING`; the body
  is a JSON object of at most 1 MiB in NFC, and the size is its own CHECK,
  `ck_run_manifests_body_size`, which the store reads back as 413 (R6.1).
- `platform.run_manifest_keys`: each version a manifest pins, one row per
  `(tenant_id, manifest_hash, artifact_version_id)`, CASCADE from its manifest
  and RESTRICT to `studio.artifact_versions` through the composite key to
  `uq_artifact_versions_tenant_id_id` (R2.18, R6.5). `id` is its primary key,
  the keyset offboarding's export pages on: ticket 05 makes
  `artifact_version_id` nullable beside its `config_version_id`, so the
  unique triple cannot be the key. The unique is named by hand: the
  convention's name is 64 characters, one past PostgreSQL's limit.
- `platform.worker_runs.run_manifest_hash`: NULL for a code-defined worker's
  run and a DW's wf-lite run; FK `(tenant_id, run_manifest_hash)` RESTRICT.
  `platform.match_run_manifest()` refuses a row whose `run_mode` is not its
  manifest's, read under the caller's RLS, and a hash changed once set
  (R6.9). The CHECK that a Studio root carries a manifest lands with
  `artifact_kind` in workflow-engine/02.

Both tables are tenant-wide (content-addressed, shared by every run of the same
content), under the tenant policy, ENABLEd and FORCEd. `dw_app` holds SELECT,
INSERT and DELETE and nothing else; the DELETE serves only the offboarding
lane's pass, `platform.refuse_delete_outside_offboarding()` refuses it
elsewhere (R3.8). Neither table is partitioned: they are keyed by content, not
time, and the foreign keys into `run_manifests` need a unique key without a
partition column; retention of run manifests is W2 (ADR-0109 Open 3).
"""

from __future__ import annotations

from alembic import op

revision = "28a94cda6fdf"
down_revision = "2354ad4d2e3c"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_HASH = "~ '^sha256:[0-9a-f]{64}$'"
_MIB = 1048576

_TABLES = (
    f"""
    CREATE TABLE platform.run_manifests (
        tenant_id uuid NOT NULL,
        hash text NOT NULL,
        body jsonb NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_run_manifests PRIMARY KEY (tenant_id, hash),
        CONSTRAINT fk_run_manifests_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE RESTRICT,
        CONSTRAINT ck_run_manifests_hash CHECK (hash {_HASH}),
        CONSTRAINT ck_run_manifests_body_object CHECK (jsonb_typeof(body) = 'object'),
        CONSTRAINT ck_run_manifests_body_size CHECK (octet_length(body::text) <= {_MIB}),
        CONSTRAINT ck_run_manifests_body_nfc CHECK (body::text IS NFC NORMALIZED)
    )
    """,
    """
    CREATE TABLE platform.run_manifest_keys (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        manifest_hash text NOT NULL,
        artifact_version_id uuid NOT NULL,
        CONSTRAINT pk_run_manifest_keys PRIMARY KEY (id),
        CONSTRAINT fk_run_manifest_keys_manifest_hash_run_manifests
            FOREIGN KEY (manifest_hash, tenant_id)
            REFERENCES platform.run_manifests (hash, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_run_manifest_keys_artifact_version_id_artifact_versions
            FOREIGN KEY (artifact_version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id) ON DELETE RESTRICT,
        -- Leads with the manifest key's two columns, so it is that key's index.
        CONSTRAINT uq_run_manifest_keys_tenant_id_manifest_hash_artifact_version
            UNIQUE (tenant_id, manifest_hash, artifact_version_id)
    )
    """,
    "CREATE INDEX ix_run_manifest_keys_tenant_id_artifact_version_id"
    " ON platform.run_manifest_keys (tenant_id, artifact_version_id)",
    "ALTER TABLE platform.worker_runs ADD COLUMN run_manifest_hash text",
    f"""
    ALTER TABLE platform.worker_runs
        ADD CONSTRAINT ck_worker_runs_run_manifest_hash
            CHECK (run_manifest_hash IS NULL OR run_manifest_hash {_HASH}),
        ADD CONSTRAINT fk_worker_runs_run_manifest_hash_run_manifests
            FOREIGN KEY (run_manifest_hash, tenant_id)
            REFERENCES platform.run_manifests (hash, tenant_id) ON DELETE RESTRICT
    """,
    "CREATE INDEX ix_worker_runs_tenant_id_run_manifest_hash"
    " ON platform.worker_runs (tenant_id, run_manifest_hash)",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
# Tenant-only: a manifest is shared by every run of the same content.
_RLS = (
    "ALTER TABLE platform.run_manifests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.run_manifests FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_run_manifests ON platform.run_manifests"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE platform.run_manifest_keys ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.run_manifest_keys FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_run_manifest_keys ON platform.run_manifest_keys"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# R6.9 (TC28): the mode the executor reads on the row is the mode the manifest
# pinned, and a pinned run keeps its manifest. Not a definer: the manifest is
# read under the caller's RLS, so a row naming another tenant's manifest, or
# one the caller cannot read, is refused like a mismatch.
_MATCH_RUN_MANIFEST = """
    CREATE FUNCTION platform.match_run_manifest() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        v_mode text;
    BEGIN
        IF TG_OP = 'UPDATE' AND OLD.run_manifest_hash IS NOT NULL
           AND NEW.run_manifest_hash IS DISTINCT FROM OLD.run_manifest_hash THEN
            RAISE EXCEPTION 'a run keeps the manifest it pinned'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_worker_runs_manifest_pinned';
        END IF;
        IF NEW.run_manifest_hash IS NOT NULL THEN
            SELECT m.body->>'run_mode' INTO v_mode
            FROM platform.run_manifests m
            WHERE m.tenant_id = NEW.tenant_id AND m.hash = NEW.run_manifest_hash;
            IF v_mode IS DISTINCT FROM NEW.run_mode THEN
                RAISE EXCEPTION 'the run mode is not the one its manifest pinned'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_worker_runs_manifest_run_mode';
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """

_TRIGGERS = (
    "CREATE TRIGGER match_run_manifest"
    " BEFORE INSERT OR UPDATE OF run_manifest_hash, run_mode ON platform.worker_runs"
    " FOR EACH ROW EXECUTE FUNCTION platform.match_run_manifest()",
    # R3.8 (TC31): only the offboarding lane's pass deletes these rows.
    "CREATE TRIGGER refuse_delete_outside_offboarding BEFORE DELETE ON platform.run_manifests"
    " FOR EACH ROW EXECUTE FUNCTION platform.refuse_delete_outside_offboarding()",
    "CREATE TRIGGER refuse_delete_outside_offboarding BEFORE DELETE"
    " ON platform.run_manifest_keys"
    " FOR EACH ROW EXECUTE FUNCTION platform.refuse_delete_outside_offboarding()",
)

# `ALTER DEFAULT PRIVILEGES` (0001_platform_grants.sql) hands `dw_app` every
# verb and `dw_agent_ro` SELECT on a new platform table; these hold exactly
# what the store and the offboarding lane run.
_GRANTS = (
    ("dw_app", "REVOKE ALL ON platform.run_manifests FROM dw_app;"),
    ("dw_app", "GRANT SELECT, INSERT, DELETE ON platform.run_manifests TO dw_app;"),
    ("dw_app", "REVOKE ALL ON platform.run_manifest_keys FROM dw_app;"),
    ("dw_app", "GRANT SELECT, INSERT, DELETE ON platform.run_manifest_keys TO dw_app;"),
    ("dw_agent_ro", "REVOKE ALL ON platform.run_manifests FROM dw_agent_ro;"),
    ("dw_agent_ro", "REVOKE ALL ON platform.run_manifest_keys FROM dw_agent_ro;"),
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
    op.execute(_MATCH_RUN_MANIFEST)
    # Called by its trigger and by no role.
    op.execute("REVOKE ALL ON FUNCTION platform.match_run_manifest() FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for role, statement in _GRANTS:
        op.execute(_for_role(role, statement))


def downgrade() -> None:
    op.execute("DROP TRIGGER match_run_manifest ON platform.worker_runs")
    op.execute("DROP FUNCTION platform.match_run_manifest()")
    op.execute("DROP INDEX platform.ix_worker_runs_tenant_id_run_manifest_hash")
    op.execute("ALTER TABLE platform.worker_runs DROP COLUMN run_manifest_hash")
    op.execute("DROP TABLE platform.run_manifest_keys")
    op.execute("DROP TABLE platform.run_manifests")
