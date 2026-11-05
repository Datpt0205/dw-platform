"""The reader of `studio.run.dead_lettered` and the binding review the worker
holds until workflow-triggers/03 (workflow-engine/04: R5.19, R5.25, R5.26).
Delivered on PostgreSQL: `dw_studio`'s `test_studio_run_lane.py`."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from dw_kernel.errors import InfrastructureError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_platform.adapters.persistence.tenant_session import TenantScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import UndeliverableEventError
from dw_worker.consumers.studio_runs import (
    DEAD_LETTERED,
    UnwiredBindingReview,
    build_dead_letter_handler,
)

pytestmark = pytest.mark.unit


@dataclass
class Holders:
    by_workspace: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    asked: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    async def tenant_depth_holders(
        self, tenant_id: uuid.UUID, key: str
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        self.asked.append((tenant_id, key))
        return self.by_workspace


@dataclass
class Inbox:
    sent: list[tuple[TenantScope, list[uuid.UUID], str]] = field(default_factory=list)

    async def deliver_in(
        self,
        scope: TenantScope,
        *,
        recipients: Sequence[uuid.UUID],
        source_key: str,
        title: str,
        body: str,
        link: str | None,
    ) -> None:
        self.sent.append((scope, list(recipients), source_key))


def event(**payload: Any) -> OutboxEvent:
    run_id, workspace, tenant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    body = {
        "run_id": str(run_id),
        "workspace_id": str(workspace),
        "requested_by": str(uuid.uuid4()),
        "trigger_kind": "manual",
    }
    body.update(payload)
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(tenant),
        workspace_id=WorkspaceId(workspace),
        event_type=DEAD_LETTERED,
        schema_version="1",
        aggregate_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=body,
    )


async def test_r5_26_each_holder_at_their_anchor_and_the_requester_in_the_runs_workspace() -> None:
    anchor, holder = uuid.uuid4(), uuid.uuid4()
    holders, inbox = Holders({anchor: [holder]}), Inbox()
    dead = event()
    await build_dead_letter_handler(holders, inbox)(dead)
    key = f"{DEAD_LETTERED}:{dead.aggregate_id}"
    assert holders.asked == [(dead.tenant_id.value, "platform.members.write")]
    assert inbox.sent == [
        (TenantScope(dead.tenant_id.value, anchor), [holder], key),
        (
            TenantScope(dead.tenant_id.value, dead.workspace_id.value),
            [uuid.UUID(str(dead.payload["requested_by"]))],
            key,
        ),
    ]


@pytest.mark.parametrize("field_", ["run_id", "workspace_id"])
async def test_r5_26_a_payload_naming_another_run_or_workspace_than_its_envelope_is_refused(
    field_: str,
) -> None:
    inbox = Inbox()
    with pytest.raises(UndeliverableEventError):
        await build_dead_letter_handler(Holders(), inbox)(event(**{field_: str(uuid.uuid4())}))
    assert inbox.sent == []


async def test_r5_25_the_unwired_binding_review_never_lets_a_triggers_run_through() -> None:
    with pytest.raises(InfrastructureError):
        await UnwiredBindingReview().review(cast(Any, object()))
