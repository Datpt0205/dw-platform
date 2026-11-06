"""A `UsageMeterPort` for tests: every call let through and every question
kept, so a test sees that a door asked, for what, and how it ended.

It honours the port's shape, not its arithmetic: the lease and the ledger are
`dw_usage.adapters.metering`'s, tested on PostgreSQL. A test that needs a spent
lease sets `refuse`, raised by `before_call` before anything is sent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dw_kernel.limits import LeaseInForce, LimitExceededError, MeteredCall, MeterPermit

__all__ = ["OpenMeter"]


@dataclass
class OpenMeter:
    """Implements `dw_knowledge.ports.UsageMeterPort`."""

    refuse: LimitExceededError | None = None
    asked: list[tuple[LeaseInForce, MeteredCall]] = field(default_factory=list)
    settled: list[tuple[LeaseInForce, MeterPermit, MeteredCall]] = field(default_factory=list)
    abandoned: list[MeterPermit] = field(default_factory=list)

    async def before_call(self, holder: LeaseInForce, call: MeteredCall) -> MeterPermit:
        self.asked.append((holder, call))
        if self.refuse is not None:
            raise self.refuse
        return MeterPermit(
            lease_id=uuid.uuid4(), call_id=uuid.uuid4(), occurred_at=datetime.now(UTC)
        )

    async def settle(self, holder: LeaseInForce, permit: MeterPermit, call: MeteredCall) -> None:
        self.settled.append((holder, permit, call))

    async def abandon(self, holder: LeaseInForce, permit: MeterPermit) -> None:
        self.abandoned.append(permit)
