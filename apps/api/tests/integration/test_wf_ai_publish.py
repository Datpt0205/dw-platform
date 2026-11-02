# ruff: noqa: F811  (the harness of test_dw_scorecard_autonomy is imported by name)
"""Integration: submitting, deciding and publishing a DW's workflow draft on
real PostgreSQL, through the real app (wf-ai ticket 03: R6.3-R6.6, R6.8,
R6.10, R6.11, R6.14, R6.16; WAI10-WAI12, WAI14-WAI17).

The world is the scorecard suite's: a `lead_care@1.0.0` DW whose Business
Owner is `bo`, Technical Owner `to` and Validator `validator`, a second DW
in the same workspace, and a stranger in a second tenant. A decision is
settled by the worker's `PublishSettler` over the same database, fed the
outbox row the decision wrote, as the raise suite settles a raise.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_dw_scorecard_autonomy import (  # noqa: F401  (fixtures, used by name)
    Harness,
    _dw,
    harness,
)
from test_wf_ai_drafts import BASE, PROPOSAL, _parameters

from dw_agent_runtime.adapters.wf_drafts import SqlWorkflowDrafts
from dw_agent_runtime.adapters.wflite_host import build_pinned_workflows
from dw_agent_runtime.wflite.catalog import load_shipped_packs, workflow_sha256
from dw_agent_runtime.wflite.publish import DW_WORKFLOW_PUBLISH_DECIDED, PublishSettler
from dw_api.bootstrap.paths import CONFIGS
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.work_queue import WorkScope

pytestmark = pytest.mark.integration

AUDITS = "SELECT count(*) FROM platform.audit_events WHERE action = :a AND resource_id = :r"


def _other_steps() -> list[dict[str, Any]]:
    steps = copy.deepcopy(BASE["steps"])
    steps[0] = {**steps[0], "description": "Một mô tả khác"}
    return steps


@dataclasses.dataclass
class Publish:
    h: Harness
    settler: PublishSettler
    app_url: str

    def path(self, suffix: str = "", dw: uuid.UUID | None = None) -> str:
        return f"/api/v1/digital-workers/{dw or self.h.world.dw}/workflow-draft{suffix}"

    async def put(self, who: str, steps: Any, dw: uuid.UUID | None = None) -> httpx.Response:
        return await self.h.client.put(
            self.path(dw=dw),
            json={"steps": steps},
            headers=self.h.headers(who, key=str(uuid.uuid4())),
        )

    async def post(self, who: str, action: str, dw: uuid.UUID | None = None) -> httpx.Response:
        return await self.h.client.post(
            self.path(f"/{action}", dw=dw), headers=self.h.headers(who, key=str(uuid.uuid4()))
        )

    async def ready(self, saver: str = "to", steps: Any = None) -> dict[str, Any]:
        """Saved by `saver` and simulated: a draft that may be submitted."""
        saved = await self.put(saver, steps or PROPOSAL["steps"])
        assert saved.status_code == 200, saved.text
        simulated = await self.post(saver, "simulate")
        assert simulated.status_code == 200 and simulated.json()["outcome"] == "passed"
        return dict(saved.json())

    async def submitted(self, saver: str = "to", submitter: str = "bo") -> str:
        await self.ready(saver)
        sent = await self.post(submitter, "submit")
        assert sent.status_code == 200, sent.text
        assert sent.json()["state"] == "submitted"
        return str(sent.json()["approval_id"])

    async def settle(self, approval: str) -> str:
        async with self.h.migrator.connect() as conn:
            payload = await conn.scalar(
                sa.text(
                    "SELECT payload FROM platform.outbox_events WHERE event_type = :e"
                    " AND aggregate_id = :a"
                ),
                {"e": DW_WORKFLOW_PUBLISH_DECIDED, "a": uuid.UUID(approval)},
            )
        assert payload is not None, "the decision announced nothing"
        world = self.h.world
        scope = WorkScope(tenant_id=world.tenant, workspace_id=world.workspace)
        settled = await self.settler.settle_publish(scope, uuid.UUID(payload["approval_id"]))
        return settled.outcome

    async def published(self, *, ready: bool = True) -> str:
        """Submitted by `bo` (after `to` saved and simulated, unless the draft
        is `ready` already), approved by the Validator, settled."""
        if ready:
            approval = await self.submitted()
        else:
            sent = await self.post("bo", "submit")
            assert sent.status_code == 200, sent.text
            approval = str(sent.json()["approval_id"])
        decided = await self.h.decide("validator", approval)
        assert decided.status_code == 200, decided.text
        assert await self.settle(approval) == "published"
        return approval

    async def pin(self, dw: uuid.UUID | None = None) -> str:
        async with self.h.migrator.connect() as conn:
            return str(
                await conn.scalar(
                    sa.text("SELECT workflow_version FROM platform.digital_workers WHERE id = :d"),
                    {"d": dw or self.h.world.dw},
                )
            )

    async def versions(self) -> int:
        return await self.h.count(
            "SELECT count(*) FROM platform.dw_workflow_versions WHERE dw_id = :d", d=self.h.world.dw
        )

    async def draft(self) -> dict[str, Any]:
        found = await self.h.client.get(self.path(), headers=self.h.headers("bo"))
        assert found.status_code == 200, found.text
        return dict(found.json())


@pytest.fixture
async def pub(harness: Harness, api_db: DatabaseUrls) -> AsyncIterator[Publish]:
    await _parameters(harness)
    engine = create_async_engine(api_db.app, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield Publish(
            harness,
            PublishSettler(
                repo=SqlWorkflowDrafts(sessions),
                workflows=build_pinned_workflows(load_shipped_packs(CONFIGS), sessions),
                clock=SystemClock(),
                id_generator=Uuid4Generator(),
            ),
            api_db.app,
        )
    finally:
        await engine.dispose()


def _reason(response: httpx.Response) -> str | None:
    return response.json().get("details", {}).get("reason_code")


async def test_a_draft_changed_after_its_simulation_is_not_submitted(pub: Publish) -> None:
    """R6.3 (WAI10): the passed simulation is of other content now."""
    await pub.ready()
    assert (await pub.put("to", _other_steps())).status_code == 200
    refused = await pub.post("bo", "submit")
    assert refused.status_code == 409 and _reason(refused) == "simulation_required"
    opened = (
        "SELECT count(*) FROM platform.approval_requests"
        " WHERE approval_type = :t AND tenant_id = :x"
    )
    assert await pub.h.count(opened, t="dw.workflow.publish", x=pub.h.world.tenant) == 0
    assert (await pub.draft())["state"] == "draft"


async def test_a_submitted_draft_is_locked_until_it_is_decided(pub: Publish) -> None:
    """R6.8 (WAI14): no save, no simulation, no second submission."""
    await pub.submitted()
    before = await pub.draft()
    refused = await pub.put("to", _other_steps())
    assert refused.status_code == 409 and _reason(refused) == "draft_submitted"
    for action in ("simulate", "submit"):
        again = await pub.post("bo", action)
        assert again.status_code == 409 and _reason(again) == "draft_submitted", action
    after = await pub.draft()
    assert after["content_sha256"] == before["content_sha256"] and after["state"] == "submitted"


async def test_the_one_who_saved_it_does_not_decide_and_the_validator_does(pub: Publish) -> None:
    """R6.4 (WAI11): saved by the Technical Owner, submitted by the Business
    Owner; the Technical Owner is refused, the Validator decides."""
    approval = await pub.submitted(saver="to", submitter="bo")
    refused = await pub.h.decide("to", approval)
    assert refused.status_code == 409 and _reason(refused) == "second_person_required"
    assert await pub.pin() == "1.0.0"
    assert (await pub.h.decide("validator", approval)).status_code == 200


async def test_an_earlier_author_does_not_decide_either(pub: Publish) -> None:
    """R6.4 (WAI16): A saves, B saves and submits, A decides: refused."""
    await pub.ready(saver="to")
    await pub.ready(saver="bo")
    assert (await pub.draft())["author_ids"] == [
        str(pub.h.world.users["to"]),
        str(pub.h.world.users["bo"]),
    ]
    sent = await pub.post("bo", "submit")
    refused = await pub.h.decide("to", str(sent.json()["approval_id"]))
    assert refused.status_code == 409 and _reason(refused) == "second_person_required"


async def test_a_validator_or_a_stranger_submits_nothing(pub: Publish) -> None:
    """The DW's owners only; another tenant does not find the DW."""
    await pub.ready()
    refused = await pub.post("validator", "submit")
    assert refused.status_code == 403 and _reason(refused) == "not_dw_owner"
    for action in ("submit", "withdraw"):
        assert (await pub.post("stranger", action)).status_code == 404, action


