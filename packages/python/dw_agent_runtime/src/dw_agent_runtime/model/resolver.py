"""`ModelResolver`: the one answer to "which route does this model call take"
(model-connections R1, R2; ADR-0118 decision 1, Amendments 2026-11-04).

Every model door of a run asks it, once per call and before anything is sent:
the run budget (`RunBudgetMiddleware`, which usage-and-limits/03's
`LimitsMiddleware` replaces), the usage meter, the structured gateway and
context compaction. Each door reads `route` and then `fallbacks` from the
answer and nothing else, so the residency gate (compliance-pdpl/03) filters one
list before the first send.

The tenant, its plan and its workspace come from the run (`RunContext`), never
from a request, and there is no `tenant_id=None` answer:

1. the tenant's own profile (the tenant layer, not filtered by plan; in W1 only
   a test registers one, W2 loads tenant-config's `model_profile` versions);
2. else the platform's, only when `platform.plan_model_profiles` lists it for
   the run's plan (`PlanModelProfilesPort`; a plan with no rows lists nothing,
   and a catalogue that cannot be read raises rather than allows);
3. never another tenant's. No answer is `model_profile_unavailable`.

A Studio run (one with `run_manifest_hash`) does not resolve at all: it reads
the routes its manifest pinned by value at admission (`engine.model_routes`,
written through `pin`), refuses a profile it did not pin (`key_not_pinned`),
and refuses a pinned profile whose current content differs from the pinned
one, or a platform profile its plan no longer lists, with
`model_profile_unavailable` before anything is sent (R1.5).

The platform layer unfiltered is `platform_profile`, for composition roots and
scripts only (embedding width, the default profile, the chat model compiled
once for a pack's agent, `make check-model`, the eval scripts); a source scan
holds every other reader to `resolve` (MR1).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.profiles import (
    PINNED_ROUTES,
    ModelProfile,
    ModelProfileRegistry,
    ModelRoute,
)
from dw_agent_runtime.ports import PinnedEnginePort, PlanModelProfilesPort
from dw_kernel.canonical import content_hash
from dw_kernel.errors import (
    ConfigError,
    EntitlementDeniedError,
    NotFoundError,
    PermissionDeniedError,
)

__all__ = [
    "MODEL_PROFILE_UNAVAILABLE",
    "ModelResolver",
    "Purpose",
    "ResolvedRoute",
    "StaticPlanModelProfiles",
    "pin_entry",
    "profile_hash",
]

Purpose = Literal["chat", "structured_extraction", "reasoning", "deep_reasoning"]
Layer = Literal["platform", "tenant"]

MODEL_PROFILE_UNAVAILABLE: Final = "model_profile_unavailable"
# Manifests a process has read, by (tenant, hash). A body never changes under
# its hash, so an entry is never stale; the bound keeps a long-lived worker
# from holding every run it ever served (failure-modes #6).
_ENGINE_CACHE_SIZE: Final = 256


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    """One door's answer. No secret version: a call through a connection takes
    its latest unrevoked key when it is made (V4.35)."""

    profile_id: str
    layer: Layer
    # The profile's `routing_policy_version`.
    version: str
    # `profile_hash` of the profile the routes came from.
    content_hash: str
    purpose: Purpose
    route: ModelRoute
    # The profile's `fallback`, when it is a different model from `route`.
    fallbacks: tuple[ModelRoute, ...]

    @property
    def attempts(self) -> tuple[ModelRoute, ...]:
        """What a door may send to, in order: the route, then the fallbacks."""
        return (self.route, *self.fallbacks)


def profile_hash(profile: ModelProfile) -> str:
    """The content a run pins and a door compares: every route but `embedding`."""
    return content_hash(profile.pinned_routes())


def _unavailable(profile_id: str, reason: str) -> EntitlementDeniedError:
    return EntitlementDeniedError(
        "this model profile is not available to the run",
        details={
            "reason_code": MODEL_PROFILE_UNAVAILABLE,
            "reason": reason,
            "profile_id": profile_id,
        },
    )


def _not_pinned(key: str) -> ConfigError:
    return ConfigError(
        "the run manifest does not pin this model profile",
        details={"reason": "key_not_pinned", "kind": "model_profile", "key": key},
    )


def _choose(routes: Mapping[str, ModelRoute], profile_id: str, purpose: Purpose) -> ModelRoute:
    """`RoutingModelGateway`'s rule, now the only copy: `deep_reasoning` falls
    back to `reasoning` when the profile has none; `chat` has no fallback."""
    if purpose == "chat":
        chat = routes.get("chat")
        if chat is None:
            raise ConfigError("model profile has no chat route", details={"profile_id": profile_id})
        return chat
    if purpose == "deep_reasoning":
        return routes.get("deep_reasoning") or routes["reasoning"]
    return routes[purpose]


def _answer(
    profile_id: str,
    layer: Layer,
    version: str,
    digest: str,
    routes: Mapping[str, ModelRoute],
    purpose: Purpose,
) -> ResolvedRoute:
    route = _choose(routes, profile_id, purpose)
    fallback = routes.get("fallback")
    fallbacks = (
        (fallback,)
        if fallback is not None
        and (fallback.provider, fallback.model) != (route.provider, route.model)
        else ()
    )
    return ResolvedRoute(profile_id, layer, version, digest, purpose, route, fallbacks)


def _routes_of(profile: ModelProfile) -> dict[str, ModelRoute]:
    return {name: r for name in PINNED_ROUTES if (r := getattr(profile, name)) is not None}


@dataclass(frozen=True)
class StaticPlanModelProfiles:
    """`PlanModelProfilesPort` in memory, for scripts, evals and tests: each
    names the plans it runs under and the profiles they list. A plan not named
    lists nothing, as one with no rows does."""

    plans: Mapping[str, frozenset[str]]

    async def allowed(self, plan_id: str) -> frozenset[str]:
        return self.plans.get(plan_id, frozenset())


@dataclass
class ModelResolver:
    profiles: ModelProfileRegistry
    plans: PlanModelProfilesPort
    # The deployment's profile (`DW_API_MODEL_PROFILE`), for a call naming none.
    default_profile: str
    # Where a Studio run's pinned routes are read; None in a process that runs
    # no Studio run, where such a run's every call is refused.
    pinned: PinnedEnginePort | None = None
    _engines: OrderedDict[tuple[UUID, str], Mapping[str, Any]] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        # At startup, not on the first call: a default nobody registered.
        self.platform_profile(self.default_profile)

    # ---- the doors -------------------------------------------------------

    async def resolve(
        self, run_context: RunContext, profile_id: str | None, purpose: Purpose
    ) -> ResolvedRoute:
        """The route this run's call takes, or a refusal before anything is sent."""
        if not isinstance(run_context, RunContext):
            raise PermissionDeniedError(
                "a model route is resolved only for a run",
                details={"reason_code": "run_context_required"},
            )
        if run_context.run_manifest_hash is not None:
            return await self._pinned(run_context, profile_id, purpose)
        chosen = profile_id or self.default_profile
        profile, layer = await self._layered(run_context.tenant_id, run_context.plan_id, chosen)
        return _answer(
            chosen,
            layer,
            profile.routing_policy_version,
            profile_hash(profile),
            _routes_of(profile),
            purpose,
        )

    # ---- admission -------------------------------------------------------

    async def pin(
        self, tenant_id: UUID, plan_id: str | None, profile_ids: frozenset[str]
    ) -> dict[str, Any]:
        """What a Studio run's manifest pins under `engine` (R1.4): each profile
        the root declares, by value, and the deployment's default when the plan
        allows it. The tenant and plan come from the admitting door's verified
        context (R1.6). A declared profile with no answer refuses the admission;
        a default the plan does not list is simply not pinned, so a run that
        calls no model still runs."""
        allowed = await self.plans.allowed(plan_id) if plan_id else frozenset[str]()
        pins: dict[str, Any] = {}
        for profile_id in sorted(profile_ids):
            profile, layer = await self._layered(tenant_id, plan_id, profile_id, allowed=allowed)
            pins[profile_id] = pin_entry(profile, layer)
        default: str | None = self.default_profile
        try:
            profile, layer = await self._layered(
                tenant_id, plan_id, self.default_profile, allowed=allowed
            )
        except EntitlementDeniedError:
            default = None
        else:
            pins.setdefault(self.default_profile, pin_entry(profile, layer))
        return {"model_routes": pins, "default_model_profile": default}

    # ---- composition roots and scripts -----------------------------------

    def platform_profile(self, profile_id: str) -> ModelProfile:
        """The platform layer, unfiltered: never for a run's call."""
        profile = self.profiles.layer(profile_id, tenant_id=None)
        if profile is None:
            raise NotFoundError("model profile not registered", details={"profile_id": profile_id})
        return profile

    # ---- internals -------------------------------------------------------

    async def _layered(
        self,
        tenant_id: UUID,
        plan_id: str | None,
        profile_id: str,
        *,
        allowed: frozenset[str] | None = None,
    ) -> tuple[ModelProfile, Layer]:
        own = self.profiles.layer(profile_id, tenant_id=tenant_id)
        if own is not None:
            return own, "tenant"
        platform = self.profiles.layer(profile_id, tenant_id=None)
        if platform is None:
            raise _unavailable(profile_id, "not_registered")
        if allowed is None:
            allowed = await self.plans.allowed(plan_id) if plan_id else frozenset()
        if profile_id not in allowed:
            raise _unavailable(profile_id, "plan")
        return platform, "platform"

    async def _pinned(
        self, run_context: RunContext, profile_id: str | None, purpose: Purpose
    ) -> ResolvedRoute:
        engine = await self._engine(run_context.tenant_id, str(run_context.run_manifest_hash))
        # A manifest built before model routes were pinned has none: every
        # call of that run is refused, as an unpinned profile is.
        pinned_routes = engine.get("model_routes") or {}
        chosen = profile_id if profile_id is not None else engine.get("default_model_profile")
        if chosen is None:
            raise _not_pinned("default")
        pin = pinned_routes.get(chosen)
        if pin is None:
            raise _not_pinned(chosen)
        layer: Layer = pin["layer"]
        current = self.profiles.layer(
            chosen, tenant_id=run_context.tenant_id if layer == "tenant" else None
        )
        if current is None or profile_hash(current) != pin["content_hash"]:
            raise _unavailable(chosen, "pinned_profile_changed")
        if layer == "platform" and chosen not in await self.plans.allowed(run_context.plan_id):
            raise _unavailable(chosen, "plan")
        routes = {name: ModelRoute.model_validate(value) for name, value in pin["routes"].items()}
        return _answer(chosen, layer, pin["version"], pin["content_hash"], routes, purpose)

    async def _engine(self, tenant_id: UUID, run_manifest_hash: str) -> Mapping[str, Any]:
        key = (tenant_id, run_manifest_hash)
        cached = self._engines.get(key)
        if cached is not None:
            self._engines.move_to_end(key)
            return cached
        engine = None if self.pinned is None else await self.pinned.engine(*key)
        if engine is None:
            raise ConfigError(
                "the run's manifest cannot be read", details={"reason": "manifest_not_found"}
            )
        self._engines[key] = engine
        if len(self._engines) > _ENGINE_CACHE_SIZE:
            self._engines.popitem(last=False)
        return engine


def pin_entry(profile: ModelProfile, layer: Layer) -> dict[str, Any]:
    """One profile as `engine.model_routes` holds it: by value, under the hash
    of exactly the routes pinned."""
    routes = profile.pinned_routes()
    return {
        "layer": layer,
        "version": profile.routing_policy_version,
        "content_hash": content_hash(routes),
        "routes": routes,
    }
