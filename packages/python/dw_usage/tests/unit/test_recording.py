"""A model call through the gateway becomes exactly one usage record, priced by
the book, estimated when the provider says nothing, unpriced when the book has
no entry (usage-and-limits R3.1, R3.3, R2.5; UL5)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.adapters.usage_recorders import CompositeUsageRecorder
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import BudgetExceededError
from dw_agent_runtime.model.gateway import ModelUsage, RoutingModelGateway
from dw_agent_runtime.model.profiles import ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry, RenderedPrompt
from dw_agent_runtime.ports import ModelRequest
from dw_agent_runtime.testing.models import resolver as model_resolver
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.ports import FixedClock, Uuid7Generator
from dw_observability.metrics import DW_USAGE_UNPRICED_TOTAL
from dw_observability.telemetry import RecordingTelemetry
from dw_usage.application.recorder import LedgerUsageRecorder
from dw_usage.domain.events import UsageEvent
from dw_usage.domain.pricing import PriceBook, price_book_from_document

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 9, tzinfo=UTC)


class Summary(BaseModel):
    summary: str


@dataclass
class FakeLedger:
    """Honours `SqlUsageLedger.settle`: one record per `(id, occurred_at)`."""

    events: list[UsageEvent] = field(default_factory=list)

    async def settle(self, event: UsageEvent) -> bool:
        if any((e.id, e.occurred_at) == (event.id, event.occurred_at) for e in self.events):
            return False
        self.events.append(event)
        return True


@dataclass
class SilentAdapter:
    """A provider whose response carried no usage block at all."""

    provider_name: str = "mock"

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        usage = ModelUsage(
            provider="mock", model=route.model, input_tokens=0, output_tokens=0, reported=False
        )
        return {"summary": "ba quyết định"}, usage, None


def _book(models: dict[str, str]) -> PriceBook:
    return price_book_from_document(
        {
            "schema_version": "1.0",
            "price_book_id": "test",
            "version": "7.0.0",
            "currency": "USD",
            "models": [
                {
                    "provider": "mock",
                    "model": model,
                    "effective_from": since,
                    "source": "test",
                    "prices": {"input_uncached": "1.00", "output": "2.00"},
                }
                for model, since in models.items()
            ],
        }
    )


def _context(*, service: bool = False) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        run_as_principal_id=uuid.uuid4() if service else None,
        worker_id="demo",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
    )


def _gateway(
    book: PriceBook, ledger: FakeLedger, telemetry: RecordingTelemetry, adapter: object = None
) -> RoutingModelGateway:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(
        PromptArtifact(
            schema_version="1.0",
            prompt_id="demo.summarize",
            version="1.0.0",
            system="Tóm tắt.",
            template="Tóm tắt nội dung: {content}",
            variables=frozenset({"content"}),
        )
    )
    mock = MockModelAdapter()
    mock.register_builder("demo.summarize", "1.0.0", lambda prompt: {"summary": "ba quyết định"})
    clock = FixedClock(NOW)
    recorder = LedgerUsageRecorder(
        ledger=ledger,
        ids=Uuid7Generator(clock),
        clock=clock,
        telemetry=telemetry,
        price_book_version=book.version,
    )
    return RoutingModelGateway(
        models=model_resolver(profiles, "balanced"),
        prompts=prompts,
        adapters={"mock": adapter or mock},  # type: ignore[dict-item]
        usage_recorder=CompositeUsageRecorder([recorder]),
        pricing=book,
        clock=clock,
        run_control=OpenRunControl(),
    )


_REQUEST = ModelRequest(
    task="structured_extraction",
    prompt_id="demo.summarize",
    prompt_version="1.0.0",
    variables={"content": "họp giao ban sáng thứ hai"},
)


async def test_one_chat_call_writes_one_attributed_record() -> None:
    """R3.1: tenant, workspace, run, root run, purpose, payer and the book's
    version; the route columns NULL until compliance-pdpl/03 writes them."""
    ledger, telemetry = FakeLedger(), RecordingTelemetry()
    gateway = _gateway(_book({"extraction-mock-1": "2026-01-01T00:00:00+00:00"}), ledger, telemetry)
    context = _context()

    await gateway.generate_structured(_REQUEST, Summary, run_context=context)

    [event] = ledger.events
    assert (event.tenant_id, event.workspace_id) == (context.tenant_id, context.workspace_id)
    assert event.run_id == event.root_run_id == context.run_id
    assert (event.purpose, event.payer, event.operation) == ("run", "platform", "chat")
    assert (event.actor_kind, event.user_id) == ("user", context.actor_id)
    assert event.price_book_version == "7.0.0"
    assert event.cost_source == "computed"
    expected = (event.input_tokens * Decimal(1) + event.output_tokens * Decimal(2)) / 10**6
    assert event.cost_usd == pytest.approx(expected)
    assert event.units == {"input_uncached": event.input_tokens, "output": event.output_tokens}
    assert (event.data_route_class, event.data_location, event.processor) == (None, None, None)
    assert event.occurred_at == NOW


async def test_a_service_principal_s_call_names_no_person() -> None:
    ledger = FakeLedger()
    gateway = _gateway(
        _book({"extraction-mock-1": "2026-01-01T00:00:00+00:00"}), ledger, RecordingTelemetry()
    )
    await gateway.generate_structured(_REQUEST, Summary, run_context=_context(service=True))
    assert (ledger.events[0].actor_kind, ledger.events[0].user_id) == ("service", None)


async def test_no_usage_reported_is_an_estimate_never_zero() -> None:
    """R3.3 (UL5): tokens estimated from what was sent and returned, priced,
    and recorded `estimated`."""
    ledger = FakeLedger()
    gateway = _gateway(
        _book({"extraction-mock-1": "2026-01-01T00:00:00+00:00"}),
        ledger,
        RecordingTelemetry(),
        adapter=SilentAdapter(),
    )
    await gateway.generate_structured(_REQUEST, Summary, run_context=_context())

    [event] = ledger.events
    assert event.cost_source == "estimated"
    assert event.input_tokens > 0 and event.output_tokens > 0
    assert event.cost_usd is not None and event.cost_usd > 0


async def test_an_unpriced_call_keeps_its_answer_and_stops_the_run_next() -> None:
    """R2.5: the book's earliest entry is after the call; the answer is returned,
    the record is `unpriced` with no cost, the metric counts it, and the run's
    next call is refused."""
    ledger, telemetry = FakeLedger(), RecordingTelemetry()
    gateway = _gateway(_book({"extraction-mock-1": "2027-01-01T00:00:00+00:00"}), ledger, telemetry)
    context = _context()

    answer = await gateway.generate_structured(_REQUEST, Summary, run_context=context)

    assert answer.summary == "ba quyết định"
    [event] = ledger.events
    assert (event.cost_source, event.cost_usd, event.price_entry_ids) == ("unpriced", None, ())
    assert event.price_book_version == "7.0.0"
    assert [name for name, *_ in telemetry.metrics] == [DW_USAGE_UNPRICED_TOTAL]
    with pytest.raises(BudgetExceededError, match="could not be priced"):
        await gateway.generate_structured(_REQUEST, Summary, run_context=context)
    assert len(ledger.events) == 1, "the refused call made no call and wrote no record"


async def test_the_same_record_settled_twice_is_one_record() -> None:
    """R3.2 against the port's fake; the SQL half is in the integration suite."""
    ledger = FakeLedger()
    event = UsageEvent(
        id=uuid.uuid4(),
        occurred_at=NOW,
        tenant_id=uuid.uuid4(),
        operation="chat",
        purpose="run",
        payer="platform",
        actor_kind="user",
        provider="mock",
        model="m",
        input_tokens=1,
        output_tokens=1,
        cost_source="computed",
        price_book_version="1",
        cost_usd=Decimal(0),
    )
    assert await ledger.settle(event) is True
    assert await ledger.settle(event) is False
