"""Claims and the dispatch log: what keeps one tool key from sending twice.

ADR-0108 decision 5. A call with an idempotency key claims the key before it
looks for a succeeded call, so two calls with one key never both run while the
claim is live. A call that leaves the platform commits a `dispatched` row in a
transaction of its own before it leaves, so a later call can tell one that never
left (run it) from one whose outcome is unknown (never run it blindly).

The three errors are what a handler raises once its send has begun, read by the
executor to write the terminal row (ADR-0115 decision 6). They are defined in
`dw_kernel.dispatch` and re-exported here as the very same classes: the egress
client in `dw_connectors` raises them too, and this package depends on that one
(connections-and-vault R3.13).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dw_agent_runtime.contracts import RunContext
from dw_kernel.dispatch import (
    DispatchOutcome,
    NotDispatchedError,
    OutcomeUnknownError,
    RejectedError,
)

__all__ = [
    "DispatchOutcome",
    "DispatchRecord",
    "NotDispatchedError",
    "OutcomeUnknownError",
    "RejectedError",
    "ToolClaimPort",
]


@dataclass(frozen=True)
class DispatchRecord:
    """The fields of a `dispatched` row the executor supplies."""

    execution_id: uuid.UUID
    tool_version: str
    input_hash: str
    started_at: datetime


class ToolClaimPort(Protocol):
    """Declared by the runtime, satisfied by an adapter wired at the composition root."""

    async def claim(
        self,
        run_context: RunContext,
        tool_name: str,
        idempotency_key: str,
        *,
        lease_seconds: float,
    ) -> uuid.UUID | None:
        """The new claim's token, or None while another claim on the key is live.

        An expired claim is taken over: deleted by its own token and only while
        still expired, then inserted again, so two takers cannot both win.
        """
        ...

    async def release(
        self, run_context: RunContext, tool_name: str, idempotency_key: str, token: uuid.UUID
    ) -> None:
        """Delete the claim only if it still carries `token`."""
        ...

    async def has_unresolved_dispatch(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> bool:
        """A `dispatched` row of the key that no `succeeded` or `failed` row closes."""
        ...

    async def dispatch(
        self,
        run_context: RunContext,
        tool_name: str,
        idempotency_key: str,
        token: uuid.UUID,
        record: DispatchRecord,
    ) -> bool:
        """Commit a `dispatched` row only while `token` holds a live claim on the key.

        False means the claim was taken over or expired: the caller must not send.
        """
        ...
