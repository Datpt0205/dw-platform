"""The one client of tenant-directed traffic (connections-and-vault R3;
ADR-0115 decision 6).

A call passes, in this order, before any byte of it leaves:

1. the run's mode: outside `live`, only `model`, and a `connector` or
   `http_tool` call of an action declared `simulate_safe`, go out; `mcp`,
   `oauth` and `webhook` never do, whatever the flag (R3.5,
   `egress_blocked:run_mode`);
2. the URL: `http` or `https` without credentials, and only `https` when
   deployed (R3.20, `egress_blocked:scheme`);
3. the destination: a `connector` or `oauth` call only to the hosts its
   catalogue connector's manifest declares (R3.17), every other purpose only to
   a live row of the company's Allowed hosts, matched by `rule_admits` (R3.7,
   R3.21), both `egress_blocked:host_not_allowed`;
4. the address, at connect time, under the pin (`PinnedNetworkBackend`,
   `egress_blocked:address`, R3.1, R3.2).

A redirect is followed only as the request's `redirect` mode allows, at most
three steps, each step through 2-4 again, and an origin change drops
`Authorization`, `Cookie` and `Proxy-Authorization` before the next step is
sent (R3.3, R3.4). The body is read while streaming, decoded, and the call ends
once it passes 2 MiB; the whole call, every step, runs within the request's
`timeout_seconds`.

Every call ends as the table in `outcome` says, by the measured `SendProbe`:
an `EgressResponse`, or exactly one of the kernel's three typed errors. The
client retries only a connection that failed before any byte was written
(`httpcore`'s own connect retry), never a call that may have been applied.
An exception the table does not know is not swallowed (runtime-hardening
R6.12).
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Final, NoReturn

import httpcore
import httpx

from dw_connectors.egress.contracts import (
    AllowedHostRule,
    AllowedHostsPort,
    CatalogueHostsPort,
    EgressContext,
    EgressRequest,
    EgressResponse,
)
from dw_connectors.egress.network import PinnedNetworkBackend, SendProbe
from dw_connectors.egress.outcome import http_answer, not_dispatched, raise_for, stopped
from dw_connectors.egress.redaction import SecretMask, install_httpx_log_scrub, scrubbing
from dw_kernel.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError
from dw_kernel.host_patterns import normalize_host, pattern_matches
from dw_observability.metrics import DW_EGRESS_BLOCKED_TOTAL, DW_EGRESS_REQUESTS_TOTAL
from dw_observability.semconv import DW_EGRESS_REQUEST
from dw_observability.telemetry import NullTelemetry, TelemetryPort

__all__ = [
    "BODY_CAP_BYTES",
    "MAX_REDIRECTS",
    "EgressClient",
    "rule_admits",
    "run_mode_admits",
]

BODY_CAP_BYTES: Final = 2 * 1024 * 1024
MAX_REDIRECTS: Final = 3
# One retry of a connection that failed before any byte was written.
_CONNECT_RETRIES: Final = 1

RUN_MODE = "egress_blocked:run_mode"
SCHEME = "egress_blocked:scheme"
HOST_NOT_ALLOWED = "egress_blocked:host_not_allowed"
REDIRECT = "egress_blocked:redirect"
URL_INVALID = "egress_blocked:url"
ALLOWLIST_UNAVAILABLE = "allowlist_unavailable"
BODY_TOO_LARGE = "body_too_large"
TIMEOUT = "timeout"
TRANSPORT = "transport_error"

_DEFAULT_PORTS: Final = {"http": 80, "https": 443}
_PASSES_OUTSIDE_LIVE: Final = frozenset({"connector", "http_tool"})
_CATALOGUE_PURPOSES: Final = frozenset({"connector", "oauth"})
_ORIGIN_BOUND_HEADERS: Final = frozenset({"authorization", "cookie", "proxy-authorization"})
_BODY_HEADERS: Final = frozenset({"content-type", "content-length", "transfer-encoding"})

install_httpx_log_scrub()


def run_mode_admits(context: EgressContext) -> bool:
    """R3.5: whether a call may leave in its run's mode."""
    if context.run_mode == "live" or context.purpose == "model":
        return True
    return context.purpose in _PASSES_OUTSIDE_LIVE and context.simulate_safe


def rule_admits(rule: AllowedHostRule, *, host: str, port: int, purpose: str) -> bool:
    """R3.21: the row's pattern matches the normalized host, the port is one of
    its ports, and its purpose is the call's or `any`."""
    return (
        pattern_matches(rule.host_pattern, host)
        and port in rule.ports
        and rule.purpose in (purpose, "any")
    )


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return (url.scheme, url.host, url.port or _DEFAULT_PORTS.get(url.scheme))


