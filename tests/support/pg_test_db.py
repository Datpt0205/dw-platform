"""Postgres bring-up shared by every integration and e2e suite.

Each suite owns a database so they never fight, but the credentials, the DSNs,
the drop/create and the alembic invocation are the same everywhere.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_A = uuid.UUID(int=0xA00)
WORKSPACE_A = uuid.UUID(int=0xA01)
TENANT_B = uuid.UUID(int=0xB00)
WORKSPACE_B = uuid.UUID(int=0xB01)


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update(
        {
            k: v
            for k, v in os.environ.items()
            if k.startswith(("DW_", "POSTGRES", "MINIO", "QDRANT", "S3_", "COMPOSE_"))
        }
    )
    return values


@dataclass(frozen=True)
class DatabaseUrls:
    admin: str
    migrator: str
    app: str


def postgres_container() -> str:
    """This checkout's Postgres container, named the way compose names it:
    after `COMPOSE_PROJECT_NAME`, read from the same `.env` the credentials
    come from. A second dw-based checkout on the machine owns "dw-postgres-1";
    a test that `docker exec`s must never land in that one."""
    explicit = os.environ.get("PG_CONTAINER")
    if explicit:
        return explicit
    return f"{load_env().get('COMPOSE_PROJECT_NAME', 'dw')}-postgres-1"


def database_urls(test_db: str) -> DatabaseUrls:
    env = load_env()
    host = env.get("DW_TEST_DB_HOST", "localhost")
    port = env.get("DW_TEST_DB_PORT", "5432")
    admin_user = env.get("POSTGRES_USER", "dw_admin")
    admin_password = env.get("POSTGRES_PASSWORD", "change-me-admin")
    migrator_password = env.get("DW_DB_MIGRATOR_PASSWORD", "change-me-migrator")
    app_password = env.get("DW_DB_APP_PASSWORD", "change-me-app")
    return DatabaseUrls(
        admin=f"postgresql+asyncpg://{admin_user}:{admin_password}@{host}:{port}/postgres",
        migrator=f"postgresql+asyncpg://dw_migrator:{migrator_password}@{host}:{port}/{test_db}",
        app=f"postgresql+asyncpg://dw_app:{app_password}@{host}:{port}/{test_db}",
    )


async def recreate_database(admin_url: str, test_db: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {test_db} WITH (FORCE)"))
            await conn.execute(text(f"CREATE DATABASE {test_db} OWNER dw_migrator"))
    finally:
        await engine.dispose()


def run_alembic(command: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(REPO_ROOT / "db" / "alembic.ini"), *command],
        env={**os.environ, "DW_DATABASE_URL": database_url},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# The password every suite gives `dw_provisioner` on the test cluster. A role is
# a cluster object, and `init-databases.sh` creates this one with the
# deployment's password, which no test knows; so whichever suite needs to log in
# as it sets this one first (`ensure_provisioner`), and they all agree on it.
PROVISIONER_TEST_PASSWORD = "test-provisioner-pw"


def provisioner_url(migrator_url: str) -> str:
    """The same database as `migrator_url`, as `dw_provisioner`."""
    scheme, rest = migrator_url.split("://", 1)
    return f"{scheme}://dw_provisioner:{PROVISIONER_TEST_PASSWORD}@{rest.split('@', 1)[1]}"


async def ensure_provisioner(admin_url: str) -> None:
    """Create `dw_provisioner` as `init-databases.sh` does, or reset its password."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_provisioner') THEN "
                    f"CREATE ROLE dw_provisioner LOGIN PASSWORD '{PROVISIONER_TEST_PASSWORD}' "
                    "NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE; "
                    "ELSE "
                    f"ALTER ROLE dw_provisioner LOGIN PASSWORD '{PROVISIONER_TEST_PASSWORD}'; "
                    "END IF; END $$;"
                )
            )
    finally:
        await engine.dispose()


def run_migrations(database_url: str) -> subprocess.CompletedProcess[str]:
    """`alembic upgrade head`, then the retention terms loader, as a deploy runs them.

    The compose `migrate` job runs both (telemetry-and-audit R5.9), so a test
    database without the second step would hold an empty `platform.retention_terms`
    no deployment ever has.
    """
    # Before the migrations, so their grants to the role are not skipped.
    test_db = database_url.rsplit("/", 1)[1]
    asyncio.run(ensure_provisioner(database_urls(test_db).admin.rsplit("/", 1)[0] + f"/{test_db}"))
    migrated = run_alembic(["upgrade", "head"], database_url)
    if migrated.returncode != 0:
        return migrated
    return subprocess.run(
        [sys.executable, "-m", "dw_platform.adapters.persistence.retention_terms"],
        env={**os.environ, "DW_PROVISIONER_DATABASE_URL": provisioner_url(database_url)},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
