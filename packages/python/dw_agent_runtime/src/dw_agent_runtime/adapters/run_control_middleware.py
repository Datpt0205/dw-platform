"""The freeze at the agent loop's model call (agent-lifecycle R7.1; ADR-0120
decision 6): before every model call of an agent and of a sub-agent, the run
asks `RunControlPort`, and a refusal ends the turn with `RunHaltedError`,
which the runner records as `cancelled` with its reason.

Not caught by any middleware of the stack: `PlatformToolErrorsMiddleware`
re-raises it, so a refusal is never turned into a sentence for the model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.runtime import get_runtime

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import RunControlPort
from dw_agent_runtime.run_control import RunControlDoor

__all__ = ["RunControlMiddleware"]


class RunControlMiddleware(AgentMiddleware[Any, Any]):
    """Refuses an agent model call while the run's company or the platform is
    frozen, its switch state is unreadable, or a component it runs is killed."""

    def __init__(self, control: RunControlPort) -> None:
        super().__init__()
        self._control = control

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        await self._control.require_open(run_context, door=RunControlDoor.MODEL)
        return await handler(request)
