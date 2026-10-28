"""A list query's values stay out of the access log (app-standards R5.12).

A filter tree carries values a person typed (a name, an amount, a phone
number), and a cursor carries a row's sort value; both arrive in the query
string, which uvicorn's access logger writes verbatim under its default
formatter (`local`, `test`). The identifier-only JSON formatter of the deployed
profiles renders no arguments at all, so there the line already holds nothing;
this filter makes the default formatter safe too, for every route, by replacing
the values of `filter` and `cursor` with one fixed mark and keeping the names.

HTTP spans need no counterpart today: the API starts no server span, and
`IdentifierOnlySpanProcessor` drops every attribute outside
`dw_observability.semconv.ALLOWED_KEYS`, which names no URL attribute. A server
span added later takes its target through :func:`redacted_target`.
"""

from __future__ import annotations

import logging
from typing import Final
from urllib.parse import unquote_plus

REDACTED: Final = "[redacted]"
_HIDDEN_VALUES: Final = frozenset({"filter", "cursor"})
_ACCESS_LOGGER: Final = "uvicorn.access"
# uvicorn's call: `'%s - "%s %s HTTP/%s" %d'`, the third argument the target.
_TARGET_ARG: Final = 2


def redacted_target(target: str) -> str:
    """``target`` (path and query) with the value of every `filter` and `cursor`
    replaced by :data:`REDACTED`, however the name was percent-encoded."""
    path, separator, query = target.partition("?")
    if not separator:
        return target
    parts = []
    for part in query.split("&"):
        name, equals, _ = part.partition("=")
        hidden = unquote_plus(name) in _HIDDEN_VALUES
        parts.append(f"{name}={REDACTED}" if hidden and equals else part)
    return f"{path}?{'&'.join(parts)}"


class ListValueRedaction(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) > _TARGET_ARG
            and isinstance(args[_TARGET_ARG], str)
        ):
            record.args = (
                *args[:_TARGET_ARG],
                redacted_target(args[_TARGET_ARG]),
                *args[_TARGET_ARG + 1 :],
            )
        return True


def install_access_log_redaction() -> None:
    """Attach the filter to uvicorn's access logger, once per process."""
    logger = logging.getLogger(_ACCESS_LOGGER)
    if not any(isinstance(existing, ListValueRedaction) for existing in logger.filters):
        logger.addFilter(ListValueRedaction())
