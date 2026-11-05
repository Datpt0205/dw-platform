"""The API's startup heap is frozen out of the collector once, after the
container and the app are built, and unfrozen on shutdown (tenant-rbac/07, K3).

discovery/08 measured every P95 miss of `GET /api/v1/me` at D12 as a full
collection walking the startup heap (~240 ms each); `gc.freeze()` in the
lifespan is what removes it, so these tests pin where and how often it runs.
"""

from __future__ import annotations

import gc

import pytest
from asgi_lifespan import LifespanManager

from dw_agent_runtime.adapters.run_events import RunStateListener
from dw_api.bootstrap import ApiContainer
from dw_api.health import HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.application.authorization import ScopeAuthorizationService

pytestmark = pytest.mark.unit


class RecordingListener(RunStateListener):
    """The LISTEN connection's start and stop, recorded instead of opened."""

    def __init__(self, calls: list[str]) -> None:
        super().__init__("postgresql://unused")
        self._calls = calls

    async def start(self) -> None:
        self._calls.append("run_events.start")

    async def stop(self) -> None:
        self._calls.append("run_events.stop")


def container(run_events: RunStateListener | None = None) -> ApiContainer:
    return ApiContainer(
        settings=ApiSettings(profile="test"),
        engine=None,
        health_service=HealthService(probes={}),
        token_verifier=None,
        access_context_factory=None,
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        run_events=run_events,
    )


async def test_the_startup_heap_is_frozen_once_after_the_app_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def recorder(name: str) -> object:
        def record(*_args: object, **_kwargs: object) -> int:
            calls.append(f"gc.{name}")
            return 0

        return record

    for name in ("collect", "freeze", "unfreeze"):
        monkeypatch.setattr(gc, name, recorder(name))

    app = create_app(container(RecordingListener(calls)))
    assert calls == [], "create_app runs before routes and middleware exist: it must not freeze"

    async with LifespanManager(app):
        assert calls == ["run_events.start", "gc.collect", "gc.freeze"]
    assert calls == [
        "run_events.start",
        "gc.collect",
        "gc.freeze",
        "gc.unfreeze",
        "run_events.stop",
    ]


async def test_the_heap_is_frozen_while_the_app_runs_and_released_after() -> None:
    """The real collector, no stand-in: objects sit in the permanent generation
    while the app serves, and none stay there once it has stopped."""
    gc.unfreeze()
    app = create_app(container())
    assert gc.get_freeze_count() == 0
    async with LifespanManager(app):
        assert gc.get_freeze_count() > 0
    assert gc.get_freeze_count() == 0
