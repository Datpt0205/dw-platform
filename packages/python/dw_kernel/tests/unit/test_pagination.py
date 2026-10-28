"""Cursor pagination: the codec, the refusals, and the property offset lacks."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from dw_kernel.errors import DomainError, ErrorCode
from dw_kernel.pagination import (
    MAX_PAGE_SIZE,
    CursorPosition,
    InvalidCursorError,
    Page,
    PageQuery,
    PageRequest,
    SortType,
    build_page,
    decode_cursor,
    encode_cursor,
    page_request,
)

pytestmark = pytest.mark.unit

_QUERY = PageQuery(key="audit.events", filters={"tenant": "acme"})
_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _position(offset_seconds: int = 0) -> CursorPosition:
    return CursorPosition(
        sort_value=_EPOCH + timedelta(seconds=offset_seconds),
        tiebreaker=uuid.uuid4(),
    )


# ----------------------------------------------------------------- codec --


def test_a_cursor_round_trips_to_the_position_it_was_minted_from() -> None:
    position = _position()
    assert decode_cursor(encode_cursor(position, _QUERY), _QUERY) == position


def test_a_cursor_survives_a_url_without_escaping() -> None:
    # The whole point of stripping base64 padding and using the urlsafe
    # alphabet: a client appends the cursor to a query string verbatim.
    cursor = encode_cursor(_position(), _QUERY)
    assert set(cursor) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_a_cursor_is_not_a_number_a_client_could_do_arithmetic_on() -> None:
    # A client that can compute "page 7" makes the page size and the sort order
    # part of the contract forever, so the cursor must not read as an index.
    cursors = [encode_cursor(_position(n), _QUERY) for n in range(3)]
    assert not any(cursor.isdigit() for cursor in cursors)
    assert len(set(cursors)) == 3


# -------------------------------------------------------------- refusals --


def test_a_cursor_issued_for_different_filters_is_refused() -> None:
    cursor = encode_cursor(_position(), _QUERY)
    other_tenant = PageQuery(key="audit.events", filters={"tenant": "globex"})
    with pytest.raises(InvalidCursorError, match="different query"):
        decode_cursor(cursor, other_tenant)


def test_a_cursor_issued_by_a_different_endpoint_is_refused() -> None:
    cursor = encode_cursor(_position(), _QUERY)
    with pytest.raises(InvalidCursorError, match="different query"):
        decode_cursor(cursor, PageQuery(key="memory.items", filters={"tenant": "acme"}))


def test_a_cursor_is_refused_when_a_filter_is_dropped() -> None:
    # Narrowing and un-narrowing are different queries in both directions: the
    # same position describes a different window in each.
    narrowed = PageQuery(key="knowledge.documents", filters={"tenant": "acme", "domain": "legal"})
    widened = PageQuery(key="knowledge.documents", filters={"tenant": "acme", "domain": None})
    cursor = encode_cursor(_position(), narrowed)
    with pytest.raises(InvalidCursorError, match="different query"):
        decode_cursor(cursor, widened)


@pytest.mark.parametrize(
    "corrupt",
    [
        "",
        "not-base64-at-all!!",
        base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
        base64.urlsafe_b64encode(b'"a string, not an object"').decode().rstrip("="),
    ],
)
def test_an_unreadable_cursor_is_refused(corrupt: str) -> None:
    with pytest.raises(InvalidCursorError, match="not readable"):
        decode_cursor(corrupt, _QUERY)


def test_a_cursor_from_an_older_format_version_is_refused() -> None:
    # Built by hand because the point is a payload this build can no longer
    # mint: an in-flight cursor must not be reinterpreted under new rules.
    stale = json.dumps(
        {"v": 0, "k": _EPOCH.isoformat(), "i": str(uuid.uuid4()), "q": _QUERY.fingerprint},
        separators=(",", ":"),
    )
    cursor = base64.urlsafe_b64encode(stale.encode()).decode().rstrip("=")
    with pytest.raises(InvalidCursorError, match="older version"):
        decode_cursor(cursor, _QUERY)


def test_a_v1_cursor_still_resumes_where_it_left_off() -> None:
    # G7, built by hand in the version 1 shape an earlier build minted, so the
    # test keeps meaning the same thing after the format moves on: a client
    # mid-listing across a deploy gets the next page, not a refusal.
    rows = _rows(6)
    table = _Table(rows)
    last_seen = sorted(rows, key=lambda row: (row.created_at, row.id), reverse=True)[1]
    v1 = json.dumps(
        {
            "v": 1,
            "k": last_seen.created_at.isoformat(),
            "i": str(last_seen.id),
            "q": _QUERY.fingerprint,
        },
        separators=(",", ":"),
    )
    cursor = base64.urlsafe_b64encode(v1.encode()).decode().rstrip("=")

    page = table.keyset_page(_request(limit=2, cursor=cursor))

    assert [row.label for row in page.items] == ["row-3", "row-2"]


def test_a_cursor_with_a_mangled_position_is_refused() -> None:
    tampered = json.dumps(
        {"v": 1, "k": "yesterday", "i": "not-a-uuid", "q": _QUERY.fingerprint},
        separators=(",", ":"),
    )
    cursor = base64.urlsafe_b64encode(tampered.encode()).decode().rstrip("=")
    with pytest.raises(InvalidCursorError, match="not readable"):
        decode_cursor(cursor, _QUERY)


def test_a_refused_cursor_reports_as_a_client_validation_failure() -> None:
    # It maps onto 422 through the existing taxonomy rather than a 500: the
    # caller sent something bad and can fix it by dropping the cursor.
    error = InvalidCursorError("nope")
    assert isinstance(error, DomainError)
    assert error.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_SIZE + 1])
def test_a_limit_outside_the_allowed_range_is_refused(limit: int) -> None:
    with pytest.raises(DomainError, match="limit must be between"):
        page_request(limit=limit, cursor=None, query=_QUERY)


def test_the_first_page_needs_no_cursor() -> None:
    request = page_request(limit=10, cursor=None, query=_QUERY)
    assert request.after is None
    assert request.fetch_limit == 11


# ------------------------------------------------------------ page shape --


@dataclass(frozen=True)
class _Row:
    """A stand-in for any of the paged tables: a sort key, an id, a payload."""

    created_at: datetime
    id: uuid.UUID
    label: str


def _row_position(row: _Row) -> CursorPosition:
    return CursorPosition(sort_value=row.created_at, tiebreaker=row.id)


def _rows(count: int, *, start: int = 0) -> list[_Row]:
    return [
        _Row(created_at=_EPOCH + timedelta(minutes=n), id=uuid.uuid4(), label=f"row-{n}")
        for n in range(start, start + count)
    ]


def test_a_full_result_set_ends_without_a_next_cursor() -> None:
    # Exactly `limit` rows came back, so the over-fetched probe row is absent
    # and there is nothing after this page.
    page = build_page(_rows(3), request=_request(limit=3), position_of=_row_position)
    assert len(page.items) == 3
    assert page.next_cursor is None


def test_an_over_fetched_row_is_dropped_and_becomes_the_next_cursor() -> None:
    rows = _rows(4)
    page = build_page(rows, request=_request(limit=3), position_of=_row_position)
    assert [row.label for row in page.items] == ["row-0", "row-1", "row-2"]
    assert page.next_cursor is not None
    # The cursor names the last row the client actually received, not the probe.
    assert decode_cursor(page.next_cursor, _QUERY) == _row_position(rows[2])


def test_an_empty_result_ends_the_run() -> None:
    page: Page[_Row] = build_page([], request=_request(limit=3), position_of=_row_position)
    assert page.items == ()
    assert page.next_cursor is None


def test_mapping_a_page_carries_the_cursor_across() -> None:
    page = build_page(_rows(4), request=_request(limit=3), position_of=_row_position)
    mapped = page.map_items(lambda row: row.label)
    assert mapped.items == ("row-0", "row-1", "row-2")
    assert mapped.next_cursor == page.next_cursor


def _request(*, limit: int, cursor: str | None = None) -> PageRequest:
    return page_request(limit=limit, cursor=cursor, query=_QUERY)


# --------------------------------------------- the property offset lacks --


class _Table:
    """An in-memory stand-in for a paged table, ordered newest first.

    Python's tuple comparison is the same total order PostgreSQL applies to the
    row-value comparison in ``dw_platform.adapters.persistence.keyset``, so this
    models the real query closely enough to show what each paging strategy does
    to a table that is being written to while a client reads it.
    """

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = list(rows)

    def insert(self, row: _Row) -> None:
        self._rows.append(row)

    def _newest_first(self) -> list[_Row]:
        return sorted(self._rows, key=lambda row: (row.created_at, row.id), reverse=True)

    def keyset_page(self, request: PageRequest) -> Page[_Row]:
        after = request.after
        candidates = [
            row
            for row in self._newest_first()
            if after is None or (row.created_at, row.id) < (after.sort_value, after.tiebreaker)
        ]
        return build_page(
            candidates[: request.fetch_limit], request=request, position_of=_row_position
        )

    def offset_page(self, *, limit: int, offset: int) -> list[_Row]:
        return self._newest_first()[offset : offset + limit]


def test_paging_by_cursor_returns_every_row_exactly_once_despite_a_mid_run_insert() -> None:
    original = _rows(6)
    table = _Table(original)

    seen: list[str] = []
    cursor: str | None = None
    inserted = False
    while True:
        page = table.keyset_page(_request(limit=2, cursor=cursor))
        seen.extend(row.label for row in page.items)
        if not inserted:
            # A row lands between two of the client's reads — the moment that
            # breaks offset. It is newer than everything, so under newest-first
            # it belongs on a page the client has already gone past.
            table.insert(_Row(created_at=_EPOCH + timedelta(hours=1), id=uuid.uuid4(), label="new"))
            inserted = True
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == sorted(row.label for row in original)
    assert len(seen) == len(set(seen)), "no row may be returned twice"


def test_paging_by_offset_does_not_return_every_row_exactly_once() -> None:
    # The same run against the same table, paged the way the obvious repair
    # would have done it. Under newest-first an insert pushes every later page
    # down and the client re-reads a row it already had; run oldest-first the
    # identical shift makes it miss one instead. Either way "exactly once" — the
    # only property a client can actually rely on — does not hold.
    original = _rows(6)
    table = _Table(original)

    seen: list[str] = []
    offset = 0
    inserted = False
    while True:
        rows = table.offset_page(limit=2, offset=offset)
        if not rows:
            break
        seen.extend(row.label for row in rows)
        if not inserted:
            table.insert(_Row(created_at=_EPOCH + timedelta(hours=1), id=uuid.uuid4(), label="new"))
            inserted = True
        offset += 2

    assert len(seen) != len(set(seen)), "offset was expected to repeat a row here"


def test_rows_sharing_a_sort_value_are_neither_repeated_nor_skipped() -> None:
    # Every paged table here sorts on a timestamp, and a batch written in one
    # transaction shares it exactly. Without the id in the cursor a page
    # boundary landing inside the tie loses or duplicates the tied rows.
    tied_at = _EPOCH
    table = _Table([_Row(created_at=tied_at, id=uuid.uuid4(), label=f"tied-{n}") for n in range(5)])

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = table.keyset_page(_request(limit=2, cursor=cursor))
        seen.extend(row.label for row in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == [f"tied-{n}" for n in range(5)]


# ------------------------------------------------------- typed cursors --

_V2_QUERY = PageQuery(
    key=None, identity={"route": "/things", "tenant": "acme"}, sort_type=SortType.INT
)


def _raw(cursor: str) -> dict[str, object]:
    decoded: dict[str, object] = json.loads(
        base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    )
    return decoded


def _minted(payload: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_a_cursor_carries_a_typed_value_a_phase_and_the_id() -> None:
    # R4.1.
    tiebreaker = uuid.uuid4()
    payload = _raw(encode_cursor(CursorPosition(sort_value=7, tiebreaker=tiebreaker), _V2_QUERY))
    assert payload == {
        "v": 2,
        "t": "int",
        "k": 7,
        "p": "values",
        "i": str(tiebreaker),
        "q": _V2_QUERY.identity_fingerprint,
    }
    nulls = _raw(encode_cursor(CursorPosition(sort_value=None, tiebreaker=tiebreaker), _V2_QUERY))
    assert (nulls["t"], nulls["p"], "k" in nulls) == ("null", "nulls", False)


def test_every_typed_value_round_trips() -> None:
    for sort_type, value in (
        (SortType.TEXT, "Hà Nội"),
        (SortType.INT, -(2**63)),
        (SortType.FLOAT, 1.5),
        (SortType.DATE, date(2026, 10, 28)),
        (SortType.DATETIME, _EPOCH),
        (SortType.BOOL, False),
    ):
        query = PageQuery(key=None, identity={"r": sort_type.value}, sort_type=sort_type)
        position = CursorPosition(sort_value=value, tiebreaker=uuid.uuid4())
        assert decode_cursor(encode_cursor(position, query), query) == position


@pytest.mark.parametrize(
    "change",
    [
        {"t": "text"},
        {"t": "bool", "k": True},
        {"p": "sideways"},
        {"p": "nulls"},
        {"p": "nulls", "t": "null"},
        {"i": "not-a-uuid"},
        {"k": 2**63},
        {"k": "7"},
    ],
    ids=["tag", "bool-for-int", "phase", "nulls-tag", "nulls-value", "id", "int64", "string"],
)
def test_a_cursor_that_does_not_fit_the_listing_is_refused(change: dict[str, object]) -> None:
    # R4.6: tag against the sort field's type, the phase, a NULL that carries
    # a value, the id.
    good = _raw(encode_cursor(CursorPosition(sort_value=7, tiebreaker=uuid.uuid4()), _V2_QUERY))
    with pytest.raises(InvalidCursorError, match="not readable"):
        decode_cursor(_minted({**good, **change}), _V2_QUERY)


def test_nan_in_a_cursor_is_not_a_number() -> None:
    good = _raw(encode_cursor(CursorPosition(sort_value=7, tiebreaker=uuid.uuid4()), _V2_QUERY))
    text = json.dumps({**good, "k": 0}).replace('"k": 0', '"k": NaN')
    cursor = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    with pytest.raises(InvalidCursorError, match="not readable"):
        decode_cursor(cursor, _V2_QUERY)


@pytest.mark.parametrize("version", [3, True, "2"])
def test_a_cursor_of_an_unknown_version_is_refused(version: object) -> None:
    # G8 for versions this build never minted.
    good = _raw(encode_cursor(CursorPosition(sort_value=7, tiebreaker=uuid.uuid4()), _V2_QUERY))
    with pytest.raises(InvalidCursorError, match="older version"):
        decode_cursor(_minted({**good, "v": version}), _V2_QUERY)


def test_a_v1_cursor_is_refused_by_a_listing_that_never_minted_one() -> None:
    v1 = {"v": 1, "k": _EPOCH.isoformat(), "i": str(uuid.uuid4()), "q": _QUERY.fingerprint}
    no_key = PageQuery(key=None, identity={"route": "/things"})
    with pytest.raises(InvalidCursorError, match="different query"):
        decode_cursor(_minted(v1), no_key)
