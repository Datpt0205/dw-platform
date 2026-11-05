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
    TenantWideLane,
    TenantWideScopeRefusedError,
    TenantWideScopeRegistry,
    bind_actor,
    tenant_wide_scope,
)

pytestmark = pytest.mark.unit


class _Result:
    def first(self) -> None:
        return None


class RecordingSession:
    """Records each statement and its parameters, in order."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.statements.append((str(statement), dict(params or {})))
        return _Result()


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
    assert params == {"kind": "user"}
    with pytest.raises(ValueError):
        await bind_actor(session, "admin")  # type: ignore[arg-type]
    assert len(session.statements) == 1
