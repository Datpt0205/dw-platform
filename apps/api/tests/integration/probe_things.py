"""A versioned resource and a queryable list that live only in tests.

app-standards ticket 03 step 8. `probe.things` is made by the fixture on the
test database as `dw_migrator`, shaped like a real tenant table: RLS ENABLEd
and FORCEd with the tenant policy, `dw_app` grants, the platform's
`touch_updated_at` trigger, and two policies a real resource has reasons for:

* a RESTRICTIVE UPDATE policy by owner, so a person who can read a row and may
  not change it exists, and R3.13's 403 branch is real;
* a RESTRICTIVE SELECT policy hiding a `private` row from everyone but its
  owner, so "out of the caller's reach" is real (R3.7, APS16).

The routes are mounted on the test's app, never on the real one; their service
does what a route that turned R3 on is required to: the effect key first in the
write's transaction (R2.34, R2.38), the comparison inside the write itself
(R3.9), and a write that matched nothing told apart under the caller's own
authority (R3.13).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.conditions import IfNoneMatchAny, MergePatch, RequireIfMatch
from dw_api.dependencies.idempotency import IdempotentOperation, idempotent
from dw_api.dependencies.listing import query_body, queryable
from dw_kernel.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
)
from dw_kernel.filters import ListQuery, QueryField, QuerySchema, compile_filter
from dw_kernel.http_conditions import ExpectedVersion, apply_merge_patch, etag_of
from dw_kernel.pagination import CursorPosition, Page, SortType, build_page
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.keyset import keyset_phases, keyset_rows
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect

PROBE_WRITE = "probe.write"
PREFIX = "/api/v1/probe/objects/{object_id}/things"

DDL = [
    "DROP SCHEMA IF EXISTS probe CASCADE",
    "CREATE SCHEMA probe",
    "GRANT USAGE ON SCHEMA probe TO dw_app",
    """
    CREATE TABLE probe.things (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        object_id uuid NOT NULL,
        owner_id uuid NOT NULL,
        private boolean NOT NULL DEFAULT false,
        name text,
        age integer,
        flag boolean,
        note text,
        rank integer,
        data jsonb NOT NULL DEFAULT '{}',
        state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived')),
        version integer NOT NULL DEFAULT 1,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_things PRIMARY KEY (tenant_id, id)
    )
    """,
    "CREATE INDEX ix_things_name ON probe.things (tenant_id, object_id, name, id, age, flag)",
    "CREATE INDEX ix_things_age ON probe.things (tenant_id, object_id, age, id)",
    "ALTER TABLE probe.things ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE probe.things FORCE ROW LEVEL SECURITY",
    """
    CREATE POLICY tenant_isolation_things ON probe.things
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """,
    """
    CREATE POLICY owner_reads_private_things ON probe.things AS RESTRICTIVE FOR SELECT
        USING (NOT private OR owner_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    """,
    """
    CREATE POLICY owner_updates_things ON probe.things AS RESTRICTIVE FOR UPDATE
        USING (owner_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON probe.things TO dw_app",
    """
    CREATE TRIGGER touch_updated_at BEFORE UPDATE ON probe.things
        FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()
    """,
]

_meta = sa.MetaData()
things = sa.Table(
    "things",
    _meta,
    sa.Column("tenant_id", UUID(as_uuid=True)),
    sa.Column("id", UUID(as_uuid=True)),
    sa.Column("object_id", UUID(as_uuid=True)),
    sa.Column("owner_id", UUID(as_uuid=True)),
    sa.Column("private", sa.Boolean),
    sa.Column("name", sa.Text),
    sa.Column("age", sa.Integer),
    sa.Column("flag", sa.Boolean),
    sa.Column("note", sa.Text),
    sa.Column("rank", sa.Integer),
    sa.Column("data", JSONB),
    sa.Column("state", sa.Text),
    sa.Column("version", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    schema="probe",
)

ORDERED = frozenset({"$eq", "$in", "$lt", "$lte", "$gt", "$gte"})
SCHEMA = QuerySchema(
    fields=(
        QueryField(
            "name", SortType.TEXT, "name", True, True, frozenset({"$eq", "$in", "$lt", "$gt"})
        ),
        QueryField("age", SortType.INT, "age", True, True, ORDERED),
        QueryField("flag", SortType.BOOL, "flag", True, False, frozenset({"$eq"})),
        # Declared and nothing more: closed by default (R5.15).
        QueryField("note", SortType.TEXT, "note"),
    ),
    default_order=("name", False),
    logical=frozenset({"$and", "$or", "$not"}),
)


class ThingView(BaseModel):
    id: str
    object_id: str
    name: str | None
    age: int | None
    flag: bool | None
    note: str | None
    data: dict[str, Any]
    state: str
    version: int


class ThingFields(BaseModel):
    """What a client writes: on a create, and as the document a patch merges into."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    age: int | None = None
    flag: bool | None = None
    note: str | None = None
    data: dict[str, Any] = {}


class NewThing(ThingFields):
    id: uuid.UUID | None = None


_FIELDS = ("name", "age", "flag", "note", "data")


def view_of(row: Any) -> ThingView:
    return ThingView(
        id=str(row.id),
        object_id=str(row.object_id),
        name=row.name,
        age=row.age,
        flag=row.flag,
        note=row.note,
        data=dict(row.data or {}),
        state=row.state,
        version=row.version,
    )


Hook = Callable[[str], Awaitable[None]]


async def _no_hook(_: str) -> None:
    return None


@dataclass
class ProbeThings:
    """The service behind the probe routes."""

    engine: AsyncEngine
    # Awaited just before a write's own statement: a test's barrier.
    before_write: Hook = _no_hook
    sessions: async_sessionmaker[AsyncSession] = field(init=False)

    def __post_init__(self) -> None:
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def _scope(self, context: AccessContext) -> TenantScope:
        return TenantScope.from_access_context(context)

    @staticmethod
    def check(context: AccessContext) -> None:
        if PROBE_WRITE not in context.scopes:
            raise PermissionDeniedError("missing permission", details={"action": PROBE_WRITE})

    async def _audit(
        self, session: AsyncSession, context: AccessContext, action: str, id_: uuid.UUID
    ) -> None:
        await session.execute(
            sa.text(
                "INSERT INTO platform.audit_events (id, tenant_id, workspace_id, actor_id, action,"
                " resource_type, resource_id, occurred_at)"
                " VALUES (:id, :t, :w, :a, :action, 'probe_thing', :r, now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": context.tenant_id,
                "w": context.workspace_id,
                "a": context.principal_id,
                "action": action,
                "r": str(id_),
            },
        )

    async def get(self, context: AccessContext, object_id: uuid.UUID, id_: uuid.UUID) -> ThingView:
        async with tenant_session(self.sessions, self._scope(context)) as session:
            row = await self._load(session, object_id, id_)
        if row is None:
            raise NotFoundError("thing not found")
        return view_of(row)

    @staticmethod
    async def _load(session: AsyncSession, object_id: uuid.UUID, id_: uuid.UUID) -> Any:
        return (
            await session.execute(
                sa.select(things).where(things.c.id == id_, things.c.object_id == object_id)
            )
        ).one_or_none()

    async def _unmatched(
        self, session: AsyncSession, object_id: uuid.UUID, id_: uuid.UUID, expected: ExpectedVersion
    ) -> Exception:
        """R3.13: the write matched no row; read it again as the caller."""
        row = await self._load(session, object_id, id_)
        if row is None:
            return NotFoundError("thing not found")
        if not expected.matches(row.version):
            return PreconditionFailedError("the thing changed since it was read")
        return PermissionDeniedError("you may read this thing and not change it")

    async def create(
        self,
        context: AccessContext,
        object_id: uuid.UUID,
        new: NewThing,
        only_if_absent: bool,
        effect: PendingEffect | None,
    ) -> ThingView:
        self.check(context)
        id_ = new.id or uuid.uuid4()
        async with tenant_session(self.sessions, self._scope(context)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(id_))
            await self.before_write("create")
            # The existence check is the insert itself (R3.4): a concurrent
            # create of the same id waits on the key, then inserts nothing.
            inserted = (
                await session.execute(
                    sa.dialects.postgresql.insert(things)
                    .values(
                        tenant_id=context.tenant_id,
                        id=id_,
                        object_id=object_id,
                        owner_id=context.principal_id,
                        **new.model_dump(include=set(_FIELDS)),
                    )
                    .on_conflict_do_nothing(constraint="pk_things")
                    .returning(things)
                )
            ).one_or_none()
            if inserted is None:
                if only_if_absent:
                    raise PreconditionFailedError("a thing with this id exists")
                raise ConflictError("a thing with this id exists")
            await self._audit(session, context, "probe.created", id_)
        return view_of(inserted)

    async def patch(
        self,
        context: AccessContext,
        object_id: uuid.UUID,
        id_: uuid.UUID,
        expected: ExpectedVersion,
        patch: dict[str, Any],
        effect: PendingEffect | None,
    ) -> ThingView:
        self.check(context)
        async with tenant_session(self.sessions, self._scope(context)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(id_))
            row = await self._load(session, object_id, id_)
            if row is None:
                raise NotFoundError("thing not found")
            current = {name: getattr(row, name) for name in _FIELDS}
            try:
                merged = ThingFields.model_validate(apply_merge_patch(current, patch))
            except ValidationError:
                raise DomainError("the patch does not fit a thing") from None
            values = merged.model_dump()
            changed = values != {**current, "data": dict(current["data"] or {})}
            await self.before_write("patch")
            guard = (
                things.c.id == id_,
                things.c.object_id == object_id,
                # Never true for a weak or foreign tag: the reread says 412.
                things.c.version == (expected.version if expected.version is not None else -1),
            )
            if changed:
                written = (
                    await session.execute(
                        sa.update(things)
                        .where(*guard)
                        .values(**values, version=things.c.version + 1)
                        .returning(things)
                    )
                ).one_or_none()
            else:
                # R3.16: nothing to change, and the same comparison all the
                # same. A row lock under the UPDATE policies rather than an
                # UPDATE, because `touch_updated_at` reads a restated
                # `updated_at` as unstated and would move it.
                written = (
                    await session.execute(sa.select(things).where(*guard).with_for_update())
                ).one_or_none()
            if written is None:
                raise await self._unmatched(session, object_id, id_, expected)
            if changed:
                await self._audit(session, context, "probe.patched", id_)
        return view_of(written)

    async def delete(
        self,
        context: AccessContext,
        object_id: uuid.UUID,
        id_: uuid.UUID,
        expected: ExpectedVersion,
    ) -> None:
        self.check(context)
        async with tenant_session(self.sessions, self._scope(context)) as session:
            await self.before_write("delete")
            deleted = await session.scalar(
                sa.delete(things)
                .where(
                    things.c.id == id_,
                    things.c.object_id == object_id,
                    things.c.version == (expected.version if expected.version is not None else -1),
                )
                .returning(things.c.id)
            )
            if deleted is None:
                raise await self._unmatched(session, object_id, id_, expected)
            await self._audit(session, context, "probe.deleted", id_)

    async def archive(
        self,
        context: AccessContext,
        object_id: uuid.UUID,
        id_: uuid.UUID,
        expected: ExpectedVersion,
    ) -> ThingView:
        """A custom method: the version first, then the state (the spec's "API")."""
        self.check(context)
        async with tenant_session(self.sessions, self._scope(context)) as session:
            row = await self._load(session, object_id, id_)
            if row is None:
                raise NotFoundError("thing not found")
            if not expected.matches(row.version):
                raise PreconditionFailedError("the thing changed since it was read")
            if row.state == "archived":
                raise ConflictError("the thing is already archived")
            await self.before_write("archive")
            written = (
                await session.execute(
                    sa.update(things)
                    .where(things.c.id == id_, things.c.version == row.version)
                    .values(state="archived", version=things.c.version + 1)
                    .returning(things)
                )
            ).one_or_none()
            if written is None:
                raise await self._unmatched(session, object_id, id_, expected)
            await self._audit(session, context, "probe.archived", id_)
        return view_of(written)

    async def list(
        self, context: AccessContext, object_id: uuid.UUID, query: ListQuery
    ) -> Page[dict[str, Any]]:
        sort = things.c[query.order.field.column]
        statement = sa.select(things).where(things.c.object_id == object_id)
        if query.filter is not None:
            compiled = compile_filter(query.filter)
            # One parenthesised term beside the route's own scope (R5.10).
            statement = statement.where(sa.text(compiled.sql).bindparams(**compiled.params))
        phases = keyset_phases(
            sort, things.c.id, descending=query.order.descending, after=query.page.after
        )
        async with tenant_session(self.sessions, self._scope(context)) as session:
            rows = await keyset_rows(session, statement, phases, fetch_limit=query.page.fetch_limit)
        page = build_page(
            rows,
            request=query.page,
            position_of=lambda row: CursorPosition(
                sort_value=getattr(row, query.order.field.column), tiebreaker=row.id
            ),
        )
        wanted = query.fields

        def shown(row: Any) -> dict[str, Any]:
            item = view_of(row).model_dump()
            return item if wanted is None else {k: item[k] for k in ("id", *wanted)}

        return page.map_items(shown)


class ThingPage(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None


async def _schema_for(_: AccessContext) -> QuerySchema:
    return SCHEMA


Create = Annotated[IdempotentOperation, idempotent(ProbeThings.check, operation=f"POST {PREFIX}")]
Patch = Annotated[
    IdempotentOperation,
    idempotent(ProbeThings.check, operation=f"PATCH {PREFIX}/{{thing_id}}"),
]
Listing = Annotated[ListQuery, queryable(_schema_for)]


def build_router(service: ProbeThings) -> APIRouter:
    router = APIRouter(prefix=PREFIX)

    def location(object_id: uuid.UUID, id_: str) -> str:
        return f"/api/v1/probe/objects/{object_id}/things/{id_}"

    @router.get("", response_model=ThingPage)
    async def list_things(
        object_id: uuid.UUID, context: RequireAccessContext, query: Listing
    ) -> ThingPage:
        page = await service.list(context, object_id, query)
        return ThingPage(items=list(page.items), next_cursor=page.next_cursor)

    @router.post("/query", response_model=ThingPage)
    async def query_things(
        object_id: uuid.UUID, request: Request, context: RequireAccessContext
    ) -> ThingPage:
        listing = request.url.path.removesuffix("/query")
        query = await query_body(request, context, SCHEMA, route=listing)
        page = await service.list(context, object_id, query)
        return ThingPage(items=list(page.items), next_cursor=page.next_cursor)

    @router.post("", response_model=ThingView, status_code=201)
    async def create_thing(
        object_id: uuid.UUID,
        body: NewThing,
        context: RequireAccessContext,
        response: Response,
        idempotency: Create,
        only_if_absent: IfNoneMatchAny,
    ) -> ThingView:
        view = await idempotency.once(
            status=201,
            run=lambda effect: service.create(context, object_id, body, only_if_absent, effect),
            reread=lambda id_: service.get(context, object_id, uuid.UUID(id_)),
        )
        headers = {"ETag": etag_of(view.version), "Location": location(object_id, view.id)}
        response.headers.update(headers)
        result: ThingView = await idempotency.record(view, status_code=201, headers=headers)
        return result

    @router.get("/{thing_id}", response_model=ThingView)
    async def read_thing(
        object_id: uuid.UUID, thing_id: uuid.UUID, context: RequireAccessContext, response: Response
    ) -> ThingView:
        # `If-None-Match` is not read at all: never a 304 (R3.15).
        view = await service.get(context, object_id, thing_id)
        response.headers["ETag"] = etag_of(view.version)
        return view

    @router.patch("/{thing_id}", response_model=ThingView)
    async def patch_thing(
        object_id: uuid.UUID,
        thing_id: uuid.UUID,
        context: RequireAccessContext,
        response: Response,
        # The key first: a retry of a write that happened meets its effect
        # before anything compares a version (R2.1, R2.34).
        idempotency: Patch,
        expected: RequireIfMatch,
        patch: MergePatch,
    ) -> ThingView:
        view = await idempotency.once(
            status=200,
            run=lambda effect: service.patch(context, object_id, thing_id, expected, patch, effect),
            reread=lambda id_: service.get(context, object_id, uuid.UUID(id_)),
        )
        headers = {"ETag": etag_of(view.version)}
        response.headers.update(headers)
        result: ThingView = await idempotency.record(view, headers=headers)
        return result

    @router.delete("/{thing_id}", status_code=204)
    async def delete_thing(
        object_id: uuid.UUID,
        thing_id: uuid.UUID,
        context: RequireAccessContext,
        expected: RequireIfMatch,
    ) -> Response:
        await service.delete(context, object_id, thing_id, expected)
        return Response(status_code=204)

    @router.post("/{thing_id}/archive", response_model=ThingView)
    async def archive_thing(
        object_id: uuid.UUID,
        thing_id: uuid.UUID,
        context: RequireAccessContext,
        response: Response,
        expected: RequireIfMatch,
    ) -> ThingView:
        view = await service.archive(context, object_id, thing_id, expected)
        response.headers["ETag"] = etag_of(view.version)
        return view

    return router


@dataclass(frozen=True)
class Seeded:
    id: uuid.UUID
    version: int
    updated_at: datetime
