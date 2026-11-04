"""Routing model gateway: the single entry point for LLM calls.

Output is ALWAYS validated into the caller's Pydantic schema; provider adapters
are selected per profile (Strategy). Usage/cost is recorded per call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Protocol

from pydantic import ValidationError

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger, route_cost
from dw_agent_runtime.model.pricing import CostSource, PricingPort
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptRegistry, RenderedPrompt
from dw_agent_runtime.ports import ModelOutputInvalidError, ModelRequest, OutputT, RunControlPort
from dw_agent_runtime.run_control import RunControlDoor
from dw_kernel.errors import InfrastructureError, NotFoundError, PriceNotFoundError
from dw_kernel.ports import SystemClock, UtcClock

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
    # False when the provider's response carried no token counts at all. The
    # gateway then estimates them rather than recording a free call (R3.3).
    reported: bool = True
    # How `cost_usd` was arrived at, and from which price book and entries;
    # set once, by whoever priced the call (the gateway or the LangChain
    # meter), and read by the usage ledger. `None` until priced.
    cost_source: CostSource | None = None
    price_book_version: str | None = None
    price_entry_ids: tuple[str, ...] = ()


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
    # The price book (usage-and-limits R2.1), injected by the composition root;
    # the clock says when a call happened, which is what the book prices by.
    pricing: PricingPort
    # The freeze and the kill (agent-lifecycle R7.1): the first door of every
    # call, before the prompt is rendered; then the residency gate and the
    # limits. Injected, never defaulted, as every door's is.
    run_control: RunControlPort
    # Per-run ceiling from the profile's own `budgets`. Enforced here because
    # this is the only place every model call passes through.
    budget: RunBudgetLedger = field(default_factory=RunBudgetLedger)
    clock: UtcClock = field(default_factory=SystemClock)

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
        await self.run_control.require_open(run_context, door=RunControlDoor.MODEL)
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

        asked = (
            request.output_schema
            if request.output_schema is not None
            else output_type.model_json_schema()
        )
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
                    asked,
                    route,
                    max_output_tokens=request.max_output_tokens,
                )
            except InfrastructureError as exc:
                last_error = exc
                continue
            usage = replace(usage, latency_ms=(perf_counter() - started) * 1000)
            if not usage.reported:
                usage = _estimated(usage, prompt, raw)
            priced = self._priced(route, usage, run_context)
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

    def _priced(self, route: ModelRoute, usage: ModelUsage, run_context: RunContext) -> ModelUsage:
        """The call's usage with a cost on it, priced once for every reader.

        The provider's own figure when it reports one; the price book's
        otherwise, which is the normal case behind a gateway that returns token
        counts and no money. Pricing here rather than inside the budget check is
        what puts the same number in the ceiling and in the ledger.

        A call the book cannot price keeps its answer, is recorded `unpriced`
        and marks the run at its cost ceiling, so the next call is refused
        (R2.5): an unknown cost is never zero.
        """
        try:
            quote = route_cost(
                self.pricing,
                route,
                tenant_id=run_context.tenant_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                at=self.clock.now(),
            )
        except PriceNotFoundError as exc:
            _LOG.error(
                "model call could not be priced for run %s (%s %s)",
                run_context.run_id,
                route.provider,
                route.model,
            )
            self.budget.mark_unpriced(run_context.run_id)
            return replace(
                usage,
                cost_usd=0.0,
                cost_source="unpriced",
                price_book_version=exc.price_book_version,
                price_entry_ids=(),
            )
        source: CostSource
        if usage.cost_usd:
            source, cost = "provider_reported", usage.cost_usd
        else:
            source = "computed" if usage.reported else "estimated"
            cost = float(quote.cost_usd)
        return replace(
            usage,
            cost_usd=cost,
            cost_source=source,
            price_book_version=quote.price_book_version,
            price_entry_ids=quote.entry_ids,
        )

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


def _estimated(usage: ModelUsage, prompt: RenderedPrompt, raw: dict[str, object]) -> ModelUsage:
    """Token counts for a call whose provider reported none (R3.3, M9).

    Four characters a token, from what was actually sent and returned: an
    estimate, recorded as one (`cost_source = 'estimated'`), never a free call.
    At least one token each way, because a call that happened consumed some.
    """
    sent = len(prompt.system) + len(prompt.user)
    returned = len(json.dumps(raw, ensure_ascii=False))
    return replace(
        usage,
        input_tokens=max(1, sent // 4),
        output_tokens=max(1, returned // 4),
        reported=False,
    )
