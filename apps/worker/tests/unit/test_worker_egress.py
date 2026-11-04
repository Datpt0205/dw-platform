"""The worker's egress client and the handler of a decided Allowed host
(connections-and-vault R3.2, R3.11, R3.20).

The builder sets `allow_private` and `require_https` from the profile alone,
as the API's does. The handler takes tenancy from the envelope and the
approval from the payload; what the settlement writes is covered over Postgres
by `apps/api/tests/integration/test_egress_allowed_hosts.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_observability.telemetry import NullTelemetry
from dw_platform.application.egress_allowlist import AllowedHostSettlement
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.composition import build_egress_client
from dw_worker.consumers.egress_allowlist import (
    EGRESS_ALLOWED_HOST_DECIDED,
    build_allowed_host_handler,
)
from dw_worker.consumers.outbox import UndeliverableEventError
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit

TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()


def _settings(profile: str) -> WorkerSettings:
    if profile not in ("uat", "production"):
        return WorkerSettings(profile=profile)  # type: ignore[arg-type]
    return WorkerSettings(
        profile=profile,  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://u:p@db/dw",
        embedding_provider="openai_compatible",
        qdrant_url="https://qdrant.example:6333",
        qdrant_api_key="unit-test-qdrant-key",
        unsubscribe_signing_secret="unit-test-unsubscribe-secret-0123456789",
    )


@pytest.mark.parametrize(
    ("profile", "private", "https"),
    [
        ("uat", False, True),
        ("production", False, True),
        ("local", True, False),
        ("test", True, False),
    ],
)
def test_the_profile_alone_sets_both(profile: str, private: bool, https: bool) -> None:
    client = build_egress_client(_settings(profile), async_sessionmaker(), NullTelemetry())
    assert (client.allow_private, client.require_https) == (private, https)


class FakeSettler:
    def __init__(self, *, missing: bool = False) -> None:
        self.calls: list[tuple[WorkScope, uuid.UUID]] = []
        self.missing = missing

    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> AllowedHostSettlement:
        self.calls.append((scope, approval_id))
        if self.missing:
            raise NotFoundError("no decided allowed-host approval of that id")
        return AllowedHostSettlement("already_present")


def _event(payload: dict[str, object]) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        event_type=EGRESS_ALLOWED_HOST_DECIDED,
        schema_version="1.0",
        aggregate_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload=payload,
    )


def test_the_event_is_the_approval_flows_announcement() -> None:
    assert EGRESS_ALLOWED_HOST_DECIDED == "egress.allowed_host.decided"


async def test_a_replay_ends_without_error_under_the_envelopes_tenant() -> None:
    """R3.11: nothing to retry, so the outbox does not."""
    settler = FakeSettler()
    approval = uuid.uuid4()

    said = await build_allowed_host_handler(settler)(_event({"approval_id": str(approval)}))

    assert said == "egress allowed host already_present"
    assert settler.calls == [(WorkScope(tenant_id=TENANT, workspace_id=WORKSPACE), approval)]


@pytest.mark.parametrize("payload", [{}, {"approval_id": "not-a-uuid"}])
async def test_a_payload_that_names_no_approval_is_undeliverable(
    payload: dict[str, object],
) -> None:
    with pytest.raises(UndeliverableEventError):
        await build_allowed_host_handler(FakeSettler())(_event(payload))


async def test_an_approval_that_is_not_there_is_undeliverable() -> None:
    with pytest.raises(UndeliverableEventError):
        await build_allowed_host_handler(FakeSettler(missing=True))(
            _event({"approval_id": str(uuid.uuid4())})
        )
