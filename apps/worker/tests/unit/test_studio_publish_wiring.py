"""The worker's half of a two-person publication (agent-lifecycle ticket 04,
step 2): every kind of its `ArtifactKindRegistry` has a `.decided` handler
and a decision guard on the chat decision door, both by a loop over the
registry; the door's strict prefixes carry `studio.publish.`; the handler
hands the settler the envelope's tenant and turns a missing request into an
undeliverable event."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.approval_flow import RuleGuard
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_observability.telemetry import NullTelemetry
from dw_platform.application.approval_codes import ApprovalSubjectVersions
from dw_platform.domain.approval import decided_event_type
from dw_platform.domain.outbox import OutboxEvent
from dw_studio.lifecycle.application.publish import PUBLISH_PREFIX, require_not_author
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError
from dw_worker.consumers.studio_publish import build_publish_decided_handler
from dw_worker.main import build_channel_decision_command, register_studio_publish
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit

_SESSIONS = cast(async_sessionmaker[AsyncSession], object())


@dataclasses.dataclass
class _Runner:
    run_store: Any = dataclasses.field(default_factory=object)
    telemetry: Any = dataclasses.field(default_factory=NullTelemetry)
    run_graphs: Any = None
    run_control: Any = dataclasses.field(default_factory=OpenRunControl)


def _decided_types(kinds: Any) -> set[str]:
    return {decided_event_type(f"studio.publish.{kind}") for kind in kinds}


@pytest.mark.parametrize("kinds", [None, FIXTURE_KINDS])
def test_every_kind_of_the_registry_has_its_decided_handler(kinds: Any) -> None:
    """`None` is the running worker's `platform_kinds(...)`; a test's kinds
    reach it through `kinds=` alone."""
    handlers: dict[str, EventHandler] = {}
    registry = register_studio_publish(
        handlers,
        _SESSIONS,
        run_control=OpenRunControl(),
        clock=SystemClock(),
        ids=Uuid4Generator(),
        kinds=kinds,
    )
    expected = {"object", "workflow", "agent"} if kinds is None else {"fixture", "fixture_gateless"}
    assert registry.kinds == expected
    assert set(handlers) == _decided_types(registry.kinds)


@pytest.mark.parametrize("kinds", [None, FIXTURE_KINDS])
def test_the_chat_decision_door_guards_every_kind_and_is_strict(kinds: Any) -> None:
    command = build_channel_decision_command(
        WorkerSettings.model_validate({"approval_code_secret": "a-code-secret-of-32-bytes-or-so"}),
        _SESSIONS,
        runner=cast(LangGraphWorkflowRunner, _Runner()),
        subjects=ApprovalSubjectVersions(),
        ids=Uuid4Generator(),
        clock=SystemClock(),
        studio_kinds=kinds,
    )
    flow = command.service.approval_flow
    expected = {"object", "workflow", "agent"} if kinds is None else {"fixture", "fixture_gateless"}
    publish = {k: g for k, g in flow.decision_guards.items() if k.startswith(PUBLISH_PREFIX)}
    assert set(publish) == {f"studio.publish.{kind}" for kind in expected}
    assert all(
        isinstance(guard, RuleGuard) and guard.rule is require_not_author
        for guard in publish.values()
    )
    assert PUBLISH_PREFIX in flow.strict_approval_prefixes
    assert flow.is_strict("studio.publish.object")


@dataclasses.dataclass
class _Settler:
    seen: list[tuple[uuid.UUID, uuid.UUID]] = dataclasses.field(default_factory=list)
    missing: bool = False

    async def settle(self, tenant_id: uuid.UUID, approval_id: uuid.UUID) -> str:
        self.seen.append((tenant_id, approval_id))
        if self.missing:
            raise NotFoundError("no decided publish request of that id")
        return "published"


def _event(payload: dict[str, object]) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        event_type="studio.publish.object.decided",
        schema_version="1.0",
        aggregate_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload=payload,
    )


async def test_the_handler_takes_the_tenant_from_the_envelope() -> None:
    settler = _Settler()
    approval = uuid.uuid4()
    event = _event({"approval_id": str(approval), "tenant_id": str(uuid.uuid4())})
    assert await build_publish_decided_handler(settler)(event) == "studio publish published"
    assert settler.seen == [(event.tenant_id.value, approval)]


async def test_a_missing_request_or_a_bad_payload_is_undeliverable() -> None:
    with pytest.raises(UndeliverableEventError):
        await build_publish_decided_handler(_Settler(missing=True))(
            _event({"approval_id": str(uuid.uuid4())})
        )
    with pytest.raises(UndeliverableEventError):
        await build_publish_decided_handler(_Settler())(_event({"approval_id": "nope"}))
