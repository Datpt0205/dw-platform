"""Keyset pagination: the one page shape every list endpoint returns.

A list endpoint that takes only ``limit`` hands a client the first page and
nothing after it. The obvious repair is ``OFFSET``, and it is wrong twice over.
Skipping N rows costs the database a scan of those N rows, so page 500 costs
five hundred pages of work; and a row inserted while a client is paging shifts
every later page down by one, so a record slides across the boundary the client
has already passed and is never returned at all. Both failures grow with the
tenant's data, which is to say they arrive first on the largest customer.

Keyset pagination remembers *where* the previous page ended — the sort key plus
the row id that breaks ties — and asks for rows strictly beyond that point. The
database seeks to the position through an index instead of counting to it, and
an insert elsewhere in the table cannot move a boundary that is expressed as a
value rather than as a count.

The cursor is deliberately opaque: a base64url blob, not a number. A client that
can compute "page 7" will, and from that moment the page size, the sort column
and the ordering are all part of the contract we have to keep forever. It also
carries a fingerprint of the query it was issued for, so a cursor replayed
against different filters is refused instead of quietly answering from a window
that does not describe it.

The encoding is *not* signed, and that is deliberate rather than an oversight.
Anyone can base64-decode a cursor and edit it; all that buys them is a different
window into a result set they are already authorized to read, because every
query still runs under the caller's verified tenant context and RLS. Signing
would require a secret, and the kernel has no configuration by design.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from dw_kernel.errors import DomainError

# What a caller gets when it does not ask, and the most it may ask for. The
# ceiling exists so one client cannot turn a paged endpoint back into a full
# table scan by requesting every row in a single page.
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 200

# The payload shapes this build reads. Version 2 is the one it mints: a typed
# sort value, a phase, and a fingerprint of the whole query (app-standards R4).
# Version 1 (a timestamp, minted by the five listings that existed before) is
# still read, against its own fingerprint, so a client paging across a deploy
# gets its next page (G7). Any other version is refused rather than guessed at,
# which is what stops an in-flight cursor being reinterpreted under new rules.
_V1: Final = 1
_V2: Final = 2

# 64 bits of query fingerprint. This detects an honest mistake — a cursor
# replayed against a different filter or a different endpoint — rather than
# resisting an attacker, and eight bytes keep the cursor short enough to sit
# comfortably in a URL.
_FINGERPRINT_BYTES: Final = 8

_INT64_MIN: Final = -(2**63)
_INT64_MAX: Final = 2**63 - 1
_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# RFC 3339: a date-time always carries its offset. One without is a wall-clock
# time in a zone nobody named, and comparing it with a timestamptz would read
# it in the session's zone.
_DATETIME: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?"
    r"([Zz]|[+-][0-9]{2}:[0-9]{2})"
)


class SortType(StrEnum):
    """The abstract types a list sorts and filters on, and their cursor tags."""

    TEXT = "text"
    INT = "int"
    FLOAT = "float"
    DATE = "date"
    DATETIME = "datetime"
    BOOL = "bool"


NULL_TAG: Final = "null"


class Phase(StrEnum):
    """Where in a nullable ordering a page ended: among the values, or past them
    among the NULLs, which always come last (R4.2)."""

    VALUES = "values"
    NULLS = "nulls"


type SortValue = str | int | float | date | datetime | bool | None


def _in_int64(value: int) -> bool:
    return _INT64_MIN <= value <= _INT64_MAX


def typed_value(sort_type: SortType, raw: object) -> SortValue:
    """``raw`` (as JSON decoded it) as a value of ``sort_type``, or ValueError.

    The one reading of a typed value, shared by the cursor and the filter tree,
    so a value a filter refuses is one a cursor refuses too: a bool is not an
    int, an int outside int64 or a float that is not finite is no number, a
    date is `YYYY-MM-DD` and a date-time carries its offset.
    """
    number = isinstance(raw, int | float) and not isinstance(raw, bool)
    if sort_type is SortType.TEXT and isinstance(raw, str):
        return raw
    if sort_type is SortType.BOOL and isinstance(raw, bool):
        return raw
    if sort_type is SortType.INT and isinstance(raw, int) and number and _in_int64(raw):
        return raw
    if sort_type is SortType.FLOAT and number:
        assert isinstance(raw, int | float)
        if (not isinstance(raw, int) or _in_int64(raw)) and math.isfinite(raw):
            return float(raw)
    if sort_type is SortType.DATE and isinstance(raw, str) and _DATE.fullmatch(raw):
        return date.fromisoformat(raw)
    if sort_type is SortType.DATETIME and isinstance(raw, str) and _DATETIME.fullmatch(raw):
        return datetime.fromisoformat(raw)
    raise ValueError("not a value of the sort type")


def _tag_of(value: SortValue) -> str:
    # bool before int (a bool is an int), datetime before date (likewise).
    if value is None:
        return NULL_TAG
    if isinstance(value, bool):
        return SortType.BOOL.value
    if isinstance(value, int):
        return SortType.INT.value
    if isinstance(value, float):
        return SortType.FLOAT.value
    if isinstance(value, datetime):
        return SortType.DATETIME.value
    if isinstance(value, date):
        return SortType.DATE.value
    return SortType.TEXT.value


def _json_of(value: SortValue) -> object:
    return value.isoformat() if isinstance(value, date) else value


def canonical_json(value: object) -> str:
    """JSON with sorted keys and no whitespace: equal for equal queries whatever
    order a caller wrote their filter's keys in (R4.5)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=_FINGERPRINT_BYTES).hexdigest()


