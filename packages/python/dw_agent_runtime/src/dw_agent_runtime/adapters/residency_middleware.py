"""The residency gate at the agent loop's model call (compliance-pdpl R2.2,
R2.3; ADR-0123 decision 4).

`ResidencyGate` wrapped as a middleware: before every model call of an agent
and of a sub-agent, the route the call goes to is resolved for the run
(`ModelResolver`, the one answer every door reads) and checked against the
class the run pinned at admission. A refusal ends the turn with
`ResidencyRefusedError` before the chat model is called, and the runner records
the run `failed` with `residency_refused`.

It sits after `RunControlMiddleware` and before the run's limits
(`RunBudgetMiddleware`, which usage-and-limits/03's `LimitsMiddleware`
replaces), so a refused call holds no lease and spends nothing (usage-and-limits
R6.5; agent-builder/03 step 2 owns the Studio stack's order and puts it right
after `StudioModelSelection`).

The loop's chat model is bound to the resolved route and `ModelRetryMiddleware`
retries only that route (provider fallback is deliberately not in the loop), so
the route is the one destination a call can reach; `admitted` is still asked
for every route the answer lists, the gateway's rule, and the call is refused
unless the bound route is among those admitted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.runtime import get_runtime

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.resolver import ModelResolver
from dw_kernel.residency import ResidencyGate, ResidencyRefusedError

__all__ = ["ResidencyGateMiddleware"]


class ResidencyGateMiddleware(AgentMiddleware[Any, Any]):
    """Refuses an agent model call to a route the run's class does not admit."""

    def __init__(self, gate: ResidencyGate, models: ModelResolver, profile_id: str | None) -> None:
        super().__init__()
        self._gate = gate
        self._models = models
        self._profile_id = profile_id

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        resolved = await self._models.resolve(run_context, self._profile_id, "chat")
        admitted = await self._gate.admitted(run_context, resolved.attempts)
        if resolved.route not in admitted:
            # Only a fallback is admitted, and the loop does not fall back.
            raise ResidencyRefusedError(
                "Lộ trình dữ liệu của công ty không cho phép gửi tới nơi xử lý này",
                details={
                    "route_class": run_context.route_class,
                    "data_location": resolved.route.data_location,
                    "processor": resolved.route.processor,
                },
            )
        return await handler(request)
