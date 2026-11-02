"""The API's one limiter and its process count (usage-and-limits R7.1, UL14).

A deployed profile names how many API processes run, because unset reads as
one and N processes each allowing the whole limit allow N times it; local and
test run one.
"""

from __future__ import annotations

import pytest
from test_dev_endpoints import deployed_settings

from dw_api.bootstrap.wiring import build_container
from dw_api.settings import ApiSettings
from dw_platform.adapters.rate_limit import InProcessRateLimiter

pytestmark = pytest.mark.unit

_TEST_SECRET = "x" * 32


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_a_deployed_api_without_its_process_count_does_not_start(profile: str) -> None:
    settings = deployed_settings(profile).model_copy(update={"api_replicas": None})
    with pytest.raises(RuntimeError, match="DW_API_REPLICAS"):
        settings.validate_for_profile()


def test_the_control_a_deployed_api_with_its_process_count_starts() -> None:
    deployed_settings("uat").model_copy(update={"api_replicas": 2}).validate_for_profile()


def test_the_process_count_reads_from_dw_api_replicas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DW_API_REPLICAS", "3")
    assert ApiSettings().api_replicas == 3
    monkeypatch.setenv("DW_API_REPLICAS", "0")
    with pytest.raises(ValueError, match="DW_API_REPLICAS"):
        ApiSettings()


def test_a_local_api_without_a_process_count_builds_its_limiter_for_one() -> None:
    container = build_container(ApiSettings(profile="local", dev_secret=_TEST_SECRET))
    assert isinstance(container.rate_limiter, InProcessRateLimiter)
    assert container.rate_limiter.replicas == 1


def test_the_limiter_takes_the_process_count_the_settings_name() -> None:
    container = build_container(
        ApiSettings(profile="test", dev_secret=_TEST_SECRET, api_replicas=3)
    )
    assert isinstance(container.rate_limiter, InProcessRateLimiter)
    assert container.rate_limiter.replicas == 3
