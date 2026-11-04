"""The usage ledger's integration database: its own name, migrated once per session.

Requires `make infra-up`; fails loudly when Postgres is unreachable. Two build
lanes set `DW_TEST_DB_SUFFIX` so neither drops the other's database.

`dw_platform`'s integration directory joins the path so the offboarding
coverage check (`test_offboarding_coverage.offboarding_violations`) runs here
too, on a catalog this suite plants tables in (R3.11): one check, not a copy.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pg_test_db import DatabaseUrls, database_urls, recreate_database, run_migrations
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

_PLATFORM_INTEGRATION = (
    Path(__file__).resolve().parents[3] / "dw_platform" / "tests" / "integration"
)
if str(_PLATFORM_INTEGRATION) not in sys.path:
    sys.path.append(str(_PLATFORM_INTEGRATION))

TEST_DB = "dw_test_usage"


@pytest.fixture(scope="session")
def usage_db() -> DatabaseUrls:
    urls = database_urls(TEST_DB)
    try:
        asyncio.run(recreate_database(urls.admin, TEST_DB))
    except (OSError, OperationalError, InterfaceError) as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up` first. Error: {exc}")
    result = run_migrations(urls.migrator)
    if result.returncode != 0:
        pytest.fail(f"migrations or the terms loader failed:\n{result.stdout}\n{result.stderr}")
    return urls


@pytest.fixture
async def app_engine(usage_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """As `dw_app`: the migrator holds BYPASSRLS and proves nothing about it."""
    engine = create_async_engine(usage_db.app, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def migrator(usage_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(usage_db.migrator, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def app_sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
