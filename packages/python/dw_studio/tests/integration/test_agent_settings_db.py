"""`studio.agent_settings` and `AgentSettingsService` against Postgres
(agent-builder ticket 02: R1.1, R1.4, R1.5, R1.8, R1.11, R6.1; AB10, AB12,
AB15; ADR-0117 decision 3).

The service runs over the real store as `dw_app` under each caller's tenant;
the table's own refusals are planted as the migrator. The HTTP half (status
codes, `ETag`, `If-Match`, idempotency) is `apps/api`'s
`test_studio_agent_settings.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, NotFoundError, PermissionDeniedError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.audience_workspaces import SqlAudienceWorkspaces
from dw_platform.application.access_context import AccessContext
from dw_platform.application.audience import AudienceValidator
from dw_platform.domain.audience import AudienceDocument, AudienceInvalidError
from dw_platform.testing.rbac import PlantedTenant, plant_person, plant_tenant
from dw_studio.agents.adapters.settings_store import SqlAgentSettingsStore
from dw_studio.agents.application.settings import (
    AGENTS_AUTHOR_SCOPE,
    AGENTS_MANAGE_SETTINGS_SCOPE,
    AgentSettingsService,
)
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.kinds import agent_kind
from dw_studio.testing.agents import agent_document, audience, plant_agent_people
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


class ExplodingAudience:
    """A validator that fails, as a database it reads might."""

    async def validate(
        self, context: AccessContext, document: object, *, at: str = ""
    ) -> AudienceDocument:
        raise RuntimeError("the audience validator failed")


@dataclass
class World:
    migrator: AsyncEngine
    tenant: PlantedTenant
    other: PlantedTenant
    people: dict[str, Person]
    strangers: dict[str, Person]
    artifacts: ArtifactService
    settings: AgentSettingsService
    sessions: async_sessionmaker[AsyncSession]

    def __getitem__(self, name: str) -> Person:
        return self.people[name]

    async def agent(self, who: str = "author", *, kind_people: str = "tenant") -> uuid.UUID:
        person = (self.people if kind_people == "tenant" else self.strangers)[who]
        row, _ = await self.artifacts.create(
            person.context(),
            kind="agent",
            api_name=f"ag_{uuid.uuid4().hex[:12]}",
            labels=[],
            document=agent_document(),
        )
        return row.id

    async def rows(self, statement: str, **values: Any) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list((await conn.execute(sa.text(statement), values)).all())

    async def settings_rows(self, artifact_id: uuid.UUID) -> list[Any]:
        return await self.rows(
            "SELECT * FROM studio.agent_settings WHERE artifact_id = :a", a=artifact_id
        )

    async def audits(self, artifact_id: uuid.UUID) -> list[Any]:
        return await self.rows(
            "SELECT tenant_id, actor_id, details FROM platform.audit_events"
            " WHERE action = 'studio.agent.settings_changed' AND resource_id = :a",
            a=str(artifact_id),
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(studio_db: DatabaseUrls) -> AsyncIterator[World]:
    migrator = create_async_engine(studio_db.migrator, poolclass=NullPool)
    app = create_async_engine(studio_db.app, poolclass=NullPool)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        other = await plant_tenant(conn)
        people = await plant_agent_people(conn, tenant)
        strangers = await plant_agent_people(conn, other)
    ids = Uuid7Generator()
    sessions = async_sessionmaker(app, class_=AsyncSession, expire_on_commit=False)
    store = SqlArtifactStore(sessions, ids)
    yield World(
        migrator=migrator,
        tenant=tenant,
        other=other,
        people=people,
        strangers=strangers,
        artifacts=ArtifactService(store, ArtifactKindRegistry((agent_kind(),)), SystemClock(), ids),
        settings=AgentSettingsService(
            SqlAgentSettingsStore(store),
            AudienceValidator(SqlAudienceWorkspaces(sessions)),
            SystemClock(),
            ids,
        ),
        sessions=sessions,
    )
    await app.dispose()
    await migrator.dispose()


async def create(
    world: World,
    artifact_id: uuid.UUID,
    who: str = "manager",
    *,
    owner: uuid.UUID | None = None,
    enabled: bool = True,
    workspaces: tuple[uuid.UUID, ...] | None = None,
) -> Any:
    return await world.settings.create(
        world[who].context(),
        artifact_id,
        audience=audience(*(workspaces or (world.tenant.main,))),
        owner_user_id=owner or world["owner"].id,
        enabled=enabled,
    )


# ---- the catalogue (R1.8; OPS-b) ------------------------------------------------


async def test_r1_8_the_kind_row_and_both_keys_are_in_the_catalogue(world: World) -> None:
    kind = await world.rows(
        "SELECT has_quality_gate FROM studio.artifact_kinds WHERE kind = 'agent'"
    )
    assert [row.has_quality_gate for row in kind] == [True]
    keys = await world.rows(
        "SELECT key, area, scope_kind, risk, status, owner_package, tenant_grantable"
        " FROM platform.permissions WHERE key = ANY(:k) ORDER BY key",
        k=[AGENTS_AUTHOR_SCOPE, AGENTS_MANAGE_SETTINGS_SCOPE],
    )
    assert [tuple(row) for row in keys] == [
        (key, "studio", "workspace", "standard", "active", "dw_studio", True)
        for key in sorted((AGENTS_AUTHOR_SCOPE, AGENTS_MANAGE_SETTINGS_SCOPE))
    ]


# ---- R1.4 (AB10): `enabled` is stated or refused --------------------------------


async def test_r1_4_a_row_without_enabled_is_refused_by_postgres(world: World) -> None:
    artifact_id = await world.agent()
    async with world.migrator.connect() as conn:
        with pytest.raises(IntegrityError, match="enabled"):
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.agent_settings"
                    " (tenant_id, artifact_id, audience, owner_user_id, row_version)"
                    " VALUES (:t, :a, CAST(:aud AS jsonb), :o, 1)"
                ),
                {
                    "t": world.tenant.tenant_id,
                    "a": artifact_id,
                    "aud": '{"schema": "dw.audience/v1", "any_of": []}',
                    "o": world["owner"].id,
                },
            )
    assert await world.settings_rows(artifact_id) == []
    column = await world.rows(
        "SELECT is_nullable, column_default FROM information_schema.columns"
        " WHERE table_schema = 'studio' AND table_name = 'agent_settings'"
        " AND column_name = 'enabled'"
    )
    assert [tuple(row) for row in column] == [("NO", None)]


async def test_a_row_naming_another_companys_agent_or_member_is_refused(world: World) -> None:
    """The composite keys: a row of company B cannot point at A's agent, nor
    name a person who is no member of its company."""
    artifact_id = await world.agent()
    stranger = world.strangers["owner"].id
    for tenant_id, owner in ((world.other.tenant_id, stranger), (world.tenant.tenant_id, stranger)):
        async with world.migrator.connect() as conn:
            with pytest.raises(IntegrityError, match="fk_agent_settings"):
                await conn.execute(
                    sa.text(
                        "INSERT INTO studio.agent_settings (tenant_id, artifact_id, audience,"
                        " owner_user_id, enabled, row_version)"
                        " VALUES (:t, :a, CAST(:aud AS jsonb), :o, true, 1)"
                    ),
                    {
                        "t": tenant_id,
                        "a": artifact_id,
                        "aud": '{"schema": "dw.audience/v1", "any_of": []}',
                        "o": owner,
                    },
                )


# ---- R1.1: one row, its values, one audit ---------------------------------------


async def test_r1_1_settings_are_one_row_from_the_body_with_one_audit(world: World) -> None:
    artifact_id = await world.agent()
    row = await create(world, artifact_id, enabled=False)

    assert (row.enabled, row.owner_user_id, row.row_version) == (False, world["owner"].id, 1)
    stored = await world.settings_rows(artifact_id)
    assert len(stored) == 1
    assert stored[0].audience == audience(world.tenant.main)
    audits = await world.audits(artifact_id)
    assert len(audits) == 1
    assert audits[0].actor_id == world["manager"].id
    assert audits[0].details["changes"] == {
        "audience": {"before": None, "after": audience(world.tenant.main)},
        "owner_user_id": {"before": None, "after": str(world["owner"].id)},
        "enabled": {"before": None, "after": False},
    }

    with pytest.raises(ConflictError) as caught:
        await create(world, artifact_id)
    assert caught.value.details["reason_code"] == "settings_exist"
    assert len(await world.settings_rows(artifact_id)) == 1
    assert len(await world.audits(artifact_id)) == 1


async def test_r1_1_two_concurrent_creates_give_one_row_and_one_conflict(world: World) -> None:
    artifact_id = await world.agent()
    answers = await asyncio.gather(
        create(world, artifact_id), create(world, artifact_id), return_exceptions=True
    )
    assert sorted(type(a).__name__ for a in answers) == ["AgentSettingsRow", "ConflictError"]
    assert len(await world.settings_rows(artifact_id)) == 1


# ---- R1.5 (AB10, AB12): the validator and the owner -----------------------------


async def test_r1_5_an_empty_audience_writes_nothing(world: World) -> None:
    artifact_id = await world.agent()
    with pytest.raises(AudienceInvalidError) as caught:
        await world.settings.create(
            world["manager"].context(),
            artifact_id,
            audience=audience(),
            owner_user_id=world["owner"].id,
            enabled=True,
        )
    assert caught.value.reason_code == "audience_empty"
    assert [p.pointer for p in caught.value.problems] == ["/audience/any_of"]
    assert await world.settings_rows(artifact_id) == []
    assert await world.audits(artifact_id) == []


async def test_r1_5_a_failing_validator_writes_nothing(world: World) -> None:
    artifact_id = await world.agent()
    exploding = AgentSettingsService(
        world.settings.store, ExplodingAudience(), SystemClock(), Uuid7Generator()
    )
    with pytest.raises(RuntimeError):
        await exploding.create(
            world["manager"].context(),
            artifact_id,
            audience=audience(world.tenant.main),
            owner_user_id=world["owner"].id,
            enabled=True,
        )
    assert await world.settings_rows(artifact_id) == []
    assert await world.audits(artifact_id) == []


async def test_r1_5_a_workspace_of_another_company_is_the_unknown_workspace(world: World) -> None:
    """AB12: company B names A's workspace in its own agent's audience; the
    refusal is exactly a random workspace's."""
    artifact_id = await world.agent(kind_people="other")
    refusals = []
    for workspace in (world.tenant.main, uuid.uuid4()):
        with pytest.raises(AudienceInvalidError) as caught:
            await world.settings.create(
                world.strangers["manager"].context(),
                artifact_id,
                audience=audience(workspace),
                owner_user_id=world.strangers["owner"].id,
                enabled=True,
            )
        refusals.append(
            (
                caught.value.reason_code,
                [(p.pointer, p.code, p.detail) for p in caught.value.problems],
            )
        )
    assert refusals[0] == refusals[1]
    assert refusals[0][1] == [
        (
            "/audience/any_of/0/all_of/0",
            "audience_workspace_unknown",
            "the workspace is not one of this company's",
        )
    ]
    assert await world.settings_rows(artifact_id) == []


