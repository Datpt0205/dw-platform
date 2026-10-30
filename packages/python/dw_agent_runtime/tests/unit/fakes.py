"""In-memory doubles for the platform ports the runtime writes through."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import PlatformUnitOfWork
from dw_platform.domain.audit import AuditEvent

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


@dataclass
class FakeExecutionStore:
    succeeded: dict[tuple[str, str], Any] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)

    async def find_succeeded(
        self, run_context: Any, tool_name: str, idempotency_key: str
    ) -> Any | None:
        return self.succeeded.get((tool_name, idempotency_key))

    async def record(self, run_context: Any, **kwargs: Any) -> Any | None:
        key = (kwargs["tool_name"], kwargs.get("idempotency_key"))
        if kwargs.get("status") == "succeeded" and key[1] and key in self.succeeded:
            # The unique index's answer, as the SQL store gives it.
            return self.succeeded[key]
        self.records.append(kwargs)
        if kwargs.get("status") == "succeeded" and key[1]:
            entry = type(
                "Stored",
                (),
                {"input_hash": kwargs["input_hash"], "output": kwargs["output"]},
            )()
            self.succeeded[cast("tuple[str, str]", key)] = entry
        return None


@dataclass
class FakeToolClaims:
    """`ToolClaimPort` over the same rows as a `FakeExecutionStore`.

    The two SQL adapters share `platform.tool_executions`, so this shares the
    store's `records`: a `dispatched` row lands there, and a terminal row the
    store records closes it by `dispatch_id`. `now` is moved by a test to expire
    a claim, the way PostgreSQL's `now()` moves for the SQL adapter.
    """

    store: FakeExecutionStore
    now: datetime = NOW
    claims: dict[tuple[str, str], tuple[UUID, datetime]] = field(default_factory=dict)

    async def claim(
        self, run_context: Any, tool_name: str, idempotency_key: str, *, lease_seconds: float
    ) -> UUID | None:
        held = self.claims.get((tool_name, idempotency_key))
        if held is not None and held[1] > self.now:
            return None
        token = uuid4()
        self.claims[(tool_name, idempotency_key)] = (
            token,
            self.now + timedelta(seconds=lease_seconds),
        )
        return token

    async def release(
        self, run_context: Any, tool_name: str, idempotency_key: str, token: UUID
    ) -> None:
        held = self.claims.get((tool_name, idempotency_key))
        if held is not None and held[0] == token:
            del self.claims[(tool_name, idempotency_key)]

    async def has_unresolved_dispatch(
        self, run_context: Any, tool_name: str, idempotency_key: str
    ) -> bool:
        closed = {
            r["dispatch_id"]
            for r in self.store.records
            if r.get("dispatch_id") is not None and r["status"] in ("succeeded", "failed")
        }
        return any(
            r["status"] == "dispatched"
            and r["tool_name"] == tool_name
            and r["idempotency_key"] == idempotency_key
            and r["execution_id"] not in closed
            for r in self.store.records
        )

    async def dispatch(
        self, run_context: Any, tool_name: str, idempotency_key: str, token: UUID, record: Any
    ) -> bool:
        held = self.claims.get((tool_name, idempotency_key))
        if held is None or held[0] != token or held[1] <= self.now:
            return False
        self.store.records.append(
            {
                "execution_id": record.execution_id,
                "tool_name": tool_name,
                "tool_version": record.tool_version,
                "status": "dispatched",
                "idempotency_key": idempotency_key,
                "input_hash": record.input_hash,
                "started_at": record.started_at,
            }
        )
        return True


@dataclass
class FakeAuditRepo:
    events: list[AuditEvent] = field(default_factory=list)

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def list_page(self, request: PageRequest, *, workspace_id: UUID) -> Page[AuditEvent]:
        # Newest first and the caller's workspace only, like the SQL repository
        # this stands in for.
        return build_page(
            [event for event in reversed(self.events) if event.workspace_id.value == workspace_id],
            request=request,
            position_of=lambda event: CursorPosition(
                sort_value=event.occurred_at, tiebreaker=event.id
            ),
        )


@dataclass
class FakeUoW:
    audit: FakeAuditRepo
    approvals: Any = None
    outbox: Any = None

    async def __aenter__(self) -> FakeUoW:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass
class FakeUoWFactory:
    audit_repo: FakeAuditRepo = field(default_factory=FakeAuditRepo)

    def __call__(self, context: AccessContext) -> PlatformUnitOfWork:
        return cast(PlatformUnitOfWork, FakeUoW(audit=self.audit_repo))
