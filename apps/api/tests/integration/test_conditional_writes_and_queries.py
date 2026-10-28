"""Conditional writes and list queries over HTTP, against Postgres.

app-standards ticket 03 (R2.1, R2.34, R3, R4, R5, R6.4; APS7, APS8, APS9,
APS16, APS18, APS25, APS38, APS45, APS46, APS48, APS49, APS50, APS51), on the
probe resource of `probe_things.py`: the real app and its real dependencies,
the probe routes mounted beside them, and the HTTP key store wrapped to fail
where a process can, after the effect committed and before the answer was
stored.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from conventions import unconditional_writes
from fastapi import FastAPI
from pg_test_db import DatabaseUrls
from plan_shape import (
    Expectation,
    Scope,
    admin_url_of,
    capture,
    paged,
    problems_of,
    sample_value,
    schema_cases,
)
from probe_things import DDL, PREFIX, PROBE_WRITE, SCHEMA, ProbeThings, build_router
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.errors import InfrastructureError
from dw_kernel.filters import QueryError, QueryField, QuerySchema, ReasonCode, parse_query
from dw_kernel.pagination import CursorPosition, SortType, encode_cursor, typed_value
from dw_kernel.ports import SystemClock
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.idempotency_store import SqlIdempotencyStore
from dw_platform.application.access_context import AccessContext
from dw_platform.application.idempotency import (
    HttpIdempotency,
    RequestFingerprint,
    ReservedKey,
    StoredResponse,
)

pytestmark = pytest.mark.integration

SECRET = "probe-secret-0123456789abcdef0123456789"
SECRET_VALUE = "SECRET-123"


class FlakyStore:
    """The SQL key store, failing `complete` when told to: the effect committed,
    the answer was never stored, and G6 releases the key."""

    def __init__(self, inner: SqlIdempotencyStore) -> None:
        self.inner = inner
        self.fail_complete = 0

    async def reserve(
        self, context: AccessContext, *, key: str, fingerprint: RequestFingerprint
    ) -> uuid.UUID | ReservedKey:
        return await self.inner.reserve(context, key=key, fingerprint=fingerprint)

    async def take_over(self, context: AccessContext, **kw: Any) -> uuid.UUID | None:
        return await self.inner.take_over(context, **kw)

    async def complete(
        self, context: AccessContext, *, key: str, token: uuid.UUID, response: StoredResponse
    ) -> None:
        if self.fail_complete:
            self.fail_complete -= 1
            raise InfrastructureError("the store went away after the effect committed")
        await self.inner.complete(context, key=key, token=token, response=response)

    async def release(self, context: AccessContext, *, key: str, token: uuid.UUID) -> None:
        await self.inner.release(context, key=key, token=token)


@dataclass
class Person:
    id: uuid.UUID
    tenant: uuid.UUID
    workspace: uuid.UUID
    scopes: frozenset[str] = frozenset({PROBE_WRITE})

    @property
    def context(self) -> AccessContext:
        return AccessContext(
            tenant_id=self.tenant,
            workspace_id=self.workspace,
            principal_id=self.id,
            roles=frozenset(),
            scopes=self.scopes,
            plan_id="professional",
        )


@dataclass
class Probe:
    client: httpx.AsyncClient
    container: ApiContainer
    service: ProbeThings
    store: FlakyStore
    migrator: AsyncEngine
    admin_url: str
    people: dict[str, Person]
    obj: uuid.UUID = field(default_factory=uuid.uuid4)
    other_obj: uuid.UUID = field(default_factory=uuid.uuid4)

    def url(self, thing: uuid.UUID | str | None = None, *, obj: uuid.UUID | None = None) -> str:
        base = PREFIX.format(object_id=obj or self.obj)
        return base if thing is None else f"{base}/{thing}"

    def headers(self, who: str, extra: Any = None) -> list[tuple[str, str]]:
        person = self.people[who]
        token = DevTokenVerifier(SECRET).issue(f"probe-{person.id}")
        headers = [
            ("Authorization", f"Bearer {token}"),
            ("X-Tenant-Id", str(person.tenant)),
            ("X-Workspace-Id", str(person.workspace)),
        ]
        if isinstance(extra, dict):
            extra = list(extra.items())
        return headers + list(extra or [])

    async def send(
        self, who: str, method: str, url: str, *, headers: Any = None, **kw: Any
    ) -> httpx.Response:
        return await self.client.request(method, url, headers=self.headers(who, headers), **kw)

    async def seed(
        self,
        who: str = "owner",
        *,
        version: int = 7,
        obj: uuid.UUID | None = None,
        private: bool = False,
        **values: Any,
    ) -> uuid.UUID:
        person = self.people[who]
        id_ = values.pop("id", None) or uuid.uuid4()
        row = {"name": "Hà Nội", "age": 30, "flag": True, "note": "giữ", "data": {}, **values}
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO probe.things (tenant_id, id, object_id, owner_id, private, name,"
                    " age, flag, note, data, version) VALUES (:t, :id, :o, :u, :p, :name, :age,"
                    " :flag, :note, CAST(:data AS jsonb), :v)"
                ),
                {
                    "t": person.tenant,
                    "id": id_,
                    "o": obj or self.obj,
                    "u": person.id,
                    "p": private,
                    "v": version,
                    **row,
                    "data": json.dumps(row["data"]),
                },
            )
        return id_

    async def row(self, id_: uuid.UUID, tenant: uuid.UUID | None = None) -> Any:
        async with self.migrator.connect() as conn:
            return (
                await conn.execute(
                    sa.text("SELECT * FROM probe.things WHERE id = :id AND tenant_id = :t"),
                    {"id": id_, "t": tenant or self.people["owner"].tenant},
                )
            ).one_or_none()

    async def audits(self, id_: uuid.UUID) -> int:
        async with self.migrator.connect() as conn:
            count = await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.audit_events"
                    " WHERE resource_type = 'probe_thing' AND resource_id = :r"
                ),
                {"r": str(id_)},
            )
        return int(count or 0)

    async def migrate(self, statement: str, **values: Any) -> None:
        async with self.migrator.begin() as conn:
            await conn.execute(sa.text(statement), values)


async def _world(migrator: AsyncEngine) -> dict[str, Person]:
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    ws1, ws2, other_ws = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    role = f"probe_{tenant.hex[:10]}"
    people = {
        "owner": Person(uuid.uuid4(), tenant, ws1),
        "other": Person(uuid.uuid4(), tenant, ws1),
        "ws2": Person(uuid.uuid4(), tenant, ws2),
        "outsider": Person(uuid.uuid4(), other_tenant, other_ws),
    }
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.roles (key, name, scopes) VALUES (:k, :k, CAST(:s AS jsonb))"
            ),
            {"k": role, "s": json.dumps([PROBE_WRITE])},
        )
        for t, workspaces in ((tenant, (ws1, ws2)), (other_tenant, (other_ws,))):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name, status)"
                    " VALUES (:t, :s, :s, 'active')"
                ),
                {"t": t, "s": f"probe-{t.hex[:12]}"},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
                    " VALUES (:id, :t, 'professional')"
                ),
                {"id": uuid.uuid4(), "t": t},
            )
            for n, w in enumerate(workspaces):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                        " VALUES (:w, :t, :s, :s)"
                    ),
                    {"w": w, "t": t, "s": f"probe{n}"},
                )
        for person in people.values():
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, email, display_name)"
                    " VALUES (:u, :sub, :e, 'Người thử')"
                ),
                {
                    "u": person.id,
                    "sub": f"probe-{person.id}",
                    "e": f"{person.id.hex[:12]}@probe.test",
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys) VALUES (:id, :t, :w, :u, CAST(:r AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": person.tenant,
                    "w": person.workspace,
                    "u": person.id,
                    "r": json.dumps([role]),
                },
            )
    return people


@pytest.fixture
async def probe(api_db: DatabaseUrls) -> AsyncIterator[Probe]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        for statement in DDL:
            await conn.execute(sa.text(statement))
    people = await _world(migrator)
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    assert container.engine is not None
    sessions = async_sessionmaker(container.engine, class_=AsyncSession, expire_on_commit=False)
    store = FlakyStore(SqlIdempotencyStore(sessions))
    container.idempotency = HttpIdempotency(store=store, clock=SystemClock())
    service = ProbeThings(container.engine)
    app = create_app(container)
    app.include_router(build_router(service))
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
                yield Probe(
                    client, container, service, store, migrator, admin_url_of(api_db), people
                )
    finally:
        await container.engine.dispose()
        await migrator.dispose()


def if_match(value: str) -> dict[str, str]:
    return {"If-Match": value}


async def patch(
    probe: Probe,
    who: str,
    id_: uuid.UUID,
    body: Any,
    *,
    match: str | None = None,
    key: str | None = None,
    content_type: str = "application/merge-patch+json",
    extra: list[tuple[str, str]] | None = None,
) -> httpx.Response:
    headers = [("Content-Type", content_type)]
    if match is not None:
        headers.append(("If-Match", match))
    if key is not None:
        headers.append(("Idempotency-Key", key))
    return await probe.send(
        who, "PATCH", probe.url(id_), headers=headers + (extra or []), content=json.dumps(body)
    )


def without_request(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in {"instance", "request_id", "trace_id"}}


def test_every_write_route_of_the_probe_requires_if_match() -> None:
    # The probe itself passes the app-build reading of R3.12.
    app = FastAPI()
    app.include_router(build_router(ProbeThings.__new__(ProbeThings)))
    assert unconditional_writes(app.openapi()) == set()


# ------------------------------------------------------- R3.1, R3.15 --


async def test_the_etag_is_the_version_on_read_and_on_write(probe: Probe) -> None:
    id_ = await probe.seed(version=7)

    read = await probe.send("owner", "GET", probe.url(id_))
    unchanged = await patch(probe, "owner", id_, {}, match='"7"')
    changed = await patch(probe, "owner", id_, {"name": "Huế"}, match='"7"')

    assert read.headers["ETag"] == '"7"' and read.json()["version"] == 7
    assert unchanged.status_code == 200 and unchanged.headers["ETag"] == '"7"'
    assert changed.status_code == 200 and changed.headers["ETag"] == '"8"'


async def test_a_read_ignores_if_none_match_and_never_answers_304(probe: Probe) -> None:
    # R3.15 (APS46).
    id_ = await probe.seed(version=7)
    response = await probe.send("owner", "GET", probe.url(id_), headers=[("If-None-Match", '"7"')])
    assert response.status_code == 200 and response.json()["id"] == str(id_)


# ------------------------------------------------ R3.2, R3.3, R3.8, R3.10 --


@pytest.mark.parametrize("stale", ['"6"', 'W/"7"'])
async def test_a_stale_or_weak_if_match_is_412_and_changes_nothing(
    probe: Probe, stale: str
) -> None:
    # R3.2 (APS7).
    id_ = await probe.seed(version=7)
    response = await patch(probe, "owner", id_, {"name": "Huế"}, match=stale)
    assert response.status_code == 412 and response.json()["code"] == "precondition_failed"
    row = await probe.row(id_)
    assert (row.version, row.name) == (7, "Hà Nội")
    assert await probe.audits(id_) == 0


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("If-Match", "*")],
        [("If-Match", '"6", "7"')],
        [("If-Match", '"7"'), ("If-Match", '"7"')],
        [("If-Match", "7")],
    ],
    ids=["missing", "wildcard", "list", "repeated", "unquoted"],
)
async def test_a_write_naming_no_single_strong_version_is_428(
    probe: Probe, headers: list[tuple[str, str]]
) -> None:
    # R3.3, R3.8 (APS7).
    id_ = await probe.seed(version=7)
    response = await patch(probe, "owner", id_, {"name": "Huế"}, extra=headers)
    assert response.status_code == 428 and response.json()["code"] == "precondition_required"
    assert (await probe.row(id_)).version == 7 and await probe.audits(id_) == 0


async def test_a_json_patch_is_415_and_changes_nothing(probe: Probe) -> None:
    # R3.10.
    id_ = await probe.seed(version=7)
    response = await patch(
        probe,
        "owner",
        id_,
        [{"op": "replace"}],
        match='"7"',
        content_type="application/json-patch+json",
    )
    assert response.status_code == 415 and response.json()["code"] == "unsupported_media_type"
    assert (await probe.row(id_)).version == 7


@pytest.mark.parametrize("content_type", ["application/merge-patch+json", "application/json"])
async def test_a_merge_patch_removes_merges_and_keeps(probe: Probe, content_type: str) -> None:
    # R3.5.
    id_ = await probe.seed(version=7, data={"b": {"d": 2}, "e": 3})
    response = await patch(
        probe,
        "owner",
        id_,
        {"note": None, "data": {"b": {"c": 1}}},
        match='"7"',
        content_type=content_type,
    )
    assert response.status_code == 200, response.text
    row = await probe.row(id_)
    assert row.note is None
    assert row.data == {"b": {"c": 1, "d": 2}, "e": 3}
    assert (row.name, row.age, row.version) == ("Hà Nội", 30, 8)


# ------------------------------------------------------------- R3.16 --


@pytest.mark.parametrize("body", [{}, {"name": "Hà Nội", "age": 30}], ids=["empty", "same"])
async def test_a_patch_that_changes_nothing_keeps_the_version_and_writes_no_audit(
    probe: Probe, body: dict[str, Any]
) -> None:
    id_ = await probe.seed(version=7)
    before = await probe.row(id_)

    response = await patch(probe, "owner", id_, body, match='"7"')

    assert response.status_code == 200 and response.headers["ETag"] == '"7"'
    after = await probe.row(id_)
    assert (after.version, after.updated_at) == (7, before.updated_at)
    assert await probe.audits(id_) == 0


async def test_a_patch_that_changes_nothing_is_still_conditional(probe: Probe) -> None:
    id_ = await probe.seed(version=7)
    stale = await patch(probe, "owner", id_, {}, match='"6"')
    not_mine = await patch(probe, "other", id_, {}, match='"7"')
    assert stale.status_code == 412
    assert not_mine.status_code == 403 and not_mine.json()["code"] == "permission_denied"
    assert (await probe.row(id_)).version == 7


# ---------------------------------------------------------- R3.7, R3.13 --


async def test_a_resource_the_caller_cannot_read_answers_as_a_missing_id(probe: Probe) -> None:
    # R3.7 (APS16): matching and stale alike, another person and another tenant.
    hidden = await probe.seed(version=7, private=True)
    missing = await patch(probe, "other", uuid.uuid4(), {"name": "x"}, match='"7"')
    assert missing.status_code == 404
    expected = without_request(missing.json())

    for who, match in (
        ("other", '"7"'),
        ("other", '"6"'),
        ("outsider", '"7"'),
        ("outsider", '"6"'),
    ):
        response = await patch(probe, who, hidden, {"name": "x"}, match=match)
        assert response.status_code == 404, (who, match)
        assert without_request(response.json()) == expected
    assert (await probe.row(hidden)).version == 7


async def test_a_reader_who_may_not_write_gets_403_not_412(probe: Probe) -> None:
    # R3.13 (APS46): readable, the version matches, the UPDATE policy refuses.
    id_ = await probe.seed(version=7)
    response = await patch(probe, "other", id_, {"name": "Huế"}, match='"7"')
    assert response.status_code == 403 and response.json()["code"] == "permission_denied"
    assert (await probe.row(id_)).version == 7 and await probe.audits(id_) == 0


@pytest.mark.parametrize(
    ("meanwhile", "status"),
    [
        ("DELETE FROM probe.things WHERE id = :id", 404),
        (
            "UPDATE probe.things SET private = true, owner_id = gen_random_uuid() WHERE id = :id",
            404,
        ),
        ("UPDATE probe.things SET version = 9 WHERE id = :id", 412),
    ],
    ids=["deleted", "out-of-reach", "changed"],
)
async def test_a_write_matching_nothing_is_told_apart_as_the_caller(
    probe: Probe, meanwhile: str, status: int
) -> None:
    # R3.13 (APS16): between the load and the write.
    id_ = await probe.seed(version=7)

    async def interfere(_: str) -> None:
        await probe.migrate(meanwhile, id=id_)

    probe.service.before_write = interfere
    response = await patch(probe, "owner", id_, {"name": "Huế"}, match='"7"')
    probe.service.before_write = ProbeThings.before_write

    assert response.status_code == status, response.text
    assert await probe.audits(id_) == 0


# --------------------------------------------------------------- R3.9 --


class Gate:
    """Holds every writer at its write until all of them are there."""

    def __init__(self, parties: int) -> None:
        self.barrier = asyncio.Barrier(parties)

    async def __call__(self, _: str) -> None:
        await asyncio.wait_for(self.barrier.wait(), timeout=10)


async def test_two_writers_holding_one_version_cannot_both_win(probe: Probe) -> None:
    # R3.9 (APS18): two connections, held at the write until both are there.
    id_ = await probe.seed(version=7)
    probe.service.before_write = Gate(2)
    first, second = await asyncio.gather(
        patch(probe, "owner", id_, {"name": "Huế"}, match='"7"'),
        patch(probe, "owner", id_, {"name": "Vinh"}, match='"7"'),
    )
    probe.service.before_write = ProbeThings.before_write

    assert sorted([first.status_code, second.status_code]) == [200, 412]
    assert (await probe.row(id_)).version == 8
    assert await probe.audits(id_) == 1


async def test_a_delete_that_wins_leaves_the_patch_a_missing_id(probe: Probe) -> None:
    # R3.9: both loaded the row at 7; the delete commits first, then the patch
    # writes and matches nothing.
    id_ = await probe.seed(version=7)
    loaded = Gate(2)

    async def ordered(step: str) -> None:
        await loaded(step)
        if step == "patch":
            for _ in range(200):
                if await probe.row(id_) is None:
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("the delete never committed")

    probe.service.before_write = ordered
    deleted, patched = await asyncio.gather(
        probe.send("owner", "DELETE", probe.url(id_), headers=if_match('"7"')),
        patch(probe, "owner", id_, {"name": "Huế"}, match='"7"'),
    )
    probe.service.before_write = ProbeThings.before_write

    assert deleted.status_code == 204, deleted.text
    assert patched.status_code == 404, patched.text


async def test_a_custom_method_compares_the_version_before_the_state(probe: Probe) -> None:
    id_ = await probe.seed(version=7)
    archived = await probe.send(
        "owner", "POST", probe.url(id_) + "/archive", headers=if_match('"7"')
    )
    stale = await probe.send("owner", "POST", probe.url(id_) + "/archive", headers=if_match('"7"'))
    again = await probe.send("owner", "POST", probe.url(id_) + "/archive", headers=if_match('"8"'))

    assert archived.status_code == 200 and archived.headers["ETag"] == '"8"'
    assert stale.status_code == 412
    assert again.status_code == 409


# ------------------------------------------------------ R3.4, R3.11 --


async def test_a_create_never_overwrites(probe: Probe) -> None:
    # R3.4 (APS46, APS50).
    id_ = await probe.seed(version=7, name="Đà Nẵng")
    plain = await probe.send("owner", "POST", probe.url(), json={"id": str(id_), "name": "Huế"})
    starred = await probe.send(
        "owner",
        "POST",
        probe.url(),
        json={"id": str(id_), "name": "Huế"},
        headers=[("If-None-Match", "*")],
    )

    assert plain.status_code == 409 and plain.json()["code"] == "conflict"
    assert "Huế" not in plain.text and "Đà Nẵng" not in plain.text
    assert starred.status_code == 412 and starred.json()["code"] == "precondition_failed"
    row = await probe.row(id_)
    assert (row.name, row.version) == ("Đà Nẵng", 7)


async def test_two_creates_of_one_id_give_one_201_and_one_412(probe: Probe) -> None:
    id_ = uuid.uuid4()
    probe.service.before_write = Gate(2)
    responses = await asyncio.gather(
        *(
            probe.send(
                "owner",
                "POST",
                probe.url(),
                json={"id": str(id_), "name": n},
                headers=[("If-None-Match", "*")],
            )
            for n in ("Huế", "Vinh")
        )
    )
    probe.service.before_write = ProbeThings.before_write

    assert sorted(r.status_code for r in responses) == [201, 412]
    created = next(r for r in responses if r.status_code == 201)
    assert created.headers["ETag"] == '"1"'
    assert created.headers["Location"].endswith(f"/things/{id_}")


async def test_another_tenant_creates_its_own_resource_under_the_same_id(probe: Probe) -> None:
    # R3.11 (APS16).
    id_ = await probe.seed(version=7, name="Đà Nẵng")
    response = await probe.send(
        "outsider",
        "POST",
        probe.url(),
        json={"id": str(id_), "name": "Huế"},
        headers=[("If-None-Match", "*")],
    )
    assert response.status_code == 201, response.text
    assert (await probe.row(id_)).name == "Đà Nẵng"
    assert (await probe.row(id_, probe.people["outsider"].tenant)).name == "Huế"


# ----------------------------------------------------- R2.1, R2.34 --


async def test_a_retry_with_the_same_key_replays_without_comparing_again(probe: Probe) -> None:
    # R2.1: the version moved to 7, so the same If-Match "6" would be a 412.
    id_ = await probe.seed(version=6)
    key = f"k-{uuid.uuid4()}"
    first = await patch(probe, "owner", id_, {"name": "Huế"}, match='"6"', key=key)
    again = await patch(probe, "owner", id_, {"name": "Huế"}, match='"6"', key=key)

    assert first.status_code == 200 and first.json()["version"] == 7
    assert again.status_code == 200 and again.json() == first.json()
    assert again.headers["ETag"] == '"7"'
    assert await probe.audits(id_) == 1


async def test_a_retry_after_the_effect_committed_meets_it_before_any_comparison(
    probe: Probe,
) -> None:
    # R2.34 (APS38): committed at 8, the answer never stored, the key released.
    id_ = await probe.seed(version=7)
    key = f"k-{uuid.uuid4()}"
    probe.store.fail_complete = 1
    failed = await patch(probe, "owner", id_, {"name": "Huế"}, match='"7"', key=key)
    retried = await patch(probe, "owner", id_, {"name": "Huế"}, match='"7"', key=key)

    assert failed.status_code == 503
    assert retried.status_code == 200, retried.text
    assert retried.json()["version"] == 8 and retried.headers["ETag"] == '"8"'
    assert (await probe.row(id_)).version == 8
    assert await probe.audits(id_) == 1


async def test_a_retried_create_with_if_none_match_meets_its_effect(probe: Probe) -> None:
    id_, key = uuid.uuid4(), f"k-{uuid.uuid4()}"
    probe.store.fail_complete = 1
    body = {"id": str(id_), "name": "Huế"}
    headers = [("If-None-Match", "*"), ("Idempotency-Key", key)]
    failed = await probe.send("owner", "POST", probe.url(), json=body, headers=headers)
    retried = await probe.send("owner", "POST", probe.url(), json=body, headers=headers)

    assert failed.status_code == 503
    assert retried.status_code == 201, retried.text
    assert retried.headers["ETag"] == '"1"' and retried.json()["id"] == str(id_)
    assert await probe.audits(id_) == 1


# ------------------------------------------------------------------ R4 --


async def _walk(
    probe: Probe, who: str, order_by: str, size: int, *, obj: uuid.UUID | None = None
) -> list[str]:
    person = probe.people[who]
    seen: list[str] = []
    cursor: str | None = None
    while True:
        query = parse_query(
            SCHEMA,
            route=probe.url(obj=obj),
            tenant=person.tenant,
            workspace=person.workspace,
            order_by=order_by,
            cursor=cursor,
            limit=size,
        )
        page = await probe.service.list(person.context, obj or probe.obj, query)
        seen.extend(item["id"] for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            return seen


async def test_paging_returns_every_row_once_with_nulls_last_either_way(probe: Probe) -> None:
    # R4.2: 1 000 rows, ages repeating, one in ten NULL.
    rng = random.Random(20261028)
    ages = [None if rng.random() < 0.1 else rng.randrange(40) for _ in range(1000)]
    async with probe.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO probe.things (tenant_id, id, object_id, owner_id, age)"
                " SELECT :t, gen_random_uuid(), :o, :u, a FROM unnest(CAST(:ages AS int[])) a"
            ),
            {
                "t": probe.people["owner"].tenant,
                "o": probe.obj,
                "u": probe.people["owner"].id,
                "ages": ages,
            },
        )
        rows = (
            await conn.execute(
                sa.text("SELECT id::text, age FROM probe.things WHERE object_id = :o"),
                {"o": probe.obj},
            )
        ).all()
    age_of = {row.id: row.age for row in rows}

    for direction in ("asc", "desc"):
        for size in (1, 2, 3, 7, 13, 50):
            seen = await _walk(probe, "owner", f"age {direction}", size)
            assert len(seen) == 1000 and len(set(seen)) == 1000, (direction, size)
            ordered = [age_of[i] for i in seen]
            values = [a for a in ordered if a is not None]
            assert ordered[len(values) :] == [None] * (1000 - len(values)), "NULLs last"
            assert values == sorted(values, reverse=direction == "desc")


async def test_a_page_carries_a_typed_cursor(probe: Probe) -> None:
    # R4.1.
    for age in (1, 2):
        await probe.seed(age=age)
    response = await probe.send("owner", "GET", probe.url(), params={"order_by": "age", "limit": 1})
    cursor = response.json()["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert (payload["v"], payload["t"], payload["k"], payload["p"]) == (2, "int", 1, "values")
    uuid.UUID(payload["i"])


async def _cursor(probe: Probe, who: str = "owner", **params: Any) -> str:
    for n in range(3):
        await probe.seed(name=f"n{n}", age=n)
    response = await probe.send(
        "owner" if who == "owner" else who, "GET", probe.url(), params={"limit": 1, **params}
    )
    assert response.status_code == 200, response.text
    cursor: str = response.json()["next_cursor"]
    return cursor


async def test_a_cursor_is_refused_by_any_other_query(probe: Probe) -> None:
    # R4.3.
    tree = json.dumps({"name": {"$gt": "a"}})
    cursor = await _cursor(probe, filter=tree, order_by="name desc", fields="name")
    same = {"filter": tree, "order_by": "name desc", "fields": "name", "cursor": cursor}

    assert (await probe.send("owner", "GET", probe.url(), params=same)).status_code == 200
    by_body = await probe.send(
        "owner",
        "POST",
        probe.url() + "/query",
        json={
            "filter": {"name": {"$gt": "a"}},
            "order_by": "name desc",
            "fields": "name",
            "cursor": cursor,
        },
    )
    assert by_body.status_code == 200, by_body.text

    for change in (
        {"filter": json.dumps({"name": {"$gt": "b"}})},
        {"order_by": "name asc"},
        {"fields": "age"},
    ):
        response = await probe.send("owner", "GET", probe.url(), params={**same, **change})
        assert response.status_code == 422, change
        assert response.json()["errors"][0] == {
            "parameter": "cursor",
            "code": "cursor_invalid",
            "detail": response.json()["errors"][0]["detail"],
        }
    other_path = await probe.send("owner", "GET", probe.url(obj=probe.other_obj), params=same)
    assert other_path.status_code == 422, "the concrete path, not the template"
    other_workspace = await probe.send("ws2", "GET", probe.url(), params=same)
    assert other_workspace.status_code == 422


async def test_a_cursor_grants_nothing_to_another_caller(probe: Probe) -> None:
    # R4.4 (APS8): another workspace, another tenant.
    cursor = await _cursor(probe)
    for who in ("ws2", "outsider"):
        response = await probe.send(who, "GET", probe.url(), params={"cursor": cursor})
        assert response.status_code == 422, who


@pytest.mark.parametrize(
    "cursor",
    ["not-base64!!", "bm90IGpzb24", None],
    ids=["base64", "json", "id"],
)
async def test_an_unreadable_cursor_is_422_before_any_sql(probe: Probe, cursor: str | None) -> None:
    # R4.6.
    if cursor is None:
        good = await _cursor(probe)
        raw = json.loads(base64.urlsafe_b64decode(good + "=" * (-len(good) % 4)))
        raw["i"] = "not-a-uuid"
        cursor = base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")
    assert probe.container.engine is not None
    with capture(probe.container.engine) as seen:
        response = await probe.send("owner", "GET", probe.url(), params={"cursor": cursor})
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert paged(seen, "probe.things") == []


# ------------------------------------------------------------------ R5 --


async def _query(probe: Probe, tree: Any, **params: Any) -> tuple[httpx.Response, list[str]]:
    assert probe.container.engine is not None
    with capture(probe.container.engine) as seen:
        response = await probe.send(
            "owner", "POST", probe.url() + "/query", json={"filter": tree, **params}
        )
    return response, [c.statement for c in paged(seen, "probe.things")]


def _nested(depth: int) -> dict[str, Any]:
    tree: dict[str, Any] = {"name": {"$eq": "a"}}
    for _ in range(depth - 1):
        tree = {"$and": [tree]}
    return tree


async def test_a_tree_at_the_limits_is_taken_and_one_past_is_refused_before_sql(
    probe: Probe,
) -> None:
    # R5.1, R5.8 (APS9).
    at_limit = [
        _nested(5),
        {"$or": [{"age": {"$eq": n}} for n in range(50)]},
        {"age": {"$in": list(range(500))}},
        {"name": {"$eq": "x" * 1024}},
    ]
    for tree in at_limit:
        response, statements = await _query(probe, tree)
        assert response.status_code == 200, response.text
        assert statements
    past = [
        (_nested(6), "filter_too_deep", "/filter" + "/$and/0" * 5),
        (
            {"$or": [{"age": {"$eq": n}} for n in range(51)]},
            "filter_too_many_leaves",
            "/filter/$or/50",
        ),
        ({"age": {"$in": list(range(501))}}, "filter_in_too_many_values", "/filter/age/$in"),
        ({"name": {"$eq": "x" * 1025}}, "filter_string_too_long", "/filter/name/$eq"),
        ({"flag": {"$gt": True}}, "operator_not_allowed", "/filter"),
    ]
    for tree, code, pointer in past:
        response, statements = await _query(probe, tree)
        assert response.status_code == 422 and response.json()["code"] == "validation_failed"
        assert response.json()["errors"][0]["code"] == code
        assert response.json()["errors"][0]["pointer"] == pointer
        assert statements == []


@pytest.mark.parametrize(
    "tree",
    [
        {"name": {"$eq": "a"}, "age": {"$eq": 2}},
        {"age": {"$gt": 1, "$lt": 5}},
        {"$and": []},
        {"age": {"$eq": "seven"}},
    ],
)
async def test_a_malformed_leaf_is_refused_where_it_stands(probe: Probe, tree: Any) -> None:
    response, statements = await _query(probe, tree)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "filter_malformed"
    assert response.json()["errors"][0]["pointer"].startswith("/filter")
    assert statements == []


async def test_a_get_and_a_query_body_refuse_a_tree_alike(probe: Probe) -> None:
    # R5.7.
    tree = {"$or": [{"name": {"$eq": "a"}}, {"ghost": {"$eq": 1}}]}
    by_get = await probe.send("owner", "GET", probe.url(), params={"filter": json.dumps(tree)})
    by_body, _ = await _query(probe, tree)
    assert by_get.status_code == by_body.status_code == 422
    assert by_get.json()["errors"] == by_body.json()["errors"]
    assert by_get.json()["errors"][0]["pointer"] == "/filter/$or/1"


async def test_order_by_sorts_and_the_statement_ends_with_id(probe: Probe) -> None:
    # R5.3.
    for name in ("b", "c", "a"):
        await probe.seed(name=name)
    assert probe.container.engine is not None
    with capture(probe.container.engine) as seen:
        response = await probe.send("owner", "GET", probe.url(), params={"order_by": "name desc"})
    assert [item["name"] for item in response.json()["items"]] == ["c", "b", "a"]
    statement = paged(seen, "probe.things")[0].statement
    assert statement.split("ORDER BY")[1].split("LIMIT")[0].strip().endswith("probe.things.id DESC")


@pytest.mark.parametrize(
    ("params", "parameter", "code"),
    [
        ({"order_by": "note"}, "order_by", "field_not_filterable"),
        ({"order_by": "ghost"}, "order_by", "field_not_readable"),
        ({"order_by": "name desc, age"}, "order_by", "order_by_too_many_fields"),
        ({"order_by": "name sideways"}, "order_by", "order_by_malformed"),
        ({"fields": "name,,id"}, "fields", "fields_malformed"),
        ({"order_by": [("order_by", "a"), ("order_by", "b")]}, "order_by", "parameter_repeated"),
    ],
)
async def test_order_by_and_fields_are_refused_by_parameter_before_sql(
    probe: Probe, params: dict[str, Any], parameter: str, code: str
) -> None:
    # R5.4, R5.9, R5.11, R5.15.
    sent: Any = params["order_by"] if isinstance(params.get("order_by"), list) else params
    assert probe.container.engine is not None
    with capture(probe.container.engine) as seen:
        response = await probe.send("owner", "GET", probe.url(), params=sent)
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["parameter"], error["code"]) == (parameter, code)
    assert paged(seen, "probe.things") == []


async def test_fields_returns_only_those_fields_and_the_id(probe: Probe) -> None:
    # R5.5.
    await probe.seed(name="a")
    response = await probe.send("owner", "GET", probe.url(), params={"fields": "name"})
    assert response.json()["items"] == [{"id": response.json()["items"][0]["id"], "name": "a"}]


async def test_a_reason_code_is_in_errors_never_in_code(probe: Probe) -> None:
    # R5.6.
    for tree, reason in (
        ({"note": {"$eq": "a"}}, "field_not_filterable"),
        ({"ghost": {"$eq": 1}}, "field_not_readable"),
    ):
        response, _ = await _query(probe, tree)
        assert response.json()["code"] == "validation_failed"
        assert response.json()["errors"][0]["code"] == reason


async def test_no_value_or_name_the_caller_sent_reaches_sql(probe: Probe) -> None:
    # R5.10 (APS25).
    injection = "x'); DROP TABLE t; --"
    response, statements = await _query(probe, {"name": {"$eq": injection}})
    assert response.status_code == 200 and statements
    assert not any(injection in s for s in statements)
    for params in ({"order_by": "name desc, (select 1)"}, {"fields": "id,pg_sleep(1)"}):
        assert probe.container.engine is not None
        with capture(probe.container.engine) as seen:
            refused = await probe.send("owner", "GET", probe.url(), params=params)
        assert refused.status_code == 422
        assert not any("pg_sleep" in c.statement or "select 1" in c.statement for c in seen)


async def test_a_tree_stays_inside_the_routes_scope(probe: Probe) -> None:
    # R5.10, R5.13 (APS45): through the route and through the kernel directly.
    mine = await probe.seed(name="a")
    await probe.seed(name="b", obj=probe.other_obj)
    tree = {"$or": [{"name": {"$eq": "b"}}, {"name": {"$eq": "a"}}]}

    response, _ = await _query(probe, tree)
    owner = probe.people["owner"]
    direct = await probe.service.list(
        owner.context,
        probe.obj,
        parse_query(
            SCHEMA,
            route="direct",
            tenant=owner.tenant,
            workspace=owner.workspace,
            filter=tree,
            limit=10,
        ),
    )

    assert [item["id"] for item in response.json()["items"]] == [str(mine)]
    assert [item["id"] for item in direct.items] == [str(mine)]


async def test_a_refusal_never_repeats_what_was_sent(probe: Probe) -> None:
    # R5.14 (APS48).
    for tree in (
        {"name": {"$eq": SECRET_VALUE + "x" * 1024}},
        {"age": {"$eq": SECRET_VALUE}},
        {SECRET_VALUE: {"$eq": 1}},
        {"$and": [{"name": {"$eq": "a"}}], SECRET_VALUE: 1},
    ):
        by_body, _ = await _query(probe, tree)
        by_get = await probe.send("owner", "GET", probe.url(), params={"filter": json.dumps(tree)})
        for response in (by_body, by_get):
            assert response.status_code == 422
            assert SECRET_VALUE not in response.text


# ---------------------------------------------------------------- R6.4 --


async def _schema_problems(
    probe: Probe, schema: QuerySchema, *, ddl: tuple[str, ...] = ()
) -> dict[str, list[str]]:
    """Plan every statement ``schema`` declares, case by case (R6.4)."""
    owner = probe.people["owner"]
    for n in range(4):
        await probe.seed(name=f"n{n}", age=n, rank=n)
    await probe.seed(name=None, age=None)
    problems: dict[str, list[str]] = {}
    assert probe.container.engine is not None
    for case in schema_cases(schema):
        field_ = schema.get(case.sort_field)
        assert field_ is not None
        first = parse_query(
            schema,
            route="plan",
            tenant=owner.tenant,
            workspace=owner.workspace,
            filter=case.filter,
            order_by=case.order_by,
            limit=1,
        )
        cursor = None
        if case.phase is not None:
            value = (
                None
                if case.phase == "nulls"
                else typed_value(field_.type, sample_value(field_.type.value))
            )
            cursor = encode_cursor(CursorPosition(value, uuid.uuid4()), first.page.query)
        query = parse_query(
            schema,
            route="plan",
            tenant=owner.tenant,
            workspace=owner.workspace,
            filter=case.filter,
            order_by=case.order_by,
            limit=1,
            cursor=cursor,
        )
        with capture(probe.container.engine) as seen:
            await probe.service.list(owner.context, probe.obj, query)
        statements = paged(seen, "probe.things")
        assert statements, case.label
        predicates = ("object_id",) + ((case.filter_field,) if case.filter_field else ())
        expected = Expectation("probe.things", predicates, (field_.column, "id"))
        found = await problems_of(
            probe.admin_url,
            Scope(str(owner.tenant), str(owner.workspace), str(owner.id)),
            statements,
            expected,
            ddl=ddl,
        )
        if found:
            problems[case.label] = found
    return problems


async def test_every_combination_the_schema_declares_has_an_index(probe: Probe) -> None:
    # R6.4 (APS51): read from the schema; 2 sortable fields x 2 directions x
    # 3 pages, and 11 operators x 2 pages.
    assert len(schema_cases(SCHEMA)) == 2 * 2 * 3 + 11 * 2
    assert await _schema_problems(probe, SCHEMA) == {}


def _with(field_: QueryField) -> QuerySchema:
    kept = tuple(f for f in SCHEMA.fields if f.name != field_.name)
    return QuerySchema(
        fields=(*kept, field_), default_order=SCHEMA.default_order, logical=SCHEMA.logical
    )


async def test_a_sortable_field_without_an_index_turns_the_check_red(probe: Probe) -> None:
    problems = await _schema_problems(
        probe, _with(QueryField("note", SortType.TEXT, "note", sortable=True))
    )
    assert set(problems) == {
        f"order_by note {direction}, {page} page"
        for direction in ("asc", "desc")
        for page in ("first", "values", "nulls")
    }


async def test_an_operator_on_a_column_no_index_carries_turns_the_check_red(probe: Probe) -> None:
    schema = _with(
        QueryField("note", SortType.TEXT, "note", filterable=True, operators=frozenset({"$lt"}))
    )
    problems = await _schema_problems(probe, schema)
    assert set(problems) == {"note $lt, first page", "note $lt, values page"}
    assert all("column note" in p for found in problems.values() for p in found)


async def test_an_index_not_led_by_the_tenant_turns_the_check_red(probe: Probe) -> None:
    schema = _with(QueryField("rank", SortType.INT, "rank", sortable=True))
    problems = await _schema_problems(
        probe,
        schema,
        ddl=("CREATE INDEX ix_things_rank ON probe.things (object_id, tenant_id, rank, id)",),
    )
    rank_cases = {label for label in problems if label.startswith("order_by rank")}
    assert len(rank_cases) == 6
    assert all(any("leads with object_id" in p for p in problems[label]) for label in rank_cases)


def test_a_query_error_from_the_kernel_is_typed_for_a_caller_outside_http() -> None:
    # R5.13: the probe's own service receives the exception, not a response.
    with pytest.raises(QueryError) as raised:
        parse_query(
            SCHEMA,
            route="x",
            tenant=uuid.uuid4(),
            workspace=None,
            filter={"ghost": {"$eq": 1}},
            limit=5,
        )
    assert raised.value.problems[0].code is ReasonCode.FIELD_NOT_READABLE
    assert raised.value.problems[0].pointer == ""