async def test_withdrawing_cancels_the_approval_and_returns_the_draft(pub: Publish) -> None:
    """R6.10, R6.11: one transaction, one audit row; the pin does not move."""
    approval = await pub.submitted()
    withdrawn = await pub.post("bo", "withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["state"] == "draft" and withdrawn.json()["approval_id"] is None
    status = "SELECT status FROM platform.approval_requests WHERE id = :a"
    async with pub.h.migrator.connect() as conn:
        assert await conn.scalar(sa.text(status), {"a": uuid.UUID(approval)}) == "cancelled"
    assert await pub.h.count(AUDITS, a="dw.workflow.withdrawn", r=str(pub.h.world.dw)) == 1
    assert await pub.pin() == "1.0.0"
    again = await pub.post("bo", "withdraw")
    assert again.status_code == 409 and _reason(again) == "draft_not_submitted"


async def test_a_decided_approval_is_not_withdrawn(pub: Publish) -> None:
    """R6.10: once decided, the settlement returns or publishes the draft; a
    withdrawal then changes nothing."""
    approval = await pub.submitted()
    assert (await pub.h.decide("validator", approval)).status_code == 200
    refused = await pub.post("bo", "withdraw")
    assert refused.status_code == 409 and _reason(refused) == "approval_decided"
    status = "SELECT status FROM platform.approval_requests WHERE id = :a"
    async with pub.h.migrator.connect() as conn:
        assert await conn.scalar(sa.text(status), {"a": uuid.UUID(approval)}) == "approved"
    assert (await pub.draft())["state"] == "submitted"
    assert await pub.settle(approval) == "published"


async def test_an_approval_publishes_the_next_version_and_moves_the_pin(pub: Publish) -> None:
    """R6.5 (WAI12): `1.0.0+t1`, then `1.0.0+t2` made from it; each audited
    as the Validator by the lane; the draft is gone; the page reads it."""
    await pub.published()
    assert await pub.pin() == "1.0.0+t1"
    content = workflow_sha256({**BASE, "steps": PROPOSAL["steps"]})
    row = (
        "SELECT version, content_sha256, approved_by FROM platform.dw_workflow_versions"
        " WHERE dw_id = :d ORDER BY seq"
    )
    async with pub.h.migrator.connect() as conn:
        (first,) = (await conn.execute(sa.text(row), {"d": pub.h.world.dw})).all()
    assert first.version == "1.0.0+t1" and first.content_sha256 == content
    assert first.approved_by == pub.h.world.users["validator"]
    (published,) = await pub.h.audits("dw.workflow.published")
    assert published.actor_id == pub.h.world.users["validator"]
    assert published.details["lane"] == "outbox"
    gone = await pub.h.client.get(pub.path(), headers=pub.h.headers("bo"))
    assert gone.status_code == 404 and _reason(gone) == "draft_not_found"
    outline = await pub.h.client.get(
        f"/api/v1/digital-workers/{pub.h.world.dw}/workflow", headers=pub.h.headers("bo")
    )
    assert outline.status_code == 200 and outline.json()["version"] == "1.0.0+t1"
    # The next draft is made from the tenant version, and publishes as +t2.
    saved = await pub.ready(steps=_other_steps())
    assert saved["base_sha256"] == content
    await pub.published(ready=False)
    assert await pub.pin() == "1.0.0+t2"


async def test_a_pin_moved_after_submission_publishes_nothing(pub: Publish) -> None:
    """R6.6 (WAI12): the DW pins another version than the approval's base;
    the draft comes back `base_changed` and the pin keeps its new value."""
    await pub.published()
    approval = await pub.submitted()
    async with pub.h.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.digital_workers SET workflow_version = '1.0.0' WHERE id = :d"),
            {"d": pub.h.world.dw},
        )
    assert (await pub.h.decide("validator", approval)).status_code == 200
    assert await pub.settle(approval) == "base_changed"
    assert await pub.versions() == 1 and await pub.pin() == "1.0.0"
    back = await pub.draft()
    assert back["state"] == "draft" and back["reason"] == "base_changed"


