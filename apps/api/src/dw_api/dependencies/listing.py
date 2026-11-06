"""The query parameters of a list route, read once and checked before any SQL.

Two shapes, one rule for both: a parameter a route does not take is refused,
never ignored, and none of `cursor`, `filter`, `order_by`, `fields` or `limit`
may be sent twice (app-standards R5.15). FastAPI silently drops a query
parameter a route does not declare and keeps one of a repeated pair, so neither
would otherwise reach a refusal.

* :data:`RequireListPage` — a listing in a fixed order (the five that existed
  before query schemas): `limit` and `cursor` only. ``page.request(...)``
  builds the page request, binding a version 2 cursor to the concrete path, the
  route's own parameters and the caller's tenant and workspace (R4.3), and
  still resuming a version 1 cursor against the identity it was minted with
  (G7).
* :func:`queryable` — a listing with a :class:`QuerySchema`: `filter`,
  `order_by` and `fields` too, all parsed by `dw_kernel.filters`
  (R5.13). :func:`query_body` reads the same query from a `POST <list>/query`
  body through the same parser, so both forms answer alike (R5.7).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal

from fastapi import Depends, Query, Request

from dw_api.dependencies.auth import RequireAccessContext
from dw_kernel.errors import DomainError
from dw_kernel.filters import (
    ListQuery,
    QueryError,
    QueryProblem,
    QuerySchema,
    ReasonCode,
    loads,
    parse_query,
)
from dw_kernel.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PageQuery,
    PageRequest,
    SortType,
    list_identity,
    page_request,
)
from dw_platform.application.access_context import AccessContext

# What `dw_kernel.filters` reads. Absent from a fixed-order route's signature,
# and so refused there rather than dropped.
SELECTION_PARAMETERS: Final = ("filter", "order_by", "fields")
SINGLE_PARAMETERS: Final = ("cursor", "limit", *SELECTION_PARAMETERS)

_CURSOR_DESCRIPTION = "Opaque cursor from a previous page."
COUNTS: Final = ("none", "exact")
Count = Literal["none", "exact"]


def _refuse_unread(request: Request, *, queryable: bool) -> None:
    params = request.query_params
    for name in SINGLE_PARAMETERS:
        if len(params.getlist(name)) > 1:
            raise QueryError(QueryProblem(ReasonCode.PARAMETER_REPEATED, parameter=name))
    if not queryable:
        for name in SELECTION_PARAMETERS:
            if name in params:
                raise QueryError(QueryProblem(ReasonCode.PARAMETER_NOT_ACCEPTED, parameter=name))


@dataclass(frozen=True)
class ListPage:
    """`limit` and `cursor` of a fixed-order listing, and the path they came on."""

    limit: int
    cursor: str | None
    path: str

    def request(
        self,
        context: AccessContext,
        *,
        key: str,
        filters: Mapping[str, object],
        params: Mapping[str, object] | None = None,
        sort_type: SortType = SortType.DATETIME,
    ) -> PageRequest:
        """The page request; ``key`` and ``filters`` are the version 1 identity
        this route minted before, ``params`` its own query parameters, and
        ``sort_type`` the type of the column it sorts on (a timestamp unless
        it says otherwise), which its cursor carries."""
        return page_request(
            limit=self.limit,
            cursor=self.cursor,
            query=PageQuery(
                key=key,
                filters=filters,
                identity=list_identity(
                    route=self.path,
                    tenant=context.tenant_id,
                    workspace=context.workspace_id,
                    params=params,
                ),
                sort_type=sort_type,
            ),
        )


async def _list_page(
    request: Request,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None, description=_CURSOR_DESCRIPTION),
) -> ListPage:
    _refuse_unread(request, queryable=False)
    return ListPage(limit=limit, cursor=cursor, path=request.url.path)


RequireListPage = Annotated[ListPage, Depends(_list_page)]

SchemaFor = Callable[[AccessContext], Awaitable[QuerySchema]]
"""The resource owner's one function from a caller to what they may query."""


def queryable(schema_for: SchemaFor) -> Any:
    """The dependency of a list route with a query schema, as a `ListQuery`."""

    async def dependency(
        request: Request,
        context: RequireAccessContext,
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(default=None, description=_CURSOR_DESCRIPTION),
        filter: str | None = Query(default=None, description="A JSON filter tree, URL-encoded."),
        order_by: str | None = Query(default=None, description="One field, then asc or desc."),
        fields: str | None = Query(default=None, description="Comma-separated field names."),
    ) -> ListQuery:
        _refuse_unread(request, queryable=True)
        schema = await schema_for(context)
        return parse_query(
            schema,
            route=request.url.path,
            tenant=context.tenant_id,
            workspace=context.workspace_id,
            filter=None if filter is None else loads(filter),
            order_by=order_by,
            fields=fields,
            cursor=cursor,
            limit=limit,
        )

    return Depends(dependency)


