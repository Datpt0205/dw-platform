"""The worker's process count and its rate limiter (custom-objects ticket 03,
R7.6; usage-and-limits R7.1), and the purger of `studio.record_write_keys`."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import SystemClock
from dw_studio.records.adapters.record_store import RECORD_WRITE_KEYS
from dw_worker.main import build_rate_limiter, build_retention_purgers
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit


def _deployed(profile: str, **overrides: object) -> WorkerSettings:
    values: dict[str, object] = {
        "profile": profile,
        "database_url": "postgresql+asyncpg://u:p@db/dw",
        "embedding_provider": "openai_compatible",
        "qdrant_url": "https://qdrant.example:6333",
        "qdrant_api_key": "unit-test-qdrant-key",
        "unsubscribe_signing_secret": "unit-test-unsubscribe-secret-0123456789",
        "worker_replicas": 2,
        **overrides,
    }
    return WorkerSettings.model_validate(values)


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_r7_6_a_deployed_worker_without_its_process_count_does_not_start(profile: str) -> None:
    _deployed(profile).validate_for_profile()
    with pytest.raises(RuntimeError, match="DW_WORKER_REPLICAS"):
        _deployed(profile, worker_replicas=None).validate_for_profile()


def test_the_limiter_takes_the_process_count_and_one_locally() -> None:
    assert build_rate_limiter(_deployed("uat", worker_replicas=3), SystemClock()).replicas == 3
    local = WorkerSettings.model_validate({"profile": "local"})
    local.validate_for_profile()
    assert build_rate_limiter(local, SystemClock()).replicas == 1


def test_the_write_keys_have_their_purger() -> None:
    purgers = build_retention_purgers(async_sessionmaker(class_=AsyncSession))
    assert RECORD_WRITE_KEYS in purgers.all()
