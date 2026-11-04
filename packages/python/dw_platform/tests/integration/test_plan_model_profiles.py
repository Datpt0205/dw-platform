"""`platform.plan_model_profiles` as migration d66d6913b249 leaves it
(model-connections ticket 02: R2.1, R2.2; MR3).

The seed lists every shipped profile for every plan, every row names a profile
`configs/models` ships (failure-modes #2: the table and the directory are two
copies of one fact, and this is what makes them disagree loudly), and the
adapter reads a plan's list as `dw_app`. Who may write the table is
`test_privileges.py`; the resolver's filter over it is `dw_agent_runtime`'s
`test_model_resolver.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.plan_model_profiles import SqlPlanModelProfiles

pytestmark = pytest.mark.integration

_MODELS = Path(__file__).resolve().parents[5] / "configs" / "models"
# What the revision seeded: the profiles `configs/models` shipped at it.
_SEEDED = frozenset({"balanced", "deepseek", "gateway", "low_cost", "luna", "openai"})


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_sessions(db_urls: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _shipped() -> frozenset[str]:
    return frozenset(path.stem for path in _MODELS.glob("*.yaml"))


async def _rows(engine: AsyncEngine) -> set[tuple[str, str]]:
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text("SELECT plan_id, profile_id FROM platform.plan_model_profiles")
        )
        return {(row.plan_id, row.profile_id) for row in result}


async def test_every_plan_lists_every_profile_the_revision_shipped(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        plans = set(await conn.scalars(sa.text("SELECT plan_id FROM platform.plans")))
    assert plans >= {"basic", "professional", "enterprise"}
    assert await _rows(migrator) == {(plan, profile) for plan in plans for profile in _SEEDED}


async def test_every_listed_profile_is_one_configs_models_ships(migrator: AsyncEngine) -> None:
    """R2.1: a row naming a profile no file defines is a plan promising a model
    the resolver can never answer with; this fails it, by name."""
    unknown = {profile for _plan, profile in await _rows(migrator)} - _shipped()
    assert unknown == set(), f"plan_model_profiles names profiles configs/models lacks: {unknown}"


async def test_the_check_reads_the_table_not_a_copy(migrator: AsyncEngine) -> None:
    """The test above can fail: a row for a profile no file defines makes it red."""
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.plan_model_profiles (plan_id, profile_id)"
                " VALUES ('basic', 'premium_nowhere')"
            )
        )
    try:
        with pytest.raises(AssertionError, match="premium_nowhere"):
            await test_every_listed_profile_is_one_configs_models_ships(migrator)
    finally:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "DELETE FROM platform.plan_model_profiles WHERE profile_id = 'premium_nowhere'"
                )
            )


async def test_a_row_names_a_plan_that_exists_and_a_profile(migrator: AsyncEngine) -> None:
    for statement in (
        "INSERT INTO platform.plan_model_profiles VALUES ('no_such_plan', 'balanced')",
        "INSERT INTO platform.plan_model_profiles VALUES ('basic', '')",
        "INSERT INTO platform.plan_model_profiles VALUES ('basic', 'balanced')",
    ):
        async with migrator.connect() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(sa.text(statement))


async def test_the_adapter_reads_a_plans_list_as_dw_app(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    profiles = SqlPlanModelProfiles(app_sessions)
    assert await profiles.allowed("basic") == _SEEDED
    # R2.2: a plan with no rows, a made-up one like `background`, lists none.
    assert await profiles.allowed("background") == frozenset()
