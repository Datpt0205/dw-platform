"""`/api/v1/studio/artifacts/{artifact_id}/bindings`: what a document's bindings
are bound to, and proposals to change it (tenant-config R7, R8; the spec's
"API").

Mounted inside the Studio group (`dw_api.main.mount_studio`). Every route asks
the artifact's kind's read key at its owning workspace first, a 404 otherwise
(R8.17); a proposal and its request live in that workspace, never the
caller's working one. A proposal is decided through the approval inbox
(`config.version`, strict), and the worker settles it. Both writes take an
optional `Idempotency-Key` (ADR-0108 decision 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_platform.application.config_versions import ConfigVersionRow, ConfigVersionService
from dw_studio.core.application.bindings import (
    BINDING_SET,
    BindingItem,
    BindingsOverview,
    BindingsReader,
)
from dw_studio.core.application.ports import BindingSetRow
from dw_studio.core.domain.bindings import BindingKind, as_uuid

router = APIRouter(prefix="/artifacts")


def _versions(container: Any) -> ConfigVersionService:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    service: ConfigVersionService = container.studio.config_versions
    return service


def _reader(container: Any) -> BindingsReader:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    reader: BindingsReader = container.studio.bindings
    return reader


class BindingDeclView(BaseModel):
    name: str
    kind: str
    required: bool
    description: str
    connector_key: str | None = None
    connector_major: int | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    has_default: bool = False


class BoundValueView(BaseModel):
    """A value as the caller may see it: a connection they do not read is its
    id alone, with `connection_hidden`."""

    value: Any = None
    connection_id: uuid.UUID | None = None
    connection_name: str | None = None
    connector_key: str | None = None
    connection_hidden: bool = False


class BindingItemView(BaseModel):
    declaration: BindingDeclView
    state: Literal["unset", "set", "default"]
    approved: BoundValueView | None
    proposed: BoundValueView | None
    proposal_open: bool


class BindingSetRef(BaseModel):
    id: uuid.UUID
    version_no: int
    status: str
    proposed_by: uuid.UUID
    decided_at: datetime | None


class BindingsView(BaseModel):
    artifact_id: uuid.UUID
    base_version: int | None = Field(
        description="The latest sealed version the values are checked against; none yet."
    )
    approved: BindingSetRef | None
    proposal: BindingSetRef | None
    items: list[BindingItemView]


class BindingProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(
        description=(
            "Each binding's value by name: a connection's or a principal's id,"
            " a variable's JSON value."
        )
    )


class BindingProposalView(BaseModel):
    id: uuid.UUID
    artifact_id: uuid.UUID
    version_no: int
    status: str
    base_version: int
    document_hash: str
    approval_id: uuid.UUID
    proposed_by: uuid.UUID
    proposed_at: datetime


def _ref(row: BindingSetRow | None) -> BindingSetRef | None:
    if row is None:
        return None
    return BindingSetRef(
        id=row.id,
        version_no=row.version_no,
        status=row.status,
        proposed_by=row.proposed_by,
        decided_at=row.decided_at,
    )


def _bound(item: BindingItem, value: Any, overview: BindingsOverview) -> BoundValueView:
    if item.decl.kind is not BindingKind.CONNECTION:
        return BoundValueView(value=value)
    connection_id = as_uuid(value)
    facts = None if connection_id is None else overview.readable_connections.get(connection_id)
    if facts is None:
        return BoundValueView(connection_id=connection_id, connection_hidden=True)
    return BoundValueView(
        connection_id=connection_id,
        connection_name=facts.name,
        connector_key=facts.connector_key,
    )


def _view(overview: BindingsOverview) -> BindingsView:
    items = []
    for item in overview.items:
        decl = item.decl
        items.append(
            BindingItemView(
                declaration=BindingDeclView(
                    name=decl.name,
                    kind=decl.kind.value,
                    required=decl.required,
                    description=decl.description,
                    connector_key=decl.connector_key,
                    connector_major=decl.connector_major,
                    schema=None if decl.schema is None else dict(decl.schema),
                    has_default=decl.has_default,
                ),
                state=item.state,
                approved=None if item.state != "set" else _bound(item, item.value, overview),
                proposed=_bound(item, item.proposed_value, overview)
                if item.has_proposed
                else None,
                proposal_open=item.has_proposed,
            )
        )
    return BindingsView(
        artifact_id=overview.artifact_id,
        base_version=overview.base_version,
        approved=_ref(overview.approved),
        proposal=_ref(overview.proposal),
        items=items,
    )


def _proposal(row: ConfigVersionRow) -> BindingProposalView:
    return BindingProposalView(
        id=row.id,
        artifact_id=uuid.UUID(row.key),
        version_no=row.version_no,
        status=row.status,
        base_version=row.base_version,
        document_hash=row.document_hash,
        approval_id=row.approval_id,
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
    )


def _path_uuid(check: CheckInput, name: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(check.request.path_params[name])
    except (KeyError, ValueError):
        return None


async def _may_propose(check: CheckInput) -> None:
    """The service's own question, before a key row is read (app-standards R2.30)."""
    artifact_id = _path_uuid(check, "artifact_id")
    if artifact_id is not None:
        await _versions(check.container).check_propose(
            check.context, BINDING_SET, str(artifact_id)
        )


