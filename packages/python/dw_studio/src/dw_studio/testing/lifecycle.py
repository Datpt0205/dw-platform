"""Moving a sealed version through the stage machine for a test, the way
`studio.guard_version_stage()` allows (agent-lifecycle ticket 03, step 11).

A test that needs a version `live` (or `evaluating`, `awaiting_approval`,
`retired`) used to set the stage with one UPDATE; the trigger now refuses that,
so these helpers walk the legal path as the migrator, in one transaction:

- `publish_for_test`: a kind without a quality gate through `draft ->
  awaiting_approval -> live`, with an approved `studio.publish.<kind>` request
  naming the version and a decision by someone outside `contributor_ids`, the
  live version it replaces retired `superseded` first. A gated kind
  (`fixture`) cannot reach `awaiting_approval` until ticket 06's gate, so a
  test that needs a live version uses `fixture_gateless` (or `object`);
  ticket 06 extends this with a passing gate run.
- `move_for_test`: any stage a sealed draft can reach, by the same path.

A test that asserts the trigger itself (a move refused) writes its SQL
directly instead.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from dw_studio.core.application.ports import ArtifactTx, VersionRow
from dw_studio.core.domain.artifacts import ClosureItem, Stage
from dw_studio.lifecycle.application.ports import SubmitRefusal

# The migrator's connection, or a store transaction's session as `dw_app`.
Conn = AsyncConnection | AsyncSession


@dataclass(frozen=True)
class _Row:
    tenant_id: uuid.UUID
    artifact_id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    gated: bool
    stage: str
    contributors: tuple[uuid.UUID, ...]
    sealed: bool


async def _read(conn: Conn, version_id: uuid.UUID) -> _Row:
    row = (
        await conn.execute(
            sa.text(
                "SELECT v.tenant_id, v.artifact_id, a.owning_workspace_id, a.kind,"
                " k.has_quality_gate, v.stage, v.contributor_ids,"
                " v.definition_hash IS NOT NULL AS sealed"
                " FROM studio.artifact_versions v"
                " JOIN studio.artifacts a ON a.tenant_id = v.tenant_id AND a.id = v.artifact_id"
                " JOIN studio.artifact_kinds k ON k.kind = a.kind"
                " WHERE v.id = :v"
            ),
            {"v": version_id},
        )
    ).one()
    return _Row(
        row.tenant_id,
        row.artifact_id,
        row.owning_workspace_id,
        row.kind,
        row.has_quality_gate,
        row.stage,
        tuple(row.contributor_ids),
        row.sealed,
    )


async def _exec(conn: Conn, statement: str, **values: Any) -> None:
    await conn.execute(sa.text(statement), values)


async def _live_hash(conn: Conn, row: _Row) -> str | None:
    found = await conn.scalar(
        sa.text(
            "SELECT definition_hash FROM studio.artifact_versions"
            " WHERE tenant_id = :t AND artifact_id = :a AND stage = 'live'"
        ),
        {"t": row.tenant_id, "a": row.artifact_id},
    )
    return None if found is None else str(found)


async def open_publish_request(
    conn: Conn,
    version_id: uuid.UUID,
    *,
    requested_by: uuid.UUID,
    kind: str | None = None,
    payload_version_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A pending `studio.publish.<kind>` request naming the version, as ticket
    04's submit will open it; `kind` and `payload_version_id` let a test name
    another kind's request or another version's."""
    row = await _read(conn, version_id)
    approval_id = uuid.uuid4()
    await _exec(
        conn,
        "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id, approval_type,"
        " requested_by, payload, status) VALUES (:id, :t, :w, :type, :by, CAST(:p AS jsonb),"
        " 'pending')",
        id=approval_id,
        t=row.tenant_id,
        w=row.workspace_id,
        type=f"studio.publish.{kind or row.kind}",
        by=requested_by,
        p=json.dumps({"version_id": str(payload_version_id or version_id)}),
    )
    return approval_id


async def decide_for_test(
    conn: Conn, approval_id: uuid.UUID, *, decided_by: uuid.UUID, approve: bool = True
) -> None:
    """The request decided, with its decision row, as the approval flow writes them."""
    outcome = "approved" if approve else "rejected"
    request = (
        await conn.execute(
            sa.text(
                "UPDATE platform.approval_requests SET status = :o, decided_at = now(),"
                " version = version + 1 WHERE id = :id RETURNING tenant_id, workspace_id"
            ),
            {"o": outcome, "id": approval_id},
        )
    ).one()
    await _exec(
        conn,
        "INSERT INTO platform.approval_decisions (id, request_id, tenant_id, workspace_id,"
        " decided_by, outcome, decided_at) VALUES (:id, :r, :t, :w, :by, :o, now())",
        id=uuid.uuid4(),
        r=approval_id,
        t=request.tenant_id,
        w=request.workspace_id,
        by=decided_by,
        o=outcome,
    )


async def submit_on(conn: Conn, version_id: uuid.UUID) -> uuid.UUID | None:
    """A sealed draft to its candidate stage on the caller's connection:
    `draft -> evaluating` for a gated kind, `draft -> awaiting_approval` with a
    pending request otherwise; the request's id, or None."""
    return await _to_candidate(conn, version_id, await _read(conn, version_id))


