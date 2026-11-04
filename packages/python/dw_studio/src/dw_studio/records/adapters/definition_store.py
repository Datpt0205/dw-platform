"""`SqlObjectDefinitionStore` and `SqlObjectDefinitionReader`: object
definitions over schema `studio`, as `dw_app` under the caller's tenant (RLS).

The store works inside the session of the `SqlArtifactTx` it is made from
(`object_store_of`), so the publish hook's writes are the publish
transaction's. The reader opens its own transaction under the tenant it is
given. Both read a definition through `_applied`, one function, so the hook's
idempotence check and the schema projector see the same shape.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_studio.core.adapters.artifact_store import SqlArtifactTx
from dw_studio.core.adapters.tables import artifact_versions
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.records.adapters.tables import field_defs, object_defs, picklist_options
from dw_studio.records.application.ports import AppliedObject, FieldStorage, ObjectVersion
from dw_studio.records.domain.document import (
    OWNER,
    WORKSPACE,
    DocumentDefinition,
    FieldDefinition,
    OptionDefinition,
)
from dw_studio.records.domain.locks import object_lock_key

_LOCK = sa.text("SELECT pg_advisory_xact_lock(:k)")

# The columns of `field_defs` a `FieldDefinition` carries, by the same names.
_FIELD_COLUMNS = (
    "api_name",
    "type",
    "labels",
    "ai_description",
    "number_mode",
    "scale",
    "currency_code",
    "max_length",
    "required",
    "is_unique",
    "indexed",
    "pd_category",
    "sensitive_type",
    "subject_identifier",
)


async def _applied(session: AsyncSession, object_id: uuid.UUID) -> AppliedObject | None:
    row = (
        await session.execute(sa.select(object_defs).where(object_defs.c.id == object_id))
    ).one_or_none()
    if row is None:
        return None
    fields = (
        await session.execute(sa.select(field_defs).where(field_defs.c.object_id == object_id))
    ).all()
    options: dict[uuid.UUID, list[OptionDefinition]] = {}
    for option in await session.execute(
        sa.select(picklist_options)
        .where(picklist_options.c.field_id.in_([f.id for f in fields]))
        .order_by(picklist_options.c.key)
    ):
        options.setdefault(option.field_id, []).append(
            OptionDefinition(option.key, dict(option.labels), option.position, option.active)
        )
    definitions = {
        f.api_name: FieldDefinition(
            **{name: getattr(f, name) for name in _FIELD_COLUMNS if name != "labels"},
            labels=dict(f.labels),
            options=tuple(options.get(f.id, ())),
        )
        for f in fields
        # Not the document's: no version decides the owner or workspace row.
        if f.api_name not in (OWNER, WORKSPACE)
    }
    return AppliedObject(
        object_id=row.id,
        api_name=row.api_name,
        applied_version_id=row.applied_version_id,
        schema_version=row.schema_version,
        definition=DocumentDefinition(
            labels=dict(row.labels),
            ai_description=row.ai_description,
            default_access=row.default_access,
            fields=definitions,
        ),
        storage={
            f.api_name: FieldStorage(f.id, f.storage_kind, f.slot, f.field_no) for f in fields
        },
    )


@dataclass
class SqlObjectDefinitionStore:
    """One publish transaction's definition writes; see `ObjectDefinitionStore`."""

    session: AsyncSession
    context: AccessContext

    def _stamped(self, **values: Any) -> dict[str, Any]:
        return {**values, "updated_by": self.context.principal_id}

    async def lock_object(self, object_id: uuid.UUID) -> None:
        await self.session.execute(_LOCK, {"k": object_lock_key(self.context.tenant_id, object_id)})

    async def version(self, version_id: uuid.UUID) -> ObjectVersion | None:
        row = (
            await self.session.execute(
                sa.select(
                    artifact_versions.c.artifact_id,
                    artifact_versions.c.version_no,
                    artifact_versions.c.document,
                ).where(artifact_versions.c.id == version_id)
            )
        ).one_or_none()
        return None if row is None else ObjectVersion(row.artifact_id, row.version_no, row.document)

    async def applied(self, object_id: uuid.UUID) -> AppliedObject | None:
        return await _applied(self.session, object_id)

    async def insert_object(
        self,
        *,
        object_id: uuid.UUID,
        api_name: str,
        labels: Mapping[str, str],
        ai_description: str | None,
        default_access: str,
        version_id: uuid.UUID,
        version_no: int,
    ) -> None:
        await self.session.execute(
            sa.insert(object_defs).values(
                id=object_id,
                tenant_id=self.context.tenant_id,
                api_name=api_name,
                labels=dict(labels),
                ai_description=ai_description,
                default_access=default_access,
                applied_version_id=version_id,
                schema_version=version_no,
                created_by=self.context.principal_id,
                updated_by=self.context.principal_id,
            )
        )

    async def update_object(self, object_id: uuid.UUID, **values: Any) -> None:
        await self.session.execute(
            sa.update(object_defs)
            .where(object_defs.c.id == object_id)
            .values(**self._stamped(**values))
        )

    async def used_slots(self, object_id: uuid.UUID) -> frozenset[str]:
        rows = await self.session.execute(
            sa.select(field_defs.c.slot).where(
                field_defs.c.object_id == object_id, field_defs.c.slot.is_not(None)
            )
        )
        return frozenset(row.slot for row in rows)

    async def take_field_no(self, object_id: uuid.UUID) -> int:
        taken = await self.session.scalar(
            sa.update(object_defs)
            .where(object_defs.c.id == object_id)
            .values(**self._stamped(next_field_no=object_defs.c.next_field_no + 1))
            .returning(object_defs.c.next_field_no - 1)
        )
        if taken is None:
            raise LookupError(f"object {object_id} has no definition row")
        return int(taken)

    async def insert_field(
        self,
        *,
        object_id: uuid.UUID,
        field_id: uuid.UUID,
        field: FieldDefinition,
        storage_kind: str,
        slot: str | None,
        field_no: int | None,
    ) -> None:
        values = {name: getattr(field, name) for name in _FIELD_COLUMNS}
        values["labels"] = dict(field.labels)
        await self.session.execute(
            sa.insert(field_defs).values(
                id=field_id,
                tenant_id=self.context.tenant_id,
                object_id=object_id,
                storage_kind=storage_kind,
                slot=slot,
                field_no=field_no,
                created_by=self.context.principal_id,
                updated_by=self.context.principal_id,
                **values,
            )
        )

    async def update_field(self, field_id: uuid.UUID, **values: Any) -> None:
        await self.session.execute(
            sa.update(field_defs)
            .where(field_defs.c.id == field_id)
            .values(**self._stamped(**values))
        )

    async def put_options(self, field_id: uuid.UUID, options: Sequence[OptionDefinition]) -> None:
        if not options:
            return
        statement = pg_insert(picklist_options).values(
            [
                {
                    "tenant_id": self.context.tenant_id,
                    "field_id": field_id,
                    "key": option.key,
                    "labels": dict(option.labels),
                    "position": option.position,
                    "active": option.active,
                    "created_by": self.context.principal_id,
                    "updated_by": self.context.principal_id,
                }
                for option in options
            ]
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "field_id", "key"],
                set_={
                    "labels": statement.excluded.labels,
                    "position": statement.excluded.position,
                    "active": statement.excluded.active,
                    "updated_by": statement.excluded.updated_by,
                },
                # Only a row that changes is touched: its `updated_at` stays.
                where=sa.or_(
                    picklist_options.c.labels.is_distinct_from(statement.excluded.labels),
                    picklist_options.c.position.is_distinct_from(statement.excluded.position),
                    picklist_options.c.active.is_distinct_from(statement.excluded.active),
                ),
            )
        )


def object_store_of(tx: ArtifactTx) -> SqlObjectDefinitionStore:
    """The factory a composition root hands `platform_kinds`: the store over
    the session of the publish transaction it is given."""
    if not isinstance(tx, SqlArtifactTx) or tx.context is None:
        raise TypeError(f"an object definition store needs a person's SqlArtifactTx, not {tx!r}")
    return SqlObjectDefinitionStore(tx.session, tx.context)


@dataclass(frozen=True)
class SqlObjectDefinitionReader:
    """`ObjectDefinitionReader`: one read under the tenant the caller names."""

    session_factory: async_sessionmaker[AsyncSession]

    async def read(self, tenant_id: uuid.UUID, object_id: uuid.UUID) -> AppliedObject | None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            return await _applied(session, object_id)
