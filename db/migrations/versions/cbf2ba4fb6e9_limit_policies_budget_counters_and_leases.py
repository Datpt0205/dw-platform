"""limit policies, budget counters and leases; the daily spend guard goes

Revision ID: cbf2ba4fb6e9
Revises: f97fd77ce9a0
Create Date: 2026-11-05 09:00:00.000000+00:00

usage-and-limits ticket 03 (spec R3.8, R4.1, R4.12-R4.16, R5.1-R5.11; UL2,
UL6, UL17, UL19; ADR-0121 decisions 4, 5, 7, 9).

- `platform.limit_policies`: one hard limit of a company at one scope of the
  chain. The scope is a typed key, `scope_workspace_id` or `scope_artifact_id`,
  each a composite foreign key `(tenant_id, <column>)` to the `UNIQUE (tenant_id,
  id)` of `platform.workspaces` (`uq_workspaces_tenant_id_id`) or
  `studio.artifacts` (`uq_artifacts_tenant_id_id`), `ON DELETE CASCADE` and
  indexed on its own side, so a row naming another company's workspace or
  component is refused even by a role that bypasses RLS (R4.13) and a deleted
  scope takes its policies with it (R4.12). Exactly the column of its
  `scope_type` is set, none for `tenant`. The pair (`metric`, `window_kind`)
  is one of the four of W1 by CHECK (R4.16), `kind` is `hard` (R4.8). Tenant
  policy only: a tenant-wide table, listed with its reason in
  `test_rls_coverage.py`. `updated_at` by `platform.touch_updated_at()`, which
  yields to a value the statement states.
- `platform.budget_counters`: one row per scope, pair and window, `used` and
  `reserved` never below zero. Tenant policy, and the drain's SELECT and
  DELETE (`retention_limits` prunes past windows across companies).
- `platform.budget_leases`: one open lease per root run (partial UNIQUE), the
  open ones indexed by `expires_at` for the reaper. Tenant policy, and the
  drain's SELECT (the reaper finds the expired leases of every company, then
  closes each under its own tenant).
- `dw_app`: SELECT, INSERT, UPDATE, DELETE on the three (DELETE for the
  offboarding lane, which exports and purges them as ordinary tables, R3.8,
  and for `retention_limits`); `dw_agent_ro` nothing.
- `platform.plan_limits.max_tokens_per_run` is the tokens in and out of one run
  (ticket 01 M2): 120000 becomes 200000, so the `gateway` profile's runs are not
  squeezed below what its budgets allowed.
- `platform.limits.manage` joins the permission catalogue (`scope_kind`
  `tenant`, `risk` `elevated`, grantable).
- `platform.tenant_daily_spend_guard` is dropped: the leases replace it
  (ADR-0121 decision 7). The downgrade recreates it with both its policies.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "cbf2ba4fb6e9"
down_revision = "f97fd77ce9a0"
branch_labels = None
depends_on = None

# Each setting read once per statement, in a sub-SELECT (foundations-hardening R5.3).
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_DRAIN = "((SELECT current_setting('app.worker_drain', true)) = 'on')"
_SCOPES = "('tenant', 'workspace', 'agent', 'workflow')"
_PAIRS = "(('cost_usd', 'day'), ('cost_usd', 'month'), ('tokens', 'month'), ('runs', 'day'))"


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


_LIMIT_POLICIES = f"""
    CREATE TABLE platform.limit_policies (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        scope_type text NOT NULL,
        scope_workspace_id uuid,
        scope_artifact_id uuid,
        metric text NOT NULL,
        window_kind text NOT NULL,
        kind text NOT NULL DEFAULT 'hard',
        limit_value numeric(20, 8) NOT NULL,
        version integer NOT NULL DEFAULT 1,
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_limit_policies PRIMARY KEY (id),
        CONSTRAINT fk_limit_policies_tenant_id_workspaces
            FOREIGN KEY (tenant_id, scope_workspace_id)
            REFERENCES platform.workspaces (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_limit_policies_tenant_id_artifacts
            FOREIGN KEY (tenant_id, scope_artifact_id)
            REFERENCES studio.artifacts (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT ck_limit_policies_scope_type CHECK (scope_type IN {_SCOPES}),
        CONSTRAINT ck_limit_policies_scope_column CHECK (
            CASE scope_type
                WHEN 'tenant' THEN num_nonnulls(scope_workspace_id, scope_artifact_id) = 0
                WHEN 'workspace' THEN num_nonnulls(scope_workspace_id, scope_artifact_id) = 1
                    AND scope_workspace_id IS NOT NULL
                ELSE num_nonnulls(scope_workspace_id, scope_artifact_id) = 1
                    AND scope_artifact_id IS NOT NULL
            END),
        CONSTRAINT ck_limit_policies_pair CHECK ((metric, window_kind) IN {_PAIRS}),
        CONSTRAINT ck_limit_policies_kind CHECK (kind IN ('hard')),
        CONSTRAINT ck_limit_policies_limit_value CHECK (limit_value >= 0),
        CONSTRAINT ck_limit_policies_version CHECK (version >= 1),
        CONSTRAINT uq_limit_policies_scope_pair UNIQUE NULLS NOT DISTINCT
            (tenant_id, scope_workspace_id, scope_artifact_id, metric, window_kind)
    )
"""

_BUDGET_COUNTERS = f"""
    CREATE TABLE platform.budget_counters (
        tenant_id uuid NOT NULL,
        scope_type text NOT NULL,
        scope_id uuid NOT NULL,
        metric text NOT NULL,
        window_kind text NOT NULL,
        window_start timestamptz NOT NULL,
        window_end timestamptz NOT NULL,
        used numeric(20, 8) NOT NULL DEFAULT 0,
        reserved numeric(20, 8) NOT NULL DEFAULT 0,
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_budget_counters PRIMARY KEY
            (tenant_id, scope_type, scope_id, metric, window_kind, window_start),
        CONSTRAINT ck_budget_counters_amounts CHECK (used >= 0 AND reserved >= 0),
        CONSTRAINT ck_budget_counters_scope_type CHECK (scope_type IN {_SCOPES}),
        CONSTRAINT ck_budget_counters_pair CHECK ((metric, window_kind) IN {_PAIRS}),
        CONSTRAINT ck_budget_counters_window CHECK (window_end > window_start)
    )
"""

_BUDGET_LEASES = """
    CREATE TABLE platform.budget_leases (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        workspace_id uuid NOT NULL,
        run_id uuid,
        root_run_id uuid NOT NULL,
        artifact_id uuid,
        purpose text NOT NULL,
        payer text NOT NULL,
        counted_run boolean NOT NULL DEFAULT false,
        counter_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
        cap_usd numeric(20, 8) NOT NULL,
        cap_tokens bigint NOT NULL,
        reserved_usd numeric(20, 8) NOT NULL DEFAULT 0,
        reserved_tokens bigint NOT NULL DEFAULT 0,
        settled_usd numeric(20, 8) NOT NULL DEFAULT 0,
        settled_tokens bigint NOT NULL DEFAULT 0,
        rolled_usd numeric(20, 8) NOT NULL DEFAULT 0,
        rolled_tokens bigint NOT NULL DEFAULT 0,
        in_flight jsonb NOT NULL DEFAULT '{}'::jsonb,
        unpriced boolean NOT NULL DEFAULT false,
        state text NOT NULL DEFAULT 'open',
        close_reason text,
        opened_at timestamptz NOT NULL,
        heartbeat_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        closed_at timestamptz,
        CONSTRAINT pk_budget_leases PRIMARY KEY (id),
        CONSTRAINT fk_budget_leases_tenant_id_workspaces
            FOREIGN KEY (tenant_id, workspace_id)
            REFERENCES platform.workspaces (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT ck_budget_leases_purpose CHECK (purpose IN (
            'run', 'eval_offline', 'ingestion', 'retrieval', 'builder_assist')),
        CONSTRAINT ck_budget_leases_payer CHECK (payer IN ('tenant', 'platform')),
        CONSTRAINT ck_budget_leases_state CHECK (state IN ('open', 'closed')),
        CONSTRAINT ck_budget_leases_close_reason CHECK (close_reason IN (
            'completed', 'failed', 'cancelled', 'paused', 'expired', 'dead_lettered')),
        CONSTRAINT ck_budget_leases_closed CHECK (
            (state = 'open') = (closed_at IS NULL)
            AND (state = 'open') = (close_reason IS NULL)),
        CONSTRAINT ck_budget_leases_amounts CHECK (
            cap_usd >= 0 AND cap_tokens >= 0 AND reserved_usd >= 0 AND reserved_tokens >= 0
            AND settled_usd >= 0 AND settled_tokens >= 0
            AND rolled_usd >= 0 AND rolled_tokens >= 0),
        CONSTRAINT ck_budget_leases_counter_keys CHECK (jsonb_typeof(counter_keys) = 'array'),
        CONSTRAINT ck_budget_leases_in_flight CHECK (jsonb_typeof(in_flight) = 'object')
    )
"""

_PERMISSION = sa.text(
    "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
    " status_reason, owner_package, tenant_grantable)"
    " VALUES ('platform.limits.manage', 'platform', 'Đặt hạn mức', 'tenant', 'elevated',"
    " 'active', NULL, 'dw_usage', true)"
    " ON CONFLICT (key) DO NOTHING"
)

# 2b5ff2bceb06 and c3ec03bd6fd1 as they were, for the downgrade.
_SPEND_GUARD_TENANT = (
    "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
)
_SPEND_GUARD = """
    CREATE TABLE platform.tenant_daily_spend_guard (
        tenant_id uuid NOT NULL,
        spend_date date NOT NULL,
        spend_usd numeric(12, 4) DEFAULT 0 NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_tenant_daily_spend_guard PRIMARY KEY (tenant_id, spend_date),
        CONSTRAINT ck_tenant_daily_spend_guard_spend_usd CHECK (spend_usd >= 0)
    )
"""


def upgrade() -> None:
    # ---- policies ----------------------------------------------------------
    op.execute(_LIMIT_POLICIES)
    op.execute(
        "CREATE INDEX ix_limit_policies_tenant_id_scope_workspace_id"
        " ON platform.limit_policies (tenant_id, scope_workspace_id)"
    )
    op.execute(
        "CREATE INDEX ix_limit_policies_tenant_id_scope_artifact_id"
        " ON platform.limit_policies (tenant_id, scope_artifact_id)"
    )
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.limit_policies"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )
    # Written out rather than looped: `scripts/verify_invariants.py` reads this
    # text, and a name built by an f-string is one it cannot see.
    op.execute("ALTER TABLE platform.limit_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.limit_policies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_limit_policies ON platform.limit_policies"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )

    # ---- counters ----------------------------------------------------------
    op.execute(_BUDGET_COUNTERS)
    op.execute(
        "CREATE INDEX ix_budget_counters_window_end ON platform.budget_counters (window_end)"
    )
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.budget_counters"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )
    op.execute("ALTER TABLE platform.budget_counters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.budget_counters FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_budget_counters ON platform.budget_counters"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute(
        "CREATE POLICY worker_drain_budget_counters ON platform.budget_counters"
        f" FOR SELECT USING ({_DRAIN})"
    )
    op.execute(
        "CREATE POLICY worker_drain_budget_counters_delete ON platform.budget_counters"
        f" FOR DELETE USING ({_DRAIN})"
    )

    # ---- leases ------------------------------------------------------------
    op.execute(_BUDGET_LEASES)
    op.execute(
        "CREATE UNIQUE INDEX uq_budget_leases_tenant_id_root_run_id_open"
        " ON platform.budget_leases (tenant_id, root_run_id) WHERE state = 'open'"
    )
    op.execute(
        "CREATE INDEX ix_budget_leases_expires_at_open"
        " ON platform.budget_leases (expires_at) WHERE state = 'open'"
    )
    op.execute(
        "CREATE INDEX ix_budget_leases_tenant_id_root_run_id"
        " ON platform.budget_leases (tenant_id, root_run_id)"
    )
    op.execute(
        "CREATE INDEX ix_budget_leases_tenant_id_workspace_id"
        " ON platform.budget_leases (tenant_id, workspace_id)"
    )
    op.execute(
        "CREATE INDEX ix_budget_leases_closed_at_closed"
        " ON platform.budget_leases (closed_at) WHERE state = 'closed'"
    )
    op.execute("ALTER TABLE platform.budget_leases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.budget_leases FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_budget_leases ON platform.budget_leases"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute(
        "CREATE POLICY worker_drain_budget_leases ON platform.budget_leases"
        f" FOR SELECT USING ({_DRAIN})"
    )

    # ---- grants ------------------------------------------------------------
    for table in ("limit_policies", "budget_counters", "budget_leases"):
        op.execute(
            _for_role(
                "dw_app",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.{table} TO dw_app;",
            )
        )
        op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON platform.{table} FROM dw_agent_ro;"))

    # ---- the plan, the key, the guard --------------------------------------
    op.execute(
        "UPDATE platform.plan_limits SET max_tokens_per_run = 200000"
        " WHERE max_tokens_per_run = 120000"
    )
    op.execute(_PERMISSION)
    op.execute("DROP TABLE platform.tenant_daily_spend_guard")


def downgrade() -> None:
    op.execute(_SPEND_GUARD)
    op.execute("ALTER TABLE platform.tenant_daily_spend_guard ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.tenant_daily_spend_guard FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_tenant_daily_spend_guard"
        " ON platform.tenant_daily_spend_guard"
        f" USING {_SPEND_GUARD_TENANT} WITH CHECK {_SPEND_GUARD_TENANT}"
    )
    op.execute(
        "CREATE POLICY worker_drain_tenant_daily_spend_guard"
        " ON platform.tenant_daily_spend_guard"
        " USING (current_setting('app.worker_drain', true) = 'on')"
        " WITH CHECK (current_setting('app.worker_drain', true) = 'on')"
    )
    op.execute(
        "DELETE FROM platform.tenant_role_permissions"
        " WHERE permission_key = 'platform.limits.manage'"
    )
    op.execute("DELETE FROM platform.permissions WHERE key = 'platform.limits.manage'")
    op.execute(
        "UPDATE platform.plan_limits SET max_tokens_per_run = 120000"
        " WHERE max_tokens_per_run = 200000"
    )
    op.execute("DROP TABLE platform.budget_leases")
    op.execute("DROP TABLE platform.budget_counters")
    op.execute("DROP TABLE platform.limit_policies")
