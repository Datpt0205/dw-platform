"""studio version assessments

Revision ID: c240f5261ec5
Revises: 8a693dcd2c04
Create Date: 2026-11-06 07:10:00.000000+00:00

compliance-pdpl ticket 05 (R4.6, R4.7, R5.5; CP21; ADR-0125 decisions 1-3).

`studio.version_assessments`: the capability analysis of a version at its
submit, written in the submit's transaction (a refused submit rolls back and
leaves none): the labels each step carried (`labels`), their union
(`signals`, what a parent workflow's step on this version reads, R4.8), the
analyser that decided it and the definition hash it ran on. One row per
`(version, definition hash, analyser version)`, written `ON CONFLICT DO
NOTHING`, so a second submit of the same content by the same analyser adds
nothing and fails nothing. A tenant-wide table (DO-01): it follows its
version, which belongs to the company. The version's key is composite,
`(version_id, tenant_id)` to `uq_artifact_versions_tenant_id_id`, so a row of
company A never names a version of company B (R4.7), and CASCADEs, so the
offboarding lane's delete of the versions takes the assessments with them
(R5.5); the unique key leads with its two columns and is its index. `dw_app`
holds SELECT and INSERT, never UPDATE or DELETE.
"""

from __future__ import annotations

from alembic import op

revision = "c240f5261ec5"
down_revision = "8a693dcd2c04"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_LABELS = "ARRAY['untrusted_source', 'private_data', 'external_effect']::text[]"

_TABLE = f"""
    CREATE TABLE studio.version_assessments (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        version_id uuid NOT NULL,
        definition_hash text NOT NULL,
        analyser_version text NOT NULL,
        signals text[] NOT NULL,
        labels jsonb NOT NULL,
        verdict text NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_version_assessments PRIMARY KEY (tenant_id, id),
        CONSTRAINT fk_version_assessments_version_id_artifact_versions
            FOREIGN KEY (version_id, tenant_id)
            REFERENCES studio.artifact_versions (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT uq_version_assessments_tenant_version_hash_analyser
            UNIQUE (tenant_id, version_id, definition_hash, analyser_version),
        CONSTRAINT ck_version_assessments_signals CHECK (signals <@ {_LABELS}),
        CONSTRAINT ck_version_assessments_verdict CHECK (verdict IN ('pass')),
        CONSTRAINT ck_version_assessments_labels CHECK (jsonb_typeof(labels) = 'object'),
        CONSTRAINT ck_version_assessments_definition_hash
            CHECK (definition_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CONSTRAINT ck_version_assessments_analyser_version
            CHECK (char_length(analyser_version) BETWEEN 1 AND 32)
    )
"""

_STATEMENTS = (
    # Written out, not looped: `scripts/verify_invariants.py` reads this text.
    # Tenant-only: the assessment's workspace is its version's artifact's.
    "ALTER TABLE studio.version_assessments ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.version_assessments FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_version_assessments ON studio.version_assessments"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# What `dw_app` holds beyond the schema's default SELECT (ADR 0100 point 4):
# an assessment is written once and never changed or deleted by it.
_APP_GRANTS = ("GRANT INSERT ON studio.version_assessments TO dw_app;",)


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
    op.execute(_TABLE)
    for statement in _STATEMENTS:
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))


def downgrade() -> None:
    op.execute("DROP TABLE studio.version_assessments")
