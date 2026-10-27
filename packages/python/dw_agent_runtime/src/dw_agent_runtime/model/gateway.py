"""Routing model gateway: the single entry point for LLM calls.

Output is ALWAYS validated into the caller's Pydantic schema; provider adapters
are selected per profile (Strategy). Usage/cost is recorded per call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Protocol

from pydantic import ValidationError

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger, route_cost
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptRegistry, RenderedPrompt
from dw_agent_runtime.ports import ModelOutputInvalidError, ModelRequest, OutputT
from dw_kernel.errors import InfrastructureError, NotFoundError

_LOG = logging.getLogger("dw_agent_runtime.model")


@dataclass(frozen=True)
class ModelUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0
    # Wall time of the provider call, filled in by the gateway (an adapter
    # reports tokens, not how long the wire took). Defaults to 0.0 so a caller
    # that builds usage by hand — every mock adapter and every test — keeps
    # working unchanged.
    latency_ms: float = 0.0
    # The model the provider says answered, which can differ from the one asked
    # for (an alias resolved, a fallback). None when the response did not say.
    response_model: str | None = None


class ModelProviderAdapter(Protocol):
    """One provider integration (mock, OpenAI-compatible, vLLM, ...)."""

    @property
    def provider_name(self) -> str: ...

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        """Returns (parsed_json, usage, visible_reasoning_or_None)."""
        ...


class UsageRecorderPort(Protocol):
    """Where a call's tokens and cost go once it has happened.

    Async because a recorder that persists has to be. The alternative - a
    synchronous method spawning a background task - loses the last calls of
    every run at shutdown, which is precisely the run someone is asking about
    when they look at the bill.
    """

    async def record(
        self, run_context: RunContext, request: ModelRequest, usage: ModelUsage
    ) -> None: ...


@dataclass
class InMemoryUsageRecorder:
    """Keeps usage in the process. Test and local default; never a ledger."""

    records: list[tuple[str, ModelUsage]] = field(default_factory=list)

    async def record(
        self, run_context: RunContext, request: ModelRequest, usage: ModelUsage
    ) -> None:
        self.records.append((str(run_context.run_id), usage))


@dataclass
class RoutingModelGateway:
    """Implements the ``ModelGateway`` port with per-profile routing."""

    profiles: ModelProfileRegistry
    prompts: PromptRegistry
    adapters: dict[str, ModelProviderAdapter]
    usage_recorder: UsageRecorderPort
    # What a request naming no profile runs on: the deployment's own
    # (DW_API_MODEL_PROFILE). No default here, so a host cannot forget it —
    # while requests defaulted to "balanced", a deployment configured for a
    # real model still sent every call that named no profile to the mock.
    default_profile: str
    # Per-run ceiling from the profile's own `budgets`. Enforced here because
    # this is the only place every model call passes through.
    budget: RunBudgetLedger = field(default_factory=RunBudgetLedger)

    def _route(self, request: ModelRequest, profile: ModelProfile) -> ModelRoute:
        if request.route_kind == "deep_reasoning":
            # Visible-thinking route is optional; degrade to reasoning route.
            return profile.deep_reasoning or profile.reasoning
        if request.route_kind == "reasoning" or (
            request.route_kind == "auto" and request.task == "reasoning"
        ):
            return profile.reasoning
        return profile.structured_extraction

    def _attempts(self, request: ModelRequest, profile: ModelProfile) -> list[ModelRoute]:
        """Attempt order: primary, primary again (transient-failure retry),
        then the profile's fallback route when it is a different model."""
        primary = self._route(request, profile)
        attempts = [primary, primary]
        fallback = profile.fallback
        if fallback is not None and (fallback.provider, fallback.model) != (
            primary.provider,
            primary.model,
        ):
            attempts.append(fallback)
        return attempts

    async def generate_structured(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> OutputT:
        output, _reasoning = await self.generate_structured_traced(
            request, output_type, run_context=run_context
        )
        return output

    async def generate_structured_traced(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> tuple[OutputT, str]:
        # The tenant comes from the run, never from the request: a caller that
        # could name the tenant whose prompt to render could read another
        # customer's wording.
        prompt = self.prompts.render(
            request.prompt_id,
            request.prompt_version,
            dict(request.variables),
            tenant_id=run_context.tenant_id,
        )
        # Transient provider errors and schema-invalid outputs get one retry
        # on the primary route, then the profile fallback (if any). Non-model
        # errors (unknown provider, missing mock fixture) fail fast.
        # One tenant-aware resolution for the route, the fallback and the
        # budget alike. The route used to be resolved without the tenant, so a
        # tenant with its own profile was charged against its own ceiling on
        # the platform's model. The effective id goes onto the request so the
        # usage recorders name the profile actually used.
        profile_id = request.model_profile or self.default_profile
        request = request.model_copy(update={"model_profile": profile_id})
        profile = self.profiles.resolve(profile_id, tenant_id=run_context.tenant_id)
        # Checked before the call, not after: the point is to not make it.
        self.budget.check(run_context.run_id, profile.budgets, task=request.task)

        last_error: Exception | None = None
        for index, route in enumerate(self._attempts(request, profile)):
            adapter = self.adapters.get(route.provider)
            if adapter is None:
                if index == 0:
                    raise NotFoundError(
                        "model provider not configured",
                        details={"provider": route.provider, "profile": profile_id},
                    )
                continue  # fallback route pointing at an unwired provider
            started = perf_counter()
            try:
                raw, usage, reasoning = await adapter.complete_json(
                    prompt,
                    output_type.model_json_schema(),
                    route,
                    max_output_tokens=request.max_output_tokens,
                )
            except InfrastructureError as exc:
                last_error = exc
                continue
            usage = replace(usage, latency_ms=(perf_counter() - started) * 1000)
            priced = self._priced(route, usage)
            self._spend(run_context, priced)
            await self._record(run_context, request, priced)
            try:
                return output_type.model_validate(raw), reasoning or ""
            except ValidationError as exc:
                last_error = ModelOutputInvalidError(
                    "model output failed schema validation",
                    details={
                        "prompt_id": request.prompt_id,
                        "output_type": output_type.__name__,
                        "errors": str(exc.error_count()),
                    },
                )
                last_error.__cause__ = exc
                continue
        assert last_error is not None  # attempts list is never empty
        raise last_error

    def _priced(self, route: ModelRoute, usage: ModelUsage) -> ModelUsage:
        """The call's usage with a cost on it, priced once for every reader.

        The provider's own figure when it reports one; the route's declared
        price otherwise, which is the normal case behind a gateway that returns
        token counts and no money. Pricing here rather than inside the budget
        check is what puts the same number in the ceiling and in the ledger -
        while they were computed separately the ledger stored NULL for every
        priced route, so the invoice could not be read back from the database.
        """
        if usage.cost_usd:
            return usage
        cost = route_cost(route, usage.input_tokens, usage.output_tokens)
        return replace(usage, cost_usd=cost) if cost else usage

    def _spend(self, run_context: RunContext, usage: ModelUsage) -> None:
        """Charge the run for a call that has already happened."""
        self.budget.record(
            run_context.run_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
        )

    async def _record(
        self, run_context: RunContext, request: ModelRequest, usage: ModelUsage
    ) -> None:
        """Accounting must never be what ends a run.

        The answer is already paid for by the time this runs; losing the
        bookkeeping is a smaller failure than throwing away the work, so an
        unreachable ledger is logged and stepped over.
        """
        try:
            await self.usage_recorder.record(run_context, request, usage)
        except Exception:
            # Broad on purpose, and logged rather than swallowed: a recorder can
            # be a database, an exporter or both, and by contract none of them
            # is allowed to decide whether a run survives.
            _LOG.warning(
                "usage not recorded for run %s (%s)",
                run_context.run_id,
                request.task,
                exc_info=True,
            )
