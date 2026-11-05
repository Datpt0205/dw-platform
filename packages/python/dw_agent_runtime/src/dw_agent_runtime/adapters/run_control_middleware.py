"""The freeze at the agent loop's model call (agent-lifecycle R7.1; ADR-0120
decision 6): before every model call of an agent and of a sub-agent, the run
asks `RunControlPort`, and a refusal ends the turn with `RunHaltedError`,
which the runner records as `cancelled` with its reason.

A sub-agent stack that runs a linked agent names that agent's component
(`artifacts`), so a kill of it refuses the delegated turn while the run's own
component is open (R8.5).

Not caught by any middleware of the stack: `PlatformToolErrorsMiddleware`
re-raises it, so a refusal is never turned into a sentence for the model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.runtime import get_runtime

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import RunControlPort
from dw_agent_runtime.run_control import RunControlDoor

__all__ = ["RunControlMiddleware"]


class RunControlMiddleware(AgentMiddleware[Any, Any]):
    """Refuses an agent model call while the run's company or the platform is
    frozen, its switch state is unreadable, or a component it runs is killed."""

    def __init__(self, control: RunControlPort, artifacts: Sequence[UUID] = ()) -> None:
        super().__init__()
        self._control = control
        # The components this stack's turns reach beyond the run's own: a
        # linked agent's, in its sub-agent stack (agent-lifecycle R8.5).
        self._artifacts = tuple(artifacts)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        run_context = get_runtime(RunContext).context
        await self._control.require_open(
            run_context, door=RunControlDoor.MODEL, artifacts=self._artifacts
        )
        return await handler(request)
