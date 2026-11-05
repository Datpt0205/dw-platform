"""The Studio run queue's worker pieces (workflow-engine/04: R5.7, R5.19, R5.25,
R5.26).

- `build_dead_letter_handler`: the reader of `studio.run.dead_lettered`, which
  `studio_run_reaper` writes with the dead letter (failure-modes #1). One
  in-app notice keyed `studio.run.dead_lettered:<run_id>` to each person
  holding `platform.members.write` at tenant depth, in the workspace their
  holding is anchored at, and to the run's `requested_by` in the run's
  workspace when that is a member there (a lane's actor is no member, and
  `platform.deliver_notification` drops a non-member). At least once, like
  every handler: the inbox's UNIQUE `(recipient_user_id, source_key)` makes a
  second delivery of the event add nothing.
- `UnwiredBindingReview`: the `BindingReviewPort` until workflow-triggers/03
  answers it. It cannot say a binding is approved, so it says nothing: every
  trigger's run is held as a broken port holds it (R5.25), never let through.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_agent_runtime.ports import BindingHold, StudioRun
from dw_kernel.errors import InfrastructureError
from dw_platform.adapters.persistence.tenant_session import TenantScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = [
    "DEAD_LETTERED",
    "UnwiredBindingReview",
    "build_dead_letter_handler",
]

DEAD_LETTERED = "studio.run.dead_lettered"
_RECIPIENT_KEY = "platform.members.write"
_TITLE = "Một lượt chạy đã dừng hẳn sau nhiều lần lỗi"
_BODY = (
    "Lượt chạy bị dừng vì tiến trình chạy nó lỗi năm lần liên tiếp. "
    "Lượt không được chạy lại tự động; hãy xem lượt chạy và quy trình của nó."
)
_LINK = "/studio/workflows"


class TenantDepthHoldersPort(Protocol):
    async def tenant_depth_holders(
        self, tenant_id: uuid.UUID, key: str
    ) -> dict[uuid.UUID, list[uuid.UUID]]: ...


class ScopedDeliveryPort(Protocol):
    async def deliver_in(
        self,
        scope: TenantScope,
        *,
        recipients: Sequence[uuid.UUID],
        source_key: str,
        title: str,
        body: str,
        link: str | None,
    ) -> None: ...


class _DeadLetteredPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: uuid.UUID
    workspace_id: uuid.UUID
    requested_by: uuid.UUID


def build_dead_letter_handler(
    holders: TenantDepthHoldersPort, notifications: ScopedDeliveryPort
) -> EventHandler:
    """The handler to wire under `DEAD_LETTERED`."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _DeadLetteredPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        if payload.run_id != event.aggregate_id:
            raise UndeliverableEventError("the payload names another run than its envelope")
        if payload.workspace_id != event.workspace_id.value:
            raise UndeliverableEventError("the payload names another workspace than its envelope")
        # The tenant from the envelope, which the database tagged.
        tenant_id = event.tenant_id.value
        source_key = f"{DEAD_LETTERED}:{payload.run_id}"
        by_workspace = await holders.tenant_depth_holders(tenant_id, _RECIPIENT_KEY)
        for workspace_id, people in sorted(by_workspace.items(), key=lambda i: str(i[0])):
            await notifications.deliver_in(
                TenantScope(tenant_id=tenant_id, workspace_id=workspace_id),
                recipients=people,
                source_key=source_key,
                title=_TITLE,
                body=_BODY,
                link=_LINK,
            )
        await notifications.deliver_in(
            TenantScope(tenant_id=tenant_id, workspace_id=payload.workspace_id),
            recipients=[payload.requested_by],
            source_key=source_key,
            title=_TITLE,
            body=_BODY,
            link=_LINK,
        )
        told = sum(len(people) for people in by_workspace.values())
        return f"dead-lettered run {payload.run_id}: {told} holders told"

    return handle


class UnwiredBindingReview:
    """Satisfies `BindingReviewPort` by refusing to answer (see module)."""

    async def review(self, run: StudioRun) -> BindingHold | None:
        raise InfrastructureError(
            "no binding review is wired in this process",
            details={"reason_code": "binding_review_unwired"},
        )
