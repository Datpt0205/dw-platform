"""Unit: the decision gate and an edited proposal (digital-worker R5.1, R5.2,
R5.4; DWK22)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import DomainError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.application.decision_gate import (
    DW_DECISION,
    AskPerson,
    Auto,
    DecisionGate,
    check_edited_proposal,
)
from dw_platform.application.digital_workers import DecisionAutonomy, DecisionLevels
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import DigitalWorker, DwConfiguration, DwPeople

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SCOPE = WorkScope(tenant_id=uuid.uuid4(), workspace_id=uuid.uuid4())
EMAIL_SCHEMA = {
    "type": "object",
    "required": ["to", "subject", "body"],
    "properties": {
        "to": {"type": "string"},
        "subject": {"type": "string", "minLength": 1},
        "body": {"type": "string"},
    },
}
PROPOSAL = {"to": "an@khach.vn", "subject": "Chào anh", "body": "Cảm ơn anh đã quan tâm."}


def worker() -> DigitalWorker:
    person = uuid.uuid4()
    return DigitalWorker(
        id=uuid.uuid4(),
        tenant_id=SCOPE.tenant_id,
        workspace_id=SCOPE.workspace_id,
        principal_user_id=uuid.uuid4(),
        configuration=DwConfiguration(
            key="lead_care",
            name="Chăm sóc lead",
            mandate="Gửi thư.",
            work_kinds=("lead.new",),
            allowed_tools=("email.send",),
            workflow_key="leadcare",
            workflow_version="1.0.0",
            parameters={},
            role_keys=frozenset({"member"}),
            decision_classes=(),
        ),
        people=DwPeople(person, person, person, person),
        state="operating",
        created_by=person,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class Levels:
    by_key: dict[str, DecisionLevels]

    async def levels(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> DecisionLevels | None:
        return self.by_key.get(key)


@dataclass
class Workers:
    found: DigitalWorker

    async def digital_worker(self, scope: WorkScope, dw_id: uuid.UUID) -> DigitalWorker | None:
        return self.found if dw_id == self.found.id else None


@dataclass
class Audit:
    appended: list[AuditEvent] = field(default_factory=list)

    async def append(self, scope: WorkScope, event: AuditEvent) -> None:
        self.appended.append(event)


def gate(dw: DigitalWorker, audit: Audit) -> DecisionGate:
    levels = Levels(
        {
            "email.send": DecisionLevels("external", False, "A3", "A2", "A4"),
            "lead.score": DecisionLevels("internal", True, "A4", "A3", "A4"),
        }
    )
    return DecisionGate(
        autonomy=DecisionAutonomy(levels),
        workers=Workers(dw),
        audit=audit,
        clock=FixedClock(NOW),
        id_generator=Uuid4Generator(),
    )


async def test_a_decision_above_its_level_opens_an_approval() -> None:
    """R5.1: `email.send` at A2 asks."""
    dw, audit = worker(), Audit()
    answer = await gate(dw, audit).check(
        SCOPE,
        dw.id,
        decision_class="email.send",
        proposal=PROPOSAL,
        proposal_schema=EMAIL_SCHEMA,
        locked_fields=["to"],
        reason="gửi thư chào",
    )
    assert isinstance(answer, AskPerson)
    assert answer.payload["approval_type"] == DW_DECISION
    assert answer.payload["effective_level"] == "A2"
    assert answer.payload["proposal"] == PROPOSAL
    assert answer.payload["locked_fields"] == ["to"]
    assert answer.payload["dw_id"] == str(dw.id)
    assert audit.appended == []


async def test_a_decision_within_its_level_is_taken_and_recorded() -> None:
    """R5.2: `lead.score` at A3 goes alone, on the record, as the principal."""
    dw, audit = worker(), Audit()
    answer = await gate(dw, audit).check(
        SCOPE,
        dw.id,
        decision_class="lead.score",
        proposal={"score": 80},
        proposal_schema={"type": "object"},
        locked_fields=[],
        reason="chấm điểm",
    )
    assert answer == Auto(effective_level="A3")
    [event] = audit.appended
    assert event.action == "dw.decision.auto"
    assert event.actor_id.value == dw.principal_user_id
    assert event.details == {"decision_class": "lead.score", "effective_level": "A3"}


async def test_an_unknown_class_asks() -> None:
    dw, audit = worker(), Audit()
    answer = await gate(dw, audit).check(
        SCOPE,
        dw.id,
        decision_class="no.such",
        proposal={},
        proposal_schema={"type": "object"},
        locked_fields=[],
        reason="x",
    )
    assert isinstance(answer, AskPerson) and answer.payload["effective_level"] == "A0"


PAYLOAD = {"proposal": PROPOSAL, "proposal_schema": EMAIL_SCHEMA, "locked_fields": ["to"]}


def test_an_edit_within_the_schema_and_the_locks_is_taken() -> None:
    check_edited_proposal(PAYLOAD, {**PROPOSAL, "body": "Nội dung đã sửa."})


@pytest.mark.parametrize(
    ("edited", "code"),
    [
        ({k: v for k, v in PROPOSAL.items() if k != "subject"}, "proposal_invalid"),
        ({**PROPOSAL, "to": "khac@khach.vn"}, "locked_field_changed"),
    ],
)
def test_an_edit_outside_the_schema_or_the_locks_is_refused(
    edited: dict[str, str], code: str
) -> None:
    """DWK22."""
    with pytest.raises(DomainError) as refused:
        check_edited_proposal(PAYLOAD, edited)
    assert refused.value.details["reason_code"] == code
