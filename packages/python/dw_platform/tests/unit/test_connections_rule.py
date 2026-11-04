"""The parts of the connections' rule that need no database
(connections-and-vault R5.15; ADR-0115 decision 2). The rule itself is asked
over Postgres in `tests/integration/test_connections_db.py`.
"""

from __future__ import annotations

import uuid

import pytest

from dw_kernel.errors import DomainError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_kernel.secret import Secret
from dw_platform.application.access_context import AccessContext
from dw_platform.application.connection_admin import (
    ConnectionService,
    NewConnection,
    NoConnectionDependents,
)
from dw_platform.application.connections import NoConnectorCatalog, UsableContext

pytestmark = pytest.mark.unit


def test_a_call_site_is_one_of_three_and_has_no_default() -> None:
    with pytest.raises(ValueError, match="call site"):
        UsableContext(
            tenant_id=uuid.uuid4(),
            principal_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            call_site="anywhere",  # type: ignore[arg-type]
            run_requested_at=None,
        )
    with pytest.raises(TypeError):
        UsableContext(  # type: ignore[call-arg]
            tenant_id=uuid.uuid4(),
            principal_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            run_requested_at=None,
        )


def test_w1_knows_no_connector() -> None:
    """The composition root's catalogue until ticket 05:
    no connector (so nothing is created and no egress call is usable)."""
    assert NoConnectorCatalog().secret_fields("smtp", 1) is None


class _NoStore:
    """A store that must not be opened: the refusals below come first."""

    def transaction(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("the store was opened")


def _service(fields: frozenset[str] | None) -> ConnectionService:
    class Catalog:
        def secret_fields(self, connector_key: str, connector_major: int) -> frozenset[str] | None:
            return fields

    return ConnectionService(
        store=_NoStore(),  # type: ignore[arg-type]
        secrets=None,  # type: ignore[arg-type]
        catalog=Catalog(),
        dependents_port=NoConnectionDependents(),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


def _context() -> AccessContext:
    return AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        roles=frozenset(),
        plan_id="professional",
    )


def _new(**change: object) -> NewConnection:
    values: dict[str, object] = {
        "name": "Hộp thư",
        "connector_key": "smtp",
        "connector_major": 1,
        "external_account": "a@x.vn",
        "share_scope": "workspace",
        "secrets": {"password": Secret("p")},
        **change,
    }
    return NewConnection(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "fields", "reason"),
    [
        ({"share_scope": "owner"}, frozenset({"password"}), "share_scope_not_allowed"),
        ({"share_scope": "workspace_subtree"}, frozenset({"password"}), "share_scope_not_allowed"),
        ({}, None, "connector_unknown"),
        ({}, frozenset({"password", "api_key"}), "secret_fields_mismatch"),
        ({"secrets": {}}, frozenset({"password"}), "secret_fields_mismatch"),
        ({"external_account": " "}, frozenset({"password"}), "external_account_required"),
    ],
)
async def test_the_service_refuses_a_create_before_it_opens_anything(
    change: dict[str, object], fields: frozenset[str] | None, reason: str
) -> None:
    """R5.1, R5.20: the service's own layer, which a caller other than the
    route (whose schema refuses first) reaches."""
    with pytest.raises(DomainError) as refused:
        await _service(fields).create(_context(), _new(**change))

    assert refused.value.details["reason_code"] == reason
