"""The worker's key service settings (connections-and-vault R2.2, CV5): the
API's rule, held by the worker's own `validate_for_profile`, which `main` runs
before any lane is built."""

from __future__ import annotations

import base64

import pytest
from pydantic import SecretStr

from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit

MASTER_B64 = base64.b64encode(bytes(range(32))).decode()


def _deployed_worker(profile: str, **overrides: object) -> WorkerSettings:
    values: dict[str, object] = {
        "profile": profile,
        "database_url": "postgresql+asyncpg://u:p@db/dw",
        "embedding_provider": "openai_compatible",
        "qdrant_url": "https://qdrant.example:6333",
        "qdrant_api_key": "unit-test-qdrant-key",
        "unsubscribe_signing_secret": "unit-test-unsubscribe-secret-0123456789",
        "worker_replicas": 1,
    }
    values.update(overrides)
    return WorkerSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_a_deployed_worker_refuses_the_local_key_service(profile: str) -> None:
    refused = _deployed_worker(
        profile, kms_provider="local", local_kms_master_key=SecretStr(MASTER_B64)
    )
    with pytest.raises(RuntimeError, match="DW_KMS_PROVIDER=local is forbidden"):
        refused.validate_for_profile()
    _deployed_worker(profile).validate_for_profile()


def test_the_default_is_no_key_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DW_KMS_PROVIDER", raising=False)
    assert WorkerSettings(profile="local").kms_provider == "none"  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "key", ["", base64.b64encode(bytes(31)).decode()], ids=["empty", "31 bytes"]
)
def test_a_local_key_service_without_a_full_master_key_does_not_start(key: str) -> None:
    settings = WorkerSettings(  # type: ignore[call-arg]
        profile="local", kms_provider="local", local_kms_master_key=SecretStr(key)
    )
    with pytest.raises(RuntimeError, match="DW_LOCAL_KMS_MASTER_KEY"):
        settings.validate_for_profile()
    WorkerSettings(  # type: ignore[call-arg]
        profile="local", kms_provider="local", local_kms_master_key=SecretStr(MASTER_B64)
    ).validate_for_profile()
