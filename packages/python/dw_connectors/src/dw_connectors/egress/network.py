"""The connection a call is allowed to open: resolved once, checked, pinned
(connections-and-vault R3.1, R3.2, R3.14; ADR-0115 decisions 5, 6).

`PinnedNetworkBackend` sits under `httpcore`'s connection pool. For each TCP
connection it resolves the host once with `net_guard.resolve_checked`, the
platform's one address policy, refuses it when any answer is not a global
address, and connects to an address that was checked, never to the name: a
resolver that answers a public address to the check and a private one to the
connect (DNS rebinding) is answered by never asking it twice. TLS is still
verified against the host name, because `httpcore` passes the origin's host as
`server_hostname` to `start_tls`, not the address it connected to.

Every stream it hands out records, in the call's `SendProbe`, the moment a
byte of a request is handed to a socket. Whether a call may have been applied
is that measured fact, not a guess from which exception `httpx` raised
(R3.14, R3.15): `sent` is set before the write is attempted, so a write that
fails half way still counts as sent.
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpcore

from dw_connectors.egress.outcome import not_dispatched
from dw_kernel.net_guard import UNRESOLVED, OutboundUrlError, resolve_checked

__all__ = ["BLOCKED_ADDRESS", "UNRESOLVED_HOST", "PinnedNetworkBackend", "SendProbe"]

BLOCKED_ADDRESS = "egress_blocked:address"
UNRESOLVED_HOST = "host_unresolved"
CONNECT_FAILED = "connect_failed"


@dataclass
class SendProbe:
    """One call's measured fact: has a byte of a request been written yet."""

    sent: bool = False


class _RecordingStream(httpcore.AsyncNetworkStream):
    def __init__(self, inner: httpcore.AsyncNetworkStream, probe: SendProbe) -> None:
        self._inner = inner
        self._probe = probe

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._inner.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        if buffer:
            self._probe.sent = True
        await self._inner.write(buffer, timeout)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        # The handshake's own bytes are not a request's: the TLS layer writes
        # them below this wrapper, and the wrapped stream records from here on.
        upgraded = await self._inner.start_tls(ssl_context, server_hostname, timeout)
        return _RecordingStream(upgraded, self._probe)

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connects only to addresses `resolve_checked` returned for the host.

    `inner` opens the socket (`httpcore`'s own backend unless a test hands it a
    fake that records where it was asked to connect). `allow_private` is the
    composition root's, `not settings.is_deployed`, and nobody else's.
    """

    def __init__(
        self,
        probe: SendProbe,
        *,
        allow_private: bool,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._probe = probe
        self._allow_private = allow_private
        self._inner = inner if inner is not None else httpcore.AnyIOBackend()

    async def _addresses(self, host: str, port: int) -> list[str]:
        try:
            return await asyncio.to_thread(
                resolve_checked, host, port, allow_private=self._allow_private
            )
        except OutboundUrlError as exc:
            unresolved = exc.details.get("reason_code") == UNRESOLVED
            raise not_dispatched(UNRESOLVED_HOST if unresolved else BLOCKED_ADDRESS) from None

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        failure: Exception | None = None
        for address in await self._addresses(host, port):
            try:
                stream = await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as exc:
                failure = exc
                continue
            return _RecordingStream(stream, self._probe)
        raise httpcore.ConnectError(CONNECT_FAILED) from failure

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise not_dispatched("egress_blocked:unix_socket")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
