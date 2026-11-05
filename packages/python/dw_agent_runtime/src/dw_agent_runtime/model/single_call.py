"""A model gateway for a caller whose run is exactly one model call.

A handler that calls `ModelGateway.generate_structured` directly — one
structured extraction, no runner — mints a fresh run id per request and never
passes the runner, which is where a run's lease is taken (usage-and-limits
R4.1). This wraps the process's gateway for exactly those callers: the call's
lease is taken before it (`LimitsPort.admit`, not counted as a run, since it is
none) and given back once the call is over, whatever the outcome, so a refused
call spent nothing and a finished one leaves no open lease behind
(failure-modes #5, #6). The composition root decides who gets it; a caller
never builds its own. Built by `ModelStack.one_call`, which both composition
roots use.
"""

from __future__ import annotations

from dataclasses import dataclass

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import LimitsPort, ModelGateway, ModelRequest, OutputT


@dataclass(frozen=True)
class SingleCallModelGateway:
    """Implements `ModelGateway` for a caller whose run is this one call."""

    inner: ModelGateway
    limits: LimitsPort

    async def generate_structured(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> OutputT:
        # Before the call, and outside the `finally`: a refused call reserved
        # nothing and left no lease to give back.
        lease = await self.limits.admit(run_context, counts_run=False)
        reason = "failed"
        try:
            answer = await self.inner.generate_structured(
                request, output_type, run_context=run_context
            )
            reason = "completed"
            return answer
        finally:
            # The run is over when this call is: nothing else would ever give
            # this lease back before the reaper.
            await lease.release(reason)
