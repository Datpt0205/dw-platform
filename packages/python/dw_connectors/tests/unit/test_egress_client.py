"""The egress client against a fake socket layer and a real local server
(connections-and-vault R3.1-R3.5, R3.7, R3.14-R3.17, R3.20, R3.21; CV7, CV8,
CV10, CV19, CV26, CV29).

Names resolve through a patched `socket.getaddrinfo`, the call
`net_guard.resolve_checked` makes, so the address policy under test is the
platform's own and not a stand-in. Two layers sit under the pin:

- `FakeNetwork`, an `httpcore` backend that records the address it was asked
  to connect to, the TLS server name, and every byte written, and answers each
  connection with the next scripted response. Asked for a name instead of an
  address (the pin removed), it resolves the name itself, as an unpinned
  connect would.
- `LocalServer`, a real asyncio server on 127.0.0.1 counting the requests it
  read, for the phases only a real socket shows: a refused connection, a reset
  after the request, a timeout.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpcore
import pytest

from dw_connectors.egress import (
    EgressClient,
    EgressContext,
    EgressPurpose,
    EgressRequest,
    NoCatalogueHosts,
)
from dw_connectors.testing import OK, FakeDns, FakeNetwork
from dw_kernel.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError
from dw_kernel.run_mode import RunMode
from dw_observability.metrics import DW_EGRESS_BLOCKED_TOTAL, DW_EGRESS_REQUESTS_TOTAL
from dw_observability.semconv import contract_violations, load_snapshot, snapshot_path
from dw_observability.telemetry import RecordingTelemetry

pytestmark = pytest.mark.unit

PUBLIC = "8.8.4.4"
TENANT = uuid.UUID(int=1)
WORKSPACE = uuid.UUID(int=2)


# -- the name service and the socket layer ------------------------------------


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> FakeDns:
    table = FakeDns()
    monkeypatch.setattr(socket, "getaddrinfo", table.getaddrinfo(socket.getaddrinfo))
    return table


# -- the client's ports ------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    host_pattern: str
    ports: tuple[int, ...] = (443,)
    purpose: str = "http_tool"


@dataclass
class Hosts:
    """The live rows of the tenant; a removed row is not live, so not here."""

    rules: list[Rule] = field(default_factory=list)
    asked: list[uuid.UUID] = field(default_factory=list)

    async def live(self, tenant_id: uuid.UUID) -> list[Rule]:
        self.asked.append(tenant_id)
        return list(self.rules)


@dataclass(frozen=True)
class Catalogue:
    hosts: dict[str, frozenset[str]]

    def egress_hosts(self, connector_key: str) -> frozenset[str]:
        return self.hosts.get(connector_key, frozenset())


@dataclass
class Telemetry:
    spans: list[str] = field(default_factory=list)
    metrics: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def span(self, name: str, attributes: Any) -> AbstractContextManager[None]:
        self.spans.append(name)
        return nullcontext()

    def add_metric(self, name: str, value: float, attributes: Any) -> None:
        self.metrics.append((name, dict(attributes)))

    def set_gauge(self, name: str, value: float, attributes: Any) -> None:
        return None

    def record_histogram(self, name: str, value: float, attributes: Any) -> None:
        return None


def client(
    *rules: Rule,
    network: httpcore.AsyncNetworkBackend | None = None,
    allow_private: bool = False,
    require_https: bool = True,
    catalogue: Any = None,
    telemetry: Telemetry | None = None,
) -> EgressClient:
    return EgressClient(
        allowed_hosts=Hosts(list(rules)),
        catalogue=catalogue if catalogue is not None else NoCatalogueHosts(),
        allow_private=allow_private,
        require_https=require_https,
        telemetry=telemetry if telemetry is not None else Telemetry(),
        network=network,
    )


def context(
    purpose: EgressPurpose = "http_tool",
    run_mode: RunMode = "live",
    *,
    simulate_safe: bool = False,
    connector_key: str | None = None,
) -> EgressContext:
    return EgressContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        run_id=None,
        run_mode=run_mode,
        purpose=purpose,
        connector_key=connector_key,
        simulate_safe=simulate_safe,
    )


def get(url: str, **kw: Any) -> EgressRequest:
    return EgressRequest(method="GET", url=url, **kw)


def reason(error: BaseException) -> object:
    assert isinstance(error, NotDispatchedError | RejectedError | OutcomeUnknownError)
    return error.details.get("reason_code")


def redirect(location: str, status: int = 302) -> bytes:
    return f"HTTP/1.1 {status} Found\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n".encode()


ACME = Rule("*.acme.vn")


# -- R3.1, R3.2: resolved once, checked, pinned ----------------------------------------


async def test_the_connection_goes_to_the_address_that_was_checked_and_tls_to_the_name(
    dns: FakeDns,
) -> None:
    """R3.1 (CV7): the name answers a public address to the check and a private
    one afterwards; the connection goes to the first, TLS names the host."""
    dns.set("api.acme.vn", [PUBLIC], ["10.0.0.5"])
    network = FakeNetwork()

    response = await client(ACME, network=network).send(context(), get("https://api.acme.vn/x"))

    assert response.status_code == 200 and response.body == b"ok"
    assert network.opened == [PUBLIC]
    assert network.connections[0].sni == "api.acme.vn"
    assert dns.asked == ["api.acme.vn"]


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",
        "2002:a9fe:a9fe::1",
        "10.0.0.5",
        "127.0.0.1",
    ],
)
async def test_an_address_that_is_not_global_is_refused_before_any_connection(
    dns: FakeDns, address: str
) -> None:
    """R3.2 (CV7): deployed (`allow_private` false), every answer is judged by
    `forbidden_address`, and nothing is opened."""
    dns.set("api.acme.vn", [address])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await client(ACME, network=network).send(context(), get("https://api.acme.vn/"))

    assert reason(refused.value) == "egress_blocked:address"
    assert network.opened == []


async def test_one_forbidden_answer_among_public_ones_refuses_the_name(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC, "169.254.169.254"])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await client(ACME, network=network).send(context(), get("https://api.acme.vn/"))

    assert reason(refused.value) == "egress_blocked:address"
    assert network.opened == []


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
async def test_a_global_address_goes_out(dns: FakeDns, address: str) -> None:
    dns.set("api.acme.vn", [address])
    network = FakeNetwork()

    await client(ACME, network=network).send(context(), get("https://api.acme.vn/"))

    assert network.opened == [address]


async def test_outside_a_deployed_profile_a_private_address_goes_out_but_never_link_local(
    dns: FakeDns,
) -> None:
    """`allow_private` lifts private and loopback ranges, nothing else."""
    dns.set("api.acme.vn", ["10.0.0.5"])
    dns.set("meta.acme.vn", ["169.254.169.254"])
    network = FakeNetwork()
    egress = client(ACME, network=network, allow_private=True)

    await egress.send(context(), get("https://api.acme.vn/"))
    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(context(), get("https://meta.acme.vn/"))

    assert reason(refused.value) == "egress_blocked:address"
    assert network.opened == ["10.0.0.5"]


async def test_a_name_that_does_not_resolve_did_not_leave(dns: FakeDns) -> None:
    dns.set("gone.acme.vn", [])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await client(ACME, network=network).send(context(), get("https://gone.acme.vn/"))

    assert reason(refused.value) == "host_unresolved"
    assert network.opened == []


# -- R3.3, R3.4: redirects ------------------------------------------------------------


async def test_a_redirect_to_the_metadata_address_is_refused_without_a_second_connection(
    dns: FakeDns,
) -> None:
    """R3.3 (CV8): an IP literal is on no list; the step after the first is
    refused, and the call may have been applied, so its outcome is unknown."""
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(redirect("http://169.254.169.254/latest/meta-data/"))

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(ACME, network=network, require_https=False).send(
            context(), get("https://api.acme.vn/", redirect="revalidate")
        )

    assert reason(stopped.value) == "egress_blocked:host_not_allowed"
    assert network.opened == [PUBLIC]


async def test_a_redirect_to_a_host_off_the_list_is_refused(dns: FakeDns) -> None:
    """R3.3: re-validated at every step, not only the first."""
    dns.set("api.acme.vn", [PUBLIC])
    dns.set("other.example", [PUBLIC])
    network = FakeNetwork(redirect("https://other.example/"), OK)

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(ACME, network=network).send(
            context(), get("https://api.acme.vn/", redirect="revalidate")
        )

    assert reason(stopped.value) == "egress_blocked:host_not_allowed"
    assert len(network.connections) == 1


async def test_a_redirect_to_a_listed_name_that_resolves_inward_is_refused(dns: FakeDns) -> None:
    """R3.3: the next step's address is checked and pinned too."""
    dns.set("api.acme.vn", [PUBLIC])
    dns.set("evil.acme.vn", ["169.254.169.254"])
    network = FakeNetwork(redirect("https://evil.acme.vn/"), OK)

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(ACME, network=network).send(
            context(), get("https://api.acme.vn/", redirect="revalidate")
        )

    assert reason(stopped.value) == "egress_blocked:address"
    assert network.opened == [PUBLIC]


