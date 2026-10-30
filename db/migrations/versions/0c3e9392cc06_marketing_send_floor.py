"""marketing send floor

Revision ID: 0c3e9392cc06
Revises: 16ac88642439
Create Date: 2026-10-30

The core of the Send floor of ADR-0124 (compliance-pdpl ticket 08; spec R3, R5.6):

- `platform.consent_records`: append-only, tenant-wide (the tenant is the
  controller, ADR-0124 decision 4), range-partitioned by month on
  `captured_at` with a DEFAULT partition, registered in
  `platform.time_partitioned_tables`. The current consent is the latest row per
  `(subject_ref, purpose, channel)`, so a withdrawal recorded anywhere stops
  sends everywhere.
- `platform.contact_suppressions`: one row per `(tenant_id, channel,
  address_hash)`, tenant-wide; `platform.guard_contact_suppression()` refuses
  every DELETE (23514) unless the tenant is `offboarding` (R5.6).
- `platform.marketing_send_log`: one row per interaction (`dispatching` or
  `blocked`), workspace-narrowed, range-partitioned by month on `created_at`.
  A delivery's outcome is the `platform.tool_executions` row of the same key.
- Counting across the tenant: `platform.marketing_sends_since(channel,
  address_hash, since)` and `platform.marketing_recipients_of_run(root_run_id)`,
  SECURITY DEFINER over every workspace of `app.tenant_id`, counts only; the
  frequency cap is the tenant's, not a workspace's (ADR-0124 decision 4).
- `platform.purge_tenant_marketing(tenant_id)`: the offboarding lane's step for
  the two append-only tables, only for the transaction's own tenant while it is
  `offboarding`.

`dw_app` holds nothing on any partition (rows go through the parent, DO-02.2);
on the parents it reads and inserts, and DELETEs only suppressions, which the
trigger allows during offboarding alone. Every new policy reads its setting in a
sub-SELECT (foundations-hardening R5.3).
"""

from __future__ import annotations

from alembic import op

revision = "0c3e9392cc06"
down_revision = "16ac88642439"
branch_labels = None
depends_on = None

_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_WORKSPACE = "(workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid))"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"
_NARROWED = f"({_TENANT} AND ({_WORKSPACE} OR {_SCOPE}))"

_CHANNELS = "('zns', 'email', 'sms', 'messenger', 'zalo_oa')"
# The refusal reasons of the floor (ADR-0124 decision 1; ticket 08 step 4 and 6).
_REASONS = (
    "('suppressed', 'no_consent', 'consent_withdrawn', 'frequency_cap', 'quiet_hours',"
    " 'recipient_cap', 'multiple_recipients')"
)
_HASH = "~ '^[0-9a-f]{64}$'"


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


def _default_partition(parent: str) -> list[str]:
    """The DEFAULT partition, as `_ensure_one_partition` makes a month: its own
    row security, and no privilege of anyone but its owner."""
    part = f"{parent}_default"
    return [
        f"CREATE TABLE platform.{part} PARTITION OF platform.{parent} DEFAULT",
        f"ALTER TABLE platform.{part} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE platform.{part} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{part} ON platform.{part}"
        f" USING {_TENANT} WITH CHECK {_TENANT}",
        f"SELECT platform._revoke_all_but_owner('platform.{part}'::regclass)",
    ]


