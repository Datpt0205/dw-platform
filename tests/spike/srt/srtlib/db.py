"""The spike's database: the repo's migrations at head, two seeded tenants, and
the `srt` schema of the prototype run lane, created here and never by a
migration (the ticket adds none).

The database is `dw_spike_srt` plus `DW_TEST_DB_SUFFIX` (`_lane2` for build lane
2), on the compose PostgreSQL the `.env` names, so it never touches a suite's
database.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "tests" / "support"))

from pg_test_db import (  # noqa: E402
    database_urls,
    recreate_database,
    run_migrations,
    test_db_name,
)

DB = "dw_spike_srt"

# Four tenants: A and B run the reference workflows, C floods (question 3, T5's
# fairness), D is the quiet company that must not wait behind C.
TENANTS: dict[str, tuple[uuid.UUID, uuid.UUID]] = {
    name: (uuid.UUID(int=0x5A0 + i * 16), uuid.UUID(int=0x5A1 + i * 16))
    for i, name in enumerate("ABCD")
}


@dataclass(frozen=True)
class Urls:
    admin: str
    migrator: str
    app: str
    name: str


def urls() -> Urls:
    found = database_urls(DB)
    return Urls(found.admin, found.migrator, found.app, test_db_name(DB))


_TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

DDL = [
    "CREATE SCHEMA IF NOT EXISTS srt",
    "GRANT USAGE ON SCHEMA srt TO dw_app",
    """CREATE TABLE srt.runs (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL,
        workspace_id uuid NOT NULL,
        workflow text NOT NULL,
        compiler text NOT NULL DEFAULT 'c1',
        saver text NOT NULL DEFAULT 'current',
        input jsonb NOT NULL DEFAULT '{}',
        status text NOT NULL CHECK (status IN ('blocked', 'queued', 'running', 'waiting',
            'completed', 'failed', 'cancelled', 'dead_lettered')),
        priority int NOT NULL DEFAULT 0,
        available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        received_at timestamptz,
        lease_owner text,
        lease_until timestamptz,
        attempt int NOT NULL DEFAULT 0,
        steps_started int NOT NULL DEFAULT 0,
        max_steps int NOT NULL DEFAULT 500,
        parent_run_id uuid,
        root_run_id uuid,
        depth int NOT NULL DEFAULT 0,
        resume jsonb,
        last_worker text,
        alternate boolean NOT NULL DEFAULT false,
        result jsonb,
        error text,
        finished_at timestamptz,
        stopped_at timestamptz,
        claims int NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX ix_srt_runs_claim ON srt.runs"
    " (tenant_id, priority, available_at, created_at, id) WHERE status = 'queued'",
    "CREATE INDEX ix_srt_runs_parent ON srt.runs (tenant_id, parent_run_id)",
    """CREATE TABLE srt.waits (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL,
        run_id uuid NOT NULL,
        step_id text NOT NULL,
        kind text NOT NULL CHECK (kind IN ('approval', 'incident', 'outcome_review',
            'child_run', 'timer')),
        status text NOT NULL CHECK (status IN ('open', 'resolved', 'cancelled')),
        interrupt_id text,
        payload jsonb NOT NULL DEFAULT '{}',
        resolution jsonb,
        opened_at timestamptz NOT NULL DEFAULT now(),
        closed_at timestamptz
    )""",
    "CREATE INDEX ix_srt_waits_run ON srt.waits (tenant_id, run_id)",
    """CREATE TABLE srt.approvals (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL,
        wait_id uuid NOT NULL,
        run_id uuid NOT NULL,
        assignee text NOT NULL,
        status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
        closed_at timestamptz
    )""",
    """CREATE TABLE srt.run_steps (
        id bigserial PRIMARY KEY,
        tenant_id uuid NOT NULL,
        run_id uuid NOT NULL,
        node text NOT NULL,
        step_id text,
        kind text NOT NULL,
        iteration_path text NOT NULL DEFAULT '',
        worker text NOT NULL,
        seq int,
        status text NOT NULL DEFAULT 'running',
        attempt int,
        started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        ended_at timestamptz
    )""",
    "CREATE INDEX ix_srt_run_steps_run ON srt.run_steps (tenant_id, run_id, id)",
    """CREATE TABLE srt.records (
        id bigserial PRIMARY KEY,
        tenant_id uuid NOT NULL,
        run_id uuid NOT NULL,
        effect_key text NOT NULL,
        payload jsonb NOT NULL,
        at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""",
    """CREATE TABLE srt.internal_keys (
        tenant_id uuid NOT NULL,
        effect_key text NOT NULL,
        result jsonb NOT NULL,
        PRIMARY KEY (tenant_id, effect_key)
    )""",
    """CREATE TABLE srt.audit (
        id bigserial PRIMARY KEY,
        tenant_id uuid NOT NULL,
        run_id uuid NOT NULL,
        action text NOT NULL,
        details jsonb NOT NULL DEFAULT '{}',
        at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""",
    # The fake provider is an outside system: no tenant, no RLS, reached only
    # through its own connection, committed at once (it survives a dead worker).
    """CREATE TABLE srt.provider_applied (
        id bigserial PRIMARY KEY,
        provider text NOT NULL,
        mode text NOT NULL,
        provider_key text NOT NULL,
        ref text NOT NULL,
        run_id uuid,
        step_id text,
        at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""",
    "CREATE INDEX ix_srt_provider_ref ON srt.provider_applied (provider, ref)",
    """CREATE TABLE srt.provider_keys (
        provider text NOT NULL,
        provider_key text NOT NULL,
        result jsonb NOT NULL,
        PRIMARY KEY (provider, provider_key)
    )""",
    "CREATE TABLE srt.provider_calls (provider text NOT NULL, ref text NOT NULL,"
    " n int NOT NULL DEFAULT 0, PRIMARY KEY (provider, ref))",
    "CREATE TABLE srt.provider_fixed (provider text PRIMARY KEY)",
    # The blob-per-channel prototype saver (ADR-0112 decision 10's later saver).
    """CREATE TABLE srt.cp (
        thread_id uuid NOT NULL,
        checkpoint_ns text NOT NULL,
        checkpoint_id text NOT NULL,
        parent_checkpoint_id text,
        tenant_id uuid NOT NULL,
        workspace_id uuid NOT NULL,
        type text NOT NULL,
        checkpoint bytea NOT NULL,
        metadata bytea NOT NULL,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )""",
    """CREATE TABLE srt.cp_blobs (
        thread_id uuid NOT NULL,
        checkpoint_ns text NOT NULL,
        channel text NOT NULL,
        version text NOT NULL,
        tenant_id uuid NOT NULL,
        type text NOT NULL,
        blob bytea,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    )""",
    """CREATE TABLE srt.cp_writes (
        thread_id uuid NOT NULL,
        checkpoint_ns text NOT NULL,
        checkpoint_id text NOT NULL,
        task_id text NOT NULL,
        idx int NOT NULL,
        tenant_id uuid NOT NULL,
        channel text NOT NULL,
        type text NOT NULL,
        blob bytea NOT NULL,
        task_path text NOT NULL DEFAULT '',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )""",
    # Question 3's per-company outbox prototype, beside the platform's FIFO one.
    """CREATE TABLE srt.outbox (
        id bigserial PRIMARY KEY,
        tenant_id uuid NOT NULL,
        occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        processed_at timestamptz
    )""",
    "CREATE INDEX ix_srt_outbox_due ON srt.outbox (tenant_id, id) WHERE processed_at IS NULL",
    # Lane functions, the shape of workflow-engine/04's: tenant ids only.
    """CREATE FUNCTION srt.scopes_due(p_limit int) RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, srt AS $$
        SELECT tenant_id FROM srt.runs
         WHERE status = 'queued' AND available_at <= now()
         GROUP BY tenant_id ORDER BY min(available_at), tenant_id LIMIT p_limit $$""",
    """CREATE FUNCTION srt.orphans_due(p_limit int) RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, srt AS $$
        SELECT DISTINCT tenant_id FROM srt.runs
         WHERE status = 'running' AND lease_until < now() LIMIT p_limit $$""",
    """CREATE FUNCTION srt.outbox_scopes_due(p_limit int) RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, srt AS $$
        SELECT tenant_id FROM srt.outbox WHERE processed_at IS NULL
         GROUP BY tenant_id ORDER BY min(id) LIMIT p_limit $$""",
    # The fence of question 1, invoker's rights so RLS applies: it is called in
    # the same statement that binds `app.tenant_id`, after the bind.
    """CREATE FUNCTION srt.lease_held(p_run uuid, p_token text) RETURNS boolean
        LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            PERFORM 1 FROM srt.runs WHERE id = p_run AND lease_owner = p_token FOR SHARE;
            RETURN FOUND;
        END $$""",
    "REVOKE EXECUTE ON FUNCTION srt.scopes_due(int), srt.orphans_due(int),"
    " srt.outbox_scopes_due(int) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION srt.scopes_due(int), srt.orphans_due(int),"
    " srt.outbox_scopes_due(int), srt.lease_held(uuid, text) TO dw_app",
]

