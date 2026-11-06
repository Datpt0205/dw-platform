"""The handler of every `studio.step.` decision (workflow-engine R6.2, R6.3,
R6.6; ADR-0112 decision 7).

A Studio step's approval request carries no `approval_requests.run_id`: its
link to the run is workflow-nodes/06's `studio.step_approvals`, asked through
`StepWaitLookupPort`. So `ApproveAndResumeService.decide` takes the run-less
path, and this handler, registered by the prefix in `decided_handlers` at
both composition roots, resolves the wait and queues the run in the decision's
own transaction: no resume on the decider's HTTP request, and no outbox event
nobody reads. A wait no longer open, or a run no longer waiting, refuses the
decision (`stale_interrupt`, 409), which rolls it back.

`resolution` is the shape `human.approval@2` reads (workflow-nodes/06):
`{decision, approval_id, decided_by, comment}`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from dw_agent_runtime.ports import RunWaitPort, StepWaitLookupPort
from dw_kernel.errors import ConfigError, ConflictError
from dw_platform.application.ports import PlatformUnitOfWork
from dw_platform.domain.approval import ApprovalDecision, ApprovalRequest, DecisionOutcome

STUDIO_STEP_PREFIX: Final = "studio.step."


def step_resolution(request: ApprovalRequest, decision: ApprovalDecision) -> dict[str, Any]:
    """What the waiting step resumes with: the decision and who made it,
    from the decision row, never from the request's payload."""
    return {
        "decision": "approved" if decision.outcome is DecisionOutcome.APPROVED else "rejected",
        "approval_id": str(request.id),
        "decided_by": str(decision.decided_by.value),
        "comment": decision.comment,
    }


@dataclass(frozen=True)
class StudioStepDecisions:
    lookup: StepWaitLookupPort
    waits: RunWaitPort

    async def decided(
        self, uow: PlatformUnitOfWork, request: ApprovalRequest, decision: ApprovalDecision
    ) -> None:
        found = await self.lookup.wait_of(uow, request.id)
        if found is None:
            raise ConflictError(
                "no wait of a run is linked to this approval request",
                details={"reason_code": "stale_interrupt", "approval_id": str(request.id)},
            )
        run_id, interrupt_id = found
        await self.waits.resolve(uow, run_id, interrupt_id, step_resolution(request, decision))


@dataclass(frozen=True)
class UnwiredStepWaitLookup:
    """The lookup until workflow-nodes/06 builds `studio.step_approvals`, which
    satisfies it: no `studio.step.` request exists before then, and one that
    did is refused, never resolved on a guess."""

    async def wait_of(self, uow: PlatformUnitOfWork, approval_id: UUID) -> tuple[UUID, str] | None:
        raise ConfigError(
            "no step approval is linked to a wait yet",
            details={"reason": "step_waits_unwired", "approval_id": str(approval_id)},
        )
