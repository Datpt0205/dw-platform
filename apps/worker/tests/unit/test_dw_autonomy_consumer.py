"""The handler of a decided raise (digital-worker R8.6): tenancy from the
envelope, the approval from the payload, and the two refusals a retry cannot
mend reported as undeliverable. What the settlement writes is covered over
Postgres by `apps/api/tests/integration/test_dw_scorecard_autonomy.py`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_platform.application.dw_autonomy import RaiseSettlement
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.dw_autonomy import DW_AUTONOMY_RAISE_DECIDED, build_raise_handler
from dw_worker.consumers.outbox import UndeliverableEventError

pytestmark = pytest.mark.unit

TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()


class FakeSettler:
    def __init__(self, *, missing: bool = False) -> None:
        self.calls: list[tuple[WorkScope, uuid.UUID]] = []
        self.missing = missing

    async def settle_raise(self, scope: WorkScope, approval_id: uuid.UUID) -> RaiseSettlement:
        self.calls.append((scope, approval_id))
        if self.missing:
            raise NotFoundError("no decided raise of that id")
        return RaiseSettlement("raised", level="A3")


def event(payload: dict[str, object]) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        event_type=DW_AUTONOMY_RAISE_DECIDED,
        schema_version="1.0",
        aggregate_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload=payload,
    )


async def test_the_raise_is_settled_under_the_envelopes_tenant() -> None:
    settler = FakeSettler()
    approval = uuid.uuid4()

    said = await build_raise_handler(settler)(
        event({"approval_id": str(approval), "outcome": "approved", "decided_by": "x"})
    )

    assert said == "dw autonomy raise raised"
    assert settler.calls == [(WorkScope(tenant_id=TENANT, workspace_id=WORKSPACE), approval)]


async def test_a_payload_without_an_approval_is_undeliverable() -> None:
    settler = FakeSettler()

    with pytest.raises(UndeliverableEventError):
        await build_raise_handler(settler)(event({"outcome": "approved"}))
    assert settler.calls == []


async def test_a_raise_that_is_not_there_is_undeliverable() -> None:
    with pytest.raises(UndeliverableEventError):
        await build_raise_handler(FakeSettler(missing=True))(
            event({"approval_id": str(uuid.uuid4())})
        )
