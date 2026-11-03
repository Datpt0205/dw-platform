"""Integration: who is in an audience, and which workspaces an audience may name
(org-and-principals ticket 04, R8.2-R8.4; OP12, OP13).

Against PostgreSQL as `dw_app` under RLS, `app.tenant_id` set per transaction;
the migrator only plants. Tenant A has W1 and W2, tenant B has WB. People:
`w1` (active in A, membership W1), `both` (active in A, W1 and W2), `w2`
(active in A, W2), `suspended` (suspended in A, membership W1), `b` (active in
B, membership WB), `straddler` (active in A with W1, active in B with WB),
`suspended_here` (suspended in A with W1, active in B with WB).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.audience_workspaces import SqlAudienceWorkspaces
from dw_platform.application.access_context import AccessContext
from dw_platform.application.audience import AudienceValidator
from dw_platform.domain.audience import AudienceInvalidError
from dw_platform.testing.members import MemberStatus, add_tenant_member

pytestmark = pytest.mark.integration


@dataclass
class World:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    w1: uuid.UUID
    w2: uuid.UUID
    wb: uuid.UUID
    users: dict[str, uuid.UUID] = field(default_factory=dict)


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def world(migrator: AsyncEngine) -> World:
    w = World(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    people: dict[str, list[tuple[uuid.UUID, MemberStatus, tuple[uuid.UUID, ...]]]] = {
        "w1": [(w.tenant_a, "active", (w.w1,))],
        "w2": [(w.tenant_a, "active", (w.w2,))],
        "both": [(w.tenant_a, "active", (w.w1, w.w2))],
        "suspended": [(w.tenant_a, "suspended", (w.w1,))],
        "b": [(w.tenant_b, "active", (w.wb,))],
        "straddler": [(w.tenant_a, "active", (w.w1,)), (w.tenant_b, "active", (w.wb,))],
        "suspended_here": [(w.tenant_a, "suspended", (w.w1,)), (w.tenant_b, "active", (w.wb,))],
    }
    w.users = {name: uuid.uuid4() for name in people}
    async with migrator.begin() as conn:
        companies: tuple[tuple[uuid.UUID, tuple[uuid.UUID, ...]], ...] = (
            (w.tenant_a, (w.w1, w.w2)),
            (w.tenant_b, (w.wb,)),
        )
        for tenant, workspaces in companies:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name, status)"
                    " VALUES (:id, :slug, 'Audience test', 'active')"
                ),
                {"id": tenant, "slug": f"aud-{tenant.hex[:12]}"},
            )
            for n, ws in enumerate(workspaces):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                        " VALUES (:id, :t, :slug, 'W')"
                    ),
                    {"id": ws, "t": tenant, "slug": f"ws{n}"},
                )
        for name, standings in people.items():
            user = w.users[name]
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, email, display_name)"
                    " VALUES (:id, :sub, :email, :name)"
                ),
                {"id": user, "sub": f"aud-{user}", "email": f"{user}@aud.test", "name": name},
            )
            for tenant, status, held in standings:
                await add_tenant_member(conn, tenant, user, status)
                for ws in held:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO platform.memberships"
                            " (id, tenant_id, workspace_id, user_id)"
                            " VALUES (:id, :t, :ws, :u)"
                        ),
                        {"id": uuid.uuid4(), "t": tenant, "ws": ws, "u": user},
                    )
    return w


def _doc(*groups: tuple[uuid.UUID | str, ...]) -> dict[str, Any]:
    return {
        "schema": "dw.audience/v1",
        "any_of": [{"all_of": [{"workspace_subtree": str(ws)} for ws in g]} for g in groups],
    }


async def _matches(
    app: AsyncEngine,
    *,
    scope: uuid.UUID | None,
    tenant: uuid.UUID,
    user: uuid.UUID,
    audience: object,
    principal: uuid.UUID | None = None,
) -> bool:
    """`platform.audience_matches` as `dw_app`, in a transaction whose
    `app.tenant_id` is ``scope`` (unset when None)."""
    async with app.begin() as conn:
        if scope is not None:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(scope)}
            )
        if principal is not None:
            await conn.execute(
                sa.text("SELECT set_config('app.principal_id', :p, true)"), {"p": str(principal)}
            )
        answer = await conn.scalar(
            sa.text("SELECT platform.audience_matches(:t, :u, CAST(:a AS jsonb))"),
            {"t": tenant, "u": user, "a": json.dumps(audience)},
        )
    assert answer is not None
    return bool(answer)


# R8.3 -----------------------------------------------------------------------


async def test_a_document_matches_when_one_group_matches_and_a_group_needs_every_condition(
    app_engine: AsyncEngine, world: World
) -> None:
    w = world

    async def matches(user: str, *groups: tuple[uuid.UUID, ...]) -> bool:
        return await _matches(
            app_engine,
            scope=w.tenant_a,
            tenant=w.tenant_a,
            user=w.users[user],
            audience=_doc(*groups),
        )

    assert await matches("w1", (w.w1,))
    assert await matches("w1", (w.w2,), (w.w1,))
    assert not await matches("w1", (w.w2,))
    assert not await matches("w1", (w.w1, w.w2))
    assert await matches("both", (w.w1, w.w2))
    assert await matches("w2", (w.w1, w.w2), (w.w2,))


# R8.4 -----------------------------------------------------------------------


async def test_a_member_who_is_not_active_matches_nothing(
    app_engine: AsyncEngine, world: World
) -> None:
    w = world

    assert not await _matches(
        app_engine,
        scope=w.tenant_a,
        tenant=w.tenant_a,
        user=w.users["suspended"],
        audience=_doc((w.w1,)),
    )


async def test_standing_in_another_tenant_does_not_make_a_suspended_member_active(
    app_engine: AsyncEngine, world: World
) -> None:
    """With the person as `app.principal_id`, `tenant_members_self_select`
    shows their active row in B; only the function's own tenant filter keeps
    it from standing in for the suspended one in A."""
    w = world
    person = w.users["suspended_here"]

    assert not await _matches(
        app_engine,
        scope=w.tenant_a,
        tenant=w.tenant_a,
        user=person,
        audience=_doc((w.w1,)),
        principal=person,
    )


async def test_a_person_of_another_tenant_never_matches_this_tenants_audience(
    app_engine: AsyncEngine, world: World
) -> None:
    w = world

    assert not await _matches(
        app_engine, scope=w.tenant_a, tenant=w.tenant_a, user=w.users["b"], audience=_doc((w.wb,))
    )


@pytest.mark.parametrize("principal_is_the_person", [False, True])
async def test_another_tenants_audience_is_never_answered_from_this_tenants_transaction(
    app_engine: AsyncEngine, world: World, principal_is_the_person: bool
) -> None:
    """`tenant_members_self_select` and `memberships_self_select` show a person
    their own rows in every tenant once `app.principal_id` is set; only the
    comparison with `app.tenant_id` keeps B's answer out of A's transaction."""
    w = world
    person = w.users["b"]
    # The function is right about B in B's own transaction, so a false below is
    # the tenant comparison and not a person who matches nothing.
    assert await _matches(
        app_engine, scope=w.tenant_b, tenant=w.tenant_b, user=person, audience=_doc((w.wb,))
    )

    assert not await _matches(
        app_engine,
        scope=w.tenant_a,
        tenant=w.tenant_b,
        user=person,
        audience=_doc((w.wb,)),
        principal=person if principal_is_the_person else None,
    )


async def test_no_tenant_in_the_transaction_matches_nothing(
    app_engine: AsyncEngine, world: World
) -> None:
    w = world
    person = w.users["straddler"]

    assert not await _matches(
        app_engine,
        scope=None,
        tenant=w.tenant_a,
        user=person,
        audience=_doc((w.w1,)),
        principal=person,
    )


async def test_a_straddler_matches_by_the_tenant_asked_only(
    app_engine: AsyncEngine, world: World
) -> None:
    """A person in A (W1) and B (WB): in A's transaction, B's workspace is not
    a membership A answers for, even with the person as principal."""
    w = world
    person = w.users["straddler"]

    assert await _matches(
        app_engine, scope=w.tenant_a, tenant=w.tenant_a, user=person, audience=_doc((w.w1,))
    )
    assert not await _matches(
        app_engine,
        scope=w.tenant_a,
        tenant=w.tenant_a,
        user=person,
        audience=_doc((w.wb,)),
        principal=person,
    )


@pytest.mark.parametrize(
    "audience",
    [
        {"schema": "dw.audience/v1", "any_of": [{"all_of": []}]},
        {"any_of": [{"all_of": []}]},
        "<W1>-team",
        "<W1>-not-uuid",
        "<W1>-schema",
        {"schema": "dw.audience/v1", "any_of": {"all_of": []}},
        {"schema": "dw.audience/v1", "any_of": [{"all_of": "x"}]},
        {"schema": "dw.audience/v1", "any_of": ["x", 1, None]},
        {"schema": "dw.audience/v1", "any_of": [{"all_of": [1, "x", None, []]}]},
        [],
        "plain string",
        None,
    ],
    ids=[
        "empty group",
        "no schema",
        "team condition",
        "not a uuid",
        "another schema",
        "any_of an object",
        "all_of a string",
        "groups not objects",
        "conditions not objects",
        "an array",
        "a string",
        "json null",
    ],
)
async def test_a_bad_document_is_false_and_never_an_error(
    app_engine: AsyncEngine, world: World, audience: object
) -> None:
    w = world
    w1 = str(w.w1)
    if audience == "<W1>-team":
        audience = {"schema": "dw.audience/v1", "any_of": [{"all_of": [{"team": w1}]}]}
    elif audience == "<W1>-not-uuid":
        audience = {
            "schema": "dw.audience/v1",
            "any_of": [{"all_of": [{"workspace_subtree": w1 + "x"}]}],
        }
    elif audience == "<W1>-schema":
        audience = {"schema": "dw.audience/v2", "any_of": [{"all_of": [{"workspace_subtree": w1}]}]}

    assert not await _matches(
        app_engine, scope=w.tenant_a, tenant=w.tenant_a, user=w.users["w1"], audience=audience
    )


async def test_an_empty_group_beside_a_real_one_is_not_true_for_everyone(
    app_engine: AsyncEngine, world: World
) -> None:
    w = world
    audience = {
        "schema": "dw.audience/v1",
        "any_of": [{"all_of": [{"workspace_subtree": str(w.w2)}]}, {"all_of": []}],
    }

    assert not await _matches(
        app_engine, scope=w.tenant_a, tenant=w.tenant_a, user=w.users["w1"], audience=audience
    )


async def test_a_bad_group_does_not_hide_a_good_one(app_engine: AsyncEngine, world: World) -> None:
    w = world
    audience = {
        "schema": "dw.audience/v1",
        "any_of": [
            {"all_of": [{"team": str(w.w1)}]},
            {"all_of": [{"workspace_subtree": str(w.w1)}]},
        ],
    }

    assert await _matches(
        app_engine, scope=w.tenant_a, tenant=w.tenant_a, user=w.users["w1"], audience=audience
    )


# R8.2: the workspaces port, with the real adapter ----------------------------


def _context(w: World, principal: str) -> AccessContext:
    return AccessContext(
        tenant_id=w.tenant_a,
        workspace_id=w.w1,
        principal_id=w.users[principal],
        roles=frozenset({"member"}),
        scopes=frozenset(),
        plan_id="professional",
    )


async def test_the_validator_accepts_this_tenants_workspaces(
    app_engine: AsyncEngine, world: World
) -> None:
    w = world
    validator = AudienceValidator(SqlAudienceWorkspaces(async_sessionmaker(app_engine)))

    document = await validator.validate(_context(w, "w1"), _doc((w.w1, w.w2)), at="/audience")

    assert document.workspace_ids() == {w.w1, w.w2}


async def test_another_tenants_workspace_and_a_missing_one_are_the_same_refusal(
    app_engine: AsyncEngine, world: World
) -> None:
    """The caller is the straddler, whose `app.principal_id` makes
    `workspaces_self_select` show B's WB: only the adapter's explicit tenant
    filter refuses it."""
    w = world
    validator = AudienceValidator(SqlAudienceWorkspaces(async_sessionmaker(app_engine)))

    with pytest.raises(AudienceInvalidError) as caught:
        await validator.validate(
            _context(w, "straddler"), _doc((w.w1,), (w.wb,), (uuid.uuid4(),)), at="/audience"
        )

    refused = caught.value
    assert refused.reason_code == "audience_invalid"
    assert [(p.pointer, p.code, p.detail) for p in refused.problems] == [
        (
            "/audience/any_of/1/all_of/0",
            "audience_workspace_unknown",
            "the workspace is not one of this company's",
        ),
        (
            "/audience/any_of/2/all_of/0",
            "audience_workspace_unknown",
            "the workspace is not one of this company's",
        ),
    ]


async def test_the_principal_does_see_the_other_tenants_workspace_through_rls(
    app_engine: AsyncEngine, world: World
) -> None:
    """The premise of the test above, measured: without the adapter's tenant
    filter, A's transaction would read B's workspace for the straddler."""
    w = world
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.principal_id', :p, true)"
            ),
            {"t": str(w.tenant_a), "p": str(w.users["straddler"])},
        )
        seen = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.workspaces WHERE id = :ws"), {"ws": w.wb}
        )
    assert seen == 1
