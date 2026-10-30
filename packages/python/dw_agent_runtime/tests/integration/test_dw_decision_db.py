"""Integration: deciding a Digital Worker's decision, and its boundary, on real PostgreSQL.

digital-worker ticket 02: R5.3 (DWK15, only the DW's Validator or Business
Owner as they are when deciding), R5.4 (DWK22, an edit within the proposal's
schema and locks), R5.5 (an approved edit is on the decision row). The
approval here has no run, so the decision is announced on the outbox instead
of resuming one; the admission and the edit are checked before either.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import pytest
import sqlalchemy as sa
from runtime_harness import RuntimeUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.digital_workers_repo import SqlDwBoundary
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.decision_gate import (
    DW_DECISION,
    DwDecisionAdmission,
    check_edited_proposal,
)

pytestmark = pytest.mark.integration

SCHEMA = {
    "type": "object",
    "required": ["to", "subject", "body"],
    "properties": {"to": {"type": "string"}, "subject": {"type": "string"}},
}
PROPOSAL = {"to": "an@khach.vn", "subject": "Chào anh", "body": "Cảm ơn anh."}


@dataclass
class World:
    tenant: uuid.UUID
    workspace: uuid.UUID
    dw: uuid.UUID
    owner: uuid.UUID
    validator: uuid.UUID
    outsider: uuid.UUID


@pytest.fixture
async def engines(urls: RuntimeUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(urls.migrator, poolclass=NullPool)
    app = create_async_engine(urls.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


async def seed(migrator: AsyncEngine) -> World:
    t, w, owner, validator, outsider, principal, dw = (uuid.uuid4() for _ in range(7))
    async with migrator.begin() as conn:
        for sql, values in (
            (
                "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)",
                {"t": t, "s": f"dwd-{t.hex[:12]}"},
            ),
            (
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'main', 'main')",
                {"w": w, "t": t},
            ),
        ):
            await conn.execute(sa.text(sql), values)
        for user in (owner, validator, outsider):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'p')"
                ),
                {"u": user, "s": f"dwd-{user}"},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys) VALUES (:i, :t, :w, :u, '[\"approver\"]'::jsonb)"
                ),
                {"i": uuid.uuid4(), "t": t, "w": w, "u": user},
            )
        for sql, values in (
            (
                "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                " VALUES (:u, :s, 'dw', 'service', :t)",
                {"u": principal, "s": f"service:{principal}", "t": t},
            ),
            (
                "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
                " name, owner_user_id) VALUES (:u, :t, :w, 'dw', :o)",
                {"u": principal, "t": t, "w": w, "o": owner},
            ),
            (
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                " role_keys) VALUES (:i, :t, :w, :u, '[\"member\"]'::jsonb)",
                {"i": uuid.uuid4(), "t": t, "w": w, "u": principal},
            ),
            (
                "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
                " principal_user_id, key, name, mandate, work_kinds, allowed_tools, workflow_key,"
                " workflow_version, state, technical_owner_id, work_assigner_id, validator_id,"
                " created_by) VALUES (:d, :t, :w, :u, 'dec_dw', 'dw', 'dw', ARRAY['lead.new'],"
                " ARRAY[]::text[], 'leadcare', '1.0.0', 'operating', :o, :o, :v, :o)",
                {"d": dw, "t": t, "w": w, "u": principal, "o": owner, "v": validator},
            ),
        ):
            await conn.execute(sa.text(sql), values)
    return World(t, w, dw, owner, validator, outsider)


async def open_decision(migrator: AsyncEngine, world: World) -> uuid.UUID:
    approval = uuid.uuid4()
    payload = {
        "dw_id": str(world.dw),
        "decision_class": "email.send",
        "effective_level": "A2",
        "proposal": PROPOSAL,
        "proposal_schema": SCHEMA,
        "locked_fields": ["to"],
    }
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, payload) VALUES (:a, :t, :w, :type, :r,"
                " CAST(:p AS jsonb))"
            ),
            {
                "a": approval,
                "t": world.tenant,
                "w": world.workspace,
                "type": DW_DECISION,
                "r": world.dw,
                "p": json.dumps(payload),
            },
        )
    return approval


def flow(app: AsyncEngine) -> ApproveAndResumeService:
    return ApproveAndResumeService(
        uow_factory=SqlPlatformUnitOfWorkFactory(async_sessionmaker(app, expire_on_commit=False)),
        runner=cast(Any, None),
        run_store=cast(Any, None),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
        type_admissions={DW_DECISION: DwDecisionAdmission()},
        proposal_editors={DW_DECISION: check_edited_proposal},
    )


def as_person(world: World, user: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=world.tenant,
        workspace_id=world.workspace,
        principal_id=user,
        roles=frozenset({"approver"}),
        scopes=frozenset({"approvals.read", "approvals.decide"}),
        plan_id="professional",
    )


async def decide(
    app: AsyncEngine, world: World, approval: uuid.UUID, user: uuid.UUID, **kw: Any
) -> Any:
    return await flow(app).decide(
        approval_id=approval,
        approve=kw.pop("approve", True),
        comment=kw.pop("comment", ""),
        context=as_person(world, user),
        authorization=ScopeAuthorizationService(),
        **kw,
    )


async def decisions(migrator: AsyncEngine, approval: uuid.UUID) -> list[Any]:
    async with migrator.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT decided_by, edited, edited_payload FROM platform.approval_decisions"
                        " WHERE request_id = :a"
                    ),
                    {"a": approval},
                )
            ).all()
        )


async def test_only_the_dws_validator_or_owner_decides(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """DWK15: a holder of `approvals.decide` outside the DW is refused; the
    Business Owner may."""
    migrator, app = engines
    world = await seed(migrator)
    approval = await open_decision(migrator, world)
    with pytest.raises(ConflictError) as refused:
        await decide(app, world, approval, world.outsider)
    assert refused.value.details["reason_code"] == "not_eligible_decider"
    assert await decisions(migrator, approval) == []

    decided = await decide(app, world, approval, world.owner)
    assert decided.status.value == "approved"


async def test_a_replaced_validator_no_longer_decides(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """DWK15: read when deciding, not when the approval was opened."""
    migrator, app = engines
    world = await seed(migrator)
    approval = await open_decision(migrator, world)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.digital_workers SET validator_id = :o WHERE id = :d"),
            {"o": world.outsider, "d": world.dw},
        )
    with pytest.raises(ConflictError):
        await decide(app, world, approval, world.validator)
    assert await decisions(migrator, approval) == []
    await decide(app, world, approval, world.outsider)
    assert len(await decisions(migrator, approval)) == 1


async def test_an_approved_edit_is_on_the_decision_row(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R5.5, D18 "Sửa rồi duyệt"."""
    migrator, app = engines
    world = await seed(migrator)
    approval = await open_decision(migrator, world)
    edited = {**PROPOSAL, "body": "Nội dung đã sửa."}
    await decide(app, world, approval, world.validator, edited_proposal=edited)
    [row] = await decisions(migrator, approval)
    assert (row.decided_by, row.edited, row.edited_payload) == (world.validator, True, edited)


