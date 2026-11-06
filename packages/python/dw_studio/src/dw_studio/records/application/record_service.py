"""`RecordService`: the one write path of a company's records, and the one
reader of what a caller may know of an object (custom-objects ticket 03; R3,
R5-R7; ADR-0107 decision 3).

Every door calls it: the REST routes, a workflow step (`RecordsPort`) and an
agent's object tool (`ObjectDataPort`). A door hands it a `RecordDoor`, whose
`transaction()` opens a transaction already bound: the company, the
principal, the actor kind (`bind_actor`) and the caller's reach row
(`studio.ensure_principal_scope()`). The service sets no `app.*` setting
(gate (c)); every transaction of its own (the audit of a refused duplicate,
the re-read after a lost race) opens through the same door, so it acts as
the same actor (gate (q)). Who the caller is, which workspace a new record
belongs to and the mode a run's row holds are all read back from that
transaction, never taken from the request.

A write, in ADR-0107's order (decision 3):

1. the object action key `obj.<api_name>.<action>`, from the principal's keys
   in the bound company: 403 `permission_denied` before any record is read
   (R3.4); an object of another company is 404 (R3.3);
2. a `wf:` key already used (`studio.record_write_keys`, or a record's
   `create_key`) answers with what its first write gave, before anything
   else (R5.10); another principal's is 409 `idempotency_conflict` (R5.11);
3. the duplicate-probe limit (R7.6), for a person and an agent;
4. `pg_advisory_xact_lock_shared` on the object, then its definition;
5. coercion and every value problem at once: 422 (R6.1-R6.5, R6.7);
6. the field decision of field-security/01 for the action: 403
   `field_not_editable` per field (R6.6);
7. the write, which the record policies decide (ADR-0105): a row the caller
   cannot read is 404 like a missing one (R5.7), one it reads and may not
   change is 403 (R5.8), a write that changes nothing included, a stale
   `If-Match` is 412 (R6.8);
8. the outbox event and the audit, in the same transaction (R5.2).

In `simulate`, and `test` (DO-26.1 (A)), every check runs and nothing is
written: the answer is the would-be record (R5.4). A duplicate is then judged
against the records the caller reads only (gate (h)).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Final, Literal, cast

from dw_kernel.errors import (
    ConflictError,
    DomainError,
    IdempotencyConflictError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
)
from dw_kernel.filters import ListQuery, QuerySchema
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import CursorPosition, build_page
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.run_mode import RunMode, child_mode
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.rate_limit import PrincipalObjectKey, RateLimiterPort
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent
from dw_studio.core.application.field_access import ActorUnboundError, Caller, FieldAccessService
from dw_studio.core.domain.artifacts import DocumentProblem
from dw_studio.core.domain.field_access import EDIT, HIDDEN, FieldAccess, FieldAction
from dw_studio.records.application.ports import (
    AppliedObject,
    CreateKeyTakenError,
    DuplicateSlotError,
    NewRecord,
    RecordStore,
    RecordTx,
    StoredRecord,
    WriteRefusedError,
)
from dw_studio.records.application.record_query import COUNT_CAP, SORTABLE, query_schema
from dw_studio.records.application.record_views import (
    Description,
    FieldView,
    ObjectEntry,
    OptionView,
    RecordPage,
    RecordView,
    WriteResult,
    readable,
    readable_names,
    record_view,
)
from dw_studio.records.application.schema_projector import (
    ObjectSchemaProjector,
    ObjectSchemas,
    narrowed,
)
from dw_studio.records.domain.document import NAME
from dw_studio.records.domain.errors import (
    FIELD_NOT_EDITABLE,
    FIELD_NOT_WRITABLE,
    DuplicateThrottledError,
    DuplicateValueError,
    FieldNotEditableError,
    RecordInvalidError,
)
from dw_studio.records.domain.values import (
    INVALID_TYPE,
    REQUIRED,
    UNKNOWN_FIELD,
    VALUE_NOT_ALLOWED,
    coerce_input,
    missing_required,
    pointer,
    problem,
)

ObjectAction = Literal["create", "read", "update", "delete", "assign"]
OBJECT_ACTIONS: Final[tuple[ObjectAction, ...]] = ("create", "read", "update", "delete", "assign")
DescribeAction = Literal["read", "create"]

# R7.6 (DO-35, Đạt 24/10/2026; provisional, FOG-11 measures again): 20
# `duplicate_value` refusals per company, principal and object in a sliding
# ten minutes.
DUPLICATE_LIMIT: Final = 20
DUPLICATE_WINDOW: Final = timedelta(minutes=10)
# Counted for a person and an agent; a workflow's probe is the intake's daily
# work under one service account, not a person probing (gate (d)).
_COUNTED_KINDS: Final = frozenset({"user", "agent"})
# The door a write came through, by the actor kind the transaction carries.
_CHANNELS: Final[Mapping[str, str]] = {"user": "api", "agent": "agent", "workflow": "workflow"}
_MODES: Final[frozenset[str]] = frozenset({"live", "test", "simulate"})
# The members of a write's body that no write sets (R6.7).
_NOT_WRITABLE: Final = ("owner", "workspace_id")

EVENT_SCHEMA: Final = "1.0"
RECORD_RESOURCE: Final = "studio_record"
OBJECT_RESOURCE: Final = "studio_object"
WF_PREFIX: Final = "wf:"


@dataclass(frozen=True, slots=True)
class RecordDoor:
    """How a caller reaches the service: ``transaction`` opens one
    transaction bound by the door (`user_session` for a person's request,
    the run's record session for a step or a tool), and ``run_id`` names the
    run behind it, for the event and the audit."""

    transaction: Callable[[], AbstractAsyncContextManager[Any]]
    run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class _Ctx:
    """Who acts, on what, read from the bound transaction once."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None
    principal_id: uuid.UUID
    kind: str
    object_id: uuid.UUID
    api_name: str
    run_id: uuid.UUID | None
    mode: RunMode

    @property
    def live(self) -> bool:
        return self.mode == "live"


@dataclass(frozen=True, slots=True)
class _Call:
    raw: Any
    tx: RecordTx
    caller: Caller
    ctx: _Ctx

    def holds(self, action: str) -> bool:
        return self.caller.holds(f"obj.{self.ctx.api_name}.{action}")


class _Duplicate(Exception):  # noqa: N818 - a signal out of the lost transaction
    def __init__(self, ctx: _Ctx, api_name: str) -> None:
        super().__init__(api_name)
        self.ctx, self.api_name = ctx, api_name


class _Throttled(Exception):  # noqa: N818
    def __init__(self, ctx: _Ctx, decision_retry_at: Any) -> None:
        super().__init__("throttled")
        self.ctx, self.retry_at = ctx, decision_retry_at


class _KeyRace(Exception):  # noqa: N818
    """Another attempt of the same principal wrote the key first."""


def record_not_found() -> NotFoundError:
    """R5.7: one answer for a record that is missing, another company's, or
    not readable, and for a transaction bound to no actor (R5.9)."""
    return NotFoundError("record not found")


def _object_not_found() -> NotFoundError:
    return NotFoundError("object not found")


def _stale() -> PreconditionFailedError:
    return PreconditionFailedError(
        "the record changed since the version named; read it again",
        details={"header": "If-Match"},
    )


def _refused(action: str) -> PermissionDeniedError:
    return PermissionDeniedError(f"the caller may not {action} this record")


def _mode(bound: str, asked: RunMode) -> RunMode:
    """The stricter of what the run's row says (`app.run_mode`, empty for a
    person) and what the door asked; an unreadable mode writes nothing
    (failure-modes #7)."""
    held: RunMode = "live" if bound == "" else "simulate"
    if bound in _MODES:
        held = cast(RunMode, bound)
    return child_mode(held, asked)


def _sent(body: Mapping[str, Any]) -> tuple[dict[str, Any], list[DocumentProblem]]:
    """The values a body sends, by `api_name` (`name` for the name), and the
    problems of its shape. Members that only describe the record (`id`,
    `version`, ...) are ignored; `owner` and `workspace_id` are refused (R6.7)."""
    problems = [
        DocumentProblem(f"/{member}", FIELD_NOT_WRITABLE, "this attribute is not written here")
        for member in _NOT_WRITABLE
        if member in body
    ]
    sent: dict[str, Any] = {}
    if NAME in body:
        sent[NAME] = body[NAME]
    fields = body.get("fields", {})
    if not isinstance(fields, Mapping):
        problems.append(problem("/fields", INVALID_TYPE))
        fields = {}
    for api_name, value in fields.items():
        if api_name == NAME or not isinstance(api_name, str):
            problems.append(problem(f"/fields/{api_name}", UNKNOWN_FIELD))
            continue
        sent[api_name] = value
    return sent, problems


def _invalid(problems: Sequence[DocumentProblem]) -> None:
    if problems:
        raise RecordInvalidError("the record has invalid values", problems)


def _editable(access: FieldAccess, names: Iterable[str]) -> None:
    """R6.6: every field the write names is `edit` for the caller, or 403 at
    each that is not. A hidden field's name is public, its value is not."""
    refused = [
        DocumentProblem(pointer(name), FIELD_NOT_EDITABLE, "the caller may not write this field")
        for name in sorted(names)
        if access.level_of(name) != EDIT
    ]
    if refused:
        raise FieldNotEditableError(refused)


def _kept(stored: StoredRecord, api_name: str) -> Any:
    return stored.name if api_name == NAME else stored.values.get(api_name)


class RecordService:
    def __init__(
        self,
        store: RecordStore,
        fields: FieldAccessService,
        limiter: RateLimiterPort,
        projector: ObjectSchemaProjector,
        clock: UtcClock,
        ids: IdGenerator,
    ) -> None:
        self.store = store
        self.fields = fields
        self.limiter = limiter
        self.projector = projector
        self.clock = clock
        self.ids = ids

    # ---- reads -----------------------------------------------------------------

    async def objects(self, door: RecordDoor) -> list[ObjectEntry]:
        """R3.5: the objects of the bound company whose read key the caller
        holds, each with every action it holds (gate (x))."""
        async with door.transaction() as raw:
            tx = await self._bind(raw)
            caller = await self._caller(raw)
            entries = []
            for summary in await tx.objects():
                actions = tuple(
                    a for a in OBJECT_ACTIONS if caller.holds(f"obj.{summary.api_name}.{a}")
                )
                if "read" in actions:
                    entries.append(
                        ObjectEntry(
                            summary.object_id,
                            summary.api_name,
                            summary.labels.get("vi", summary.api_name),
                            actions,
                        )
                    )
            return entries

    async def describe(self, door: RecordDoor, api_name: str, action: str = "read") -> Description:
        """R3.1-R3.4: the object as the caller may know it; `action=create`
        is the creation form, asked with the create key and decided with
        field-security's `create` branch."""
        if action not in ("read", "create"):
            raise DomainError("action is read or create", details={"parameter": "action"})
        async with door.transaction() as raw:
            call = await self._enter(raw, door, api_name, action, "live")
            obj = await self._definition(call)
            decided: FieldAction = "create" if action == "create" else "update"
            access = await self.fields.for_object(raw, obj.object_id, decided, caller=call.caller)
            return _description(obj, access)

    async def schemas(self, door: RecordDoor, api_name: str) -> ObjectSchemas:
        """R3.6, R3.7: the projector's schemas narrowed to the caller after
        its cache, never inside it (gate M5)."""
        async with door.transaction() as raw:
            call = await self._enter(raw, door, api_name, "read", "live")
            obj = await self._definition(call)
            accesses = await self.fields.for_actions(
                raw, obj.object_id, ("read", "update", "create"), caller=call.caller
            )
        full = await self.projector.schemas(call.ctx.tenant_id, obj.object_id, obj.schema_version)
        if full is None:
            raise _object_not_found()
        return narrowed(
            full,
            readable=_at_least(accesses["read"], HIDDEN),
            editable=_at_least(accesses["update"], "read"),
            creatable=_at_least(accesses["create"], "read"),
        )

    async def readable(self, door: RecordDoor, api_name: str) -> frozenset[str]:
        """The fields the caller reads of the object now, by `api_name`: what
        an agent's object tool is narrowed to before each model call
        (tools-and-skills R6.3), from the same decision `get` and `query`
        read in their own transaction, never kept."""
        async with door.transaction() as raw:
            call = await self._enter(raw, door, api_name, "read", "live")
            access = await self.fields.for_object(
                raw, call.ctx.object_id, "read", caller=call.caller
            )
            return readable_names(access)

    async def require(self, door: RecordDoor, api_name: str, action: ObjectAction) -> None:
        """The route's own check before an idempotency key row is read
        (app-standards R2.17): the object, then its action key."""
        async with door.transaction() as raw:
            await self._enter(raw, door, api_name, action, "live")

    async def get(self, door: RecordDoor, api_name: str, record_id: uuid.UUID) -> RecordView:
        async with door.transaction() as raw:
            call = await self._enter(raw, door, api_name, "read", "live")
            obj = await self._definition(call)
            stored = await call.tx.read(obj, record_id)
            if stored is None:
                raise record_not_found()
            access = await self.fields.for_object(raw, obj.object_id, "read", caller=call.caller)
            return record_view(obj, stored, access, call.caller.holds)

    async def query(
        self,
        door: RecordDoor,
        api_name: str,
        parse: Callable[[QuerySchema], ListQuery],
        *,
        count: bool = False,
    ) -> RecordPage:
        """R8: a page of the live records the caller reads, filtered, ordered
        and paged as ``parse`` reads the caller's query against the caller's
        own `QuerySchema` (`record_query`). In order: the object (404) and
        `obj.<api_name>.read` (403, R3.3, R3.4), then the field decision, then
        ``parse``, whose refusal (`QueryError`, 422) comes before any record
        SQL (R8.4-R8.7), then the page under the record policies. ``count``
        asks how many match (R8.8), counted on a first page only."""
        async with door.transaction() as raw:
            call = await self._enter(raw, door, api_name, "read", "live")
            obj = await self._definition(call)
            access = await self.fields.for_object(raw, obj.object_id, "read", caller=call.caller)
            listing = parse(query_schema(obj, readable_names(access)))
            rows = await call.tx.page(obj, listing)
            counted = None
            if count and listing.page.after is None:
                counted = await call.tx.count(obj, listing, COUNT_CAP)
        column = listing.order.field.column
        page = build_page(
            rows,
            request=listing.page,
            position_of=lambda row: CursorPosition(getattr(row, column), row.id),
        )
        chosen = None if listing.fields is None else frozenset(listing.fields)

        def shown(stored: StoredRecord) -> RecordView:
            view = record_view(obj, stored, access, call.caller.holds)
            if chosen is None:
                return view
            return replace(view, fields={k: v for k, v in view.fields.items() if k in chosen})

        return RecordPage(
            items=tuple(shown(row) for row in page.items),
            next_cursor=page.next_cursor,
            count=None if counted is None else min(counted, COUNT_CAP),
            count_capped=None if counted is None else counted > COUNT_CAP,
        )

    # ---- writes ----------------------------------------------------------------

    async def create(
        self,
        door: RecordDoor,
        api_name: str,
        body: Mapping[str, Any],
        *,
        effect: PendingEffect | None = None,
        write_key: str | None = None,
        run_mode: RunMode = "live",
    ) -> WriteResult:
        """R5.1: a record owned by the caller in the working workspace,
        version 1. ``write_key`` is a step's `wf:` key, kept as `create_key`
        (R5.3); ``effect`` an HTTP `Idempotency-Key`'s, claimed in the same
        transaction (app-standards R2.16)."""
        _check_write_key(write_key)

        async def act(call: _Call) -> WriteResult:
            return await self._create(call, body, effect, write_key)

        return await self._write(door, api_name, "create", run_mode, write_key, act)

    async def update(
        self,
        door: RecordDoor,
        api_name: str,
        record_id: uuid.UUID,
        patch: Mapping[str, Any],
        *,
        expected: int | None = None,
        write_key: str | None = None,
        run_mode: RunMode = "live",
    ) -> WriteResult:
        """A JSON Merge Patch on `name` and `fields` (R6), at ``expected``
        (`If-Match`) when given; a step's ``write_key`` is kept with the
        result (R5.9)."""
        _check_write_key(write_key)

        async def act(call: _Call) -> WriteResult:
            return await self._update(call, record_id, patch, expected, write_key)

        return await self._write(door, api_name, "update", run_mode, write_key, act)

    async def delete(
        self,
        door: RecordDoor,
        api_name: str,
        record_id: uuid.UUID,
        *,
        expected: int | None = None,
        run_mode: RunMode = "live",
    ) -> WriteResult:
        """R5.5: `deleted_at` and `deleted_by` set, the row kept. The new row
        must lie in the caller's `delete` reach: the WITH CHECK of the update
        policy decides it, not this service (gate (f))."""

        async def act(call: _Call) -> WriteResult:
            return await self._delete(call, record_id, expected)

        return await self._write(door, api_name, "delete", run_mode, None, act)

    async def upsert(
        self,
        door: RecordDoor,
        api_name: str,
        body: Mapping[str, Any],
        *,
        effect: PendingEffect | None = None,
        write_key: str | None = None,
        run_mode: RunMode = "live",
    ) -> WriteResult:
        """R7.2-R7.4: create by `match_field`, a unique field, or change the
        one live record holding its normalized value, as a merge patch (s).
        A record the caller cannot change answers like any duplicate: 409
        `duplicate_value`, never which record (R7.4)."""
        _check_write_key(write_key)

        async def act(call: _Call) -> WriteResult:
            return await self._upsert(call, body, effect, write_key)

        return await self._write(door, api_name, "create", run_mode, write_key, act)

    # ---- the pipeline ------------------------------------------------------------

    async def _write(
        self,
        door: RecordDoor,
        api_name: str,
        action: ObjectAction,
        run_mode: RunMode,
        write_key: str | None,
        act: Callable[[_Call], Awaitable[WriteResult]],
    ) -> WriteResult:
        try:
            async with door.transaction() as raw:
                call = await self._enter(raw, door, api_name, action, run_mode)
                try:
                    return await act(call)
                except DuplicateSlotError as duplicate:
                    raise _Duplicate(call.ctx, duplicate.api_name) from None
                except CreateKeyTakenError:
                    raise _KeyRace() from None
                except WriteRefusedError:
                    # The record policies' WITH CHECK, or the owner check.
                    raise _refused(action) from None
        except _Duplicate as refused:
            await self._duplicate_refused(door, refused.ctx, refused.api_name)
            raise DuplicateValueError(pointer(refused.api_name)) from None
        except _Throttled as throttled:
            await self._audit_alone(door, throttled.ctx, "studio.record.duplicate_throttled", {})
            raise DuplicateThrottledError(
                throttled.retry_at, self.clock.now(), DUPLICATE_WINDOW
            ) from None
        except _KeyRace:
            # The other attempt committed first: its result, read in a new
            # transaction of the same door (gate (q)), or 409 when it is not
            # this principal's (gate (u)).
            async with door.transaction() as raw:
                call = await self._enter(raw, door, api_name, action, run_mode)
                replay = await self._replayed(call, write_key)
            if replay is None:
                raise _key_conflict() from None
            return replay

    async def _bind(self, raw: Any) -> RecordTx:
        try:
            return await self.store.bind(raw)
        except ActorUnboundError:
            raise record_not_found() from None

    async def _caller(self, raw: Any) -> Caller:
        try:
            return await self.fields.caller(raw)
        except ActorUnboundError:
            raise record_not_found() from None

    async def _enter(
        self, raw: Any, door: RecordDoor, api_name: str, action: str, run_mode: RunMode
    ) -> _Call:
        tx = await self._bind(raw)
        object_id = await tx.object_id(api_name)
        if object_id is None:
            raise _object_not_found()
        caller = await self._caller(raw)
        if not caller.holds(f"obj.{api_name}.{action}"):
            raise PermissionDeniedError(
                f"the caller may not {action} records of this object",
                details={"action": f"obj.{api_name}.{action}"},
            )
        binding = tx.binding
        ctx = _Ctx(
            tenant_id=binding.tenant_id,
            workspace_id=binding.workspace_id,
            principal_id=caller.actor.principal_id,
            kind=caller.actor.kind,
            object_id=object_id,
            api_name=api_name,
            run_id=door.run_id,
            mode=_mode(binding.run_mode, run_mode),
        )
        return _Call(raw, tx, caller, ctx)

    async def _definition(self, call: _Call) -> AppliedObject:
        obj = await call.tx.definition(call.ctx.object_id)
        if obj is None:
            raise _object_not_found()
        return obj

    async def _snapshot(self, call: _Call) -> AppliedObject:
        """Step 4: the shared lock, then the definition it holds still."""
        await call.tx.lock_shared(call.ctx.object_id)
        return await self._definition(call)

    async def _not_throttled(self, call: _Call) -> None:
        """Step 3 (R7.6): asked without counting before every write of a
        counted actor kind; a refusal is raised out of the transaction."""
        if not call.ctx.live or call.ctx.kind not in _COUNTED_KINDS:
            return
        decision = await self.limiter.peek(_limit_key(call.ctx), DUPLICATE_LIMIT, DUPLICATE_WINDOW)
        if not decision.allowed:
            raise _Throttled(call.ctx, decision.retry_at)

    async def _replayed(self, call: _Call, write_key: str | None) -> WriteResult | None:
        """Step 2 (R5.10, R5.11, gate (b)): the key in both places a `wf:` key
        may sit. Another principal's `create_key` is a conflict; another's
        write key row is not even seen (RESTRICTIVE), its PK the only trace."""
        if write_key is None:
            return None
        keyed = await call.tx.written(write_key)
        if keyed is None:
            keyed = await call.tx.by_create_key(call.ctx.object_id, write_key)
            if keyed is not None and keyed.actor_id != call.ctx.principal_id:
                raise _key_conflict()
        if keyed is None:
            return None
        obj = await self._definition(call)
        stored = await call.tx.read(obj, keyed.record_id)
        if stored is None or stored.object_id != obj.object_id:
            raise _key_conflict()
        return WriteResult(
            await self._view(call, obj, stored),
            created=keyed.created,
            version=keyed.version,
            replayed=True,
        )

    async def _view(self, call: _Call, obj: AppliedObject, stored: StoredRecord) -> RecordView:
        access = await self.fields.for_object(call.raw, obj.object_id, "read", caller=call.caller)
        return record_view(obj, stored, access, call.caller.holds)

    def _workspace(self, call: _Call) -> uuid.UUID:
        if call.ctx.workspace_id is None:
            raise PermissionDeniedError("the request names no working workspace")
        return call.ctx.workspace_id

    async def _create(
        self,
        call: _Call,
        body: Mapping[str, Any],
        effect: PendingEffect | None,
        write_key: str | None,
    ) -> WriteResult:
        replay = await self._replayed(call, write_key)
        if replay is not None:
            return replay
        await self._not_throttled(call)
        record_id = self.ids.new_uuid()
        if effect is not None and call.ctx.live:
            await call.tx.claim(effect.of(record_id))
        obj = await self._snapshot(call)
        sent, problems = _sent(body)
        coerced = coerce_input(obj.definition.fields, sent, creating=True)
        _invalid([*problems, *coerced.problems])
        _editable(await self._access(call, obj, "create"), sent)
        new = NewRecord(
            id=record_id,
            workspace_id=self._workspace(call),
            owner_id=call.ctx.principal_id,
            name=str(coerced.values[NAME]),
            values={k: v for k, v in coerced.values.items() if k != NAME},
            create_key=write_key,
        )
        if not call.ctx.live:
            await self._no_readable_duplicate(call, obj, coerced.values, None)
            return WriteResult(await self._would_be(call, obj, new), created=True, version=1)
        await call.tx.insert(obj, new, arbiter=None)
        return await self._created(call, obj, new, sorted(coerced.values), effect, write_key)

    async def _created(
        self,
        call: _Call,
        obj: AppliedObject,
        new: NewRecord,
        changed: Sequence[str],
        effect: PendingEffect | None,
        write_key: str | None,
    ) -> WriteResult:
        await self._events(
            call,
            "created",
            record_id=new.id,
            version=1,
            workspace_id=new.workspace_id,
            owner_id=new.owner_id,
            changed=changed,
            operation_id=_operation_id(effect, write_key),
        )
        stored = await call.tx.read(obj, new.id)
        view = (
            await self._view(call, obj, stored)
            if stored is not None
            # A creator who does not read the object sees what it may of what
            # it wrote: nothing hidden, no permission.
            else await self._would_be(call, obj, new)
        )
        return WriteResult(view, created=True, version=1)

    async def _update(
        self,
        call: _Call,
        record_id: uuid.UUID,
        patch: Mapping[str, Any],
        expected: int | None,
        write_key: str | None,
    ) -> WriteResult:
        replay = await self._replayed(call, write_key)
        if replay is not None:
            return replay
        await self._not_throttled(call)
        obj = await self._snapshot(call)
        current = await call.tx.read(obj, record_id)
        if current is None or current.deleted_at is not None:
            raise record_not_found()
        sent, problems = _sent(patch)
        coerced = coerce_input(obj.definition.fields, sent, creating=False)
        _invalid([*problems, *coerced.problems])
        _editable(await self._access(call, obj, "update"), sent)
        return await self._apply(call, obj, current, coerced.values, expected, write_key, "update")

    async def _apply(
        self,
        call: _Call,
        obj: AppliedObject,
        current: StoredRecord,
        values: Mapping[str, Any],
        expected: int | None,
        write_key: str | None,
        op: str,
    ) -> WriteResult:
        """A merge patch of ``values`` onto ``current``, conditional on
        ``expected`` or the version read. Nothing changed writes nothing:
        no version, no event, no audit (gate (s)).

        Where no UPDATE runs for the policy to decide (nothing changed, or a
        simulation), the row's `may_update`, the policy's own text, decides
        instead: a record the caller reads and may not change is 403 (R5.8,
        app-standards R3.16), which the upsert answers as 409 (R7.4), and no
        `wf:` key is kept for it (custom-objects ticket 11)."""
        changes = {k: v for k, v in values.items() if _kept(current, k) != v}
        version = current.version if expected is None else expected
        may_change = call.holds("update") and current.may_update
        if not changes:
            if version != current.version:
                raise _stale()
            if not may_change:
                raise _refused("change")
            if write_key is not None and call.ctx.live:
                await self._keep_key(call, write_key, current.id, op, current.version)
            return WriteResult(await self._view(call, obj, current), False, current.version)
        if not call.ctx.live:
            if not may_change:
                raise _refused("change")
            if version != current.version:
                raise _stale()
            await self._no_readable_duplicate(call, obj, changes, current.id)
            would_be = _changed(current, changes, self.clock.now(), call.ctx.principal_id)
            return WriteResult(await self._view(call, obj, would_be), False, would_be.version)
        new_version = await call.tx.update(obj, current.id, version, changes, call.ctx.principal_id)
        if new_version is None:
            replay = await self._replayed(call, write_key)
            if replay is not None:
                return replay
            raise await self._why_not(call, obj, current.id, version, "change")
        if write_key is not None:
            await self._keep_key(call, write_key, current.id, op, new_version)
        await self._events(
            call,
            "updated",
            record_id=current.id,
            version=new_version,
            workspace_id=current.workspace_id,
            owner_id=current.owner_id,
            changed=sorted(changes),
            operation_id=write_key,
        )
        stored = await call.tx.read(obj, current.id)
        if stored is None:
            raise record_not_found()
        return WriteResult(await self._view(call, obj, stored), False, new_version)

    async def _delete(self, call: _Call, record_id: uuid.UUID, expected: int | None) -> WriteResult:
        await self._not_throttled(call)
        obj = await self._snapshot(call)
        current = await call.tx.read(obj, record_id)
        if current is None or current.deleted_at is not None:
            raise record_not_found()
        version = current.version if expected is None else expected
        if not call.ctx.live:
            if not current.may_delete:
                raise _refused("delete")
            if version != current.version:
                raise _stale()
            now = self.clock.now()
            would_be = replace(
                current,
                version=current.version + 1,
                deleted_at=now,
                deleted_by=call.ctx.principal_id,
                updated_at=now,
                updated_by=call.ctx.principal_id,
            )
            return WriteResult(await self._view(call, obj, would_be), False, would_be.version)
        try:
            new_version = await call.tx.soft_delete(current.id, version, call.ctx.principal_id)
        except WriteRefusedError:
            # The update policy's WITH CHECK: the new row is outside the
            # caller's `delete` reach (gate (f), record-access:R2.7).
            raise _refused("delete") from None
        if new_version is None:
            raise await self._why_not(call, obj, current.id, version, "delete")
        await self._events(
            call,
            "deleted",
            record_id=current.id,
            version=new_version,
            workspace_id=current.workspace_id,
            owner_id=current.owner_id,
            changed=(),
            operation_id=None,
        )
        stored = await call.tx.read(obj, current.id)
        if stored is None:
            raise record_not_found()
        return WriteResult(await self._view(call, obj, stored), False, new_version)

    async def _upsert(
        self,
        call: _Call,
        body: Mapping[str, Any],
        effect: PendingEffect | None,
        write_key: str | None,
    ) -> WriteResult:
        replay = await self._replayed(call, write_key)
        if replay is not None:
            return replay
        await self._not_throttled(call)
        obj = await self._snapshot(call)
        fields = obj.definition.fields
        match = body.get("match_field")
        if not isinstance(match, str) or match not in fields or not fields[match].is_unique:
            raise RecordInvalidError(
                "match_field is not a unique field of the object",
                [DocumentProblem("/match_field", VALUE_NOT_ALLOWED, "name a unique field")],
            )
        sent, problems = _sent(body)
        coerced = coerce_input(fields, sent, creating=False)
        problems.extend(coerced.problems)
        if coerced.values.get(match) is None and not any(
            p.pointer == pointer(match) for p in problems
        ):
            problems.append(problem(pointer(match), REQUIRED))
        _invalid(problems)
        value = coerced.values[match]

        existing = await call.tx.match(obj, match, value)
        if existing is None:
            _invalid(missing_required(fields, sent))
            _editable(await self._access(call, obj, "create"), sent)
            new = NewRecord(
                id=self.ids.new_uuid(),
                workspace_id=self._workspace(call),
                owner_id=call.ctx.principal_id,
                name=str(coerced.values[NAME]),
                values={k: v for k, v in coerced.values.items() if k != NAME},
                create_key=write_key,
            )
            if not call.ctx.live:
                # Only records the caller reads were compared: nothing else
                # is probed in a simulation (gate (h)).
                return WriteResult(await self._would_be(call, obj, new), created=True, version=1)
            if await call.tx.insert(obj, new, arbiter=match):
                if effect is not None:
                    await call.tx.claim(effect.of(new.id))
                return await self._created(
                    call, obj, new, sorted(coerced.values), effect, write_key
                )
            # Another write holds the value: a concurrent upsert that has
            # committed now, or a record the caller does not read.
            existing = await call.tx.match(obj, match, value)
            if existing is None:
                raise _Duplicate(call.ctx, match)
        return await self._upsert_existing(
            call, obj, existing, match, sent, coerced.values, effect, write_key
        )

    async def _upsert_existing(
        self,
        call: _Call,
        obj: AppliedObject,
        existing: StoredRecord,
        match: str,
        sent: Mapping[str, Any],
        values: Mapping[str, Any],
        effect: PendingEffect | None,
        write_key: str | None,
    ) -> WriteResult:
        """The update branch (s): the record found is changed like a `PATCH`,
        or, when the caller may not change it, refused as a duplicate (R7.4)."""

        def duplicate() -> Exception:
            if call.ctx.live:
                return _Duplicate(call.ctx, match)
            return DuplicateValueError(pointer(match))

        if not call.holds("update"):
            raise duplicate()
        _editable(await self._access(call, obj, "update"), (k for k in sent if k != match))
        if effect is not None and call.ctx.live:
            await call.tx.claim(effect.of(existing.id))
        try:
            return await self._apply(call, obj, existing, values, None, write_key, "upsert")
        except PermissionDeniedError:
            raise duplicate() from None
        except PreconditionFailedError:
            raise ConflictError(
                "a concurrent write changed the record; try again",
                details={"reason_code": "concurrent_write"},
            ) from None

    async def _access(self, call: _Call, obj: AppliedObject, action: FieldAction) -> FieldAccess:
        return await self.fields.for_object(call.raw, obj.object_id, action, caller=call.caller)

    async def _no_readable_duplicate(
        self,
        call: _Call,
        obj: AppliedObject,
        values: Mapping[str, Any],
        record_id: uuid.UUID | None,
    ) -> None:
        """A simulated write's uniqueness, against the records the caller
        reads only, by a SELECT under the record policies (gate (h)): no
        audit, no count, nothing probed past them."""
        for api_name in sorted(values):
            definition = obj.definition.fields.get(api_name)
            if definition is None or not definition.is_unique or values[api_name] is None:
                continue
            found = await call.tx.match(obj, api_name, values[api_name])
            if found is not None and found.id != record_id:
                raise DuplicateValueError(pointer(api_name))

    async def _would_be(self, call: _Call, obj: AppliedObject, new: NewRecord) -> RecordView:
        now = self.clock.now()
        stored = StoredRecord(
            id=new.id,
            object_id=obj.object_id,
            workspace_id=new.workspace_id,
            owner_kind="user",
            owner_id=new.owner_id,
            name=new.name,
            version=1,
            created_at=now,
            created_by=call.ctx.principal_id,
            updated_at=now,
            updated_by=call.ctx.principal_id,
            deleted_at=None,
            deleted_by=None,
            values=new.values,
            may_update=False,
            may_delete=False,
        )
        return await self._view(call, obj, stored)

    async def _why_not(
        self, call: _Call, obj: AppliedObject, record_id: uuid.UUID, version: int, action: str
    ) -> Exception:
        """A conditional write that matched no row, told apart under the
        caller's own authority (app-standards R3.9): gone or unreadable is
        404, another version 412, otherwise the policy refused it, 403."""
        now = await call.tx.read(obj, record_id)
        if now is None or now.deleted_at is not None:
            return record_not_found()
        if now.version != version:
            return _stale()
        return _refused(action)

    async def _keep_key(
        self, call: _Call, write_key: str, record_id: uuid.UUID, op: str, version: int
    ) -> None:
        """R5.9: the key with the result, in the write's transaction. A PK
        already held: this principal's concurrent attempt (rolled back, its
        result replayed) or another's (409)."""
        if await call.tx.keep_write_key(write_key, record_id, op, version, call.ctx.principal_id):
            return
        if await call.tx.written(write_key) is not None:
            raise _KeyRace()
        raise _key_conflict()

    async def _events(
        self,
        call: _Call,
        verb: str,
        *,
        record_id: uuid.UUID,
        version: int,
        workspace_id: uuid.UUID,
        owner_id: uuid.UUID,
        changed: Sequence[str],
        operation_id: str | None,
    ) -> None:
        """R5.2: one outbox event and one audit, field keys only (gate (w))."""
        ctx, now = call.ctx, self.clock.now()
        event_type = f"studio.record.{verb}"
        await call.tx.outbox(
            OutboxEvent(
                id=self.ids.new_uuid(),
                tenant_id=TenantId(ctx.tenant_id),
                workspace_id=WorkspaceId(workspace_id),
                event_type=event_type,
                schema_version=EVENT_SCHEMA,
                aggregate_id=record_id,
                occurred_at=now,
                actor_id=ctx.principal_id,
                payload={
                    "object_id": str(ctx.object_id),
                    "record_id": str(record_id),
                    "version": version,
                    "workspace_id": str(workspace_id),
                    "owner_kind": "user",
                    "owner_id": str(owner_id),
                    "changed_fields": list(changed),
                    "channel": _CHANNELS.get(ctx.kind, ctx.kind),
                    "run_id": None if ctx.run_id is None else str(ctx.run_id),
                    "operation_id": operation_id,
                    "run_mode": ctx.mode,
                },
            )
        )
        await call.tx.audit(
            AuditEvent(
                id=self.ids.new_uuid(),
                tenant_id=TenantId(ctx.tenant_id),
                workspace_id=WorkspaceId(workspace_id),
                actor_id=UserId(ctx.principal_id),
                action=event_type,
                resource_type=RECORD_RESOURCE,
                resource_id=str(record_id),
                occurred_at=now,
                run_id=ctx.run_id,
                details={"fields": list(changed), "version": version},
            )
        )

    async def _duplicate_refused(self, door: RecordDoor, ctx: _Ctx, api_name: str) -> None:
        """R7.5: the audit, in its own transaction since the write's rolled
        back; then one count for a counted actor kind (R7.6)."""
        await self._audit_alone(door, ctx, "studio.record.duplicate_refused", {"field": api_name})
        if ctx.kind in _COUNTED_KINDS:
            await self.limiter.acquire(_limit_key(ctx), DUPLICATE_LIMIT, DUPLICATE_WINDOW)

    async def _audit_alone(
        self, door: RecordDoor, ctx: _Ctx, action: str, details: Mapping[str, object]
    ) -> None:
        """One audit of the object in a transaction of its own, through the
        same door (gate (q)): the object, the field key, the caller as the
        actor; never a value or a record id (R7.5, R7.8)."""
        if ctx.workspace_id is None:
            raise PermissionDeniedError("the request names no working workspace")
        async with door.transaction() as raw:
            tx = await self._bind(raw)
            await tx.audit(
                AuditEvent(
                    id=self.ids.new_uuid(),
                    tenant_id=TenantId(ctx.tenant_id),
                    workspace_id=WorkspaceId(ctx.workspace_id),
                    actor_id=UserId(ctx.principal_id),
                    action=action,
                    resource_type=OBJECT_RESOURCE,
                    resource_id=str(ctx.object_id),
                    occurred_at=self.clock.now(),
                    run_id=ctx.run_id,
                    details={"object_id": str(ctx.object_id), **details},
                )
            )


def _check_write_key(write_key: str | None) -> None:
    """Only a step's `wf:` key reaches `create_key` or a key row (gate (a));
    a route never passes one, whatever its `Idempotency-Key` says."""
    if write_key is not None and not write_key.startswith(WF_PREFIX):
        raise ValueError("a record write key is a workflow step's `wf:` key")


def _key_conflict() -> IdempotencyConflictError:
    return IdempotencyConflictError(
        "this write key was used by another principal or for another record",
        details={"hint": "a step's key is its own; nothing was written"},
    )


def _limit_key(ctx: _Ctx) -> PrincipalObjectKey:
    return PrincipalObjectKey(TenantId(ctx.tenant_id), ctx.principal_id, ctx.object_id)


def _operation_id(effect: PendingEffect | None, write_key: str | None) -> str | None:
    if write_key is not None:
        return write_key
    return None if effect is None else effect.key.idempotency_key


def _changed(
    current: StoredRecord, changes: Mapping[str, Any], now: Any, by: uuid.UUID
) -> StoredRecord:
    values = {**current.values, **{k: v for k, v in changes.items() if k != NAME}}
    name = changes.get(NAME, current.name)
    return replace(
        current,
        name=str(name),
        values=values,
        version=current.version + 1,
        updated_at=now,
        updated_by=by,
    )


def _at_least(access: FieldAccess, below: str) -> frozenset[str]:
    """The field names whose level is above ``below``: `HIDDEN` gives the
    readable ones, `read` the editable ones."""
    order = {HIDDEN: 0, "read": 1, EDIT: 2}
    return frozenset(
        name
        for field, name in access.api_names.items()
        if order[access.levels[field]] > order[below]
    )


def _description(obj: AppliedObject, access: FieldAccess) -> Description:
    """R3.1, R3.2: every field of the object; a hidden one with its name,
    label and `access` only, nothing it holds or how it is described."""
    views = []
    for api_name in (NAME, *sorted(n for n in obj.definition.fields if n != NAME)):
        definition = obj.definition.fields[api_name]
        level = access.level_of(api_name) or HIDDEN
        label = definition.labels.get("vi", api_name)
        if not readable(access, api_name):
            views.append(FieldView(api_name=api_name, label=label, access=HIDDEN))
            continue
        storage = obj.storage[api_name]
        filters = storage.storage_kind == "slot"
        views.append(
            FieldView(
                api_name=api_name,
                label=label,
                access=level,
                type=definition.type,
                ai_description=definition.ai_description,
                number_mode=definition.number_mode,
                scale=definition.scale,
                currency_code=definition.currency_code,
                max_length=definition.max_length,
                required=definition.required,
                unique=definition.is_unique,
                editable=level == EDIT,
                filterable=filters or api_name == NAME,
                # W1 sorts on `name`, `created_at` and `updated_at` only (R8.2).
                sortable=api_name in SORTABLE,
                options=tuple(
                    OptionView(o.key, o.labels.get("vi", o.key), o.position, o.active)
                    for o in sorted(definition.options, key=lambda o: (o.position, o.key))
                ),
            )
        )
    return Description(
        object_id=obj.object_id,
        api_name=obj.api_name,
        label=obj.definition.labels.get("vi", obj.api_name),
        ai_description=obj.definition.ai_description,
        schema_version=obj.schema_version,
        fields=tuple(views),
    )