async def owner_refusal(world: World, owner: uuid.UUID) -> list[tuple[str, str]]:
    artifact_id = await world.agent()
    with pytest.raises(DocumentInvalidError) as caught:
        await create(world, artifact_id, owner=owner)
    assert await world.settings_rows(artifact_id) == []
    return [(p.pointer, p.code) for p in caught.value.problems]


async def test_r1_5_an_owner_who_is_not_an_active_person_is_one_refusal(world: World) -> None:
    async with world.migrator.begin() as conn:
        service = await plant_person(conn, world.tenant.tenant_id, kind="service")
        suspended = await plant_person(conn, world.tenant.tenant_id, status="suspended")
    expected = [("/owner_user_id", "owner_unknown")]
    for owner in (uuid.uuid4(), world.strangers["owner"].id, service, suspended):
        assert await owner_refusal(world, owner) == expected


# ---- R1.11 (AB15), R6.1 (AB12): who may -----------------------------------------


async def test_r1_11_the_settings_key_alone_is_enough_and_the_author_key_is_not(
    world: World,
) -> None:
    artifact_id = await world.agent()
    await create(world, artifact_id, who="manager")
    assert (await world.settings.get(world["manager"].context(), artifact_id)).row_version == 1

    with pytest.raises(PermissionDeniedError):
        await world.settings.get(world["author"].context(), artifact_id)
    with pytest.raises(PermissionDeniedError):
        await world.settings.update(
            world["author"].context(), artifact_id, ExpectedVersion(1), {"enabled": False}
        )
    for who in ("nobody", "elsewhere"):
        with pytest.raises(NotFoundError):
            await world.settings.update(
                world[who].context(), artifact_id, ExpectedVersion(1), {"enabled": False}
            )
    assert (await world.settings_rows(artifact_id))[0].enabled is True
    assert len(await world.audits(artifact_id)) == 1


