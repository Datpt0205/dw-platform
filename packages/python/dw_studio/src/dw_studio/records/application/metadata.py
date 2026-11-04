"""`MetadataService.apply`: the `object` kind's publish hook (R1.1; ADR-0109
decision 1; ADR-0107 decisions 1, 5).

Agent-lifecycle calls it in the transaction that takes a version `live`, at
the `studio.publish.object.decided` handler and on the tighten-only branch
(agent-lifecycle R2.9, R5.5). In that transaction, in this order:

1. the exclusive advisory lock on the object (`object_lock_key`), so a slot is
   given once and RecordService's shared lock waits for the new definition;
2. nothing at all when the object already stands at this version;
3. `check_against_live` against the applied version's document, the last
   fence: a refusal is `ObjectVersionRejected` and the publish rolls back;
4. the object, its three system rows the first time, each field (a new one in
   the smallest free slot of its family or under the next `field_no`, an
   existing one with every attribute the document carries), each option,
   `applied_version_id` and `schema_version` (the version's `version_no`, no
   second counter); one audit event per row changed, keys and versions only.

It changes no stage and writes no `studio.version.published`: that event is
agent-lifecycle's, once per publish.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Final

from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.domain.audit import AuditEvent
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.domain.artifacts import DocumentInvalidError, DocumentProblem
from dw_studio.records.application.ports import AppliedObject, FieldStorage, ObjectDefinitionStore
from dw_studio.records.domain.document import (
    OBJECT_KIND,
    OWNER,
    WORKSPACE,
    FieldDefinition,
    FieldDocument,
    ObjectDocument,
    field_definition,
    name_definition,
    parse_object,
)
from dw_studio.records.domain.field_types import family_of, smallest_free_slot
from dw_studio.records.domain.rules import ObjectVersionRejected, check_against_live

RESOURCE: Final = "studio_object"

# Attributes a published field may change (R2.4 fixes the rest).
_MUTABLE: Final = (
    "labels",
    "ai_description",
    "required",
    "max_length",
    "pd_category",
    "sensitive_type",
    "subject_identifier",
)


def _system_row(api_name: str, type_: str, label: str) -> FieldDefinition:
    return FieldDefinition(
        api_name=api_name,
        type=type_,
        labels={"vi": label},
        ai_description=None,
        number_mode=None,
        scale=None,
        currency_code=None,
        max_length=None,
        required=True,
        is_unique=False,
        indexed=False,
        pd_category="none",
        sensitive_type=None,
        subject_identifier=None,
    )


# The two system rows no document decides: the record's owner and owning
# workspace, system columns of `studio.records` (R4.1).
OWNER_ROW: Final = _system_row(OWNER, "owner", "Người phụ trách")
WORKSPACE_ROW: Final = _system_row(WORKSPACE, "workspace", "Workspace sở hữu")


def _changes(before: FieldDefinition, after: FieldDefinition) -> dict[str, Any]:
    return {
        name: dict(getattr(after, name)) if name == "labels" else getattr(after, name)
        for name in _MUTABLE
        if getattr(before, name) != getattr(after, name)
    }


class MetadataService:
    def __init__(
        self,
        store_of: Callable[[ArtifactTx], ObjectDefinitionStore],
        clock: UtcClock,
        ids: IdGenerator,
    ) -> None:
        self.store_of = store_of
        self.clock = clock
        self.ids = ids

    async def apply(self, tx: ArtifactTx, version_id: uuid.UUID) -> None:
        store = self.store_of(tx)
        version = await store.version(version_id)
        if version is None or version.version_no is None:
            raise NotFoundError("object version not found")
        artifact = await tx.artifact(version.artifact_id)
        if artifact is None or artifact.kind != OBJECT_KIND:
            raise NotFoundError("object version not found")
        object_id = artifact.id
        await self.lock(store, object_id)
        applied = await store.applied(object_id)
        if applied is not None and applied.applied_version_id == version_id:
            return
        live_document = None
        if applied is not None:
            live = await store.version(applied.applied_version_id)
            live_document = None if live is None else live.document
        problems = check_against_live(live_document, version.document)
        if problems:
            raise ObjectVersionRejected("the version changes what is published", problems)
        try:
            document = parse_object(version.document)
        except DocumentInvalidError as exc:
            raise ObjectVersionRejected("the version is not valid", exc.problems) from None

        context = _Audit(self, tx, store, object_id, version_id, version.version_no)
        if applied is None:
            await store.insert_object(
                object_id=object_id,
                api_name=artifact.api_name,
                labels=document.labels.as_json(),
                ai_description=document.ai_description,
                default_access=document.default_access,
                version_id=version_id,
                version_no=version.version_no,
            )
            await context.event("studio.object.created")
            for row in (name_definition(document.name_field), OWNER_ROW, WORKSPACE_ROW):
                field_id = self.ids.new_uuid()
                await store.insert_field(
                    object_id=object_id,
                    field_id=field_id,
                    field=row,
                    storage_kind="system",
                    slot=None,
                    field_no=None,
                )
                await context.event(
                    "studio.field.created", field_id=field_id, api_name=row.api_name
                )
        else:
            await self._update_object(store, applied, document, context, version.version_no)
            await self._update_field(store, applied, name_definition(document.name_field), context)

        for n, field in enumerate(document.fields):
            if applied is not None and field.api_name in applied.storage:
                await self._update_field(store, applied, field_definition(field), context)
                continue
            placed = await self.add_field(store, object_id, field, at=f"/fields/{n}")
            await context.event(
                "studio.field.created", field_id=placed.field_id, api_name=field.api_name
            )
            if field.options:
                await store.put_options(placed.field_id, field_definition(field).options)
                await context.event(
                    "studio.picklist.updated", field_id=placed.field_id, api_name=field.api_name
                )

    async def lock(self, store: ObjectDefinitionStore, object_id: uuid.UUID) -> None:
        """Step 1, alone, for a caller that runs `add_field` itself (R1.5)."""
        await store.lock_object(object_id)

    async def add_field(
        self, store: ObjectDefinitionStore, object_id: uuid.UUID, field: FieldDocument, *, at: str
    ) -> FieldStorage:
        """A new field's storage, given under the object's lock: the smallest
        free slot of its family when it filters (R1.5), the next `field_no`
        otherwise; no free slot is `ObjectVersionRejected` (R1.6)."""
        field_id = self.ids.new_uuid()
        slot: str | None = None
        field_no: int | None = None
        family = family_of(field.type, number_mode=field.number_mode, is_unique=field.is_unique)
        if field.filters and family is not None:
            slot = smallest_free_slot(family, await store.used_slots(object_id))
            if slot is None:
                raise ObjectVersionRejected(
                    "no slot is free",
                    [DocumentProblem(at, "slot_budget_exceeded", f"family {family} is full")],
                )
        else:
            field_no = await store.take_field_no(object_id)
        kind = "slot" if slot is not None else "data"
        await store.insert_field(
            object_id=object_id,
            field_id=field_id,
            field=field_definition(field),
            storage_kind=kind,
            slot=slot,
            field_no=field_no,
        )
        return FieldStorage(field_id, kind, slot, field_no)

    @staticmethod
    async def _update_object(
        store: ObjectDefinitionStore,
        applied: AppliedObject,
        document: ObjectDocument,
        context: _Audit,
        version_no: int,
    ) -> None:
        await store.update_object(
            applied.object_id,
            labels=document.labels.as_json(),
            ai_description=document.ai_description,
            default_access=document.default_access,
            applied_version_id=context.version_id,
            schema_version=version_no,
        )
        await context.event("studio.object.updated")

    @staticmethod
    async def _update_field(
        store: ObjectDefinitionStore,
        applied: AppliedObject,
        after: FieldDefinition,
        context: _Audit,
    ) -> None:
        before = applied.definition.fields[after.api_name]
        field_id = applied.storage[after.api_name].field_id
        changes = _changes(before, after)
        if changes:
            await store.update_field(field_id, **changes)
            await context.event("studio.field.updated", field_id=field_id, api_name=after.api_name)
        if after.options != before.options:
            await store.put_options(field_id, after.options)
            await context.event(
                "studio.picklist.updated", field_id=field_id, api_name=after.api_name
            )


class _Audit:
    """The hook's audit events: the transaction's actor, keys and versions only."""

    def __init__(
        self,
        service: MetadataService,
        tx: ArtifactTx,
        store: ObjectDefinitionStore,
        object_id: uuid.UUID,
        version_id: uuid.UUID,
        version_no: int,
    ) -> None:
        self.service, self.tx, self.store = service, tx, store
        self.object_id, self.version_id, self.version_no = object_id, version_id, version_no

    async def event(self, action: str, **keys: object) -> None:
        context = self.store.context
        details: dict[str, object] = {
            "object_id": str(self.object_id),
            "version_id": str(self.version_id),
            "version_no": self.version_no,
        }
        details.update((name, str(value)) for name, value in keys.items())
        await self.tx.audit(
            AuditEvent(
                id=self.service.ids.new_uuid(),
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(context.workspace_id),
                actor_id=UserId(context.principal_id),
                action=action,
                resource_type=RESOURCE,
                resource_id=str(self.object_id),
                occurred_at=self.service.clock.now(),
                details=details,
            )
        )