def upgrade() -> None:
    # ---- consent records ---------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE platform.consent_records (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            subject_ref text NOT NULL,
            purpose text NOT NULL,
            channel text NOT NULL,
            state text NOT NULL,
            captured_at timestamp with time zone DEFAULT now() NOT NULL,
            source text NOT NULL,
            evidence_ref text,
            notice_version text NOT NULL,
            withdrawn_at timestamp with time zone,
            CONSTRAINT pk_consent_records PRIMARY KEY (id, captured_at),
            CONSTRAINT fk_consent_records_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE RESTRICT,
            CONSTRAINT ck_consent_records_subject_ref
                CHECK (char_length(subject_ref) BETWEEN 1 AND 320),
            CONSTRAINT ck_consent_records_purpose CHECK (purpose IN ('marketing')),
            CONSTRAINT ck_consent_records_channel CHECK (channel IN {_CHANNELS}),
            CONSTRAINT ck_consent_records_state CHECK (state IN ('granted', 'withdrawn')),
            CONSTRAINT ck_consent_records_source CHECK (char_length(source) BETWEEN 1 AND 120),
            CONSTRAINT ck_consent_records_notice_version
                CHECK (char_length(notice_version) BETWEEN 1 AND 64),
            CONSTRAINT ck_consent_records_withdrawn
                CHECK ((state = 'withdrawn') = (withdrawn_at IS NOT NULL))
        ) PARTITION BY RANGE (captured_at)
        """
    )
    # The current consent: the latest row per subject, purpose and channel. It
    # leads with what RLS supplies, and carries the tenant foreign key.
    op.execute(
        "CREATE INDEX ix_consent_records_current ON platform.consent_records"
        " (tenant_id, subject_ref, channel, purpose, captured_at DESC)"
    )
    for statement in _default_partition("consent_records"):
        op.execute(statement)

    # ---- suppressions ------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE platform.contact_suppressions (
            tenant_id uuid NOT NULL,
            channel text NOT NULL,
            address_hash text NOT NULL,
            source text NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_contact_suppressions PRIMARY KEY (tenant_id, channel, address_hash),
            CONSTRAINT fk_contact_suppressions_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE RESTRICT,
            CONSTRAINT ck_contact_suppressions_channel CHECK (channel IN {_CHANNELS}),
            CONSTRAINT ck_contact_suppressions_address_hash CHECK (address_hash {_HASH}),
            CONSTRAINT ck_contact_suppressions_source
                CHECK (source IN ('unsubscribe_link', 'keyword', 'operator'))
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.guard_contact_suppression()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        BEGIN
            -- R5.6: an opt-out is never taken back, except when the whole tenant
            -- is deleted by the offboarding lane.
            IF NOT EXISTS (
                SELECT 1 FROM platform.tenants t
                WHERE t.id = OLD.tenant_id AND t.status = 'offboarding'
            ) THEN
                RAISE EXCEPTION 'a suppression is deleted only while its tenant is offboarding'
                    USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.guard_contact_suppression() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER guard_contact_suppression BEFORE DELETE ON platform.contact_suppressions"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_contact_suppression()"
    )

    # ---- send log ----------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE platform.marketing_send_log (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            channel text NOT NULL,
            address_hash text NOT NULL,
            outcome text NOT NULL,
            blocked_reason text,
            idempotency_key text,
            run_id uuid,
            root_run_id uuid,
            consent_record_id uuid,
            tool_name text NOT NULL,
            tool_version text NOT NULL,
            CONSTRAINT pk_marketing_send_log PRIMARY KEY (id, created_at),
            CONSTRAINT fk_marketing_send_log_workspace
                FOREIGN KEY (tenant_id, workspace_id)
                REFERENCES platform.workspaces(tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT ck_marketing_send_log_channel CHECK (channel IN {_CHANNELS}),
            CONSTRAINT ck_marketing_send_log_address_hash CHECK (address_hash {_HASH}),
            CONSTRAINT ck_marketing_send_log_outcome CHECK (outcome IN ('dispatching', 'blocked')),
            CONSTRAINT ck_marketing_send_log_blocked_reason
                CHECK (blocked_reason IS NULL OR blocked_reason IN {_REASONS}),
            CONSTRAINT ck_marketing_send_log_outcome_shape CHECK (
                (outcome = 'dispatching' AND blocked_reason IS NULL
                    AND idempotency_key IS NOT NULL AND consent_record_id IS NOT NULL)
                OR (outcome = 'blocked' AND blocked_reason IS NOT NULL)
            )
        ) PARTITION BY RANGE (created_at)
        """
    )
    # A replay finds its dispatching row by key; the frequency cap counts an
    # address in a window; the recipient cap counts a root run. Each leads with
    # what RLS supplies; the first two carry the workspace foreign key's tenant.
    op.execute(
        "CREATE INDEX ix_marketing_send_log_idempotency_key"
        " ON platform.marketing_send_log (tenant_id, idempotency_key)"
    )
    op.execute(
        "CREATE INDEX ix_marketing_send_log_address"
        " ON platform.marketing_send_log (tenant_id, channel, address_hash, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_marketing_send_log_root_run"
        " ON platform.marketing_send_log (tenant_id, root_run_id)"
    )
    op.execute(
        "CREATE INDEX ix_marketing_send_log_workspace"
        " ON platform.marketing_send_log (tenant_id, workspace_id)"
    )
    for statement in _default_partition("marketing_send_log"):
        op.execute(statement)

    # ---- row security on the parents ----------------------------------------
    # Written out per table: `scripts/verify_invariants.py` reads this text.
    op.execute("ALTER TABLE platform.consent_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.consent_records FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_consent_records ON platform.consent_records"
        f" USING {_TENANT} WITH CHECK {_TENANT}"
    )
    op.execute("ALTER TABLE platform.contact_suppressions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.contact_suppressions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_contact_suppressions ON platform.contact_suppressions"
        f" USING {_TENANT} WITH CHECK {_TENANT}"
    )
    op.execute("ALTER TABLE platform.marketing_send_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.marketing_send_log FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_marketing_send_log ON platform.marketing_send_log"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )
    for table in ("consent_records", "contact_suppressions", "marketing_send_log"):
        op.execute(_for_role("dw_app", f"REVOKE ALL ON platform.{table} FROM dw_app;"))
        op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON platform.{table} FROM dw_agent_ro;"))
    op.execute(
        _for_role("dw_app", "GRANT SELECT, INSERT ON platform.consent_records TO dw_app;")
    )
    op.execute(
        _for_role("dw_app", "GRANT SELECT, INSERT ON platform.marketing_send_log TO dw_app;")
    )
    op.execute(
        _for_role(
            "dw_app", "GRANT SELECT, INSERT, DELETE ON platform.contact_suppressions TO dw_app;"
        )
    )

    # ---- partitions --------------------------------------------------------
    for table in ("consent_records", "marketing_send_log"):
        op.execute(
            "INSERT INTO platform.time_partitioned_tables"
            " (schema_name, table_name, append_only, registered_by)"
            f" VALUES ('platform', '{table}', true, 'compliance-pdpl')"
        )

    # ---- counting across the tenant -----------------------------------------
    op.execute(
        """
        CREATE FUNCTION platform.marketing_sends_since(
            p_channel text, p_address_hash text, p_since timestamp with time zone
        )
        RETURNS bigint
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        DECLARE
            tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        BEGIN
            IF tenant IS NULL THEN
                RAISE EXCEPTION 'app.tenant_id is not set';
            END IF;
            RETURN (
                SELECT count(*) FROM platform.marketing_send_log
                WHERE tenant_id = tenant AND channel = p_channel
                  AND address_hash = p_address_hash AND outcome = 'dispatching'
                  AND created_at >= p_since
            );
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.marketing_recipients_of_run(p_root_run_id uuid)
        RETURNS bigint
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        DECLARE
            tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        BEGIN
            IF tenant IS NULL THEN
                RAISE EXCEPTION 'app.tenant_id is not set';
            END IF;
            RETURN (
                SELECT count(DISTINCT (channel, address_hash)) FROM platform.marketing_send_log
                WHERE tenant_id = tenant AND root_run_id = p_root_run_id
                  AND outcome = 'dispatching'
            );
        END
        $$
        """
    )

    # ---- offboarding ---------------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION platform.purge_tenant_marketing(p_tenant_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        BEGIN
            IF p_tenant_id IS DISTINCT FROM
                NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
                RAISE EXCEPTION 'purge_tenant_marketing runs for the transaction''s own tenant';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM platform.tenants t
                WHERE t.id = p_tenant_id AND t.status = 'offboarding'
            ) THEN
                RAISE EXCEPTION 'purge_tenant_marketing runs only for a tenant offboarding';
            END IF;
            DELETE FROM platform.consent_records WHERE tenant_id = p_tenant_id;
            DELETE FROM platform.marketing_send_log WHERE tenant_id = p_tenant_id;
        END
        $$
        """
    )
    for function in (
        "platform.marketing_sends_since(text, text, timestamp with time zone)",
        "platform.marketing_recipients_of_run(uuid)",
        "platform.purge_tenant_marketing(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))


def downgrade() -> None:
    for function in (
        "platform.purge_tenant_marketing(uuid)",
        "platform.marketing_recipients_of_run(uuid)",
        "platform.marketing_sends_since(text, text, timestamp with time zone)",
    ):
        op.execute(f"DROP FUNCTION {function}")
    op.execute(
        "DELETE FROM platform.time_partitioned_tables WHERE schema_name = 'platform'"
        " AND table_name IN ('consent_records', 'marketing_send_log')"
    )
    op.execute("DROP TABLE platform.marketing_send_log")
    op.execute("DROP TABLE platform.contact_suppressions")
    op.execute("DROP FUNCTION platform.guard_contact_suppression()")
    op.execute("DROP TABLE platform.consent_records")
