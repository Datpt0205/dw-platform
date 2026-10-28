"""The SQL half of keyset pagination: one predicate, one ordering.

`dw_kernel.pagination` owns the cursor; this owns the two SQL clauses that have
to agree with it. They live together because getting them apart is how the bug
happens: a ``<`` written as ``<=`` repeats the boundary row on every page, an
ORDER BY that lists the tiebreaker in the other direction skips tied rows, and
neither mistake shows up until two rows share a timestamp in production.

SQL expression helpers, not an adapter — nothing here holds a session or a
connection of its own (``keyset_rows`` runs on the one it is handed), so a
gateway in another package may import it without acquiring a concrete
dependency.

The five listings that existed before typed cursors sort on a NOT NULL
timestamp, newest first, and keep :func:`after_position` and
:func:`newest_first`. A listing that sorts on a column a caller picks, either
way, possibly NULL, uses :func:`keyset_phases`.
"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from dw_kernel.pagination import CursorPosition, Phase


def after_position(
    sort_column: sa.ColumnElement[object],
    id_column: sa.ColumnElement[object],
    after: CursorPosition | None,
) -> ColumnElement[bool]:
    """Rows strictly past ``after`` in descending ``(sort_column, id_column)``.

    A row-value comparison rather than the ``sort < k OR (sort = k AND id < i)``
    it expands to, because PostgreSQL can drive an index scan from the row-value
    form and because the expanded form is where the tie handling gets written
    wrong. ``after`` of ``None`` is the first page and matches everything.
    """
    if after is None:
        return sa.true()
    return sa.tuple_(sort_column, id_column) < sa.tuple_(
        sa.literal(after.sort_value, sort_column.type),
        sa.literal(after.tiebreaker, id_column.type),
    )


def newest_first(
    sort_column: sa.ColumnElement[object],
    id_column: sa.ColumnElement[object],
) -> tuple[ColumnElement[object], ColumnElement[object]]:
    """The ORDER BY that :func:`after_position` assumes.

    Returned as a pair so a query cannot order by the sort column and forget the
    tiebreaker, which would make the position of a tied row depend on whatever
    order the planner happened to return it in — and therefore make a page
    boundary that lands inside a tie non-deterministic.
    """
    return (sort_column.desc(), id_column.desc())


@dataclass(frozen=True)
class KeysetPhase:
    """One statement of a nullable ordering: its rows, in its order."""

    phase: Phase
    where: ColumnElement[bool]
    order_by: tuple[ColumnElement[object], ...]


def keyset_phases(
    sort_column: sa.ColumnElement[object],
    id_column: sa.ColumnElement[object],
    *,
    descending: bool,
    after: CursorPosition | None,
) -> tuple[KeysetPhase, ...]:
    """The statements that page a nullable column, either way, NULLs last (R4.2).

    Two phases rather than one ``NULLS LAST`` ordering, because the one-statement
    form needs ``sort > k OR sort IS NULL`` past the boundary, which no index
    can seek to. Each phase is a range one ``(tenant_id, sort, id)`` index
    serves in order: the values past ``after``, then the NULLs (past ``after``'s
    id once the cursor is among them). A page that runs out of values continues
    into the NULLs in the same request, so pages stay full and the boundary
    between the phases is crossed exactly once. ``id`` breaks ties in the same
    direction as the sort; both phases order by the pair, which among the NULLs
    is the id order the index already holds.
    """
    beyond = operator.lt if descending else operator.gt
    order = (
        (sort_column.desc(), id_column.desc())
        if descending
        else (sort_column.asc(), id_column.asc())
    )
    nulls_after = (
        sa.true()
        if after is None or after.phase is Phase.VALUES
        else beyond(id_column, sa.literal(after.tiebreaker, id_column.type))
    )
    nulls = KeysetPhase(Phase.NULLS, sa.and_(sort_column.is_(None), nulls_after), order)
    if after is not None and after.phase is Phase.NULLS:
        return (nulls,)
    values_after = (
        sa.true()
        if after is None
        else beyond(
            sa.tuple_(sort_column, id_column),
            sa.tuple_(
                sa.literal(after.sort_value, sort_column.type),
                sa.literal(after.tiebreaker, id_column.type),
            ),
        )
    )
    values = KeysetPhase(Phase.VALUES, sa.and_(sort_column.is_not(None), values_after), order)
    return (values, nulls)


async def keyset_rows(
    session: AsyncSession,
    statement: sa.Select[Any],
    phases: Sequence[KeysetPhase],
    *,
    fetch_limit: int,
) -> list[sa.Row[Any]]:
    """Run ``statement`` phase by phase until ``fetch_limit`` rows are in hand."""
    rows: list[sa.Row[Any]] = []
    for phase in phases:
        result = await session.execute(
            statement.where(phase.where).order_by(*phase.order_by).limit(fetch_limit - len(rows))
        )
        rows.extend(result.all())
        if len(rows) >= fetch_limit:
            break
    return rows
