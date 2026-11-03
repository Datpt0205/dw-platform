# ruff: noqa: F811  (the harness of test_dw_scorecard_autonomy is imported by name)
"""Integration: a DW's workflow draft and its dry run on real PostgreSQL, through
the real app (wf-ai ticket 02: R6.1, R6.2, R6.7, R6.12, R6.13, R6.15; WAI9,
WAI13, WAI15).

The world is the scorecard suite's: one tenant with a `lead_care@1.0.0` DW
whose Business Owner is `bo` and Technical Owner `to`, and a stranger in a
second tenant. The draft is the assistant's mock proposal (one more wait).
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_dw_scorecard_autonomy import (  # noqa: F401  (fixtures, used by name)
    Harness,
    harness,
)

from dw_agent_runtime.testing.wf_ai import fixture_steps
from dw_agent_runtime.wflite.catalog import load_shipped_packs, workflow_sha256
from dw_api.bootstrap.paths import CONFIGS, MOCK_MODEL_FIXTURES
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

pytestmark = pytest.mark.integration

_PINNED = load_shipped_packs(CONFIGS).workflow("lead_care", "1.0.0")
assert _PINNED is not None
# The mock model's proposal as document steps, the form a draft is saved in (wf-ai/05).
PROPOSAL = {"steps": fixture_steps(MOCK_MODEL_FIXTURES, _PINNED)}
BASE = _PINNED.document.model_dump(by_alias=True, exclude_none=True)


def _path(h: Harness, suffix: str = "") -> str:
    return f"/api/v1/digital-workers/{h.world.dw}/workflow-draft{suffix}"


async def _put(h: Harness, who: str, steps: Any, key: str | None = None) -> Any:
    return await h.client.put(
        _path(h), json={"steps": steps}, headers=h.headers(who, key=key or str(uuid.uuid4()))
    )


async def _count(h: Harness, sql: str, **values: Any) -> int:
    async with h.migrator.connect() as conn:
        return int(await conn.scalar(sa.text(sql), values) or 0)


async def _parameters(h: Harness) -> None:
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.digital_workers SET parameters = CAST(:p AS jsonb) WHERE id = :d"
            ),
            {
                "p": json.dumps(
                    {"sender_address": "dw@demo.local", "sales_assignee_id": str(uuid.uuid4())}
                ),
                "d": h.world.dw,
            },
        )


async def test_owners_save_one_draft_and_both_stay_its_authors(harness: Harness) -> None:
    """R6.1, R6.12: one row per DW; the second save keeps the first author;
    the hash is the rebuilt document's; one audit row per save."""
    h = harness
    first = await _put(h, "bo", PROPOSAL["steps"])
    assert first.status_code == 200, first.text
    second = await _put(h, "to", PROPOSAL["steps"])
    assert second.status_code == 200, second.text
    view = second.json()
    assert view["state"] == "draft" and view["simulation"] is None
    assert view["author_ids"] == [str(h.world.users["bo"]), str(h.world.users["to"])]
    assert view["content_sha256"] == workflow_sha256({**BASE, "steps": PROPOSAL["steps"]})
    assert view["base_sha256"] == workflow_sha256(BASE)
    rows = "SELECT count(*) FROM platform.dw_workflow_drafts WHERE dw_id = :d"
    assert await _count(h, rows, d=h.world.dw) == 1
    audits = "SELECT count(*) FROM platform.audit_events WHERE action = :a AND resource_id = :r"
    assert await _count(h, audits, a="dw.workflow.draft_saved", r=str(h.world.dw)) == 2


async def test_a_tree_without_its_gate_is_refused_and_nothing_is_stored(harness: Harness) -> None:
    """R6.7 (WAI13): the server rebuilds and checks what it is sent."""
    h = harness
    steps = copy.deepcopy(BASE["steps"])
    steps.insert(2, steps[2]["config"]["approved"].pop(0))
    refused = await _put(h, "bo", steps)
    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["details"]["reason_code"] == "draft_not_publishable"
    assert "wf.hitl_gate_missing" in {p["code"] for p in body["details"]["problems"]}
    rows = "SELECT count(*) FROM platform.dw_workflow_drafts WHERE dw_id = :d"
    assert await _count(h, rows, d=h.world.dw) == 0


