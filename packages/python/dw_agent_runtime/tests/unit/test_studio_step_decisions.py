"""The `studio.step.` handler (workflow-engine R6.2, R6.3, R6.6): the wait the
request decides, from `StepWaitLookupPort`, resolved with the decision's
shape, in the decision's transaction; no linked wait is `stale_interrupt`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from dw_agent_runtime.studio_step_decisions import (
    StudioStepDecisions,
    UnwiredStepWaitLookup,
    step_resolution,
)
from dw_agent_runtime.testing.run_waits import FakeRunWaits, FakeUnitOfWork
from dw_kernel.errors import ConfigError, ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.domain.approval import ApprovalRequest, DecisionOutcome

pytestmark = pytest.mark.unit

RUN = uuid.uuid4()


def request() -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        approval_type="studio.step.approval",
        requested_by=UserId(uuid.uuid4()),
        reason="duyệt bước",
        payload={},
    )


class Links:
    def __init__(self, found: tuple[uuid.UUID, str] | None) -> None:
        self.found = found

    async def wait_of(self, uow: Any, approval_id: uuid.UUID) -> tuple[uuid.UUID, str] | None:
        return self.found


def decided(req: ApprovalRequest, outcome: DecisionOutcome) -> Any:
    return req.decide(
        decision_id=uuid.uuid4(),
        decided_by=UserId(uuid.uuid4()),
        outcome=outcome,
        decided_at=datetime.now(UTC),
        comment="ok",
        channel="web",
    )


async def opened(waits: FakeRunWaits) -> str:
    uow = FakeUnitOfWork()
    interrupt_id = await waits.open(uow, RUN, "duyet", "", "approval")
    await uow.commit()
    waits.runs[RUN] = "waiting"
    return interrupt_id


async def test_the_decision_resolves_its_wait_and_queues_the_run() -> None:
    waits = FakeRunWaits()
    interrupt_id = await opened(waits)
    req = request()
    decision = decided(req, DecisionOutcome.APPROVED)
    uow = FakeUnitOfWork()
    await StudioStepDecisions(Links((RUN, interrupt_id)), waits).decided(
        cast(Any, uow), req, decision
    )
    await uow.commit()
    (row,) = waits.of(RUN)
    assert row.status == "resolved" and waits.runs[RUN] == "queued"
    assert row.resolution == {
        "decision": "approved",
        "approval_id": str(req.id),
        "decided_by": str(decision.decided_by.value),
        "comment": "ok",
    }


async def test_a_rejection_resolves_with_rejected() -> None:
    req = request()
    assert step_resolution(req, decided(req, DecisionOutcome.REJECTED))["decision"] == "rejected"


async def test_a_wait_no_longer_open_is_stale() -> None:
    waits = FakeRunWaits()
    interrupt_id = await opened(waits)
    waits.of(RUN)[0].status = "cancelled"
    req = request()
    with pytest.raises(ConflictError) as refused:
        await StudioStepDecisions(Links((RUN, interrupt_id)), waits).decided(
            cast(Any, FakeUnitOfWork()), req, decided(req, DecisionOutcome.APPROVED)
        )
    assert refused.value.details["reason_code"] == "stale_interrupt"


async def test_a_request_no_wait_links_to_is_stale() -> None:
    req = request()
    with pytest.raises(ConflictError) as refused:
        await StudioStepDecisions(Links(None), FakeRunWaits()).decided(
            cast(Any, FakeUnitOfWork()), req, decided(req, DecisionOutcome.APPROVED)
        )
    assert refused.value.details["reason_code"] == "stale_interrupt"


async def test_the_unwired_lookup_refuses_rather_than_guess() -> None:
    with pytest.raises(ConfigError):
        await UnwiredStepWaitLookup().wait_of(cast(Any, None), uuid.uuid4())