async def _may_withdraw(check: CheckInput) -> None:
    artifact_id = _path_uuid(check, "artifact_id")
    config_version_id = _path_uuid(check, "config_version_id")
    if artifact_id is not None and config_version_id is not None:
        await _versions(check.container).check_withdraw(
            check.context, BINDING_SET, str(artifact_id), config_version_id
        )


ProposeIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_propose, operation="POST /studio/artifacts/{artifact_id}/bindings/proposals"),
]
WithdrawIdempotency = Annotated[
    IdempotentOperation,
    idempotent(
        _may_withdraw,
        operation=(
            "POST /studio/artifacts/{artifact_id}/bindings/proposals/{config_version_id}/withdraw"
        ),
    ),
]


@router.get("/{artifact_id}/bindings", response_model=BindingsView)
async def read_bindings(
    artifact_id: uuid.UUID, context: RequireStudioAccess, container: RequireContainer
) -> BindingsView:
    return _view(await _reader(container).overview(context, artifact_id))


@router.post(
    "/{artifact_id}/bindings/proposals", response_model=BindingProposalView, status_code=201
)
async def propose_bindings(
    artifact_id: uuid.UUID,
    body: BindingProposalBody,
    context: RequireStudioAccess,
    container: RequireContainer,
    idempotency: ProposeIdempotency,
) -> BindingProposalView:
    service = _versions(container)
    key = str(artifact_id)

    async def run(effect: Any) -> BindingProposalView:
        row = await service.propose(
            context, BINDING_SET, key, {"values": body.values}, effect=effect
        )
        return _proposal(row)

    async def reread(id_: str) -> BindingProposalView:
        return _proposal(await service.get(context, BINDING_SET, key, uuid.UUID(id_)))

    view = await idempotency.once(status=201, run=run, reread=reread)
    result: BindingProposalView = await idempotency.record(view, status_code=201)
    return result


@router.post(
    "/{artifact_id}/bindings/proposals/{config_version_id}/withdraw",
    response_model=BindingProposalView,
)
async def withdraw_bindings_proposal(
    artifact_id: uuid.UUID,
    config_version_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    idempotency: WithdrawIdempotency,
) -> BindingProposalView:
    service = _versions(container)
    key = str(artifact_id)

    async def run(effect: Any) -> BindingProposalView:
        return _proposal(
            await service.withdraw(context, BINDING_SET, key, config_version_id, effect=effect)
        )

    async def reread(_id: str) -> BindingProposalView:
        return _proposal(await service.get(context, BINDING_SET, key, config_version_id))

    view = await idempotency.once(status=200, run=run, reread=reread)
    result: BindingProposalView = await idempotency.record(view, status_code=200)
    return result
