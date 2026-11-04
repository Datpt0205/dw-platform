"""The API's egress client, as its composition root sets it
(connections-and-vault R3.2, R3.7, R3.20; CV7, CV19, CV29).

`allow_private` and `require_https` come from the profile and nothing else;
the operator's `outbound_allowed_hosts` is not the company's list and admits
nothing to egress.
"""

from __future__ import annotations

import socket
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_dev_endpoints import deployed_settings

from dw_api.bootstrap.egress import build_egress_client
from dw_api.settings import ApiSettings
from dw_connectors.egress import EgressClient, EgressContext, EgressRequest
from dw_kernel.dispatch import NotDispatchedError
from dw_observability.telemetry import NullTelemetry

pytestmark = pytest.mark.unit

CONTEXT = EgressContext(
    tenant_id=uuid.UUID(int=1),
    workspace_id=uuid.UUID(int=2),
    run_id=None,
    run_mode="live",
    purpose="http_tool",
)


@dataclass(frozen=True)
class Rule:
    host_pattern: str
    ports: tuple[int, ...] = (443,)
    purpose: str = "http_tool"


class Hosts:
    def __init__(self, *rules: Rule) -> None:
        self.rules = list(rules)

    async def live(self, tenant_id: uuid.UUID) -> list[Rule]:
        return self.rules


def _build(settings: ApiSettings) -> EgressClient:
    return build_egress_client(settings, async_sessionmaker(), NullTelemetry())


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_deployed_no_private_address_and_only_https(profile: str) -> None:
    client = _build(deployed_settings(profile))
    assert (client.allow_private, client.require_https) == (False, True)


@pytest.mark.parametrize("profile", ["local", "test"])
def test_outside_a_deployed_profile_both_are_open(profile: str) -> None:
    client = _build(ApiSettings(profile=profile))  # type: ignore[arg-type]
    assert (client.allow_private, client.require_https) == (True, False)


async def test_deployed_a_listed_host_that_answers_a_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.2 (CV7): the deployed client, not a hand-built one."""

    def private(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", private)
    client = _build(deployed_settings())
    client.allowed_hosts = Hosts(Rule("api.acme.vn"))

    with pytest.raises(NotDispatchedError) as refused:
        await client.send(CONTEXT, EgressRequest("GET", "https://api.acme.vn/"))

    assert refused.value.details["reason_code"] == "egress_blocked:address"


async def test_the_operators_outbound_hosts_admit_nothing_to_egress() -> None:
    """R3.7 (CV19): a host the operator's list names, off the company's list."""
    settings = deployed_settings().model_copy(update={"outbound_allowed_hosts": ["api.vendor.vn"]})
    client = _build(settings)
    client.allowed_hosts = Hosts()

    with pytest.raises(NotDispatchedError) as refused:
        await client.send(CONTEXT, EgressRequest("GET", "https://api.vendor.vn/"))

    assert refused.value.details["reason_code"] == "egress_blocked:host_not_allowed"
