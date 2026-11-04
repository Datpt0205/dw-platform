"""The per-run spend ceiling, on the path that actually loops.

`RunBudgetLedger` has bounded a run since the profiles grew `budgets` — but only
on `RoutingModelGateway.generate_structured`, the one-shot structured path. The
agent loop talks to its model through `ChatModelFactory`, a bare chat model the
gateway never sees, so the path that CAN loop had no ceiling at all. Its only
bound was `recursion_limit`, which counts steps and not money, and a run that
reached it had already spent whatever those steps cost.

This middleware puts the same ledger in front of every agent model call: refuse
before the call if the run is already over its ceiling, add what the call spent
after it. "Before" is the point — a ceiling checked afterwards is a report on
what was lost, not a limit.

The ledger passed in MUST be the one the gateway and the runner hold. A run that
mixes structured calls and agent steps spends against one ceiling, and the runner
frees the run's entry when it ends; a second ledger would split the spend in two
so neither half ever reaches the limit, and would never be freed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from langgraph.runtime import get_runtime

from dw_agent_runtime.adapters.chat_model import chat_route
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger, route_cost
from dw_agent_runtime.model.pricing import PricingPort
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_kernel.errors import PriceNotFoundError
from dw_kernel.ports import SystemClock, UtcClock

__all__ = ["AGENT_LOOP_TASK", "RunBudgetMiddleware"]

# The task name the ceiling reports under, matching what the usage meter already
# books agent-loop tokens as, so a refusal and a ledger row name the same thing.
AGENT_LOOP_TASK = "agent_loop"


class RunBudgetMiddleware(AgentMiddleware[Any, Any]):
    """Refuses an agent model call once the run has spent its ceiling."""

    def __init__(
        self,
        ledger: RunBudgetLedger,
        profiles: ModelProfileRegistry,
        profile_id: str,
        pricing: PricingPort,
        clock: UtcClock | None = None,
    ) -> None:
        super().__init__()
        self._ledger = ledger
        self._profiles = profiles
        self._profile_id = profile_id
        self._pricing = pricing
        self._clock: UtcClock = clock if clock is not None else SystemClock()

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        # Resolved per call and per tenant: a tenant's own profile may carry its
        # own ceiling and its own price, and the agent is compiled once for all
        # of them.
        profile = self._profiles.resolve(self._profile_id, tenant_id=run_context.tenant_id)
        # Resolved BEFORE the call, like the ceiling. A profile with no chat route
        # is a refusal, and a refusal discovered after the model already answered
        # has already spent the money it exists to protect.
        route = chat_route(self._profiles, self._profile_id, tenant_id=run_context.tenant_id)
        self._ledger.check(run_context.run_id, profile.budgets, task=AGENT_LOOP_TASK)

        response = await handler(request)

        input_tokens, output_tokens = _usage(response)
        try:
            cost = float(
                route_cost(
                    self._pricing,
                    route,
                    tenant_id=run_context.tenant_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    at=self._clock.now(),
                ).cost_usd
            )
        except PriceNotFoundError:
            # The answer is already paid for and is returned; the run stops at
            # its next call instead (R2.5). The usage meter records the row.
            self._ledger.mark_unpriced(run_context.run_id)
            cost = 0.0
        self._ledger.record(
            run_context.run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        return response


def _usage(response: ModelResponse[Any]) -> tuple[int, int]:
    """Tokens the call reported, summed over every assistant message it returned.

    Zero when the provider reported nothing. That under-counts rather than
    guesses, and the input-token ceiling is still enforced on the calls that do
    report — which, behind the gateway, is all of them.
    """
    input_tokens = output_tokens = 0
    for message in response.result:
        if isinstance(message, AIMessage) and message.usage_metadata:
            input_tokens += int(message.usage_metadata.get("input_tokens", 0))
            output_tokens += int(message.usage_metadata.get("output_tokens", 0))
    return input_tokens, output_tokens