async def test_r6_1_another_company_meets_the_id_of_nothing(world: World) -> None:
    artifact_id = await world.agent()
    await create(world, artifact_id)
    stranger = world.strangers["both"].context()
    for call in (
        world.settings.get(stranger, artifact_id),
        world.settings.update(stranger, artifact_id, ExpectedVersion(1), {"enabled": False}),
        world.settings.create(
            stranger,
            artifact_id,
            audience=audience(world.other.main),
            owner_user_id=world.strangers["owner"].id,
            enabled=True,
        ),
    ):
        with pytest.raises(NotFoundError) as caught:
            await call
        assert str(caught.value) == "agent not found"
    rows = await world.settings_rows(artifact_id)
    assert [(r.row_version, r.enabled) for r in rows] == [(1, True)]
    assert len(await world.audits(artifact_id)) == 1


async def test_rls_hides_every_row_from_another_company_and_from_no_company(world: World) -> None:
    artifact_id = await world.agent()
    await create(world, artifact_id)
    for tenant_id in (str(world.other.tenant_id), ""):
        async with world.sessions() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
            )
            count = await session.scalar(
                sa.text("SELECT count(*) FROM studio.agent_settings WHERE artifact_id = :a"),
                {"a": artifact_id},
            )
        assert count == 0


# ---- the keys' ON DELETE ----------------------------------------------------------


async def test_an_owner_who_leaves_leaves_a_null_owner_and_the_row(world: World) -> None:
    artifact_id = await world.agent()
    async with world.migrator.begin() as conn:
        leaving = await plant_person(conn, world.tenant.tenant_id)
    await create(world, artifact_id, owner=leaving)
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": world.tenant.tenant_id, "u": leaving},
        )
    rows = await world.settings_rows(artifact_id)
    assert [(r.owner_user_id, r.enabled) for r in rows] == [(None, True)]
