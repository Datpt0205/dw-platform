"""plan limits

Revision ID: 764b0e239f95
Revises: 349080a62e41
Create Date: 2026-11-02 07:49:59.522772+00:00

usage-and-limits ticket 01 (R1.1-R1.4, UL1; ADR-0121 decision 9): a plan's
numbers have one owner, `platform.plan_limits`, and `DEFAULT_PLANS` in
`dw_platform.application.entitlement` is gone with this revision.

- `platform.plan_limits`: one row per plan, `plan_id` the primary key and a
  foreign key into `platform.plans` ON DELETE CASCADE (the key carries the
  index). Global, like `platform.permissions`: no `tenant_id`, no RLS. Written
  by migrations only: `ALTER DEFAULT PRIVILEGES` (0001_platform_grants.sql)
  handed `dw_app` INSERT, UPDATE and DELETE on it, so those are revoked here,
  with TRUNCATE, from every application role; `dw_app` alone reads it.
- Columns: the daily and monthly ceilings are NULL for "no limit", CHECK
  `>= 0`; the per-run maxima are NOT NULL, `max_steps_per_run` BETWEEN 1 AND
  500 (the `le=500` of `recursion_limit`, `contracts.py`), the others `> 0`.
  USD in `numeric(20,8)` as `platform.limit_policies.limit_value` will be,
  tokens `bigint`, counts `integer` (ticket Comments M4). No column for run
  time, concurrency or rate: each joins in W2 with its reader.
- Data: `platform.plans.quotas` moves to the columns, for the three plans the
  code catalogue knew; the runtime read those numbers from that dict, not from
  this column, so the move refuses if the two disagree rather than choosing
  one quietly (failure-modes #2). A plan the dict did not know was refused a
  run, and it still is: it gets no row. Money NULL (DO-59.1); the per-run
  maxima equal on every plan: 2.0 USD and 120000 tokens (`ModelBudgets`,
  `profiles.py`), 50 steps (`recursion_limit`), 50 model calls and 200 tool
  calls (ticket Comments B3). Then `quotas` is dropped; features stay in
  `platform.plans.features`.
"""

from __future__ import annotations

from alembic import op

revision = "764b0e239f95"
down_revision = "349080a62e41"
branch_labels = None
depends_on = None

_TABLE = "platform.plan_limits"
_ROLES = ("dw_app", "dw_provisioner", "dw_agent_ro")
# What `DEFAULT_PLANS` enforced until this revision: (plan_id, runs_per_day).
_CODE_CATALOGUE = (("basic", 20), ("professional", 200), ("enterprise", 2000))


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
            runs_per_day integer,
            cost_usd_per_day numeric(20, 8),
            cost_usd_per_month numeric(20, 8),
            tokens_per_month bigint,
            max_cost_usd_per_run numeric(20, 8) NOT NULL,
            max_tokens_per_run bigint NOT NULL,
            max_steps_per_run integer NOT NULL,
            max_model_calls_per_run integer NOT NULL,
            max_tool_calls_per_run integer NOT NULL,
            CONSTRAINT pk_plan_limits PRIMARY KEY (plan_id),
            CONSTRAINT fk_plan_limits_plan_id_plans FOREIGN KEY (plan_id)
                REFERENCES platform.plans (plan_id) ON DELETE CASCADE,
            CONSTRAINT ck_plan_limits_runs_per_day CHECK (runs_per_day >= 0),
            CONSTRAINT ck_plan_limits_cost_usd_per_day CHECK (cost_usd_per_day >= 0),
            CONSTRAINT ck_plan_limits_cost_usd_per_month CHECK (cost_usd_per_month >= 0),
            CONSTRAINT ck_plan_limits_tokens_per_month CHECK (tokens_per_month >= 0),
            CONSTRAINT ck_plan_limits_max_cost_usd_per_run CHECK (max_cost_usd_per_run > 0),
            CONSTRAINT ck_plan_limits_max_tokens_per_run CHECK (max_tokens_per_run > 0),
            CONSTRAINT ck_plan_limits_max_steps_per_run
                CHECK (max_steps_per_run BETWEEN 1 AND 500),
            CONSTRAINT ck_plan_limits_max_model_calls_per_run
                CHECK (max_model_calls_per_run > 0),
            CONSTRAINT ck_plan_limits_max_tool_calls_per_run CHECK (max_tool_calls_per_run > 0)
        )
        """
    )
    known = ", ".join(f"('{plan}', {runs})" for plan, runs in _CODE_CATALOGUE)
    op.execute(
        f"""
        INSERT INTO {_TABLE} (plan_id, runs_per_day, max_cost_usd_per_run, max_tokens_per_run,
                              max_steps_per_run, max_model_calls_per_run, max_tool_calls_per_run)
        SELECT p.plan_id, (p.quotas ->> 'runs_per_day')::integer, 2.0, 120000, 50, 50, 200
        FROM platform.plans p
        JOIN (VALUES {known}) AS code (plan_id, runs_per_day) ON code.plan_id = p.plan_id
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM {_TABLE} l
                JOIN (VALUES {known}) AS code (plan_id, runs_per_day) USING (plan_id)
                WHERE l.runs_per_day IS DISTINCT FROM code.runs_per_day
            ) THEN
                RAISE EXCEPTION 'platform.plans.quotas disagrees with the runs_per_day the'
                    ' runtime enforced (DEFAULT_PLANS); decide which is right first';
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER TABLE platform.plans DROP COLUMN quotas")
    for role in _ROLES:
        op.execute(
            _for_role(role, f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {_TABLE} FROM {role};")
        )
    op.execute(_for_role("dw_app", f"GRANT SELECT ON {_TABLE} TO dw_app;"))


def downgrade() -> None:
    op.execute("ALTER TABLE platform.plans ADD COLUMN quotas jsonb DEFAULT '{}'::jsonb NOT NULL")
    op.execute(
        f"""
        UPDATE platform.plans p
        SET quotas = jsonb_build_object('runs_per_day', l.runs_per_day)
        FROM {_TABLE} l
        WHERE l.plan_id = p.plan_id AND l.runs_per_day IS NOT NULL
        """
    )
    op.execute(f"DROP TABLE {_TABLE}")
