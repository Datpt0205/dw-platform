"""Test doubles for the egress client's two outside worlds: the name service
and the socket layer (connections-and-vault R3). Imported by tests only.

- `FakeDns` answers names through a patched `socket.getaddrinfo`, the very
  call `net_guard.resolve_checked` makes, so a test exercises the platform's
  own address policy, not a stand-in. An empty answer is a name that does not
  resolve; a name it does not hold goes to the real resolver.
- `FakeNetwork` is an `httpcore` backend for the layer under the pin: it
  records the address it was asked to connect to, the TLS server name and
  every byte written, and answers each connection with the next scripted
  response. Asked for a name instead of an address (the pin removed), it
  resolves the name itself, as an unpinned connect would.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpcore

__all__ = ["OK", "FakeConnection", "FakeDns", "FakeNetwork"]

OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


class FakeDns:
    """Answers per name, in order: the last answer repeats."""

    def __init__(self) -> None:
        self.answers: dict[str, list[list[str]]] = {}
        self.asked: list[str] = []

    def set(self, host: str, *answers: list[str]) -> None:
        self.answers[host] = list(answers)

    def lookup(self, host: str) -> list[str] | None:
        queue = self.answers.get(host)
        if queue is None:
            return None
        self.asked.append(host)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def getaddrinfo(self, real: Callable[..., Any]) -> Callable[..., Any]:
        """A `socket.getaddrinfo` answering from this table, else from `real`."""

        def fake(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            answer = self.lookup(str(host))
            if answer is None:
                return real(host, port, *args, **kwargs)
            if not answer:
                raise socket.gaierror(socket.EAI_NONAME, "no such name")
            return [
                (
                    socket.AF_INET6 if ":" in ip else socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (ip, port or 0),
                )
                for ip in answer
            ]

        return fake


@dataclass
class FakeConnection:
    address: str
    port: int
    response: bytes
    sni: str | None = None
    written: bytearray = field(default_factory=bytearray)
    answered: bool = False


class _FakeStream(httpcore.AsyncNetworkStream):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self.connection.answered:
            return b""
        self.connection.answered = True
        return self.connection.response

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.connection.written.extend(buffer)

    async def aclose(self) -> None:
        return None

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connection.sni = server_hostname
        return self


class FakeNetwork(httpcore.AsyncNetworkBackend):
    def __init__(self, *responses: bytes) -> None:
        self.responses = list(responses) or [OK]
        self.connections: list[FakeConnection] = []

    @property
    def opened(self) -> list[str]:
        return [c.address for c in self.connections]

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            # What a connect that was handed the name would reach.
            address = str(socket.getaddrinfo(host, port)[0][4][0])
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        connection = FakeConnection(address, port, response)
        self.connections.append(connection)
        return _FakeStream(connection)

    async def sleep(self, seconds: float) -> None:
        return None
