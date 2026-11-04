"""studio display stage over versions

Revision ID: 9b97696ff72f
Revises: 6503c6f309b1
Create Date: 2026-11-04

agent-lifecycle ticket 03 (R1.5): `studio.artifact_display_stage` computed
from `studio.artifact_versions` alone, grouped by artifact, instead of from
`studio.artifacts` with a subquery per stage. The list of artifacts reads the
view for each row it pages through; read through `studio.artifacts` again,
that is a second scan of the table the page is ordered on, which
`test_plan_shape.py` refuses (a paged route reads through the index that
carries it). Grouped by `(tenant_id, artifact_id)`, the per-row lookup pushes
into `ix_artifact_versions_tenant_id_artifact_id`. Same columns, same order of
precedence (killed, live, awaiting approval, evaluating, draft, retired),
still `security_invoker`; every artifact has a version from its creation, so
no artifact drops out.
"""

from __future__ import annotations

from alembic import op

revision = "9b97696ff72f"
down_revision = "6503c6f309b1"
branch_labels = None
depends_on = None

_OVER_VERSIONS = """
    CREATE OR REPLACE VIEW studio.artifact_display_stage WITH (security_invoker = true) AS
    SELECT v.tenant_id,
           v.artifact_id,
           CASE
               WHEN EXISTS (
                   SELECT 1 FROM platform.control_switches s
                    WHERE s.tenant_id = v.tenant_id AND s.target_id = v.artifact_id
                      AND s.action = 'kill' AND s.lifted_at IS NULL
               ) THEN 'killed'
               WHEN bool_or(v.stage = 'live') THEN 'live'
               WHEN bool_or(v.stage = 'awaiting_approval') THEN 'awaiting_approval'
               WHEN bool_or(v.stage = 'evaluating') THEN 'evaluating'
               WHEN bool_or(v.stage = 'draft') THEN 'draft'
               WHEN bool_or(v.stage = 'retired') THEN 'retired'
           END AS display_stage
    FROM studio.artifact_versions v
    GROUP BY v.tenant_id, v.artifact_id
    """

# Revision 6503c6f309b1's, restored on the way down.
_OVER_ARTIFACTS = """
    CREATE OR REPLACE VIEW studio.artifact_display_stage WITH (security_invoker = true) AS
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


def upgrade() -> None:
    op.execute(_OVER_VERSIONS)


def downgrade() -> None:
    op.execute(_OVER_ARTIFACTS)