@dataclass(frozen=True)
class _Step:
    method: str
    url: httpx.URL
    headers: tuple[tuple[str, str], ...]
    content: bytes | None

    def redirected(self, response: httpx.Response) -> _Step:
        """The next step, as a browser makes it: 303 (and 301/302 after a POST)
        turns into a body-less GET; an origin change drops the credentials."""
        location = response.headers.get("location")
        if not location:
            raise not_dispatched(REDIRECT)
        target = self.url.join(location)
        method, content, headers = self.method, self.content, self.headers
        status = response.status_code
        if (status == 303 and method != "HEAD") or (status in (301, 302) and method == "POST"):
            method, content = "GET", None
            headers = tuple((k, v) for k, v in headers if k.lower() not in _BODY_HEADERS)
        if _origin(target) != _origin(self.url):
            headers = tuple((k, v) for k, v in headers if k.lower() not in _ORIGIN_BOUND_HEADERS)
        return _Step(method, target, headers, content)


@dataclass
class EgressClient:
    """Implements ``EgressPort``.

    `allow_private` and `require_https` are the composition root's
    (`not settings.is_deployed`, `settings.is_deployed`); their defaults are
    the closed ones.
    """

    allowed_hosts: AllowedHostsPort
    catalogue: CatalogueHostsPort
    allow_private: bool = False
    require_https: bool = True
    telemetry: TelemetryPort = field(default_factory=NullTelemetry)
    # The socket layer under the pin; a test hands in a fake.
    network: httpcore.AsyncNetworkBackend | None = None

    async def send(self, context: EgressContext, request: EgressRequest) -> EgressResponse:
        mask = SecretMask.of(request.secret_values)
        probe = SendProbe()
        attributes = {
            "dw.tenant_id": str(context.tenant_id),
            "dw.workspace_id": str(context.workspace_id),
            "dw.egress.purpose": context.purpose,
            "dw.run_mode": context.run_mode,
        }
        with scrubbing(mask), self.telemetry.span(DW_EGRESS_REQUEST, attributes):
            try:
                response = await self._send(context, request, probe, mask)
            except (NotDispatchedError, RejectedError, OutcomeUnknownError) as exc:
                self._count(context, exc.outcome, exc.details.get("reason_code"))
                raise
        self._count(context, "succeeded", None)
        return response

    def _count(self, context: EgressContext, outcome: str, code: object) -> None:
        self.telemetry.add_metric(
            DW_EGRESS_REQUESTS_TOTAL, 1, {"purpose": context.purpose, "outcome": outcome}
        )
        if isinstance(code, str) and code.startswith("egress_blocked:"):
            self.telemetry.add_metric(
                DW_EGRESS_BLOCKED_TOTAL, 1, {"purpose": context.purpose, "reason": code}
            )

    async def _send(
        self,
        context: EgressContext,
        request: EgressRequest,
        probe: SendProbe,
        mask: SecretMask,
    ) -> EgressResponse:
        if not run_mode_admits(context):
            raise not_dispatched(RUN_MODE)
        try:
            url = httpx.URL(request.url)
        except httpx.InvalidURL:
            raise not_dispatched(URL_INVALID) from None
        step = _Step(request.method.upper(), url, tuple(request.headers.items()), request.content)
        try:
            async with asyncio.timeout(request.timeout_seconds):
                return await self._exchange(context, request, step, probe, mask)
        except NotDispatchedError as exc:
            # A stop raised before a byte of its own step left (a check, the
            # pin, the cap) is certain only while nothing was written at all.
            _stopped(probe, str(exc.details.get("reason_code")))
        except (TimeoutError, httpx.TimeoutException):
            _stopped(probe, TIMEOUT)
        except httpx.TransportError as exc:
            _stopped(probe, _transport_code(exc))

    async def _exchange(
        self,
        context: EgressContext,
        request: EgressRequest,
        step: _Step,
        probe: SendProbe,
        mask: SecretMask,
    ) -> EgressResponse:
        backend = PinnedNetworkBackend(probe, allow_private=self.allow_private, inner=self.network)
        timeout = httpx.Timeout(request.timeout_seconds)
        async with httpx.AsyncClient(
            transport=_PinnedTransport(backend),
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        ) as client:
            for hop in range(MAX_REDIRECTS + 1):
                await self._admit(context, step.url)
                outgoing = client.build_request(
                    step.method, step.url, headers=list(step.headers), content=step.content
                )
                response = await client.send(outgoing, stream=True)
                try:
                    if response.is_redirect and request.redirect != "none":
                        if hop == MAX_REDIRECTS:
                            raise not_dispatched(REDIRECT)
                        following = step.redirected(response)
                        if request.redirect == "same_origin" and _origin(following.url) != _origin(
                            step.url
                        ):
                            raise not_dispatched(REDIRECT)
                        step = following
                        continue
                    status = response.status_code
                    outcome = http_answer(status)
                    if outcome == "outcome_unknown":
                        # A 5xx, a 1xx, a 3xx not followed: nothing to read.
                        raise_for(outcome, code=f"http_{status}")
                    body = await _read_capped(response)
                    raise_for(outcome, code=f"http_{status}", provider_code=str(status))
                    return EgressResponse(
                        status_code=status,
                        headers=tuple((k, mask.text(v)) for k, v in response.headers.items()),
                        body=mask.data(body),
                        url=mask.text(str(response.url.copy_with(query=None))),
                    )
                finally:
                    await response.aclose()
        raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover

    async def _admit(self, context: EgressContext, url: httpx.URL) -> None:
        """Steps 2 and 3 of the module docstring, for one step of the call."""
        if url.scheme not in _DEFAULT_PORTS or (self.require_https and url.scheme != "https"):
            raise not_dispatched(SCHEME)
        if url.userinfo:
            raise not_dispatched(URL_INVALID)
        try:
            host = normalize_host(url.raw_host.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            raise not_dispatched(URL_INVALID) from None
        port = url.port or _DEFAULT_PORTS[url.scheme]
        if context.purpose in _CATALOGUE_PURPOSES:
            if not self._catalogue_admits(context.connector_key, host):
                raise not_dispatched(HOST_NOT_ALLOWED)
            return
        rules = await self._live_rules(context)
        if not any(rule_admits(r, host=host, port=port, purpose=context.purpose) for r in rules):
            raise not_dispatched(HOST_NOT_ALLOWED)

    def _catalogue_admits(self, connector_key: str | None, host: str) -> bool:
        """R3.17: a manifest host, compared whole after normalizing."""
        if not connector_key:
            return False
        declared = set()
        for name in self.catalogue.egress_hosts(connector_key):
            try:
                declared.add(normalize_host(name))
            except ValueError:
                continue
        return host in declared

    async def _live_rules(self, context: EgressContext) -> Sequence[AllowedHostRule]:
        try:
            return await self.allowed_hosts.live(context.tenant_id)
        except Exception as exc:
            # Nothing has left: the list could not be read, so nothing is let out.
            raise not_dispatched(ALLOWLIST_UNAVAILABLE) from exc


@cache
def _tls_context() -> ssl.SSLContext:
    """Verifying, from the bundled CA set, never the environment's; built once
    per process: loading the CA set costs about half a second on every build."""
    return httpx.create_ssl_context(trust_env=False)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """httpx's own transport over a pool whose every connection is pinned.

    `httpx` takes no network backend, so the pool it built is replaced by one
    built on the pin; everything else (the request and response mapping, the
    exception mapping) is httpx's.
    """

    def __init__(self, backend: PinnedNetworkBackend) -> None:
        tls = _tls_context()
        super().__init__(verify=tls, trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=tls,
            network_backend=backend,
            retries=_CONNECT_RETRIES,
            http1=True,
            http2=False,
        )


async def _read_capped(response: httpx.Response) -> bytes:
    """The decoded body, ended once it passes the cap (a gzip that inflates
    past it included): a body read in part is not an answer."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > BODY_CAP_BYTES:
            raise not_dispatched(BODY_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _transport_code(error: httpx.TransportError) -> str:
    if isinstance(error, httpx.ConnectError):
        return "connect_failed"
    if isinstance(error, httpx.RemoteProtocolError | httpx.ReadError | httpx.WriteError):
        return "connection_lost"
    return TRANSPORT


def _stopped(probe: SendProbe, code: str) -> NoReturn:
    """A call that ended without an answer, as the table says by the probe.

    Raised without its cause: a transport error's text can carry the URL, and
    with it a value the caller asked to have scrubbed.
    """
    try:
        raise_for(stopped(sent=probe.sent), code=code)
    except (NotDispatchedError, OutcomeUnknownError) as error:
        raise error from None
    raise AssertionError("a stop is never a success")  # pragma: no cover