_TENANT_TABLES = [
    "runs",
    "waits",
    "approvals",
    "run_steps",
    "records",
    "internal_keys",
    "audit",
    "cp",
    "cp_blobs",
    "cp_writes",
    "outbox",
]


def _rls() -> list[str]:
    out: list[str] = []
    for table in _TENANT_TABLES:
        out += [
            f"ALTER TABLE srt.{table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE srt.{table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant ON srt.{table} USING ({_TENANT_POLICY})"
            f" WITH CHECK ({_TENANT_POLICY})",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON srt.{table} TO dw_app",
        ]
    out.append("GRANT USAGE ON ALL SEQUENCES IN SCHEMA srt TO dw_app")
    return out


async def _create_schema(migrator: AsyncEngine) -> None:
    async with migrator.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS srt CASCADE"))
        for statement in [*DDL, *_rls()]:
            await conn.execute(text(statement))
        for name, (tenant, workspace) in TENANTS.items():
            slug = f"srt-{name.lower()}"
            await conn.execute(
                text(
                    "INSERT INTO platform.tenants (id, slug, name) VALUES (:id, :slug, :slug)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"id": tenant, "slug": slug},
            )
            await conn.execute(
                text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:id, :tenant, 'main', 'main') ON CONFLICT DO NOTHING"
                ),
                {"id": workspace, "tenant": tenant},
            )


def create(*, migrate: bool = True) -> Urls:
    """Recreate the spike database at the migrations' head and the `srt` schema."""
    found = urls()
    if migrate:
        asyncio.run(recreate_database(found.admin, DB))
        result = run_migrations(found.migrator)
        if result.returncode != 0:
            raise RuntimeError(f"migrations failed:\n{result.stdout}\n{result.stderr}")

    async def schema() -> None:
        engine = create_async_engine(found.migrator, poolclass=NullPool)
        try:
            await _create_schema(engine)
        finally:
            await engine.dispose()

    asyncio.run(schema())
    return found


async def reset(migrator: AsyncEngine) -> None:
    """Empty the lane's tables between experiments, keeping the schema."""
    async with migrator.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE srt.runs, srt.waits, srt.approvals, srt.run_steps, srt.records,"
                " srt.internal_keys, srt.audit, srt.provider_applied, srt.provider_keys,"
                " srt.provider_calls, srt.provider_fixed, srt.cp, srt.cp_blobs, srt.cp_writes,"
                " srt.outbox, platform.run_checkpoints, platform.run_checkpoint_writes,"
                " platform.tool_execution_claims"
            )
        )


def env_suffix() -> str:
    return os.environ.get("DW_TEST_DB_SUFFIX", "")
