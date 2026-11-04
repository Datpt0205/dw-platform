"""The worker builds its model stack with the API's builder (`model_stack`).

One builder for both composition roots, so a model call made in the worker (a
product's chat command) spends against the same per-run ledger and daily spend
guard, and is refused the same way in a deployed profile.
"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.model_stack import ModelStack
from dw_agent_runtime.adapters.usage_recorders import CompositeUsageRecorder
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.ports import SystemClock
from dw_observability.telemetry import NullTelemetry
from dw_usage.adapters.price_book_file import load_price_book
from dw_usage.application.recorder import LedgerUsageRecorder
from dw_usage.domain.pricing import PriceBook
from dw_worker.composition import build_model_stack_for, model_provider_config
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit

_SESSIONS = cast(async_sessionmaker[AsyncSession], object())


def test_the_worker_maps_its_settings_onto_the_shared_builder() -> None:
    settings = WorkerSettings(  # type: ignore[call-arg]
        model_provider="openai_compatible",
        openai_api_key="sk-test",
        openai_base_url="https://gateway.example/v1",
        outbound_allowed_hosts=["gateway.example"],
    )
    config = model_provider_config(settings)
    assert config.provider == "openai_compatible"
    assert config.openai_base_url == "https://gateway.example/v1"
    assert config.outbound_allowed_hosts == ("gateway.example",)
    assert config.is_deployed is False


def test_the_worker_builds_one_gateway_and_one_ledger() -> None:
    stack = build_model_stack_for(
        WorkerSettings(model_provider="mock"),  # type: ignore[call-arg]
        _SESSIONS,
        clock=SystemClock(),
        telemetry=NullTelemetry(),
        run_control=OpenRunControl(),
    )
    assert isinstance(stack, ModelStack)
    assert stack.gateway is not None and stack.budget is not None


def test_every_recorded_call_reaches_the_usage_ledger_priced_by_the_book() -> None:
    """usage-and-limits R3.1, R2.1: the composite the gateway and the meter
    record into carries the ledger's recorder, and the gateway prices by the
    shipped book; without either, a call leaves no usage record or no price."""
    stack = build_model_stack_for(
        WorkerSettings(model_provider="mock"),  # type: ignore[call-arg]
        _SESSIONS,
        clock=SystemClock(),
        telemetry=NullTelemetry(),
        run_control=OpenRunControl(),
    )
    recorder = stack.usage_recorder
    assert isinstance(recorder, CompositeUsageRecorder)
    assert [type(r) for r in recorder.recorders].count(LedgerUsageRecorder) == 1
    assert isinstance(stack.gateway.pricing, PriceBook)
    assert stack.gateway.pricing.version == load_price_book().version


def test_a_deployed_worker_is_refused_the_fixture_model() -> None:
    settings = WorkerSettings(  # type: ignore[call-arg]
        profile="production", model_provider="mock"
    )
    with pytest.raises(RuntimeError, match="mock"):
        build_model_stack_for(
            settings,
            _SESSIONS,
            clock=SystemClock(),
            telemetry=NullTelemetry(),
            run_control=OpenRunControl(),
        )


def _deployed_worker(**overrides: object) -> WorkerSettings:
    values: dict[str, object] = {
        "profile": "uat",
        "database_url": "postgresql+asyncpg://u:p@db/dw",
        "embedding_provider": "openai_compatible",
        "qdrant_url": "https://qdrant.example:6333",
        "qdrant_api_key": "unit-test-qdrant-key",
        "unsubscribe_signing_secret": "unit-test-unsubscribe-secret-0123456789",
    }
    values.update(overrides)
    return WorkerSettings(**values)  # type: ignore[arg-type]


def test_a_deployed_worker_without_a_qdrant_key_does_not_start() -> None:
    """runtime-hardening R8.2 (RH22). The control: with it, it starts."""
    _deployed_worker().validate_for_profile()
    with pytest.raises(RuntimeError, match="Qdrant API key"):
        _deployed_worker(qdrant_api_key=None).validate_for_profile()
    with pytest.raises(RuntimeError, match="Qdrant API key"):
        _deployed_worker(qdrant_api_key="").validate_for_profile()
