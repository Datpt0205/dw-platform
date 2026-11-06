"""What every model door shares: one call's usage (`ModelUsage`), the provider
adapter a route is sent through, and where usage is recorded.

The structured door itself, `RoutingModelGateway`, lives in
`dw_agent_runtime.model.routing`, which only a composition root imports
(usage-and-limits R6.1; ADR-0121 decision 7); a context is handed it as a
`MeteredModelGateway`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.pricing import CostSource
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_agent_runtime.ports import CallPermit, ModelRequest


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
    # The run's data route class and where the call was processed, set by the
    # door that sent it, after `ResidencyGate` admitted the route
    # (compliance-pdpl R2.1; ADR-0123 decision 6). None until a door sets them,
    # and the ledger then records NULL, never `vn_only`.
    data_route_class: str | None = None
    data_location: str | None = None
    processor: str | None = None
    # The lease's permit the call was sent under (usage-and-limits R5.2): the
    # usage record's key and lease, so writing the record settles the call into
    # its lease (R5.11). None for a call no lease permitted.
    permit: CallPermit | None = None


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
