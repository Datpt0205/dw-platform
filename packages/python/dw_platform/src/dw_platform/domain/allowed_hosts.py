"""An Allowed host pattern a company may ask for (connections-and-vault R3.8,
R3.21; ADR-0115 decision 6).

A pattern is a host name, or `*.` and a host name: one wildcard level, which
the egress client matches against exactly one label. It is stored the way the
egress client compares it (`dw_kernel.host_patterns.normalize_host`: lower
case, no trailing dot, IDN labels as A-labels), so the approval's payload and
the row carry the form a person reviews and the client reads.

Refused, 422, before any approval is opened:

- an IP literal, with or without a wildcard (the table's CHECK refuses an IPv4
  one too, even from a direct write);
- anything but letters, digits, dots and hyphens, or longer than 253;
- a wildcard on a public suffix, ICANN and PRIVATE sections alike
  (`*.com.vn`, `*.github.io`): one row would open every company under it.

The Public Suffix List is pinned in this package (`public_suffix_list.dat`,
publicsuffix/list at commit 52b71b3c4576ff77450cc7ebcfc7f34a916af3f9 of
2026-10-17, sha256 3d92f70d…25e5f33, MPL-2.0) and never fetched at run time;
a newer list is a commit.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from importlib.resources import files
from typing import Final, Literal

from dw_kernel.errors import DomainError
from dw_kernel.host_patterns import WILDCARD_PREFIX, normalize_host

__all__ = [
    "ALLOWED_HOST_PURPOSES",
    "AllowedHost",
    "AllowedHostPurpose",
    "HostPatternError",
    "PublicSuffixList",
    "is_public_suffix",
    "normalize_allowed_host_pattern",
    "normalize_ports",
]

AllowedHostPurpose = Literal["http_tool", "mcp", "webhook", "model", "any"]
ALLOWED_HOST_PURPOSES: Final[tuple[AllowedHostPurpose, ...]] = (
    "http_tool",
    "mcp",
    "webhook",
    "model",
    "any",
)

MAX_PATTERN_LENGTH: Final = 253
_PATTERN: Final = re.compile(r"^(\*\.)?[a-z0-9.-]+$")
_IPV4_LIKE: Final = re.compile(r"^[0-9.]+$")


class HostPatternError(DomainError):
    """The pattern may not be an Allowed host; `details.reason_code` says why."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(
            "not an allowed host pattern",
            details={"reason_code": reason_code, "pointer": "/host_pattern"},
        )


@dataclass(frozen=True)
class PublicSuffixList:
    """The rules of the list, A-labels: exact suffixes, the parents of `*.`
    rules, and the `!` exceptions."""

    exact: frozenset[str]
    wildcard_parents: frozenset[str]
    exceptions: frozenset[str]

    @classmethod
    def parse(cls, text: str) -> PublicSuffixList:
        exact: set[str] = set()
        parents: set[str] = set()
        exceptions: set[str] = set()
        for line in text.splitlines():
            rule = line.strip().split(maxsplit=1)[0] if line.strip() else ""
            if not rule or rule.startswith("//"):
                continue
            if rule.startswith("!"):
                target, name = exceptions, rule[1:]
            elif rule.startswith(WILDCARD_PREFIX):
                target, name = parents, rule[len(WILDCARD_PREFIX) :]
            else:
                target, name = exact, rule
            try:
                target.add(normalize_host(name))
            except ValueError:
                continue
        return cls(frozenset(exact), frozenset(parents), frozenset(exceptions))

    def is_public_suffix(self, domain: str) -> bool:
        """Whether `domain` (normalized) is itself a public suffix: listed, under
        a `*.` rule and not excepted, or a single label (the list's implicit
        `*` rule: every top-level domain)."""
        if domain in self.exceptions:
            return False
        if domain in self.exact or "." not in domain:
            return True
        return domain.partition(".")[2] in self.wildcard_parents


@cache
def _pinned() -> PublicSuffixList:
    data = files("dw_platform.domain").joinpath("public_suffix_list.dat")
    return PublicSuffixList.parse(data.read_text(encoding="utf-8"))


def is_public_suffix(domain: str) -> bool:
    return _pinned().is_public_suffix(domain)


def _is_ip_literal(name: str) -> bool:
    try:
        ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        return bool(_IPV4_LIKE.match(name))
    return True


def normalize_allowed_host_pattern(raw: str) -> str:
    """The pattern as stored and matched, or HostPatternError (422)."""
    wildcard = raw.startswith(WILDCARD_PREFIX)
    name = raw[len(WILDCARD_PREFIX) :] if wildcard else raw
    if _is_ip_literal(name.rstrip(".")):
        raise HostPatternError("host_pattern_ip_literal")
    try:
        host = normalize_host(name)
    except ValueError:
        raise HostPatternError("host_pattern_invalid") from None
    pattern = f"{WILDCARD_PREFIX}{host}" if wildcard else host
    if not _PATTERN.match(pattern) or len(pattern) > MAX_PATTERN_LENGTH:
        raise HostPatternError("host_pattern_invalid")
    if _IPV4_LIKE.match(host):
        raise HostPatternError("host_pattern_ip_literal")
    if wildcard and is_public_suffix(host):
        raise HostPatternError("host_pattern_public_suffix")
    return pattern


MAX_PORTS: Final = 16


def normalize_ports(ports: tuple[int, ...]) -> tuple[int, ...]:
    """Distinct ports in order, each a TCP port, one to sixteen of them."""
    distinct = tuple(sorted(set(ports)))
    if not distinct or len(distinct) > MAX_PORTS or not all(0 < p < 65536 for p in distinct):
        raise DomainError(
            "not a set of TCP ports",
            details={"reason_code": "ports_invalid", "pointer": "/ports"},
        )
    return distinct


@dataclass(frozen=True)
class AllowedHost:
    """A live row of `platform.egress_allowed_hosts`; its id is the approval's."""

    id: uuid.UUID
    host_pattern: str
    ports: tuple[int, ...]
    purpose: str
    note: str | None
    owning_workspace_id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
