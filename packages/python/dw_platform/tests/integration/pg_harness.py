"""Platform integration harness: its own database."""

from __future__ import annotations

from pg_test_db import (
    REPO_ROOT,
    DatabaseUrls,
    database_urls,
    postgres_container,
    recreate_database,
    run_alembic,
)

__all__ = [
    "REPO_ROOT",
    "DatabaseUrls",
    "database_urls",
    "postgres_container",
    "recreate_database",
    "run_alembic",
]

TEST_DB = "dw_test"


def platform_urls() -> DatabaseUrls:
    return database_urls(TEST_DB)


def admin_url(urls: DatabaseUrls) -> str:
    """The superuser on this suite's database, not on `postgres`.

    For the planted cases that need what no application role may do (create a
    role, grant membership, grant on another's object), each inside a
    transaction that rolls back: role DDL is transactional in Postgres.
    """
    return urls.admin.rsplit("/", 1)[0] + f"/{TEST_DB}"
