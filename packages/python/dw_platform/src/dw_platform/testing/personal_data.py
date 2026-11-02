"""The catalog check every field-definition table's owner runs (compliance-pdpl R1.2-R1.4).

A migration writes its CHECKs as literals, since no migration imports a
package, so nothing ties a table's CHECK to ``dw_kernel.personal_data`` except
this net. It asks the database, not the migration text (failure-modes #0):
for each table, the three columns and five CHECKs named by
``NAMING_CONVENTION`` (``ck_<table>_<name>``):

* ``pd_category`` text NOT NULL, ``sensitive_type`` and ``subject_identifier``
  text NULL;
* ``ck_<table>_pd_category``, ``ck_<table>_sensitive_type`` and
  ``ck_<table>_subject_identifier``: ``<column> IN (...)`` over exactly the
  kernel enum's values, in any order, and nothing else in the expression;
* ``ck_<table>_pd_sensitive_type`` and ``ck_<table>_pd_subject_identifier``:
  the definition Postgres prints for the kernel's
  ``SENSITIVE_TYPE_PAIRING_SQL`` and ``SUBJECT_IDENTIFIER_PAIRING_SQL``,
  built on a temporary table in the same connection, so the comparison is
  between two printings by the same server.

Every problem of every table is collected and raised as one ``AssertionError``
naming the table and the constraint or column.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from dw_kernel.personal_data import (
    SENSITIVE_TYPE_PAIRING_SQL,
    SUBJECT_IDENTIFIER_PAIRING_SQL,
    PdCategory,
    SensitiveType,
    SubjectIdentifierKind,
)

__all__ = ["assert_field_tables_classified"]

# column -> (its enum, whether it is NOT NULL)
_COLUMNS: dict[str, tuple[type[StrEnum], bool]] = {
    "pd_category": (PdCategory, True),
    "sensitive_type": (SensitiveType, False),
    "subject_identifier": (SubjectIdentifierKind, False),
}
# constraint suffix -> the kernel's expression
_PAIRINGS: dict[str, str] = {
    "pd_sensitive_type": SENSITIVE_TYPE_PAIRING_SQL,
    "pd_subject_identifier": SUBJECT_IDENTIFIER_PAIRING_SQL,
}

_LITERAL = re.compile(r"'((?:[^']|'')*)'::text")


def _literals(definition: str) -> list[str]:
    """The literals of `col = ANY (ARRAY['a'::text, ...])` as Postgres prints it."""
    return [match.replace("''", "'") for match in _LITERAL.findall(definition)]


def _in_list(column: str, values: Sequence[str]) -> str:
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"{column} IN ({quoted})"


async def _printed(conn: AsyncConnection, expressions: Sequence[str]) -> list[str]:
    """How this server prints each expression as a CHECK on the three columns."""
    reference = f"pd_reference_{uuid.uuid4().hex}"
    await conn.execute(
        sa.text(
            f"CREATE TEMPORARY TABLE {reference}"
            " (pd_category text NOT NULL, sensitive_type text, subject_identifier text)"
        )
    )
    try:
        for index, expression in enumerate(expressions):
            await conn.execute(
                sa.text(f"ALTER TABLE {reference} ADD CONSTRAINT c{index} CHECK ({expression})")
            )
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint"
                    " WHERE conrelid = CAST(:reference AS regclass) AND contype = 'c'"
                ),
                {"reference": reference},
            )
        ).all()
    finally:
        await conn.execute(sa.text(f"DROP TABLE {reference}"))
    by_name = {row.conname: row.definition for row in rows}
    return [by_name[f"c{index}"] for index in range(len(expressions))]


async def _table_problems(conn: AsyncConnection, table: str) -> list[str]:
    found = (
        await conn.execute(
            sa.text("SELECT c.oid, c.relname FROM pg_class c WHERE c.oid = to_regclass(:table)"),
            {"table": table},
        )
    ).first()
    if found is None:
        return [f"{table}: no such table"]
    oid, name = found.oid, found.relname

    columns = {
        row.attname: row
        for row in (
            await conn.execute(
                sa.text(
                    "SELECT attname, format_type(atttypid, atttypmod) AS type, attnotnull"
                    " FROM pg_attribute WHERE attrelid = :oid AND attnum > 0"
                    " AND NOT attisdropped"
                ),
                {"oid": oid},
            )
        ).all()
    }
    checks: dict[str, str] = {
        row.conname: row.definition
        for row in (
            await conn.execute(
                sa.text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition"
                    " FROM pg_constraint WHERE conrelid = :oid AND contype = 'c'"
                ),
                {"oid": oid},
            )
        ).all()
    }

    problems: list[str] = []
    for column, (_, not_null) in _COLUMNS.items():
        row = columns.get(column)
        if row is None:
            problems.append(f"{table}: column {column} is missing")
        elif row.type != "text" or row.attnotnull != not_null:
            wanted = "text NOT NULL" if not_null else "text NULL"
            actual = f"{row.type} {'NOT NULL' if row.attnotnull else 'NULL'}"
            problems.append(f"{table}.{column}: {actual}, expected {wanted}")

    # (constraint name, the expression its definition must print as)
    expected: list[tuple[str, str]] = []
    for column, (enum, _) in _COLUMNS.items():
        constraint = f"ck_{name}_{column}"
        definition = checks.get(constraint)
        if definition is None:
            problems.append(f"{table}: CHECK {constraint} is missing")
            continue
        allowed = _literals(definition)
        kernel = [member.value for member in enum]
        if set(allowed) != set(kernel) or len(allowed) != len(kernel):
            extra = sorted(set(allowed) - set(kernel))
            missing = sorted(set(kernel) - set(allowed))
            problems.append(
                f"{table}: CHECK {constraint} differs from dw_kernel.personal_data."
                f"{enum.__name__}: not in the kernel {extra}, missing {missing}"
            )
            continue
        expected.append((constraint, _in_list(column, allowed)))
    for suffix, expression in _PAIRINGS.items():
        constraint = f"ck_{name}_{suffix}"
        if constraint not in checks:
            problems.append(f"{table}: CHECK {constraint} is missing")
            continue
        expected.append((constraint, expression))

    if expected:
        printed = await _printed(conn, [expression for _, expression in expected])
        for (constraint, expression), reference in zip(expected, printed, strict=True):
            if checks[constraint] != reference:
                problems.append(
                    f"{table}: CHECK {constraint} is {checks[constraint]!r},"
                    f" expected {reference!r} (from {expression!r})"
                )
    return problems


async def assert_field_tables_classified(conn: AsyncConnection, tables: Sequence[str]) -> None:
    """Fail, naming each table and constraint, unless every table carries the
    classification columns and CHECKs of ``dw_kernel.personal_data``.

    ``tables`` are names as ``to_regclass`` reads them (``studio.field_defs``).
    An empty list is refused: a check over nothing passes for ever.
    """
    if not tables:
        raise AssertionError("assert_field_tables_classified needs at least one table")
    problems: list[str] = []
    for table in tables:
        problems.extend(await _table_problems(conn, table))
    if problems:
        raise AssertionError("personal-data classification drifted:\n" + "\n".join(problems))
