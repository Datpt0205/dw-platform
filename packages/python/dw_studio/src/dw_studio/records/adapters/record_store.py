"""`SqlRecordStore`: RecordService's statements over `studio.records` and
`studio.record_write_keys` (custom-objects ticket 03; ADR-0107 decision 3).

The one module whose SQL names the records table outside the definitions'
store (R5.6, CO10). Every statement runs on the session the door bound and
names the bound company's `tenant_id` itself, which also lets the planner
prune the hash partitions; which rows it sees or changes is the record
policies' answer (ADR-0105), never a predicate written here. The one thing
read from the policies' own text is `permissions`: `may_sql` of the policy
template, selected beside the row (gate (l)).

A field's value lives in its slot column, or in `data` under its `field_no`
(the key never reused, so a field added later never meets an old value).
A refusal reaches RecordService typed: a unique slot by its constraint name,
read off the partition's index as PostgreSQL reports it
(`records_p<n>_tenant_id_object_id_u01_idx`, measured), `create_key` the
same way, and a row the policies refuse (42501) or the owner check refuses.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlAuditRepository, SqlOutboxRepository
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent
from dw_studio.core.application.field_access import ActorUnboundError
from dw_studio.records.adapters.definition_store import applied_object
from dw_studio.records.adapters.record_policy import may_sql
from dw_studio.records.adapters.tables import object_defs, record_write_keys, records
from dw_studio.records.application.ports import (
    AppliedObject,
    Binding,
    CreateKeyTakenError,
    DuplicateSlotError,
    KeyedRecord,
    NewRecord,
    ObjectSummary,
    StoredRecord,
    WriteRefusedError,
)
from dw_studio.records.domain.document import NAME
from dw_studio.records.domain.locks import object_lock_key
from dw_studio.records.domain.values import from_json, to_json

logger = logging.getLogger(__name__)

# The store key of this table's retention fragment and purger.
RECORD_WRITE_KEYS: Final = "studio.record_write_keys"

_BINDING = sa.text(
    "SELECT NULLIF(current_setting('app.tenant_id', true), '') AS tenant_id,"
    " NULLIF(current_setting('app.workspace_id', true), '') AS workspace_id,"
    " coalesce(current_setting('app.run_mode', true), '') AS run_mode"
)
_LOCK_SHARED = sa.text("SELECT pg_advisory_xact_lock_shared(:k)")
_PURGE = sa.text("SELECT studio.purge_expired_record_write_keys()")

_INSUFFICIENT_PRIVILEGE: Final = "42501"
_UNIQUE: Final = "23505"
_OWNER_CHECK: Final = "ck_records_owner_in_tenant"
# The unique slot's index on the parent, or the one PostgreSQL names on the
# partition the row hashes to.
_SLOT_UNIQUE: Final = re.compile(r"^(?:uq_records|records_p[0-9]+)_tenant_id_object_id_(u[0-9]{2})")
_CREATE_KEY: Final = re.compile(r"^(?:uq_records|records_p[0-9]+)_tenant_id_object_id_create_key")

_MAY_UPDATE = sa.literal_column(may_sql("update"), sa.Boolean).label("may_update")
_MAY_DELETE = sa.literal_column(may_sql("soft_delete"), sa.Boolean).label("may_delete")
_ROW = (
    records.c.id,
    records.c.object_id,
    records.c.workspace_id,
    records.c.owner_kind,
    records.c.owner_id,
    records.c.name,
    records.c.version,
    records.c.created_at,
    records.c.created_by,
    records.c.updated_at,
    records.c.updated_by,
    records.c.deleted_at,
    records.c.deleted_by,
    records.c.data,
)


def _cause(error: DBAPIError) -> Any:
    return getattr(error.orig, "__cause__", None) or error.orig


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(_cause(error), "sqlstate", None) or getattr(error.orig, "sqlstate", None)


def _constraint(error: DBAPIError) -> str:
    return str(getattr(_cause(error), "constraint_name", None) or "")


def _uuid(value: Any) -> uuid.UUID | None:
    return None if value in (None, "") else uuid.UUID(str(value))


def _data_key(obj: AppliedObject, api_name: str) -> str:
    return str(obj.storage[api_name].field_no)


def _columns(
    obj: AppliedObject, values: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``values`` split into slot columns and `data` members, by `api_name`."""
    slots: dict[str, Any] = {}
    data: dict[str, Any] = {}
    for api_name, value in values.items():
        storage = obj.storage[api_name]
        if storage.storage_kind == "slot" and storage.slot is not None:
            slots[storage.slot] = value
        else:
            data[_data_key(obj, api_name)] = to_json(obj.definition.fields[api_name], value)
    return slots, data


def _slot_field(obj: AppliedObject, slot: str) -> str:
    for api_name, storage in obj.storage.items():
        if storage.slot == slot:
            return api_name
    return slot


