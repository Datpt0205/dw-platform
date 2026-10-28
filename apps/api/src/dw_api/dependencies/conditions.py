"""`If-Match`, `If-None-Match` and the merge-patch body, on a route that turned
conditional writes on (app-standards R3).

`RequireIfMatch` parses the header and hands the service the version the caller
read. It loads nothing and compares nothing: the comparison is the service's
conditional write (`UPDATE ... WHERE id = :id AND version = :v`), and a write
that matched no row is told apart under the caller's own authority (R3.9,
R3.13). It sits after the route's idempotency dependency in the signature, and
the service's effect-key lookup runs before that write, so a retry of a write
that already happened gets its first answer, not a 412 (R2.1, R2.34).

There is no optional mode. A resource that turned R3 on requires `If-Match` on
every write, and the app-build test reads this dependency's header in the
schema to tell which routes did (R3.12).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, Request

from dw_kernel.errors import DomainError
from dw_kernel.http_conditions import (
    ExpectedVersion,
    parse_if_match,
    parse_if_none_match,
    require_patch_media_type,
)

IF_MATCH = "If-Match"
IF_NONE_MATCH = "If-None-Match"


# A list, so a repeated header reaches the parser instead of FastAPI keeping one.
_IF_MATCH_HEADER = Header(
    default=None,
    alias=IF_MATCH,
    description=(
        'Required. The strong ETag of the version you read, for example "7".'
        " A stale or weak one is a 412; none, *, a list or a repeat is a 428."
    ),
)
_IF_NONE_MATCH_HEADER = Header(
    default=None,
    alias=IF_NONE_MATCH,
    description="Optional on a create. `*` turns an existing id into a 412 instead of a 409.",
)


async def _require_if_match(if_match: list[str] | None = _IF_MATCH_HEADER) -> ExpectedVersion:
    return parse_if_match(if_match)


RequireIfMatch = Annotated[ExpectedVersion, Depends(_require_if_match)]


async def _if_none_match(if_none_match: list[str] | None = _IF_NONE_MATCH_HEADER) -> bool:
    return parse_if_none_match(if_none_match)


IfNoneMatchAny = Annotated[bool, Depends(_if_none_match)]


async def _merge_patch(request: Request) -> dict[str, Any]:
    require_patch_media_type(request.headers.get("content-type"))
    try:
        patch = await request.json()
    except ValueError:
        raise DomainError("the body is not valid JSON") from None
    if not isinstance(patch, dict):
        raise DomainError("a merge patch is a JSON object")
    return patch


MergePatch = Annotated[dict[str, Any], Depends(_merge_patch)]
"""A `PATCH` body as RFC 7396 reads it; 415 for any other media type (R3.10)."""