_BODY_MEMBERS: Final = frozenset({"filter", "order_by", "fields", "cursor", "limit"})
_BODY_SHAPE: Final = (
    "the body is one JSON object of filter, order_by, fields, cursor and limit, each named once"
)


_COUNTED_SHAPE: Final = (
    "the body is one JSON object of filter, order_by, fields, cursor, limit and count"
    " (none or exact), each named once"
)


@dataclass(frozen=True)
class RawListQuery:
    """A list query as the request carried it, its shape checked and nothing
    read against a schema yet. ``count`` is None for a listing that does not
    count; otherwise `none` or `exact`, and part of the cursor's identity."""

    route: str
    filter: object | None = None
    order_by: str | None = None
    fields: str | None = None
    cursor: str | None = None
    limit: int = DEFAULT_PAGE_SIZE
    count: Count | None = None

    def parse(self, schema: QuerySchema, context: AccessContext) -> ListQuery:
        """Every part checked against ``schema``, the cursor bound to all of
        it and to the caller's tenant and workspace (R4.3)."""
        return parse_query(
            schema,
            route=self.route,
            tenant=context.tenant_id,
            workspace=context.workspace_id,
            filter=self.filter,
            order_by=self.order_by,
            fields=self.fields,
            cursor=self.cursor,
            limit=self.limit,
            params=None if self.count is None else {"count": self.count},
        )


async def read_query_body(request: Request, *, route: str, counts: bool = False) -> RawListQuery:
    """A `POST <list>/query` body, its shape checked (``route`` is the list's
    own path, so the cursor is `GET <list>`'s); with ``counts``, `count` too."""
    shape = _COUNTED_SHAPE if counts else _BODY_SHAPE
    members = _BODY_MEMBERS | {"count"} if counts else _BODY_MEMBERS
    try:
        body = loads(await request.body())
    except QueryError:
        body = None
    # The body itself, not the filter in it: refused without a pointer.
    if type(body) is not dict or not set(body) <= members:
        raise DomainError(shape)
    order_by, fields, cursor = body.get("order_by"), body.get("fields"), body.get("cursor")
    limit = body.get("limit", DEFAULT_PAGE_SIZE)
    if any(
        value is not None and not isinstance(value, str) for value in (order_by, fields, cursor)
    ):
        raise DomainError(shape)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise QueryError(QueryProblem(ReasonCode.LIMIT_OUT_OF_RANGE, parameter="limit"))
    count = body.get("count", "none") if counts else None
    if count is not None and count not in COUNTS:
        raise DomainError(shape)
    return RawListQuery(
        route=route,
        filter=body.get("filter"),
        order_by=order_by,
        fields=fields,
        cursor=cursor,
        limit=limit,
        count=count,
    )


async def query_body(
    request: Request, context: AccessContext, schema: QuerySchema, *, route: str
) -> ListQuery:
    """`POST <list>/query`: the body's members through the same parser as the
    query string, bound to the same cursor identity as `GET <list>` (``route``
    is the list's own path)."""
    return (await read_query_body(request, route=route)).parse(schema, context)


def counted_listing(*, url_sortable: frozenset[str]) -> Any:
    """`GET <list>` of a counted listing whose schema the resource builds in
    its own transaction: `limit`, `cursor`, `order_by`, `fields` and `count`
    as a :class:`RawListQuery`. `filter` is refused (it belongs in the body of
    `POST <list>/query`), and so is an `order_by` on a field outside
    ``url_sortable``: both `parameter_not_accepted`, with the parameter."""
    sortable_text = ", ".join(sorted(url_sortable))

    async def dependency(
        request: Request,
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(default=None, description=_CURSOR_DESCRIPTION),
        order_by: str | None = Query(
            default=None,
            description=f"One of {sortable_text}, then asc or desc; any other field in the"
            " body of POST <list>/query.",
        ),
        fields: str | None = Query(default=None, description="Comma-separated field names."),
        count: Literal["none", "exact"] = Query(
            default="none", description="`exact` counts the matches on a first page, to 10 000."
        ),
    ) -> RawListQuery:
        _refuse_unread(request, queryable=True)
        params = request.query_params
        if len(params.getlist("count")) > 1:
            raise QueryError(QueryProblem(ReasonCode.PARAMETER_REPEATED, parameter="count"))
        if "filter" in params:
            raise QueryError(QueryProblem(ReasonCode.PARAMETER_NOT_ACCEPTED, parameter="filter"))
        if order_by is not None and order_by.strip().split(" ")[0] not in url_sortable:
            raise QueryError(QueryProblem(ReasonCode.PARAMETER_NOT_ACCEPTED, parameter="order_by"))
        return RawListQuery(
            route=request.url.path,
            order_by=order_by,
            fields=fields,
            cursor=cursor,
            limit=limit,
            count=count,
        )

    return Depends(dependency)
