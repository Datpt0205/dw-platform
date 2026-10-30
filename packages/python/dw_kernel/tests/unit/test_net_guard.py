"""Outbound URL guard fails closed on private/invalid destinations."""

from __future__ import annotations

import pytest

from dw_kernel.net_guard import OutboundUrlError, ensure_allowed_outbound_url

pytestmark = pytest.mark.unit


def test_rejects_non_http_schemes() -> None:
    for url in ("ftp://example.com", "file:///etc/passwd", "gopher://x", "not-a-url"):
        with pytest.raises(OutboundUrlError):
            ensure_allowed_outbound_url(url)


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(OutboundUrlError, match="credentials"):
        ensure_allowed_outbound_url("https://user:pass@api.example.com/v1")


def test_rejects_loopback_and_private_addresses_by_default() -> None:
    for url in (
        "http://127.0.0.1:11434/v1",
        "http://localhost:8080",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "http://10.0.0.5/internal",
        "http://192.168.1.10",
        "http://0.0.0.0:9000",
    ):
        with pytest.raises(OutboundUrlError, match=r"private|resolve"):
            ensure_allowed_outbound_url(url)


def test_allow_private_permits_local_dev_providers() -> None:
    url = "http://localhost:11434/v1"
    assert ensure_allowed_outbound_url(url, allow_private=True) == url


def test_explicit_allowlist_bypasses_the_private_check() -> None:
    url = "http://localhost:11434/v1"
    assert ensure_allowed_outbound_url(url, allowed_hosts=("localhost",)) == url


def test_unresolvable_host_is_rejected() -> None:
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url("https://definitely-not-a-real-host.invalid")


def test_a_host_that_cannot_be_encoded_is_refused_rather_than_raising() -> None:
    """`getaddrinfo` IDNA-encodes first, and that step does not raise `gaierror`.

    A label over 63 characters raises `UnicodeError`, which is not an `OSError`
    and so escaped this guard: a scraped link with a malformed host propagated
    out of the fetcher and killed the run that read it.
    """
    too_long = "a" * 64
    with pytest.raises(OutboundUrlError, match="resolvable"):
        ensure_allowed_outbound_url(f"https://{too_long}.example.com/path")


def test_an_empty_label_is_refused_the_same_way() -> None:
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url("https://example..com/path")


def _resolving_to(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    """A resolver that answers every name with `address`."""
    import socket

    family = socket.AF_INET6 if ":" in address else socket.AF_INET

    def fake(host: str, port: object, *args: object, **kwargs: object) -> list[object]:
        return [(family, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.1",  # shared address space (CGNAT)
        "100.100.100.200",  # a cloud metadata address in that space
        "224.0.0.1",  # multicast
        "ff02::1",
        "::ffff:169.254.169.254",  # IPv4-mapped
        "64:ff9b::a9fe:a9fe",  # NAT64: Python calls it global
        "2002:a9fe:a9fe::1",  # 6to4
        "2001:0:4136:e378:8000:63bf:5601:5601",  # Teredo, client 169.254.169.254
    ],
)
def test_an_address_that_is_not_global_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    """runtime-hardening R7.2 (RH21)."""
    _resolving_to(monkeypatch, address)
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url("https://models.example.com/v1")


def test_a_global_address_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    for address in ("8.8.8.8", "::ffff:8.8.8.8", "64:ff9b::808:808"):
        _resolving_to(monkeypatch, address)
        url = "https://models.example.com/v1"
        assert ensure_allowed_outbound_url(url) == url


def test_allow_private_never_lets_link_local_or_metadata_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7.2: the dev flag lifts private and loopback, not the metadata address."""
    for address in ("169.254.169.254", "fe80::1", "64:ff9b::a9fe:a9fe", "224.0.0.1"):
        _resolving_to(monkeypatch, address)
        with pytest.raises(OutboundUrlError):
            ensure_allowed_outbound_url("http://models.example.com/v1", allow_private=True)
    _resolving_to(monkeypatch, "10.0.0.5")
    url = "http://models.example.com/v1"
    assert ensure_allowed_outbound_url(url, allow_private=True) == url


def test_an_allow_listed_name_passes_by_its_whole_name_without_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("an allow-listed host must not be resolved")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    url = "http://Ollama.Internal:11434/v1"
    assert ensure_allowed_outbound_url(url, allowed_hosts=("ollama.internal",)) == url
    _resolving_to(monkeypatch, "10.0.0.5")
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url(
            "http://evil-ollama.internal/v1", allowed_hosts=("ollama.internal",)
        )


def test_an_ip_literal_is_judged_without_a_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("an IP literal must not be resolved")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url("http://[64:ff9b::a9fe:a9fe]/latest")
    assert ensure_allowed_outbound_url("http://8.8.8.8/") == "http://8.8.8.8/"


def test_an_unresolvable_name_is_refused_only_in_a_deployed_profile() -> None:
    url = "https://definitely-not-a-real-host.invalid/v1"
    assert ensure_allowed_outbound_url(url, allow_private=True) == url
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url(url)