async def test_a_validator_is_not_an_owner_of_the_draft(harness: Harness) -> None:
    h = harness
    refused = await _put(h, "validator", PROPOSAL["steps"])
    assert refused.status_code == 403
    assert refused.json()["details"]["reason_code"] == "not_dw_owner"


async def test_another_tenant_reads_and_changes_nothing(
    harness: Harness, api_db: DatabaseUrls
) -> None:
    """R6.13 (WAI15): 404 on every route for a caller of another tenant, and
    no row reads under that tenant."""
    h = harness
    assert (await _put(h, "bo", PROPOSAL["steps"])).status_code == 200
    stranger = h.headers("stranger", key=str(uuid.uuid4()))
    assert (await h.client.get(_path(h), headers=stranger)).status_code == 404
    assert (
        await h.client.put(_path(h), json={"steps": PROPOSAL["steps"]}, headers=stranger)
    ).status_code == 404
    assert (await h.client.post(_path(h, "/simulate"), headers=stranger)).status_code == 404
    engine = create_async_engine(api_db.app, poolclass=NullPool)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        scope = TenantScope(tenant_id=h.world.other_tenant, workspace_id=h.world.other_workspace)
        async with tenant_session(sessions, scope) as session:
            for table in ("dw_workflow_drafts", "dw_workflow_simulations"):
                seen = await session.scalar(sa.text(f"SELECT count(*) FROM platform.{table}"))
                assert seen == 0, table
    finally:
        await engine.dispose()
    rows = "SELECT count(*) FROM platform.dw_workflow_drafts WHERE tenant_id = :t"
    assert await _count(h, rows, t=h.world.tenant) == 1


async def test_the_simulation_passes_and_records_the_send(harness: Harness) -> None:
    """R6.2 (WAI9): the stored draft runs dry; the send is recorded, not sent;
    the result and an audit row are stored under the content's hash."""
    h = harness
    await _parameters(h)
    saved = (await _put(h, "bo", PROPOSAL["steps"])).json()
    simulated = await h.client.post(
        _path(h, "/simulate"), headers=h.headers("to", key=str(uuid.uuid4()))
    )
    assert simulated.status_code == 200, simulated.text
    result = simulated.json()
    assert result["outcome"] == "passed", result
    assert result["content_sha256"] == saved["content_sha256"]
    assert result["tool_calls"][0]["tool"] == "email.send@1.0.0"
    assert "wait_more" in {e["step_id"] for e in result["trail"]}
    view = (await h.client.get(_path(h), headers=h.headers("bo"))).json()
    assert view["simulation"]["outcome"] == "passed"
    audits = "SELECT count(*) FROM platform.audit_events WHERE action = :a AND resource_id = :r"
    assert await _count(h, audits, a="dw.workflow.simulated", r=str(h.world.dw)) == 1
    sends = "SELECT count(*) FROM platform.marketing_send_log WHERE tenant_id = :t"
    assert await _count(h, sends, t=h.world.tenant) == 0


async def test_a_replayed_key_saves_once(harness: Harness) -> None:
    """R6.15: the same key and body is one save; another body under it is
    refused."""
    h = harness
    key = str(uuid.uuid4())
    assert (await _put(h, "bo", PROPOSAL["steps"], key)).status_code == 200
    replay = await _put(h, "bo", PROPOSAL["steps"], key)
    assert replay.status_code == 200
    audits = "SELECT count(*) FROM platform.audit_events WHERE action = :a AND resource_id = :r"
    assert await _count(h, audits, a="dw.workflow.draft_saved", r=str(h.world.dw)) == 1
    other = await _put(h, "bo", BASE["steps"], key)
    assert other.status_code >= 400
