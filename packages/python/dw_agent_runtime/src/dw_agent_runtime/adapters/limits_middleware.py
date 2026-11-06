"""The hard limits at the agent loop's model call (usage-and-limits R5.2, R5.5,
R5.10, R6.5; ADR-0121 decision 5), in place of `RunBudgetMiddleware`.

Before every model call of an agent and of a sub-agent, the run's lease is
asked for a permit for what the call sends: refused, the turn ends with
`LimitExceededError` before the chat model is called; let through, the call's
`max_tokens` is the permit's, so the answer cannot spend past what the lease
holds. After the call, its usage is recorded keyed by the permit, which is the
call's settlement into the lease and the ledger in one transaction (R5.11), and
the tokens are claimed from the invocation's usage meter so they are not
recorded a second time (`claim_usage`). The permit is in force for the call it
was asked for and no other (`permitted`), which is what lets a chat model from
`LimitedChatModelFactory` through (usage-and-limits R6.1, R6.2).

It sits after `ResidencyGateMiddleware`, so a call the residency gate refuses
asks for no permit and is recorded nowhere (R6.5); agent-builder/03 keeps that
order in the Studio stack.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Final

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.runtime import get_runtime

from dw_agent_runtime.adapters.langchain_usage import claim_usage
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import ModelUsage, UsageRecorderPort
from dw_agent_runtime.model.limits import approximate_tokens, estimate_call, permitted
from dw_agent_runtime.model.pricing import PricingPort, route_cost
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.ports import CallPermit, LimitsPort
from dw_agent_runtime.ports import ModelRequest as GatewayRequest
from dw_kernel.errors import PriceNotFoundError
from dw_kernel.ports import SystemClock, UtcClock

__all__ = ["AGENT_LOOP_TASK", "LimitsMiddleware"]

# The task the loop's calls are recorded under, as the usage meter names them.
AGENT_LOOP_TASK: Final = "agent_loop"


class LimitsMiddleware(AgentMiddleware[Any, Any]):
    """Asks the run's lease before every agent model call and settles after."""

    def __init__(
        self,
        limits: LimitsPort,
        models: ModelResolver,
        profile_id: str | None,
        pricing: PricingPort,
        recorder: UsageRecorderPort,
        clock: UtcClock | None = None,
    ) -> None:
        super().__init__()
        self._limits = limits
        self._models = models
        self._profile_id = profile_id
        self._pricing = pricing
        self._recorder = recorder
        self._clock: UtcClock = clock if clock is not None else SystemClock()

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        # Per call, for the run's tenant and plan (model-connections R1.1).
        route = (await self._models.resolve(run_context, self._profile_id, "chat")).route
        lease = self._limits.lease(run_context)
        asked = request.model_settings.get("max_tokens")
        permit = await lease.before_call(
            run_context,
            estimate_call(
                self._pricing,
                route,
                tenant_id=run_context.tenant_id,
                input_tokens=approximate_tokens(_sent(request)),
                max_output_tokens=asked if isinstance(asked, int) else None,
                at=self._clock.now(),
            ),
        )
        bounded = request.override(
            model_settings={**request.model_settings, "max_tokens": permit.max_output_tokens}
        )
        try:
            # The permit in force for exactly this call: a chat model from
            # `LimitedChatModelFactory` refuses one made without it (R6.2).
            with permitted(permit):
                response = await handler(bounded)
        except BaseException:
            await lease.abandon(permit)
            raise
        await self._settle(run_context, route, permit, response)
        return response

    async def _settle(
        self,
        run_context: RunContext,
        route: ModelRoute,
        permit: CallPermit,
        response: ModelResponse[Any],
    ) -> None:
        input_tokens = output_tokens = 0
        for message in response.result:
            if isinstance(message, AIMessage) and message.usage_metadata:
                spent_in = int(message.usage_metadata.get("input_tokens", 0))
                spent_out = int(message.usage_metadata.get("output_tokens", 0))
                input_tokens += spent_in
                output_tokens += spent_out
                name = message.response_metadata.get("model_name")
                if isinstance(name, str) and name:
                    claim_usage(name, spent_in, spent_out)
        usage = ModelUsage(
            provider=str(route.provider),
            model=route.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            data_route_class=run_context.route_class,
            data_location=route.data_location,
            processor=route.processor,
            permit=permit,
        )
        try:
            quote = route_cost(
                self._pricing,
                route,
                tenant_id=run_context.tenant_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                at=self._clock.now(),
            )
        except PriceNotFoundError as exc:
            # The answer is paid for and is returned; the record says
            # `unpriced`, which stops the run at its next call (R2.5).
            usage = replace(
                usage, cost_source="unpriced", price_book_version=exc.price_book_version
            )
        else:
            usage = replace(
                usage,
                cost_usd=float(quote.cost_usd),
                cost_source="computed",
                price_book_version=quote.price_book_version,
                price_entry_ids=quote.entry_ids,
            )
        await self._recorder.record(
            run_context,
            GatewayRequest(
                task=AGENT_LOOP_TASK,
                prompt_id=AGENT_LOOP_TASK,
                prompt_version="1.0.0",
                model_profile=self._profile_id,
            ),
            usage,
        )


def _sent(request: ModelRequest[Any]) -> list[str]:
    """The text a call sends: the system message and every message's content."""
    texts: list[str] = []
    messages: list[BaseMessage] = list(request.messages)
    if request.system_message is not None:
        messages.insert(0, request.system_message)
    for message in messages:
        content = message.content
        texts.append(content if isinstance(content, str) else str(content))
    return texts
