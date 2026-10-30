"""Unit: a Digital Worker's run context (digital-worker R1.4, DWK2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from dw_agent_runtime.contracts import ToolDefinition
from dw_agent_runtime.digital_worker_context import run_context_for, tool_scopes
from dw_platform.domain.audit import system_actor
from dw_platform.domain.digital_worker import DigitalWorker, DwConfiguration, DwPeople

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 30, tzinfo=UTC)


def tool(name: str, *scopes: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0.0",
        description=name,
        input_schema_ref="i",
        output_schema_ref="o",
        required_scopes=frozenset(scopes),
        side_effect_level="none",
        approval_policy="never",
        timeout_seconds=10,
        max_retries=0,
        idempotent=True,
        data_classification=frozenset({"internal"}),
    )


def worker(allowed: tuple[str, ...]) -> DigitalWorker:
    person = uuid.uuid4()
    return DigitalWorker(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_user_id=uuid.uuid4(),
        configuration=DwConfiguration(
            key="lead_care",
            name="Chăm sóc lead",
            mandate="Gửi thư.",
            work_kinds=("lead.new",),
            allowed_tools=allowed,
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


def test_a_dw_run_is_the_lanes_request_acting_as_the_principal_within_its_tools() -> None:
    """DWK2: the creator held `admin.*`, the principal holds `email.send` and
    `records.read`, and the allowed tools need only `email.send`."""
    dw = worker(("email.send",))
    definitions = [tool("email.send", "email.send"), tool("records.read", "records.read")]
    run_id = uuid.uuid4()
    context = run_context_for(
        dw,
        run_id=run_id,
        membership_scopes=frozenset({"email.send", "records.read"}),
        tool_scopes=tool_scopes(definitions, dw.configuration.allowed_tools),
        plan_id="professional",
        trace_id="t",
    )
    assert context.scopes == {"email.send"}
    assert context.requested_by == system_actor("dw_work").value
    assert context.worker_id == "dw:leadcare"
    assert context.actor_id == context.run_as_principal_id == dw.principal_user_id
    assert context.run_id == run_id
    assert context.roles == frozenset()
    assert context.autonomy_ceiling == "A0"


def test_a_tool_scope_the_principal_lacks_stays_out() -> None:
    dw = worker(("email.send", "records.read"))
    definitions = [tool("email.send", "email.send"), tool("records.read", "records.read")]
    context = run_context_for(
        dw,
        run_id=uuid.uuid4(),
        membership_scopes=frozenset({"email.send"}),
        tool_scopes=tool_scopes(definitions, dw.configuration.allowed_tools),
        plan_id="professional",
        trace_id="t",
    )
    assert context.scopes == {"email.send"}
