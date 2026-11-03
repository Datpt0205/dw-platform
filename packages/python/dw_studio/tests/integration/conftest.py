"""Studio's integration database: its own name, migrated once per session.

Requires `make infra-up`; fails loudly when Postgres is unreachable. Two build
lanes set `DW_TEST_DB_SUFFIX` so neither drops the other's database.
"""

from __future__ import annotations

import asyncio

import pytest
from pg_test_db import DatabaseUrls, database_urls, recreate_database, run_migrations
from sqlalchemy.exc import InterfaceError, OperationalError

TEST_DB = "dw_test_studio"


@pytest.fixture(scope="session")
def studio_db() -> DatabaseUrls:
    urls = database_urls(TEST_DB)
    try:
        asyncio.run(recreate_database(urls.admin, TEST_DB))
    except (OSError, OperationalError, InterfaceError) as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up` first. Error: {exc}")
    result = run_migrations(urls.migrator)
    if result.returncode != 0:
        pytest.fail(f"migrations or the terms loader failed:\n{result.stdout}\n{result.stderr}")
    return urls