@pytest.mark.parametrize(
    ("edited", "approve", "code"),
    [
        ({k: v for k, v in PROPOSAL.items() if k != "subject"}, True, "proposal_invalid"),
        ({**PROPOSAL, "to": "khac@khach.vn"}, True, "locked_field_changed"),
        ({**PROPOSAL, "body": "x"}, False, "proposal_not_editable"),
    ],
)
async def test_an_edit_outside_its_rules_decides_nothing(
    engines: tuple[AsyncEngine, AsyncEngine], edited: dict[str, str], approve: bool, code: str
) -> None:
    """DWK22, and an edit sent with a rejection."""
    migrator, app = engines
    world = await seed(migrator)
    approval = await open_decision(migrator, world)
    with pytest.raises(DomainError) as refused:
        await decide(
            app,
            world,
            approval,
            world.validator,
            approve=approve,
            comment="không",
            edited_proposal=edited,
        )
    assert refused.value.details["reason_code"] == code
    assert await decisions(migrator, approval) == []
    async with migrator.connect() as conn:
        status = (
            await conn.execute(
                sa.text("SELECT status FROM platform.approval_requests WHERE id = :a"),
                {"a": approval},
            )
        ).scalar_one()
    assert status == "pending"


async def test_the_boundary_is_read_live_and_a_refusal_is_a_refused_row(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6 on the real tables: the boundary follows the DW's state and its
    principal's membership as they change; a `refused` row carries no key."""
    migrator, app = engines
    world = await seed(migrator)
    async with migrator.connect() as conn:
        principal = (
            await conn.execute(
                sa.text("SELECT principal_user_id FROM platform.digital_workers WHERE id = :d"),
                {"d": world.dw},
            )
        ).scalar_one()
    port = SqlDwBoundary(async_sessionmaker(app, expire_on_commit=False))

    async def read() -> Any:
        return await port.boundary(
            tenant_id=world.tenant, workspace_id=world.workspace, principal_id=principal
        )

    first = await read()
    assert first is not None and first.operating and "approvals.read" in first.scopes
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.memberships SET role_keys = '[]'::jsonb WHERE user_id = :u"),
            {"u": principal},
        )
        await conn.execute(
            sa.text("UPDATE platform.digital_workers SET state = 'paused' WHERE id = :d"),
            {"d": world.dw},
        )
    second = await read()
    assert second is not None and not second.operating and second.scopes == frozenset()
    assert (
        await port.boundary(
            tenant_id=world.tenant, workspace_id=uuid.uuid4(), principal_id=principal
        )
        is None
    )

    insert = (
        "INSERT INTO platform.tool_executions (id, tenant_id, workspace_id, tool_name,"
        " tool_version, status, idempotency_key, input_hash, started_at)"
        " VALUES (:i, :t, :w, 'email.send', '1.0.0', 'refused', :k, 'h', now())"
    )
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(insert), {"i": uuid.uuid4(), "t": world.tenant, "w": world.workspace, "k": None}
        )
    with pytest.raises(sa.exc.IntegrityError, match="ck_tool_executions_refused_unkeyed"):
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(insert),
                {"i": uuid.uuid4(), "t": world.tenant, "w": world.workspace, "k": "key-1"},
            )
