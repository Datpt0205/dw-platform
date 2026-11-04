"""The handler of a decided `connections.enable` (connections-and-vault R5.12,
R5.19). Tenancy comes from the envelope and the approval from the payload;
what the settlement writes is covered over Postgres by
`apps/api/tests/integration/test_connections_api.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.connections import CONNECTIONS_ENABLE_DECIDED, build_enable_handler
from dw_worker.consumers.outbox import UndeliverableEventError

pytestmark = pytest.mark.unit

TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()


class FakeSettler:
    def __init__(self, *, missing: bool = False, outcome: str = "not_disabled") -> None:
        self.calls: list[tuple[WorkScope, uuid.UUID]] = []
        self.missing = missing
        self.outcome = outcome

    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> str:
        self.calls.append((scope, approval_id))
        if self.missing:
            raise NotFoundError("no decided connections.enable approval of that id")
        return self.outcome


def _event(payload: dict[str, object]) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        event_type=CONNECTIONS_ENABLE_DECIDED,
        schema_version="1.0",
        aggregate_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload=payload,
    )


def test_the_event_is_the_approval_flows_announcement() -> None:
    assert CONNECTIONS_ENABLE_DECIDED == "connections.enable.decided"


@pytest.mark.parametrize("outcome", ["enabled", "not_disabled", "stale", "gone", "rejected"])
async def test_every_settlement_ends_without_error_under_the_envelopes_tenant(
    outcome: str,
) -> None:
    """R5.12, R5.19: a replay or a stale request is nothing to retry."""
    settler = FakeSettler(outcome=outcome)
    approval = uuid.uuid4()

    said = await build_enable_handler(settler)(_event({"approval_id": str(approval)}))

    assert said == f"connection enable {outcome}"
    assert settler.calls == [(WorkScope(tenant_id=TENANT, workspace_id=WORKSPACE), approval)]


@pytest.mark.parametrize("payload", [{}, {"approval_id": "not-a-uuid"}])
async def test_a_payload_that_names_no_approval_is_undeliverable(
    payload: dict[str, object],
) -> None:
    with pytest.raises(UndeliverableEventError):
        await build_enable_handler(FakeSettler())(_event(payload))


async def test_an_approval_that_is_not_there_is_undeliverable() -> None:
    with pytest.raises(UndeliverableEventError):
        await build_enable_handler(FakeSettler(missing=True))(
            _event({"approval_id": str(uuid.uuid4())})
        )
