"""JSON log lines that carry identifiers only (spec R1.5).

A log line is read by more people, and kept in more places, than the row it is
about, so it carries what a span carries: identifiers, counts and type names.
`IdentifierOnlyJsonFormatter` writes one JSON object per record:

- the formatter's own fields (`LOG_BASE_FIELDS`): time, level, logger, and
  `message`, which is the call's template, never the template filled in. The
  arguments of `logger.info("rerank skipped: %s", exc)` are where values ride,
  so they are not rendered at all;
- the `extra=` keys listed in `dw_observability.semconv.ALLOWED_KEYS`; every
  other key is dropped;
- for an exception, its type and the code locations of its frames, never its
  message, which is built from whatever value failed.

A value shaped like an email address, a phone number or a URL query string is
dropped even under an allowed key, because the key says what a field was meant
to hold, not what a caller put in it.

The API's uvicorn loggers use it through `configs/logging/uvicorn.json`; the
worker installs it with `configure_json_logging`.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime
from typing import Any, Final

from dw_observability.semconv import ALLOWED_KEYS

__all__ = [
    "DROPPED_MESSAGE",
    "LOG_BASE_FIELDS",
    "IdentifierOnlyJsonFormatter",
    "configure_json_logging",
    "looks_like_a_value",
]

LOG_BASE_FIELDS: Final = frozenset(
    {"timestamp", "level", "logger", "message", "exception.type", "exception.frames"}
)
# What `message` becomes when the template itself carries a value: an f-string
# passed as the template, which `test_log_templates_are_constants` refuses in src/.
DROPPED_MESSAGE: Final = "log.message_dropped"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A run of digits with the separators people write phone numbers with. Nine
# digits or more: a date (`2026-10-27`) has eight, a version far fewer.
_PHONE_RUN = re.compile(r"(?<![\w.-])\+?\d[\d\s().-]{7,}\d(?![\w.-])")
_QUERY_STRING = re.compile(r"\?[^\s=&?]+=|&[^\s=&?]+=")
_PHONE_MIN_DIGITS = 9

# Attributes every LogRecord has; anything else on the record came from `extra=`.
_RECORD_ATTRIBUTES: Final = frozenset(
    set(vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)))
    | {"message", "asctime"}
)


def looks_like_a_value(text: str) -> bool:
    """True when `text` holds an email address, a phone number or a query string."""
    if _EMAIL.search(text) or _QUERY_STRING.search(text):
        return True
    return any(
        sum(ch.isdigit() for ch in match.group()) >= _PHONE_MIN_DIGITS
        for match in _PHONE_RUN.finditer(text)
    )


def _clean(value: Any) -> Any:
    """The value as JSON, or `None` when any part of it looks like a value."""
    if isinstance(value, bool) or value is None or isinstance(value, float):
        return value
    if isinstance(value, int):
        return None if looks_like_a_value(str(value)) else value
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_clean(item) for item in value]
        return None if any(item is None for item in items) else items
    text = str(value)
    return None if looks_like_a_value(text) else text


class IdentifierOnlyJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        template = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
        line: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": DROPPED_MESSAGE if looks_like_a_value(template) else template,
        }
        for key, value in vars(record).items():
            if key in _RECORD_ATTRIBUTES or key not in ALLOWED_KEYS:
                continue
            cleaned = _clean(value)
            if cleaned is not None:
                line[key] = cleaned
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            line["exception.type"] = exc_type.__name__
            line["exception.frames"] = [
                f"{frame.filename}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(tb)
            ]
        return json.dumps(line, ensure_ascii=False)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Send the root logger to stdout through the formatter, replacing its handlers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(IdentifierOnlyJsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
