"""`assert_field_tables_classified` on tables Postgres built (compliance-pdpl R1.2-R1.4).

Every case is a temporary table written the way an owner's migration writes
its CHECKs, as literals, inside a transaction that rolls back. No migration is
needed: the helper reads `pg_class`, `pg_attribute` and `pg_constraint`, and a
temporary table is in all three. The connection is the cluster's superuser on
the maintenance database, which owns nothing of this suite's.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import platform_urls
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.personal_data import assert_field_tables_classified

pytestmark = pytest.mark.integration

TABLE = "pd_fields"

# The well-formed table, piece by piece, so each case changes one piece.
COLUMNS = {
    "pd_category": "pd_category text NOT NULL",
    "sensitive_type": "sensitive_type text",
    "subject_identifier": "subject_identifier text",
}
CHECKS = {
    "pd_category": "pd_category IN ('none', 'basic', 'sensitive')",
    "sensitive_type": (
        "sensitive_type IN ('racial_ethnic_origin', 'political_religious_views',"
        " 'private_life', 'health', 'biometric_genetic', 'sex_life_orientation',"
        " 'crime_violation', 'location', 'identity_credentials', 'financial',"
        " 'behaviour_tracking', 'legally_confidential')"
    ),
    "subject_identifier": (
        "subject_identifier IN ('email', 'phone', 'national_id', 'zalo_user_id',"
        " 'facebook_psid', 'tax_code', 'bank_account')"
    ),
    "pd_sensitive_type": "(pd_category = 'sensitive') = (sensitive_type IS NOT NULL)",
    "pd_subject_identifier": "pd_category <> 'none' OR subject_identifier IS NULL",
}


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(platform_urls().admin, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _create(
    conn: AsyncConnection,
    *,
    columns: dict[str, str | None] | None = None,
    checks: dict[str, str | None] | None = None,
) -> None:
    """The well-formed table with `columns` and `checks` overriding pieces;
    None drops a piece."""
    merged_columns = {**COLUMNS, **(columns or {})}
    merged_checks = {**CHECKS, **(checks or {})}
    parts = ["id int PRIMARY KEY"]
    parts += [sql for sql in merged_columns.values() if sql is not None]
    parts += [
        f"CONSTRAINT ck_{TABLE}_{name} CHECK ({sql})"
        for name, sql in merged_checks.items()
        if sql is not None
    ]
    await conn.execute(sa.text(f"CREATE TEMPORARY TABLE {TABLE} ({', '.join(parts)})"))


async def _refusal(conn: AsyncConnection) -> str:
    with pytest.raises(AssertionError) as caught:
        await assert_field_tables_classified(conn, [TABLE])
    return str(caught.value)


async def test_a_table_written_to_the_pattern_passes(conn: AsyncConnection) -> None:
    """R1.2 (CP1): three columns and the CHECKs, written as a migration writes them."""
    await _create(conn)
    await assert_field_tables_classified(conn, [TABLE])


@pytest.mark.parametrize(
    ("checks", "constraint"),
    [
        pytest.param(
            {"pd_category": "pd_category IN ('none', 'basic', 'sensitive', 'secret')"},
            "ck_pd_fields_pd_category",
            id="a value outside the kernel",
        ),
        pytest.param(
            {"pd_category": "pd_category IN ('none', 'basic')"},
            "ck_pd_fields_pd_category",
            id="a kernel value missing",
        ),
        pytest.param(
            {"sensitive_type": None}, "ck_pd_fields_sensitive_type", id="no sensitive_type CHECK"
        ),
        pytest.param(
            {"subject_identifier": "subject_identifier IN ('email', 'phone')"},
            "ck_pd_fields_subject_identifier",
            id="a subject identifier kind missing",
        ),
        pytest.param(
            {"pd_category": "pd_category IN ('none', 'basic', 'sensitive') OR true"},
            "ck_pd_fields_pd_category",
            id="the right values in a CHECK that admits anything",
        ),
    ],
)
async def test_a_value_set_check_that_drifted_is_named(
    conn: AsyncConnection, checks: dict[str, str | None], constraint: str
) -> None:
    """R1.3 (CP1): the helper goes red and names the table and the constraint."""
    await _create(conn, checks=checks)
    message = await _refusal(conn)
    assert f"{TABLE}: CHECK {constraint}" in message


async def test_a_missing_column_is_named(conn: AsyncConnection) -> None:
    """R1.3: no `subject_identifier` column, so neither of its CHECKs either."""
    await _create(
        conn,
        columns={"subject_identifier": None},
        checks={"subject_identifier": None, "pd_subject_identifier": None},
    )
    message = await _refusal(conn)
    assert f"{TABLE}: column subject_identifier is missing" in message


async def test_a_nullable_category_is_named(conn: AsyncConnection) -> None:
    await _create(conn, columns={"pd_category": "pd_category text"})
    message = await _refusal(conn)
    assert f"{TABLE}.pd_category: text NULL, expected text NOT NULL" in message


@pytest.mark.parametrize(
    "pairing",
    [
        pytest.param(None, id="missing"),
        pytest.param("sensitive_type IS NOT NULL", id="only sensitive_type IS NOT NULL"),
        pytest.param(
            "pd_category <> 'sensitive' OR sensitive_type IS NOT NULL", id="one direction only"
        ),
    ],
)
async def test_a_pairing_check_that_is_not_the_kernels_is_named(
    conn: AsyncConnection, pairing: str | None
) -> None:
    """R1.4: `ck_<table>_pd_sensitive_type` absent or holding another expression."""
    await _create(conn, checks={"pd_sensitive_type": pairing})
    message = await _refusal(conn)
    assert f"{TABLE}: CHECK ck_{TABLE}_pd_sensitive_type" in message


async def test_a_subject_identifier_pairing_that_is_missing_is_named(
    conn: AsyncConnection,
) -> None:
    await _create(conn, checks={"pd_subject_identifier": None})
    message = await _refusal(conn)
    assert f"{TABLE}: CHECK ck_{TABLE}_pd_subject_identifier is missing" in message


@pytest.mark.parametrize(
    ("row", "constraint"),
    [
        pytest.param(
            {"pd_category": "sensitive", "sensitive_type": None},
            "ck_pd_fields_pd_sensitive_type",
            id="sensitive without a type",
        ),
        pytest.param(
            {"pd_category": "basic", "sensitive_type": "health"},
            "ck_pd_fields_pd_sensitive_type",
            id="basic with a type",
        ),
        pytest.param(
            {"pd_category": "none", "subject_identifier": "email"},
            "ck_pd_fields_pd_subject_identifier",
            id="none with a subject identifier",
        ),
    ],
)
async def test_the_pattern_refuses_a_row_that_breaks_a_pairing(
    conn: AsyncConnection, row: dict[str, str | None], constraint: str
) -> None:
    """R1.4: the database half of the rule the 422 states first (R1.5)."""
    await _create(conn)
    insert = sa.text(
        f"INSERT INTO {TABLE} (id, pd_category, sensitive_type, subject_identifier)"
        " VALUES (:id, :pd_category, :sensitive_type, :subject_identifier)"
    )
    # The well-formed rows first, so a refusal below is the pairing's.
    await conn.execute(
        insert,
        {
            "id": 1,
            "pd_category": "sensitive",
            "sensitive_type": "health",
            "subject_identifier": None,
        },
    )
    await conn.execute(
        insert,
        {"id": 2, "pd_category": "basic", "sensitive_type": None, "subject_identifier": "email"},
    )
    values = {"id": 3, "sensitive_type": None, "subject_identifier": None, **row}
    savepoint = await conn.begin_nested()
    with pytest.raises(sa.exc.IntegrityError, match=constraint):
        await conn.execute(insert, values)
    await savepoint.rollback()


async def test_a_table_that_does_not_exist_or_no_table_at_all_is_red(
    conn: AsyncConnection,
) -> None:
    with pytest.raises(AssertionError, match="pd_nowhere: no such table"):
        await assert_field_tables_classified(conn, ["pd_nowhere"])
    with pytest.raises(AssertionError, match="at least one table"):
        await assert_field_tables_classified(conn, [])
