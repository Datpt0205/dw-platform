"""The tenant-wide scope's registry and the actor binding, without a database
(record-access ticket 03, R7.2, step 5; ADR-0105 decisions 5 and 6).

The database half (what the scope opens, for one transaction) is
`test_record_policies.py` and `test_rls_coverage.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_platform.adapters.persistence.tenant_session import (
    ActorBindingRefusedError,
    TenantWideLane,
    TenantWideScopeRefusedError,
    TenantWideScopeRegistry,
    bind_actor,
    tenant_wide_scope,
)

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, row: Any = None) -> None:
        self.row = row

    def first(self) -> None:
        return None

    def one_or_none(self) -> Any:
        return self.row


class RecordingSession:
    """Records each statement and its parameters, in order; a run's row, when
    given, answers the read of `bind_actor`."""

    def __init__(self, run_row: Any = None) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.run_row = run_row

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.statements.append((str(statement), dict(params or {})))
        return _Result(self.run_row if "platform.worker_runs" in str(statement) else None)


OFFBOARDING = TenantWideLane(
    lane="offboarding", reason="exports and purges one leaving tenant", reads_private_tables=True
)


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"lane": "offboarding", "reason": "  ", "reads_private_tables": True}, ValueError),
        ({"lane": "offboarding", "reason": "", "reads_private_tables": False}, ValueError),
        ({"lane": "offboarding", "reason": "why", "reads_private_tables": None}, ValueError),
        ({"lane": "offboarding", "reason": "why", "reads_private_tables": "yes"}, ValueError),
        ({"lane": "offboarding", "reason": "why"}, TypeError),
        ({"lane": "Off Boarding", "reason": "why", "reads_private_tables": True}, ValueError),
    ],
    ids=["blank reason", "empty reason", "no answer", "not a bool", "missing", "bad name"],
)
def test_r7_2_an_entry_without_its_reason_or_its_answer_fails_when_built(
    values: dict[str, Any], error: type[Exception]
) -> None:
    with pytest.raises(error):
        TenantWideLane(**values)


def test_the_registry_is_frozen_and_lists_a_lane_once() -> None:
    registry = TenantWideScopeRegistry(OFFBOARDING)
    assert registry.get("offboarding") is OFFBOARDING
    assert registry.get("record_index") is None
    assert registry.lanes() == (OFFBOARDING,)
    with pytest.raises(TypeError):
        registry._lanes["record_index"] = OFFBOARDING  # type: ignore[index]
    with pytest.raises(ValueError, match="twice"):
        TenantWideScopeRegistry(OFFBOARDING, OFFBOARDING)
    with pytest.raises(ValueError):
        TenantWideScopeRegistry("offboarding")  # type: ignore[arg-type]


async def test_r7_2_an_unregistered_lane_is_refused_before_any_statement() -> None:
    session = RecordingSession()
    with pytest.raises(TenantWideScopeRefusedError):
        await tenant_wide_scope(
            session,  # type: ignore[arg-type]
            uuid.uuid4(),
            "record_index",
            TenantWideScopeRegistry(OFFBOARDING),
        )
    assert session.statements == []


async def test_a_registered_lane_binds_the_tenant_and_the_scope_for_its_transaction() -> None:
    session = RecordingSession()
    tenant = uuid.uuid4()
    await tenant_wide_scope(
        session,  # type: ignore[arg-type]
        tenant,
        "offboarding",
        TenantWideScopeRegistry(OFFBOARDING),
    )
    [(sql, params)] = session.statements
    assert "set_config('app.workspace_scope', 'tenant', true)" in sql
    assert "set_config('app.tenant_id', :tenant_id, true)" in sql
    assert params == {"tenant_id": str(tenant)}


async def test_bind_actor_binds_user_for_the_transaction_and_refuses_another_kind() -> None:
    session = RecordingSession()
    await bind_actor(session, "user")  # type: ignore[arg-type]
    [(sql, params)] = session.statements
    assert "set_config('app.actor_kind', :kind, true)" in sql
    assert "set_config('app.boundary_id', :boundary, true)" in sql
    assert "set_config('app.run_mode', :mode, true)" in sql
    # `user` clears whatever a run's actor bound earlier in the transaction.
    assert params == {"kind": "user", "boundary": "", "mode": ""}
    with pytest.raises(ValueError):
        await bind_actor(session, "admin")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await bind_actor(session, "user", run_id=uuid.uuid4())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await bind_actor(session, "agent")  # type: ignore[arg-type]
    assert len(session.statements) == 1


class _RunRow:
    def __init__(self, principal: uuid.UUID, bound: uuid.UUID | None) -> None:
        self.run_mode = "live"
        self.principal = principal
        self.bound = bound
        self.chain = "b1,b2"


@pytest.mark.parametrize("kind", ["agent", "workflow"])
async def test_a_run_s_actor_binds_its_row_s_mode_and_chain(kind: str) -> None:
    """R6.3 (gate (d), (e)): the mode and the boundaries are the row's."""
    run, principal = uuid.uuid4(), uuid.uuid4()
    session = RecordingSession(_RunRow(principal, principal))
    await bind_actor(session, kind, run_id=run)  # type: ignore[arg-type]
    [(read, read_params), (_, params)] = session.statements
    assert "studio.boundary_chain(r.id)" in read and read_params == {"run": run}
    assert params == {"kind": kind, "boundary": "b1,b2", "mode": "live"}


@pytest.mark.parametrize("bound", ["another", "none"])
async def test_a_run_s_actor_for_another_principal_or_no_row_binds_nothing(bound: str) -> None:
    """Gate (m): `bind_actor` sets no principal; it refuses one the run does not act as."""
    principal = uuid.uuid4()
    session = RecordingSession(_RunRow(principal, uuid.uuid4() if bound == "another" else None))
    with pytest.raises(ActorBindingRefusedError):
        await bind_actor(session, "agent", run_id=uuid.uuid4())  # type: ignore[arg-type]
    missing = RecordingSession(None)
    with pytest.raises(ActorBindingRefusedError):
        await bind_actor(missing, "workflow", run_id=uuid.uuid4())  # type: ignore[arg-type]
    assert all("set_config" not in sql for sql, _ in (*session.statements, *missing.statements))
