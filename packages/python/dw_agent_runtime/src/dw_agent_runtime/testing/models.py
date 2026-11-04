"""Model routes and resolvers for tests (model-connections ticket 02).

A `ModelRoute` declares its data route with no default (R3.2), so a test that
builds one in code says where it processes too: `route(...)` declares the mock
adapter's values (`vn`, processed by `mock`, kept 0 days, no training), which is
what a fixture route is, and a test about a real route names its own.

A `ModelResolver` filters platform profiles by the run's plan; `any_plan(...)`
is a catalogue where every plan lists the profiles named, for a test whose
subject is not the plan filter.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from dw_agent_runtime.model.profiles import ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.resolver import ModelResolver, pin_entry
from dw_agent_runtime.ports import PinnedEnginePort, PlanModelProfilesPort

__all__ = ["AnyManifest", "AnyPlan", "any_plan", "pinned_default", "resolver", "route"]

_MOCK_DATA_ROUTE: dict[str, Any] = {
    "data_location": "vn",
    "processor": "mock",
    "retention_days": 0,
    "no_training": True,
}


def route(provider: str = "mock", model: str = "extraction-mock-1", **fields: Any) -> ModelRoute:
    """A route with the mock adapter's data route unless `fields` says otherwise."""
    return ModelRoute.model_validate(
        {"provider": provider, "model": model, **_MOCK_DATA_ROUTE, **fields}
    )


@dataclass(frozen=True)
class AnyPlan:
    """Every plan lists `profiles`; `asked` keeps each plan id asked about."""

    profiles: frozenset[str]
    asked: list[str]

    async def allowed(self, plan_id: str) -> frozenset[str]:
        self.asked.append(plan_id)
        return self.profiles


def any_plan(profiles: Iterable[str]) -> AnyPlan:
    return AnyPlan(frozenset(profiles), [])


@dataclass(frozen=True)
class AnyManifest:
    """`PinnedEnginePort` where every manifest pinned `pinned`: for a Studio
    run whose subject is not what it pinned."""

    pinned: Mapping[str, Any]

    async def engine(self, tenant_id: UUID, run_manifest_hash: str) -> Mapping[str, Any] | None:
        return self.pinned


def pinned_default(profiles: ModelProfileRegistry, profile_id: str) -> AnyManifest:
    """Every manifest pinned the platform's `profile_id` as its default."""
    profile = profiles.layer(profile_id, tenant_id=None)
    assert profile is not None, profile_id
    return AnyManifest(
        {
            "durability": "sync",
            "model_routes": {profile_id: pin_entry(profile, "platform")},
            "default_model_profile": profile_id,
        }
    )


def resolver(
    profiles: ModelProfileRegistry,
    default: str,
    *,
    plans: PlanModelProfilesPort | None = None,
    pinned: PinnedEnginePort | None = None,
) -> ModelResolver:
    """A resolver over `profiles`; without `plans`, every plan lists every
    platform profile registered."""
    catalogue = plans if plans is not None else any_plan(profiles.platform_ids())
    return ModelResolver(profiles, catalogue, default, pinned)
