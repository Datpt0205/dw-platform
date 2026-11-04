"""plan model profiles

Revision ID: d66d6913b249
Revises: ef68083f2905
Create Date: 2026-11-05 03:10:00.000000+00:00

model-connections ticket 02 (R2.1, R2.2; MR3; ADR-0118 decision 1): which
platform model profiles a plan lists, read by `ModelResolver` through
`SqlPlanModelProfiles`. A platform profile a plan does not list never resolves
for a tenant on that plan, and a plan with no rows lists none.

- `platform.plan_model_profiles`: `(plan_id, profile_id)` the primary key,
  leading with `plan_id`, so it is also the index of the foreign key into
  `platform.plans` ON DELETE CASCADE (a plan's rows go with it, as
  `platform.plan_limits`' do). `profile_id` names a file of `configs/models`,
  a configuration file rather than a row, so it has no foreign key; a test
  fails a row whose profile is not there (failure-modes #2).
- Global, like `platform.plan_limits`: no `tenant_id`, no RLS. Written by
  migrations only: `ALTER DEFAULT PRIVILEGES` (0001_platform_grants.sql)
  handed `dw_app` INSERT, UPDATE and DELETE on it, so those are revoked here,
  with TRUNCATE, from every application role; `dw_app` alone reads it.
- Data: every plan in `platform.plans` times every profile in `configs/models`
  at this revision, so no tenant loses a model the day the table appears. A
  profile added later belongs to no plan until a revision lists it.
"""

from __future__ import annotations

from alembic import op

revision = "d66d6913b249"
down_revision = "ef68083f2905"
branch_labels = None
depends_on = None

_TABLE = "platform.plan_model_profiles"
_ROLES = ("dw_app", "dw_provisioner", "dw_agent_ro")
# `configs/models/*.yaml` at this revision.
_PROFILES = ("balanced", "deepseek", "gateway", "low_cost", "luna", "openai")


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
    op.execute(
        f"""
        CREATE TABLE {_TABLE} (
            plan_id text NOT NULL,
            profile_id text NOT NULL,
            CONSTRAINT pk_plan_model_profiles PRIMARY KEY (plan_id, profile_id),
            CONSTRAINT fk_plan_model_profiles_plan_id_plans FOREIGN KEY (plan_id)
                REFERENCES platform.plans (plan_id) ON DELETE CASCADE,
            CONSTRAINT ck_plan_model_profiles_profile_id CHECK (profile_id <> '')
        )
        """
    )
    listed = ", ".join(f"('{profile}')" for profile in _PROFILES)
    op.execute(
        f"""
        INSERT INTO {_TABLE} (plan_id, profile_id)
        SELECT p.plan_id, m.profile_id
        FROM platform.plans p
        CROSS JOIN (VALUES {listed}) AS m (profile_id)
        """
    )
    for role in _ROLES:
        op.execute(
            _for_role(role, f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {_TABLE} FROM {role};")
        )
    op.execute(_for_role("dw_app", f"GRANT SELECT ON {_TABLE} TO dw_app;"))


def downgrade() -> None:
    op.execute(f"DROP TABLE {_TABLE}")