async def test_an_origin_change_drops_authorization_and_cookie(dns: FakeDns) -> None:
    """R3.4 (CV8): the next origin never sees the credentials."""
    dns.set("api.acme.vn", [PUBLIC])
    dns.set("cdn.acme.vn", ["8.8.8.8"])
    network = FakeNetwork(redirect("https://cdn.acme.vn/file", 307), OK)
    request = get(
        "https://api.acme.vn/",
        headers={"Authorization": "Bearer tok", "Cookie": "s=1", "X-Trace": "t"},
        redirect="revalidate",
    )

    await client(ACME, network=network).send(context(), request)

    first, second = (bytes(c.written).lower() for c in network.connections)
    assert b"authorization: bearer tok" in first and b"cookie: s=1" in first
    assert b"authorization" not in second and b"cookie" not in second
    assert b"x-trace: t" in second


async def test_the_same_origin_keeps_the_credentials(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(redirect("/next", 307), OK)

    await client(ACME, network=network).send(
        context(),
        get(
            "https://api.acme.vn/", headers={"Authorization": "Bearer tok"}, redirect="same_origin"
        ),
    )

    assert all(
        b"authorization: bearer tok" in bytes(c.written).lower() for c in network.connections
    )


async def test_same_origin_mode_refuses_another_origin(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(redirect("https://cdn.acme.vn/"), OK)

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(ACME, network=network).send(
            context(), get("https://api.acme.vn/", redirect="same_origin")
        )

    assert reason(stopped.value) == "egress_blocked:redirect"
    assert len(network.connections) == 1


async def test_a_fourth_redirect_is_not_followed(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(*(redirect(f"/r{n}") for n in range(5)))

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(ACME, network=network).send(
            context(), get("https://api.acme.vn/", redirect="revalidate")
        )

    assert reason(stopped.value) == "egress_blocked:redirect"
    assert len(network.connections) == 4


async def test_without_a_redirect_mode_a_3xx_ends_the_call_unknown(dns: FakeDns) -> None:
    """The default `none`: a 3xx not followed is an answer nobody read."""
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(redirect("/elsewhere", 301))

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(ACME, network=network).send(context(), get("https://api.acme.vn/"))

    assert reason(stopped.value) == "http_301"
    assert len(network.connections) == 1


async def test_a_303_after_a_post_is_a_get_without_the_body(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(redirect("/done", 303), OK)

    await client(ACME, network=network).send(
        context(),
        EgressRequest(
            method="POST",
            url="https://api.acme.vn/submit",
            headers={"Content-Type": "application/json"},
            content=b'{"a":1}',
            redirect="revalidate",
        ),
    )

    second = bytes(network.connections[1].written)
    assert second.startswith(b"GET /done ")
    assert b'{"a":1}' not in second and b"content-type" not in second.lower()


# -- R3.5: the run's mode ------------------------------------------------------------------


@pytest.mark.parametrize("run_mode", ["simulate", "test"])
@pytest.mark.parametrize("purpose", ["connector", "http_tool", "webhook", "mcp", "oauth"])
async def test_outside_live_no_purpose_but_model_goes_out(
    dns: FakeDns, run_mode: RunMode, purpose: EgressPurpose
) -> None:
    """R3.5 (CV10): refused before anything is asked, the list included."""
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork()
    hosts = Hosts([Rule("*.acme.vn", purpose="any")])
    egress = EgressClient(allowed_hosts=hosts, catalogue=NoCatalogueHosts(), network=network)

    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(
            context(purpose, run_mode, connector_key="crm"), get("https://api.acme.vn/")
        )

    assert reason(refused.value) == "egress_blocked:run_mode"
    assert network.opened == [] and hosts.asked == []


@pytest.mark.parametrize("purpose", ["mcp", "oauth", "webhook"])
async def test_simulate_safe_frees_no_purpose_but_connector_and_http_tool(
    dns: FakeDns, purpose: EgressPurpose
) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork()
    catalogue = Catalogue({"crm": frozenset({"api.acme.vn"})})

    with pytest.raises(NotDispatchedError) as refused:
        await client(Rule("*.acme.vn", purpose="any"), network=network, catalogue=catalogue).send(
            context(purpose, "simulate", simulate_safe=True, connector_key="crm"),
            get("https://api.acme.vn/"),
        )

    assert reason(refused.value) == "egress_blocked:run_mode"
    assert network.opened == []


async def test_in_simulate_a_model_call_and_a_read_only_action_go_out(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork()
    catalogue = Catalogue({"crm": frozenset({"api.acme.vn"})})
    egress = client(Rule("*.acme.vn", purpose="any"), network=network, catalogue=catalogue)

    await egress.send(context("model", "simulate"), get("https://api.acme.vn/"))
    await egress.send(
        context("http_tool", "simulate", simulate_safe=True), get("https://api.acme.vn/")
    )
    await egress.send(
        context("connector", "simulate", simulate_safe=True, connector_key="crm"),
        get("https://api.acme.vn/"),
    )

    assert network.opened == [PUBLIC] * 3


@pytest.mark.parametrize("purpose", ["http_tool", "webhook", "mcp", "model"])
async def test_live_goes_out(dns: FakeDns, purpose: EgressPurpose) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork()

    await client(Rule("*.acme.vn", purpose="any"), network=network).send(
        context(purpose), get("https://api.acme.vn/")
    )

    assert network.opened == [PUBLIC]


# -- R3.7, R3.21: the company's Allowed hosts -----------------------------------------------


@pytest.mark.parametrize(
    "url", ["https://api.acme.vn/", "https://API.Acme.vn./", "https://api.acme.vn:443/"]
)
async def test_a_host_one_label_under_the_wildcard_on_a_listed_port_goes_out(
    dns: FakeDns, url: str
) -> None:
    """R3.21 (CV19): normalized (case, trailing dot) before it is compared."""
    dns.set("api.acme.vn", [PUBLIC])
    dns.set("api.acme.vn.", [PUBLIC])
    network = FakeNetwork()

    await client(ACME, network=network).send(context(), get(url))

    assert network.opened == [PUBLIC]


@pytest.mark.parametrize(
    ("url", "purpose"),
    [
        ("https://acme.vn/", "http_tool"),
        ("https://a.b.acme.vn/", "http_tool"),
        ("https://api.acme.vn:8443/", "http_tool"),
        ("https://api.acme.vn/", "mcp"),
        ("https://api.other.vn/", "http_tool"),
    ],
)
async def test_anything_else_is_not_allowed(dns: FakeDns, url: str, purpose: EgressPurpose) -> None:
    """R3.7, R3.21 (CV19): the wildcard's own domain, two labels under it,
    another port, another purpose, another host."""
    for name in ("acme.vn", "a.b.acme.vn", "api.acme.vn", "api.other.vn"):
        dns.set(name, [PUBLIC])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await client(ACME, network=network).send(context(purpose), get(url))

    assert reason(refused.value) == "egress_blocked:host_not_allowed"
    assert network.opened == []


async def test_a_row_for_any_purpose_admits_every_purpose_it_lists(dns: FakeDns) -> None:
    dns.set("hooks.acme.vn", [PUBLIC])
    network = FakeNetwork()

    await client(Rule("hooks.acme.vn", purpose="any"), network=network).send(
        context("webhook"), get("https://hooks.acme.vn/")
    )

    assert network.opened == [PUBLIC]


async def test_the_list_is_read_for_the_calls_tenant_on_every_call(dns: FakeDns) -> None:
    """R3.18: no copy kept between calls; a removal takes effect at the next."""
    dns.set("api.acme.vn", [PUBLIC])
    hosts = Hosts([ACME])
    egress = EgressClient(allowed_hosts=hosts, catalogue=NoCatalogueHosts(), network=FakeNetwork())

    await egress.send(context(), get("https://api.acme.vn/"))
    hosts.rules.clear()
    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(context(), get("https://api.acme.vn/"))

    assert reason(refused.value) == "egress_blocked:host_not_allowed"
    assert hosts.asked == [TENANT, TENANT]


async def test_a_list_that_cannot_be_read_lets_nothing_out(dns: FakeDns) -> None:
    class Broken:
        async def live(self, tenant_id: uuid.UUID) -> list[Rule]:
            raise ConnectionError("database down")

    network = FakeNetwork()
    egress = EgressClient(allowed_hosts=Broken(), catalogue=NoCatalogueHosts(), network=network)

    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(context(), get("https://api.acme.vn/"))

    assert reason(refused.value) == "allowlist_unavailable"
    assert network.opened == []


# -- R3.17: a catalogue connector's manifest hosts -------------------------------------------


@pytest.mark.parametrize("purpose", ["connector", "oauth"])
async def test_a_connector_call_goes_only_to_its_manifest_hosts(
    dns: FakeDns, purpose: EgressPurpose
) -> None:
    """R3.17 (CV29): not the company's list, which admits the host here."""
    dns.set("api.example.vn", [PUBLIC])
    dns.set("other.example.vn", [PUBLIC])
    network = FakeNetwork()
    egress = client(
        Rule("*.example.vn", purpose="any"),
        network=network,
        catalogue=Catalogue({"crm": frozenset({"api.example.vn"})}),
    )

    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(context(purpose, connector_key="crm"), get("https://other.example.vn/"))
    assert reason(refused.value) == "egress_blocked:host_not_allowed"
    assert network.opened == []

    await egress.send(context(purpose, connector_key="crm"), get("https://api.example.vn/"))
    assert network.opened == [PUBLIC]


@pytest.mark.parametrize("purpose", ["connector", "oauth"])
async def test_a_connector_call_without_a_connector_key_is_not_allowed(
    dns: FakeDns, purpose: EgressPurpose
) -> None:
    dns.set("api.example.vn", [PUBLIC])
    network = FakeNetwork()
    egress = client(network=network, catalogue=Catalogue({"crm": frozenset({"api.example.vn"})}))

    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(context(purpose), get("https://api.example.vn/"))

    assert reason(refused.value) == "egress_blocked:host_not_allowed"
    assert network.opened == []


async def test_w1s_catalogue_refuses_every_connector_call(dns: FakeDns) -> None:
    dns.set("api.example.vn", [PUBLIC])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await client(network=network).send(
            context("connector", connector_key="crm"), get("https://api.example.vn/")
        )

    assert reason(refused.value) == "egress_blocked:host_not_allowed"
    assert network.opened == []


# -- R3.20: only https when deployed -----------------------------------------------------------


async def test_deployed_plain_http_is_refused_before_anything(dns: FakeDns) -> None:
    """R3.20 (CV29)."""
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await client(Rule("*.acme.vn", (80,)), network=network).send(
            context(), get("http://api.acme.vn/", headers={"Authorization": "Bearer tok"})
        )

    assert reason(refused.value) == "egress_blocked:scheme"
    assert network.opened == []


async def test_deployed_a_redirect_down_to_http_is_refused_and_sends_no_credential_in_clear(
    dns: FakeDns,
) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork(redirect("http://api.acme.vn/plain"), OK)

    with pytest.raises(OutcomeUnknownError) as stopped:
        await client(Rule("*.acme.vn", (80, 443)), network=network).send(
            context(),
            get(
                "https://api.acme.vn/",
                headers={"Authorization": "Bearer tok"},
                redirect="revalidate",
            ),
        )

    assert reason(stopped.value) == "egress_blocked:scheme"
    assert [c.port for c in network.connections] == [443]


async def test_outside_a_deployed_profile_plain_http_goes_out(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    network = FakeNetwork()

    await client(Rule("*.acme.vn", (80,)), network=network, require_https=False).send(
        context(), get("http://api.acme.vn/")
    )

    assert [(c.address, c.port) for c in network.connections] == [(PUBLIC, 80)]


@pytest.mark.parametrize("url", ["ftp://api.acme.vn/", "https://user:pw@api.acme.vn/", "not a url"])
async def test_a_url_that_is_not_plain_http_or_https_is_refused(dns: FakeDns, url: str) -> None:
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError):
        await client(ACME, network=network, require_https=False).send(context(), get(url))

    assert network.opened == []


# -- R3.14-R3.16: a real server, and what it saw ----------------------------------------------


@dataclass
class LocalServer:
    port: int
    requests: list[bytes]


Behaviour = Callable[[asyncio.StreamReader, asyncio.StreamWriter, list[bytes]], Awaitable[None]]


async def _read_request(reader: asyncio.StreamReader, seen: list[bytes]) -> None:
    head = await reader.readuntil(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    body = await reader.readexactly(length) if length else b""
    seen.append(head + body)


def answering(raw: bytes) -> Behaviour:
    async def behave(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter, seen: list[bytes]
    ) -> None:
        await _read_request(reader, seen)
        writer.write(raw)
        await writer.drain()
        writer.close()

    return behave


async def resetting(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, seen: list[bytes]
) -> None:
    await _read_request(reader, seen)
    sock = writer.get_extra_info("socket")
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    writer.transport.abort()


async def silent(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, seen: list[bytes]
) -> None:
    await _read_request(reader, seen)
    await asyncio.sleep(5)


@pytest.fixture
async def serve(dns: FakeDns) -> AsyncIterator[Callable[[Behaviour], Awaitable[LocalServer]]]:
    servers: list[asyncio.Server] = []
    dns.set("provider.test", ["127.0.0.1"])
    dns.set("elsewhere.test", ["127.0.0.1"])

    async def start(behaviour: Behaviour) -> LocalServer:
        seen: list[bytes] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await behaviour(reader, writer, seen)
            except (asyncio.IncompleteReadError, ConnectionError):
                return

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        servers.append(server)
        return LocalServer(server.sockets[0].getsockname()[1], seen)

    yield start
    for server in servers:
        server.close()


def local(server: LocalServer, **kw: Any) -> EgressClient:
    return client(
        Rule("provider.test", (server.port,)), allow_private=True, require_https=False, **kw
    )


def at(server: LocalServer, path: str = "/") -> str:
    return f"http://provider.test:{server.port}{path}"


async def test_a_refused_connection_did_not_leave(dns: FakeDns) -> None:
    """R3.14 (CV26): nothing listens; the client knows no byte left."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    dns.set("provider.test", ["127.0.0.1"])
    egress = client(Rule("provider.test", (port,)), allow_private=True, require_https=False)

    with pytest.raises(NotDispatchedError) as refused:
        await egress.send(context(), get(f"http://provider.test:{port}/"))

    assert reason(refused.value) == "connect_failed"


async def test_a_reset_after_the_request_is_unknown_and_never_sent_again(serve: Any) -> None:
    """R3.15 (CV26): the server read the request; nobody knows if it acted."""
    server = await serve(resetting)

    with pytest.raises(OutcomeUnknownError) as stopped:
        await local(server).send(context(), EgressRequest("POST", at(server), content=b"x"))

    assert reason(stopped.value) == "connection_lost"
    assert len(server.requests) == 1


async def test_a_503_is_unknown(serve: Any) -> None:
    server = await serve(answering(b"HTTP/1.1 503 Busy\r\nContent-Length: 0\r\n\r\n"))

    with pytest.raises(OutcomeUnknownError) as stopped:
        await local(server).send(context(), EgressRequest("POST", at(server), content=b"x"))

    assert reason(stopped.value) == "http_503"
    assert len(server.requests) == 1


async def test_a_post_redirected_off_the_list_is_unknown_and_sent_once(serve: Any) -> None:
    """R3.15: the first step was sent; the refused second one changes nothing
    about that."""
    server = await serve(answering(redirect("http://elsewhere.test/take", 307)))

    with pytest.raises(OutcomeUnknownError) as stopped:
        await local(server).send(
            context(), EgressRequest("POST", at(server), content=b"x", redirect="revalidate")
        )

    assert reason(stopped.value) == "egress_blocked:host_not_allowed"
    assert len(server.requests) == 1


@pytest.mark.parametrize("gzipped", [False, True])
async def test_a_body_over_two_mebibytes_is_unknown(serve: Any, gzipped: bool) -> None:
    """R3.15: counted on the decoded bytes, so a small gzip that inflates past
    the cap is over it too."""
    body = b"\0" * (3 * 1024 * 1024)
    encoding = b""
    if gzipped:
        body, encoding = gzip.compress(body), b"Content-Encoding: gzip\r\n"
    head = b"HTTP/1.1 200 OK\r\n" + encoding + f"Content-Length: {len(body)}\r\n\r\n".encode()
    server = await serve(answering(head + body))

    with pytest.raises(OutcomeUnknownError) as stopped:
        await local(server).send(context(), get(at(server)))

    assert reason(stopped.value) == "body_too_large"
    assert len(server.requests) == 1


async def test_a_422_is_rejected_with_its_status(serve: Any) -> None:
    """R3.16 (CV26)."""
    server = await serve(answering(b"HTTP/1.1 422 No\r\nContent-Length: 2\r\n\r\nno"))

    with pytest.raises(RejectedError) as refused:
        await local(server).send(context(), EgressRequest("POST", at(server), content=b"x"))

    assert refused.value.provider_code == "422"
    assert len(server.requests) == 1


async def test_a_timeout_after_sending_is_unknown(serve: Any) -> None:
    server = await serve(silent)

    with pytest.raises(OutcomeUnknownError) as stopped:
        await local(server).send(context(), get(at(server), timeout_seconds=0.5))

    assert reason(stopped.value) == "timeout"
    assert len(server.requests) == 1


async def test_a_2xx_comes_back_with_the_calls_secrets_scrubbed(serve: Any) -> None:
    """The caller's values, as written, URL-encoded and base64, out of the body,
    the headers and the URL it returns."""
    secret = "tok/123+x"
    echoed = f"{secret} {quote(secret, safe='')} dG9rLzEyMyt4".encode()
    raw = (
        b"HTTP/1.1 200 OK\r\nX-Echo: "
        + secret.encode()
        + b"\r\n"
        + f"Content-Length: {len(echoed)}\r\n\r\n".encode()
        + echoed
    )
    server = await serve(answering(raw))

    response = await local(server).send(
        context(), get(at(server, f"/v1/{quote(secret, safe='')}?key=1"), secret_values=(secret,))
    )

    assert secret.encode() not in response.body and b"dG9rLzEyMyt4" not in response.body
    assert response.body.count(b"[secret]") == 3
    assert dict(response.headers)["x-echo"] == "[secret]"
    assert "key=1" not in response.url and quote(secret, safe="") not in response.url


async def test_the_httpx_log_line_carries_no_query_and_no_secret(
    serve: Any, caplog: pytest.LogCaptureFixture
) -> None:
    server = await serve(answering(OK))
    secret = "s3cr3t-path-token"

    with caplog.at_level(logging.INFO, logger="httpx"):
        await local(server).send(
            context(), get(at(server, f"/bot{secret}/send?api_key=abc"), secret_values=(secret,))
        )

    lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert lines, "httpx logged nothing to check"
    assert all(secret not in line and "api_key" not in line for line in lines)


async def test_an_error_the_table_does_not_know_is_not_swallowed(dns: FakeDns) -> None:
    """runtime-hardening R6.12: the ToolExecutor records it `outcome_unknown`."""

    class Exploding(FakeNetwork):
        async def connect_tcp(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
            raise LookupError("a bug")

    dns.set("api.acme.vn", [PUBLIC])

    with pytest.raises(LookupError):
        await client(ACME, network=Exploding()).send(context(), get("https://api.acme.vn/"))


# -- telemetry -----------------------------------------------------------------------------------


async def test_every_call_is_a_span_and_a_count_and_a_refusal_a_blocked_count(dns: FakeDns) -> None:
    dns.set("api.acme.vn", [PUBLIC])
    telemetry = Telemetry()
    egress = client(ACME, network=FakeNetwork(), telemetry=telemetry)

    await egress.send(context(), get("https://api.acme.vn/"))
    with pytest.raises(NotDispatchedError):
        await egress.send(context(), get("https://api.other.vn/"))

    assert telemetry.spans == ["dw.egress.request"] * 2
    assert telemetry.metrics == [
        (DW_EGRESS_REQUESTS_TOTAL, {"purpose": "http_tool", "outcome": "succeeded"}),
        (DW_EGRESS_REQUESTS_TOTAL, {"purpose": "http_tool", "outcome": "not_dispatched"}),
        (
            DW_EGRESS_BLOCKED_TOTAL,
            {"purpose": "http_tool", "reason": "egress_blocked:host_not_allowed"},
        ),
    ]


async def test_what_the_client_records_keeps_to_the_pinned_telemetry_contract(dns: FakeDns) -> None:
    """The span, its attributes and the counters' labels are all declared
    names (`dw_observability.semconv`), so an exporter keeps every one."""
    dns.set("api.acme.vn", [PUBLIC])
    recording = RecordingTelemetry()
    egress = EgressClient(
        allowed_hosts=Hosts([ACME]),
        catalogue=NoCatalogueHosts(),
        telemetry=recording,
        network=FakeNetwork(),
    )

    await egress.send(context(), get("https://api.acme.vn/"))
    with pytest.raises(NotDispatchedError):
        await egress.send(context(), get("https://api.other.vn/"))

    snapshot = load_snapshot(snapshot_path(Path(__file__).resolve().parents[5]))
    assert contract_violations(snapshot, recording) == []
    assert {name for name, _ in recording.spans} == {"dw.egress.request"}


def test_a_request_prints_none_of_its_secrets() -> None:
    request = EgressRequest(
        method="POST",
        url="https://api.acme.vn/",
        headers={"Authorization": "Bearer tok-1"},
        content=b"password=tok-2",
        secret_values=("tok-1", "tok-2"),
    )

    assert "tok-1" not in repr(request) and "tok-2" not in repr(request)
