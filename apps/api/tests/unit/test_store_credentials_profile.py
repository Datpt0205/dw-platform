"""A deployed API refuses to start without the stores' credentials
(runtime-hardening R8.2, RH22): an empty Qdrant API key, or a REDIS_URL without
the Valkey password. A local profile does not ask for them."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from test_dev_endpoints import deployed_settings

from dw_api.settings import ApiSettings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_a_deployed_api_without_a_qdrant_key_does_not_start(profile: str) -> None:
    settings = deployed_settings(profile).model_copy(update={"qdrant_api_key": None})
    with pytest.raises(RuntimeError, match="Qdrant API key"):
        settings.validate_for_profile()


def test_a_deployed_api_with_a_password_less_redis_url_does_not_start() -> None:
    settings = deployed_settings("uat").model_copy(update={"redis_url": "redis://valkey:6379/0"})
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        settings.validate_for_profile()
    with_password = deployed_settings("uat").model_copy(
        update={"redis_url": "redis://:s3cret@valkey:6379/0"}
    )
    with_password.validate_for_profile()


def test_the_control_a_deployed_api_with_both_starts_and_local_asks_for_neither() -> None:
    deployed_settings("uat").validate_for_profile()
    ApiSettings(
        profile="local", qdrant_api_key=None, redis_url="redis://valkey:6379/0"
    ).validate_for_profile()


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_a_deployed_api_with_a_short_unsubscribe_secret_does_not_start(profile: str) -> None:
    """compliance-pdpl R3.6 (CP29): a 16-byte secret is refused; 32 starts."""
    short = deployed_settings(profile).model_copy(
        update={"unsubscribe_signing_secret": SecretStr("x" * 16)}
    )
    with pytest.raises(RuntimeError, match="UNSUBSCRIBE_SIGNING_SECRET"):
        short.validate_for_profile()
    deployed_settings(profile).model_copy(
        update={"unsubscribe_signing_secret": SecretStr("x" * 32)}
    ).validate_for_profile()
