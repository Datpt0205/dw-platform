"""Connections to the harness's own PostgreSQL, as the three roles it uses.

- the cluster's superuser: the template database, statistics views, memory
  contexts (gate MEDIUM (a): `pg_backend_memory_contexts` is closed to `dw_app`,
  so a superuser session `SET ROLE dw_app`, runs the queries, `RESET ROLE` and
  reads the view in the same backend; `dw_app` is never granted
  `pg_read_all_stats`);
- `dw_migrator`: `CREATE DATABASE dw_bench`, the migrations, the variant DDL
  and the seed;
- `dw_app`: every measured read and write, under FORCE RLS, with `app.tenant_id`,
  `app.user_id` and `app.actor_kind` set per transaction by `set_config(..., true)`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[3]
BENCH_DB = "dw_bench"
TEMPLATE_DB = "dw_bench_template"


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith(("DW_", "POSTGRES"))})
    return values


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    admin_user: str
    admin_password: str
    migrator_password: str
    app_password: str
    database: str = BENCH_DB

    @classmethod
    def from_env(cls, host: str, port: int) -> Endpoint:
        env = _env()
        return cls(
            host=host,
            port=port,
            admin_user=env.get("POSTGRES_USER", "dw_admin"),
            admin_password=env.get("POSTGRES_PASSWORD", "change-me-admin"),
            migrator_password=env.get("DW_DB_MIGRATOR_PASSWORD", "change-me-migrator"),
            app_password=env.get("DW_DB_APP_PASSWORD", "change-me-app"),
        )

    def on(self, database: str) -> Endpoint:
        return replace(self, database=database)

    def _credentials(self, role: str) -> tuple[str, str]:
        if role == "admin":
            return self.admin_user, self.admin_password
        if role == "migrator":
            return "dw_migrator", self.migrator_password
        if role == "app":
            return "dw_app", self.app_password
        raise ValueError(role)

    def url(self, role: str, driver: str = "postgresql") -> str:
        user, password = self._credentials(role)
        return f"{driver}://{user}:{password}@{self.host}:{self.port}/{self.database}"

    async def connect(self, role: str, **kwargs: Any) -> asyncpg.Connection:
        user, password = self._credentials(role)
        # No parallel index build or vacuum: its dead-tuple store and sort space
        # live in dynamic shared memory, and the compose image's 64 MB /dev/shm
        # cannot hold maintenance_work_mem's 64 MB ("could not resize shared
        # memory segment", smoke run 3/11/2026). Autovacuum is never parallel, so
        # this is all the host can do; the report says so.
        settings = {"max_parallel_maintenance_workers": "0"}
        if role == "app":
            # A read that never ends still ends the run (it counts as a slow sample).
            settings["statement_timeout"] = "60s"
        kwargs["server_settings"] = {**settings, **kwargs.get("server_settings", {})}
        return await asyncpg.connect(
            host=self.host,
            port=self.port,
            user=user,
            password=password,
            database=self.database,
            statement_cache_size=kwargs.pop("statement_cache_size", 256),
            **kwargs,
        )


def _setting(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def scope_sql(
    tenant: uuid.UUID, user: uuid.UUID, actor_kind: str, workspace_scope: str | None = None
) -> str:
    """BEGIN and the transaction's settings in one round trip (simple protocol).

    Values are uuids this harness made and a fixed actor kind, never input.
    """
    settings = [
        f"set_config('app.tenant_id', {_setting(str(tenant))}, true)",
        f"set_config('app.user_id', {_setting(str(user))}, true)",
        f"set_config('app.actor_kind', {_setting(actor_kind)}, true)",
    ]
    if workspace_scope is not None:
        settings.append(f"set_config('app.workspace_scope', {_setting(workspace_scope)}, true)")
    return "BEGIN; SELECT " + ", ".join(settings)


@asynccontextmanager
async def scoped(
    conn: asyncpg.Connection,
    tenant: uuid.UUID,
    user: uuid.UUID,
    actor_kind: str,
    workspace_scope: str | None = None,
) -> AsyncIterator[asyncpg.Connection]:
    """One `dw_app` transaction with its settings; COMMIT on success."""
    await conn.execute(scope_sql(tenant, user, actor_kind, workspace_scope))
    try:
        yield conn
    except BaseException:
        await conn.execute("ROLLBACK")
        raise
    await conn.execute("COMMIT")
