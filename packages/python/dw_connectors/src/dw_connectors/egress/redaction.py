"""A call's secret values, scrubbed by value from what leaves the client
(connections-and-vault R1.2, R3; ADR-0115 decision 6).

The caller names the values it put in a header or the body. Each is matched as
written, URL-encoded and base64-encoded (standard and URL-safe, with and
without padding), because a provider that echoes a credential back echoes it
in whichever form it received. Longest first, so a value that contains another
is replaced whole.

The `httpx` logger's line carries the request URL: the filter installed here
drops every query string from it and, during a call, the call's own values,
read from a context variable so two concurrent calls never see each other's.
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import quote, quote_plus

__all__ = ["MASK", "SecretMask", "install_httpx_log_scrub", "scrubbing"]

MASK = "[secret]"


def _variants(value: str) -> set[str]:
    raw = value.encode("utf-8")
    found = {value, quote(value, safe=""), quote_plus(value)}
    for encoded in (base64.b64encode(raw), base64.urlsafe_b64encode(raw)):
        text = encoded.decode("ascii")
        found |= {text, text.rstrip("=")}
    return {variant for variant in found if variant}


@dataclass(frozen=True)
class SecretMask:
    """The forms of a call's secret values, longest first."""

    variants: tuple[str, ...] = ()

    @classmethod
    def of(cls, values: Iterable[str]) -> SecretMask:
        forms: set[str] = set()
        for value in values:
            if value:
                forms |= _variants(value)
        return cls(tuple(sorted(forms, key=len, reverse=True)))

    def text(self, text: str) -> str:
        for variant in self.variants:
            text = text.replace(variant, MASK)
        return text

    def data(self, data: bytes) -> bytes:
        mask = MASK.encode("ascii")
        for variant in self.variants:
            data = data.replace(variant.encode("utf-8"), mask)
        return data


_CALL_MASK: ContextVar[SecretMask | None] = ContextVar("dw_egress_call_mask", default=None)
_QUERY = re.compile(r"(https?://[^\s?#\"']*)\?[^\s#\"']*")


@contextmanager
def scrubbing(mask: SecretMask) -> Iterator[None]:
    """The call's mask, set for the log filter while the call runs."""
    token = _CALL_MASK.set(mask)
    try:
        yield
    finally:
        _CALL_MASK.reset(token)


class _ScrubHttpxRecord(logging.Filter):
    """Formats the record, drops query strings and the running call's secrets,
    and drops the args, so nothing survives in an arg the format left alone."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        scrubbed = _QUERY.sub(r"\1", message)
        mask = _CALL_MASK.get()
        if mask is not None:
            scrubbed = mask.text(scrubbed)
        if scrubbed != message:
            record.msg, record.args = scrubbed, None
        return True


_FILTER = _ScrubHttpxRecord()


def install_httpx_log_scrub() -> None:
    """Idempotent: one filter on the `httpx` logger, whoever asks first."""
    logger = logging.getLogger("httpx")
    if _FILTER not in logger.filters:
        logger.addFilter(_FILTER)
