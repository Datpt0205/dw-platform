"""Transactional outbox record.

Written in the same transaction as the aggregate change; the worker process
publishes/executes and marks processed with idempotency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from dw_kernel.ids import TenantId, WorkspaceId


@dataclass(slots=True)
class OutboxEvent:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    event_type: str
    schema_version: str
    aggregate_id: uuid.UUID
    occurred_at: datetime
    payload: dict[str, object] = field(default_factory=dict)
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    processed_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        if "." not in self.event_type:
            raise ValueError("event_type must be namespaced like '<context>.<aggregate>.<verb>'")

    @property
    def is_processed(self) -> bool:
        return self.processed_at is not None

    def mark_processed(self, at: datetime) -> None:
        if self.processed_at is not None:
            return  # idempotent
        self.processed_at = at

    def record_attempt(self) -> None:
        self.attempts += 1

    def record_failure(self, error: str) -> None:
        """Keep why the last delivery failed, so a stuck event can be diagnosed.

        The attempt count alone cannot separate an account that was deleted from
        a database that was unreachable, and those two want opposite responses.
        """
        self.last_error = error


@dataclass(frozen=True, slots=True)
class OutboxBacklog:
    """A snapshot of what a dispatcher still owes, for the types it handles.

    Ops hardening Phase 5: the two numbers a "backlog above threshold" alert
    needs. ``oldest_pending_at`` is ``None`` exactly when ``pending`` is 0 —
    there is no oldest row in an empty backlog.
    """

    pending: int
    oldest_pending_at: datetime | None
    # Given up on (runtime-hardening R10.3): never in `pending`.
    dead: int = 0