@dataclass(frozen=True)
class SqlRecordStore:
    """`RecordStore`: the statements of the open transaction a door hands in."""

    async def bind(self, tx: Any) -> SqlRecordTx:
        row = (await tx.execute(_BINDING)).one()
        if row.tenant_id is None:
            raise ActorUnboundError("the transaction is bound to no company")
        return SqlRecordTx(
            tx,
            Binding(
                tenant_id=uuid.UUID(row.tenant_id),
                workspace_id=_uuid(row.workspace_id),
                run_mode=row.run_mode,
            ),
        )


class SqlRecordTx:
    def __init__(self, session: Any, binding: Binding) -> None:
        self.session = session
        self._binding = binding

    @property
    def binding(self) -> Binding:
        return self._binding

    @property
    def _tenant(self) -> uuid.UUID:
        return self._binding.tenant_id

    async def object_id(self, api_name: str) -> uuid.UUID | None:
        found = await self.session.scalar(
            sa.select(object_defs.c.id).where(
                object_defs.c.tenant_id == self._tenant, object_defs.c.api_name == api_name
            )
        )
        return None if found is None else uuid.UUID(str(found))

    async def objects(self) -> Sequence[ObjectSummary]:
        rows = await self.session.execute(
            sa.select(
                object_defs.c.id,
                object_defs.c.api_name,
                object_defs.c.labels,
                object_defs.c.ai_description,
            )
            .where(object_defs.c.tenant_id == self._tenant)
            .order_by(object_defs.c.api_name)
        )
        return [ObjectSummary(r.id, r.api_name, dict(r.labels), r.ai_description) for r in rows]

    async def lock_shared(self, object_id: uuid.UUID) -> None:
        await self.session.execute(_LOCK_SHARED, {"k": object_lock_key(self._tenant, object_id)})

    async def definition(self, object_id: uuid.UUID) -> AppliedObject | None:
        return await applied_object(self.session, object_id)

    def _select(self, obj: AppliedObject) -> sa.Select[Any]:
        slots = sorted(
            {
                s.slot
                for s in obj.storage.values()
                if s.storage_kind == "slot" and s.slot is not None
            }
        )
        return sa.select(
            *_ROW, *(records.c[slot] for slot in slots), _MAY_UPDATE, _MAY_DELETE
        ).where(records.c.tenant_id == self._tenant, records.c.object_id == obj.object_id)

    @staticmethod
    def _stored(obj: AppliedObject, row: Any) -> StoredRecord:
        mapping = row._mapping
        data = row.data or {}
        values: dict[str, Any] = {}
        for api_name, definition in obj.definition.fields.items():
            if api_name == NAME:
                continue
            storage = obj.storage[api_name]
            if storage.storage_kind == "slot" and storage.slot is not None:
                values[api_name] = mapping[storage.slot]
            else:
                values[api_name] = from_json(definition, data.get(_data_key(obj, api_name)))
        return StoredRecord(
            id=row.id,
            object_id=row.object_id,
            workspace_id=row.workspace_id,
            owner_kind=row.owner_kind,
            owner_id=row.owner_id,
            name=row.name,
            version=row.version,
            created_at=row.created_at,
            created_by=row.created_by,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
            deleted_at=row.deleted_at,
            deleted_by=row.deleted_by,
            values=values,
            may_update=bool(row.may_update),
            may_delete=bool(row.may_delete),
        )

    async def read(self, obj: AppliedObject, record_id: uuid.UUID) -> StoredRecord | None:
        row = (
            await self.session.execute(self._select(obj).where(records.c.id == record_id))
        ).one_or_none()
        return None if row is None else self._stored(obj, row)

    async def match(self, obj: AppliedObject, api_name: str, value: Any) -> StoredRecord | None:
        slot = obj.storage[api_name].slot
        if slot is None:
            raise LookupError(f"{api_name} holds no slot")
        row = (
            await self.session.execute(
                self._select(obj).where(records.c[slot] == value, records.c.deleted_at.is_(None))
            )
        ).one_or_none()
        return None if row is None else self._stored(obj, row)

    async def by_create_key(self, object_id: uuid.UUID, key: str) -> KeyedRecord | None:
        row = (
            await self.session.execute(
                sa.select(records.c.id, records.c.created_by).where(
                    records.c.tenant_id == self._tenant,
                    records.c.object_id == object_id,
                    records.c.create_key == key,
                )
            )
        ).one_or_none()
        return None if row is None else KeyedRecord(row.id, row.created_by, 1, True)

    async def written(self, write_key: str) -> KeyedRecord | None:
        k = record_write_keys.c
        row = (
            await self.session.execute(
                sa.select(k.record_id, k.actor_id, k.version, k.created).where(
                    k.tenant_id == self._tenant, k.write_key == write_key
                )
            )
        ).one_or_none()
        return (
            None
            if row is None
            else KeyedRecord(row.record_id, row.actor_id, row.version, row.created)
        )

    async def insert(self, obj: AppliedObject, record: NewRecord, *, arbiter: str | None) -> bool:
        slots, data = _columns(obj, record.values)
        statement = pg_insert(records).values(
            id=record.id,
            tenant_id=self._tenant,
            object_id=obj.object_id,
            workspace_id=record.workspace_id,
            owner_kind="user",
            owner_id=record.owner_id,
            name=record.name,
            version=1,
            create_key=record.create_key,
            data=data,
            created_by=record.owner_id,
            updated_by=record.owner_id,
            **slots,
        )
        if arbiter is not None:
            slot = obj.storage[arbiter].slot
            assert slot is not None
            statement = statement.on_conflict_do_nothing(
                index_elements=[records.c.tenant_id, records.c.object_id, records.c[slot]],
                index_where=sa.text(f"{slot} IS NOT NULL AND deleted_at IS NULL"),
            )
        try:
            # No RETURNING: it would ask the read policy of a creator who
            # may not read what it creates (create-only roles, gate (r)).
            result = await self.session.execute(statement)
        except DBAPIError as exc:
            raise self._refusal(obj, exc) from exc
        return bool(result.rowcount)

    async def update(
        self,
        obj: AppliedObject,
        record_id: uuid.UUID,
        version: int,
        changes: Mapping[str, Any],
        by: uuid.UUID,
    ) -> int | None:
        fields = {k: v for k, v in changes.items() if k != NAME}
        slots, data = _columns(obj, fields)
        values: dict[str, Any] = {
            **slots,
            "version": records.c.version + 1,
            "updated_by": by,
            "updated_at": sa.func.now(),
        }
        if NAME in changes:
            values["name"] = changes[NAME]
        if data:
            removed = [key for key, value in data.items() if value is None]
            kept = {key: value for key, value in data.items() if value is not None}
            values["data"] = records.c.data.op("-")(
                sa.cast(sa.literal(removed, ARRAY(sa.Text)), ARRAY(sa.Text))
            ).op("||")(sa.cast(sa.literal(json.dumps(kept)), JSONB))
        statement = (
            sa.update(records)
            .where(
                records.c.tenant_id == self._tenant,
                records.c.object_id == obj.object_id,
                records.c.id == record_id,
                records.c.version == version,
                records.c.deleted_at.is_(None),
            )
            .values(**values)
            .returning(records.c.version)
        )
        try:
            return await self.session.scalar(statement)  # type: ignore[no-any-return]
        except DBAPIError as exc:
            raise self._refusal(obj, exc) from exc

    async def soft_delete(self, record_id: uuid.UUID, version: int, by: uuid.UUID) -> int | None:
        statement = (
            sa.update(records)
            .where(
                records.c.tenant_id == self._tenant,
                records.c.id == record_id,
                records.c.version == version,
                records.c.deleted_at.is_(None),
            )
            .values(
                deleted_at=sa.func.now(),
                deleted_by=by,
                version=records.c.version + 1,
                updated_by=by,
                updated_at=sa.func.now(),
            )
            .returning(records.c.version)
        )
        try:
            return await self.session.scalar(statement)  # type: ignore[no-any-return]
        except DBAPIError as exc:
            if _sqlstate(exc) == _INSUFFICIENT_PRIVILEGE:
                raise WriteRefusedError() from exc
            raise

    async def keep_write_key(
        self, write_key: str, record_id: uuid.UUID, op: str, version: int, by: uuid.UUID
    ) -> bool:
        result = await self.session.execute(
            pg_insert(record_write_keys)
            .values(
                tenant_id=self._tenant,
                write_key=write_key,
                record_id=record_id,
                op=op,
                version=version,
                created=False,
                actor_id=by,
            )
            .on_conflict_do_nothing(constraint="pk_record_write_keys")
        )
        return bool(result.rowcount)

    async def outbox(self, event: OutboxEvent) -> None:
        await SqlOutboxRepository(self.session).add(event)

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)

    @staticmethod
    def _refusal(obj: AppliedObject, exc: DBAPIError) -> Exception:
        state, name = _sqlstate(exc), _constraint(exc)
        if state == _UNIQUE:
            slot = _SLOT_UNIQUE.match(name)
            if slot is not None:
                return DuplicateSlotError(_slot_field(obj, slot.group(1)))
            if _CREATE_KEY.match(name):
                return CreateKeyTakenError()
        if state == _INSUFFICIENT_PRIVILEGE or name == _OWNER_CHECK:
            return WriteRefusedError()
        return exc


@dataclass(frozen=True)
class SqlRecordWriteKeyRetention:
    """The purger registered for `studio.record_write_keys` (gate (p)): the
    definer function deletes every tenant's expired rows, which the retention
    lane would not see through the RESTRICTIVE policy. Housekeeping: it logs
    the count and writes no audit row (`CLAUDE.md` "Agent and tool rules")."""

    session_factory: async_sessionmaker[AsyncSession]

    async def purge(self) -> None:
        async with self.session_factory() as session, session.begin():
            removed = await session.scalar(_PURGE)
        logger.info(
            "record write keys purged",
            extra={"deleted": removed, "retention_class": RECORD_WRITE_KEYS},
        )