async def test_content_rewritten_after_submission_publishes_nothing(pub: Publish) -> None:
    """R6.6 (WAI14): content overwritten by the migrator, its hash column
    untouched: the settlement hashes the content itself."""
    approval = await pub.submitted()
    async with pub.h.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.dw_workflow_drafts SET content = CAST(:c AS jsonb)"
                " WHERE dw_id = :d"
            ),
            {"c": json.dumps({**BASE, "steps": _other_steps()}), "d": pub.h.world.dw},
        )
    assert (await pub.h.decide("validator", approval)).status_code == 200
    assert await pub.settle(approval) == "content_changed"
    assert await pub.versions() == 0 and await pub.pin() == "1.0.0"
    assert (await pub.draft())["reason"] == "content_changed"


async def test_a_rejection_returns_the_draft_and_the_pin_stays(pub: Publish) -> None:
    """R6.11."""
    approval = await pub.submitted()
    rejected = await pub.h.decide("validator", approval, approve=False, comment="chưa ổn")
    assert rejected.status_code == 200, rejected.text
    assert await pub.settle(approval) == "rejected"
    back = await pub.draft()
    assert back["state"] == "draft" and back["approval_id"] is None
    assert await pub.versions() == 0 and await pub.pin() == "1.0.0"


async def test_a_decision_delivered_twice_publishes_once(pub: Publish) -> None:
    """R6.14 (WAI17)."""
    approval = await pub.published()
    assert await pub.settle(approval) == "settled"
    assert await pub.versions() == 1
    assert await pub.h.count(AUDITS, a="dw.workflow.published", r=str(pub.h.world.dw)) == 1


