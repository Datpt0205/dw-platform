"""Outbound URL guard (SSRF defence for provider adapters; runtime-hardening R7.2).

One policy for every address the platform calls out to (ADR-0115 decision 5):
`forbidden_address`. An address that embeds an IPv4 one (IPv4-mapped, 6to4
`2002::/16`, Teredo, NAT64 `64:ff9b::/96`) is judged by the IPv4 it carries;
then anything that is not `is_global`, or is multicast, is refused.
`64:ff9b::a9fe:a9fe` is the reason for the order: Python calls it global, and
it reaches `169.254.169.254` through a NAT64 gateway (measured 30/10/2026).

Fail closed: only http(s), no credentials in the URL, and every address the
host resolves to must be allowed. `allow_private`, passed only by a process
that is not deployed (local dev against Ollama or vLLM), lifts private and
loopback ranges and nothing else: link-local (the cloud metadata address),
multicast, unspecified and reserved stay refused, and a name that does not
resolve passes, reaching nothing, as it did before. A host on the allow-list
passes by its name, compared whole and case-insensitively, without resolving.

What this checks, and what it does not: the base URL an operator configured,
when it is validated. It does not pin the addresses at connect time, so a name
that resolves differently later is not caught here. A URL a tenant gives goes
through `connections-and-vault`'s egress client, which pins what
`resolve_checked` returns.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from dw_kernel.errors import DomainError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
UNRESOLVED = "outbound_host_unresolved"


class OutboundUrlError(DomainError):
    """The URL must not be called from this process."""


def _embedded(address: IPAddress) -> IPAddress:
    """The IPv4 address an IPv6 one carries, or the address itself."""
    if not isinstance(address, ipaddress.IPv6Address):
        return address
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    if address in _NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address


def forbidden_address(ip: str | IPAddress, *, allow_private: bool = False) -> bool:
    """Whether an outbound call may not reach `ip`."""
    address = _embedded(ipaddress.ip_address(str(ip).split("%")[0]))
    if address.is_link_local or address.is_multicast or address.is_unspecified:
        return True
    # Before `is_reserved`: Python files `::1` under the reserved `::/8`.
    if allow_private and (address.is_private or address.is_loopback):
        return False
    return address.is_reserved or not address.is_global


def resolve_checked(
    host: str, port: int | None = None, *, allow_private: bool = False
) -> list[str]:
    """Resolve `host` once and refuse it when any answer is forbidden; the
    checked addresses, for a caller that pins them. An IP literal is checked
    without resolving."""
    try:
        addresses = [str(ipaddress.ip_address(host.split("%")[0]))]
    except ValueError:
        try:
            addresses = sorted({str(info[4][0]) for info in socket.getaddrinfo(host, port)})
        except socket.gaierror as exc:
            raise OutboundUrlError(
                "outbound host does not resolve",
                details={"host": host, "reason_code": UNRESOLVED},
            ) from exc
        except UnicodeError as exc:
            # `getaddrinfo` IDNA-encodes the host before it looks anything up,
            # and that step raises `UnicodeError` - not `gaierror` - for a label
            # over 63 characters or an empty one. It is not an OSError either,
            # so it escaped this guard entirely: a scraped link with a malformed
            # host took down the whole run instead of being one page nobody
            # could read. A host that cannot be encoded cannot be resolved, so
            # it gets the same verdict.
            raise OutboundUrlError(
                "outbound host is not a resolvable name",
                details={"host": host, "reason_code": UNRESOLVED},
            ) from exc
    if not addresses or any(forbidden_address(a, allow_private=allow_private) for a in addresses):
        raise OutboundUrlError(
            "outbound URL resolves to an address that is not global",
            details={"host": host},
        )
    return addresses


def ensure_allowed_outbound_url(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: tuple[str, ...] = (),
) -> str:
    """Validate an outbound base URL; returns it unchanged when acceptable."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise OutboundUrlError(
            "outbound URL must be http(s)", details={"scheme": parts.scheme or "<none>"}
        )
    if not parts.hostname:
        raise OutboundUrlError("outbound URL has no host", details={"url": url})
    if parts.username or parts.password:
        raise OutboundUrlError(
            "outbound URL must not embed credentials", details={"host": parts.hostname}
        )
    host = parts.hostname
    if host.lower() in {allowed.lower() for allowed in allowed_hosts}:
        return url
    try:
        resolve_checked(host, parts.port, allow_private=allow_private)
    except OutboundUrlError as exc:
        # A name that does not resolve reaches no address. Outside a deployed
        # profile it passes, as it always has (a compose service may not be up
        # yet); a deployed one refuses it.
        if not (allow_private and exc.details.get("reason_code") == UNRESOLVED):
            raise
    return url