async def _to_candidate(conn: Conn, version_id: uuid.UUID, row: _Row) -> uuid.UUID | None:
    if not row.sealed or row.stage != Stage.DRAFT.value:
        raise ValueError(f"version {version_id} is not a sealed draft: seal it first")
    submitter = row.contributors[0]
    compared = await _live_hash(conn, row)
    if row.gated:
        await _exec(
            conn,
            "UPDATE studio.artifact_versions SET stage = 'evaluating', submitted_by = :s,"
            " submitted_at = now(), compared_live_hash = :h WHERE id = :v",
            s=submitter,
            h=compared,
            v=version_id,
        )
        return None
    approval_id = await open_publish_request(conn, version_id, requested_by=submitter)
    await _exec(
        conn,
        "UPDATE studio.artifact_versions SET stage = 'awaiting_approval', submitted_by = :s,"
        " submitted_at = now(), compared_live_hash = :h, publish_approval_id = :a WHERE id = :v",
        s=submitter,
        h=compared,
        a=approval_id,
        v=version_id,
    )
    return approval_id


async def _go_live(conn: Conn, version_id: uuid.UUID, row: _Row, approver: uuid.UUID) -> None:
    await _exec(
        conn,
        "UPDATE studio.artifact_versions SET stage = 'retired', retired_by = :by,"
        " retired_at = now(), retire_reason_code = 'superseded'"
        " WHERE tenant_id = :t AND artifact_id = :a AND stage = 'live'",
        by=approver,
        t=row.tenant_id,
        a=row.artifact_id,
    )
    await _exec(
        conn,
        "UPDATE studio.artifact_versions SET stage = 'live', published_by = :by,"
        " published_at = now() WHERE id = :v",
        by=approver,
        v=version_id,
    )


async def publish_on(
    conn: Conn, version_id: uuid.UUID, *, approver: uuid.UUID | None = None
) -> None:
    """`publish_for_test` on a connection the caller holds (the migrator's)."""
    row = await _read(conn, version_id)
    if row.gated:
        raise ValueError(
            f"{row.kind} has a quality gate: it reaches live through ticket 06's gate;"
            " use fixture_gateless"
        )
    decider = approver or uuid.uuid4()
    if decider in row.contributors:
        raise ValueError("the approver is a contributor")
    approval_id = await _to_candidate(conn, version_id, row)
    assert approval_id is not None
    await decide_for_test(conn, approval_id, decided_by=decider)
    await _go_live(conn, version_id, row, decider)


async def publish_for_test(
    migrator: AsyncEngine, version_id: uuid.UUID, *, approver: uuid.UUID | None = None
) -> None:
    """A sealed draft of a kind without a gate, live by the legal path."""
    async with migrator.begin() as conn:
        await publish_on(conn, version_id, approver=approver)


async def move_for_test(migrator: AsyncEngine, version_id: uuid.UUID, stage: str) -> None:
    """A sealed draft (or a candidate, for `draft`) to `stage` by the legal
    path: `evaluating` for a gated kind, `awaiting_approval`, `live` or
    `retired` (`explicit`) for one without a gate, `draft` back from a
    candidate with every submit column cleared, as a withdrawal leaves it."""
    target = Stage(stage)
    async with migrator.begin() as conn:
        row = await _read(conn, version_id)
        if target is Stage.DRAFT:
            if row.stage == Stage.DRAFT.value:
                return
            await _exec(
                conn,
                "UPDATE platform.approval_requests SET status = 'cancelled', version = version + 1"
                " WHERE id = (SELECT publish_approval_id FROM studio.artifact_versions"
                " WHERE id = :v) AND status = 'pending'",
                v=version_id,
            )
            await _exec(
                conn,
                "UPDATE studio.artifact_versions SET stage = 'draft', gate_run_id = NULL,"
                " publish_approval_id = NULL, submitted_by = NULL, submitted_at = NULL,"
                " compared_live_hash = NULL, tighten_only = false WHERE id = :v",
                v=version_id,
            )
        elif target in (Stage.EVALUATING, Stage.AWAITING_APPROVAL):
            if row.gated != (target is Stage.EVALUATING):
                raise ValueError(f"{row.kind} does not reach {target} (gated: {row.gated})")
            await _to_candidate(conn, version_id, row)
        elif target is Stage.LIVE:
            await publish_on(conn, version_id)
        else:
            if row.stage != Stage.LIVE.value:
                await publish_on(conn, version_id)
            await _exec(
                conn,
                "UPDATE studio.artifact_versions SET stage = 'retired', retired_by = :by,"
                " retired_at = now(), retire_reason_code = 'explicit' WHERE id = :v",
                by=uuid.uuid4(),
                v=version_id,
            )


@dataclass
class RefusingCheck:
    """A per-kind submit check for a test: refuses with `reason_code`, or
    raises when `fail` is set (R2.3, R2.7); counts its calls."""

    reason_code: str = "fixture_refused"
    fail: bool = False
    calls: int = 0

    async def __call__(
        self, tx: ArtifactTx, version: VersionRow, closure: Sequence[ClosureItem]
    ) -> SubmitRefusal | None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("the check could not answer")
        return SubmitRefusal(self.reason_code, "the fixture check refuses this version")