class InvalidCursorError(DomainError):
    """The cursor is unreadable, or was issued for a different query.

    A ``DomainError`` because it is bad client input and maps onto the existing
    ``validation_failed`` code; a distinct type because a caller that wants to
    restart the listing from the beginning needs to tell this apart from every
    other validation failure.
    """


def list_identity(
    *,
    route: str,
    tenant: object,
    workspace: object | None,
    params: Mapping[str, object] | None = None,
    selection: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """What a version 2 cursor is bound to (R4.3, the spec's "API" section).

    ``route`` is the concrete list path with its path parameters filled in, so
    a cursor from `/runs/{run1}/audit` is refused at `/runs/{run2}/audit`;
    `GET <list>` and `POST <list>/query` pass the same path. ``params`` are the
    route's own query parameters other than `cursor` and `limit`, and
    ``selection`` the parsed filter, ordering and fields. The tenant and
    workspace are the verified context's, never anything the client sent."""
    return {
        "route": route,
        "params": {
            name: None if value is None else str(value) for name, value in (params or {}).items()
        },
        "tenant": str(tenant),
        "workspace": None if workspace is None else str(workspace),
        "selection": dict(selection or {}),
    }


@dataclass(frozen=True)
class PageQuery:
    """The identity of the query a cursor belongs to.

    ``identity`` is what a version 2 cursor is bound to, built by
    :func:`list_identity`: the route, its parameters, the caller's tenant and
    workspace, and the filter, ordering and fields. ``sort_type`` is the type of
    the value the listing is ordered by, which a cursor's tag must name.

    ``key`` and ``filters`` are the version 1 identity: the endpoint's name and
    the values that narrowed it. They are read only to resume a version 1
    cursor; a listing that never minted one has no ``key``, and a version 1
    cursor sent to it is refused. Without an ``identity`` (an internal one-page
    read) the version 2 fingerprint is taken from them.
    """

    key: str | None
    filters: Mapping[str, object] = field(default_factory=dict)
    identity: Mapping[str, object] | None = None
    sort_type: SortType = SortType.DATETIME

    @property
    def fingerprint(self) -> str:
        """The version 1 digest: the endpoint's name and its stringified filters.

        Values are stringified rather than serialized structurally: the digest
        only has to be equal for equal queries and different for different ones,
        and stringifying keeps a UUID filter from depending on whether the route
        happened to pass the object or its text.
        """
        canonical = json.dumps(
            [self.key, {key: str(value) for key, value in sorted(self.filters.items())}],
            separators=(",", ":"),
        )
        return _digest(canonical)

    @property
    def identity_fingerprint(self) -> str:
        """The version 2 digest, over :attr:`identity` as canonical JSON."""
        identity = self.identity
        if identity is None:
            identity = {
                "key": self.key,
                "filters": {key: str(value) for key, value in self.filters.items()},
            }
        return _digest(canonical_json(identity))


@dataclass(frozen=True, slots=True)
class CursorPosition:
    """The exact row a page ended on: the sort key, plus the id breaking ties.

    The id is not decoration. Sort columns tie — two audit events appended in one
    transaction share ``occurred_at`` down to the microsecond — and a cursor that
    remembered only the timestamp would either repeat every tied row on the next
    page or skip all but one of them, depending on which way the comparison was
    written. With the id in the position the comparison is exact.

    A ``sort_value`` of None is a row among the NULLs, which sort after every
    value in either direction: that is the position's :attr:`phase`.
    """

    sort_value: SortValue
    tiebreaker: uuid.UUID

    @property
    def phase(self) -> Phase:
        return Phase.NULLS if self.sort_value is None else Phase.VALUES


@dataclass(frozen=True, slots=True)
class PageRequest:
    """One page of a query: how many rows, and where to resume.

    ``query`` travels with the request so that whatever mints the next cursor
    cannot disagree with whatever validated the incoming one.
    """

    limit: int
    after: CursorPosition | None
    query: PageQuery

    @property
    def fetch_limit(self) -> int:
        """How many rows to ask the database for: one more than the client gets.

        The extra row is how a query learns that a further page exists without a
        second ``COUNT`` over the whole table. It is dropped by :func:`build_page`
        and never returned, and its absence is what keeps the final page from
        handing back a cursor that resolves to nothing.
        """
        return self.limit + 1


@dataclass(frozen=True, slots=True)
class Page[ItemT]:
    """A page of results and the cursor that continues it.

    ``next_cursor`` is ``None`` on the last page, and that — not an empty
    ``items`` — is the client's stop condition: a filtered listing can return an
    empty page in the middle of a run and still have more rows behind it.
    """

    items: tuple[ItemT, ...]
    next_cursor: str | None

    def map_items[MappedT](self, transform: Callable[[ItemT], MappedT]) -> Page[MappedT]:
        """Re-type the rows while carrying the cursor across unchanged.

        Every list endpoint maps a domain object onto a view model. Doing that by
        rebuilding the page by hand loses the cursor the first time someone
        forgets to copy it, and a lost cursor looks exactly like the last page.
        """
        return Page(
            items=tuple(transform(item) for item in self.items),
            next_cursor=self.next_cursor,
        )


def encode_cursor(position: CursorPosition, query: PageQuery) -> str:
    """Render a position as the opaque version 2 string a client sends back."""
    payload: dict[str, object] = {
        "v": _V2,
        "t": _tag_of(position.sort_value),
        "p": position.phase.value,
        "i": str(position.tiebreaker),
        "q": query.identity_fingerprint,
    }
    if position.sort_value is not None:
        payload["k"] = _json_of(position.sort_value)
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    # Padding is stripped so the cursor survives a query string without
    # percent-encoding; :func:`decode_cursor` puts it back.
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


_UNREADABLE: Final = "cursor is not readable; drop it and request the first page again"
_FOREIGN: Final = (
    "cursor was issued for a different query; "
    "request the first page again with the filters you want"
)


def _refuse_constant(_: str) -> object:
    # `NaN`, `Infinity` and `-Infinity`, which `json` accepts by default.
    raise ValueError("not a JSON number")


def _decode_v1(payload: Mapping[str, object], query: PageQuery) -> CursorPosition:
    # Only a listing that minted version 1 cursors reads one, and only against
    # the fingerprint it minted them with (G7, R4.3).
    if query.key is None or query.sort_type is not SortType.DATETIME:
        raise InvalidCursorError(_FOREIGN)
    if payload.get("q") != query.fingerprint:
        raise InvalidCursorError(_FOREIGN)
    try:
        sort_value = datetime.fromisoformat(str(payload["k"]))
        tiebreaker = uuid.UUID(str(payload["i"]))
    except (KeyError, ValueError) as exc:
        raise InvalidCursorError(_UNREADABLE) from exc
    return CursorPosition(sort_value=sort_value, tiebreaker=tiebreaker)


def _decode_v2(payload: Mapping[str, object], query: PageQuery) -> CursorPosition:
    if payload.get("q") != query.identity_fingerprint:
        raise InvalidCursorError(_FOREIGN)
    tag, phase = payload.get("t"), payload.get("p")
    try:
        tiebreaker = uuid.UUID(str(payload["i"]))
        if phase == Phase.NULLS.value:
            # A NULL has no value to carry; one that does is not a NULL.
            if tag != NULL_TAG or "k" in payload:
                raise ValueError("a nulls position carries no value")
            return CursorPosition(sort_value=None, tiebreaker=tiebreaker)
        if phase != Phase.VALUES.value or tag != query.sort_type.value:
            raise ValueError("phase or type tag does not fit this listing")
        sort_value = typed_value(query.sort_type, payload["k"])
    except (KeyError, ValueError) as exc:
        raise InvalidCursorError(_UNREADABLE) from exc
    return CursorPosition(sort_value=sort_value, tiebreaker=tiebreaker)


def decode_cursor(cursor: str, query: PageQuery) -> CursorPosition:
    """Read a cursor back, refusing one that does not belong to ``query``.

    Raises :class:`InvalidCursorError` for anything unreadable, for a payload
    written by a format version this build does not read, and for a cursor
    whose fingerprint does not match — a stale or foreign cursor is refused
    rather than silently applied, because applying it would return a window of
    the wrong result set and the client would have no way to notice.
    """
    try:
        # ``binascii.Error`` and ``json.JSONDecodeError`` are both ValueError.
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded), parse_constant=_refuse_constant)
    except (ValueError, TypeError) as exc:
        raise InvalidCursorError(_UNREADABLE) from exc
    if not isinstance(payload, dict):
        raise InvalidCursorError(_UNREADABLE)
    version = payload.get("v")
    if isinstance(version, int) and not isinstance(version, bool):
        if version == _V2:
            return _decode_v2(payload, query)
        if version == _V1:
            return _decode_v1(payload, query)
    raise InvalidCursorError(
        "cursor was issued by an older version of this API; "
        "drop it and request the first page again"
    )


def page_request(*, limit: int, cursor: str | None, query: PageQuery) -> PageRequest:
    """Turn a client's ``limit``/``cursor`` pair into a validated request."""
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise DomainError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return PageRequest(
        limit=limit,
        after=decode_cursor(cursor, query) if cursor else None,
        query=query,
    )


def build_page[ItemT](
    rows: Sequence[ItemT],
    *,
    request: PageRequest,
    position_of: Callable[[ItemT], CursorPosition],
) -> Page[ItemT]:
    """Trim an over-fetched result set into a page and mint its next cursor.

    ``rows`` is whatever came back for :attr:`PageRequest.fetch_limit` — one row
    more than the client asked for, when a further page exists. The surplus row
    is dropped here and its presence is the only thing consulted to decide
    whether ``next_cursor`` is set, so the last page reliably ends the run.
    """
    kept = tuple(rows[: request.limit])
    has_more = len(rows) > request.limit
    next_cursor = encode_cursor(position_of(kept[-1]), request.query) if has_more and kept else None
    return Page(items=kept, next_cursor=next_cursor)