async def test_another_dws_or_another_tenants_version_is_not_shipped(
    pub: Publish, api_db: DatabaseUrls
) -> None:
    """R6.16: the second DW of the workspace pinned to the first one's `+t1`,
    and a DW of tenant B pinned to `+t1` only tenant A has: both 404
    `workflow_not_shipped`; tenant B reads no version row."""
    await pub.published()
    world = pub.h.world
    stranger = world.users["stranger"]
    b_world = dataclasses.replace(world, tenant=world.other_tenant, workspace=world.other_workspace)
    async with pub.h.migrator.begin() as conn:
        b_dw, _ = await _dw(
            conn,
            b_world,
            f"bw_{world.tenant.hex[:8]}",
            {"bo": stranger, "to": stranger, "validator": stranger},
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.digital_workers SET workflow_version = '1.0.0+t1'"
                " WHERE id IN (:a, :b)"
            ),
            {"a": world.other_dw, "b": b_dw},
        )
    for who, dw in (("to", world.other_dw), ("stranger", b_dw)):
        refused = await pub.put(who, PROPOSAL["steps"], dw=dw)
        assert refused.status_code == 404 and _reason(refused) == "workflow_not_shipped", who
    engine = create_async_engine(api_db.app, poolclass=NullPool)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        scope = TenantScope(tenant_id=world.other_tenant, workspace_id=world.other_workspace)
        async with tenant_session(sessions, scope) as session:
            seen = await session.scalar(
                sa.text("SELECT count(*) FROM platform.dw_workflow_versions")
            )
            assert seen == 0
    finally:
        await engine.dispose()
