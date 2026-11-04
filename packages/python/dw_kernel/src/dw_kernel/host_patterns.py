"""Host names and allowed-host patterns, normalized one way
(connections-and-vault R3.21; ADR-0115 decision 6).

One owner for two readers that must agree: the API that stores a company's
Allowed host pattern (`dw_platform.domain.allowed_hosts`) and the egress client
that compares a call's host with it (`dw_connectors.egress`). A host is
lower-cased, loses one trailing dot, and has each IDN label written as its
A-label; a pattern is a host, or `*.` and a host, which matches exactly one
label before that host and never the host itself.

The A-label comes from the standard library's IDNA codec (IDNA 2003). Where it
and IDNA 2008, which the HTTP client connects with, disagree on a label (`ß`,
`ς`, joiners), the egress client compares the host it will actually connect
to, so such a call matches no pattern and is refused: closed, never wider.
"""

from __future__ import annotations

__all__ = ["WILDCARD_PREFIX", "normalize_host", "pattern_matches"]

WILDCARD_PREFIX = "*."


def normalize_host(host: str) -> str:
    """Lower case, no trailing dot, IDN labels as A-labels.

    Raises ValueError for a name that is empty or has an empty or overlong
    label: it names no host.
    """
    name = host.lower()
    if name.endswith("."):
        name = name[:-1]
    if not name or name != name.strip():
        raise ValueError("not a host name")
    try:
        encoded = name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("not a host name") from exc
    if any(not label for label in encoded.split(".")):
        raise ValueError("not a host name")
    return encoded


def pattern_matches(pattern: str, host: str) -> bool:
    """Whether a normalized `host` is the normalized `pattern`, or has exactly
    one label before the domain of a `*.<domain>` pattern."""
    if pattern.startswith(WILDCARD_PREFIX):
        domain = pattern[len(WILDCARD_PREFIX) :]
        label, dot, rest = host.partition(".")
        return bool(label) and bool(dot) and rest == domain
    return host == pattern
