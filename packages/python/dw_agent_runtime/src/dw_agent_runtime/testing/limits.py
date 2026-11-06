"""A `LimitsPort` for tests and for the scripts that run the gateway with no
database (`eval_*`, `check_model_gateway`): every admission and every call let
through, and every question kept, so a test can see that a door asked.

It honours the port's shape, not its arithmetic: the leases, counters and the
reaper are `dw_usage.adapters.limits_sql`'s, tested on PostgreSQL. A test that
needs a refusal sets `refuse` (raised by `admit`, `resume`, `admit_operation`
and `before_call`), `refuse_calls` (by `before_call` only), or
`refuse_after_calls`, the calls one run may make before its next one is
refused, as a spent lease would. `admit` and `resume` hand back the run's
limits clamped by `ceiling`, as the real port clamps by the plan (R6.4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Literal

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.limits import clamp_run_limits
from dw_agent_runtime.ports import CallEstimate, CallPermit, OperationPurpose, RunLease, RunLimits
from dw_kernel.limits import LimitExceededError

__all__ = ["TEST_CEILING", "OpenLimits", "OpenRunLease"]

# What a permit allows when the caller asked for no bound and nothing limits it.
UNBOUNDED_OUTPUT_TOKENS: Final = 1_000_000
# A test's ceiling, not a plan's: the plans' numbers live in
# `platform.plan_limits` alone (failure-modes #2).
TEST_CEILING: Final = RunLimits(
    max_steps=40,
    max_model_calls=30,
    max_tool_calls=60,
    max_cost_usd=Decimal("1.5"),
    max_tokens=100_000,
)


@dataclass
class OpenRunLease:
    limits: OpenLimits
    root: uuid.UUID
    run_limits: RunLimits | None = None
    purpose: str = "run"

    @property
    def root_run_id(self) -> uuid.UUID:
        return self.root

    async def before_call(self, run_context: RunContext, estimate: CallEstimate) -> CallPermit:
        self.limits.calls.append((run_context.run_id, estimate))
        refused = self.limits.refuse_calls or self.limits.refuse
        if refused is not None:
            raise refused
        ceiling = self.limits.refuse_after_calls
        if ceiling is not None and (
            sum(1 for run_id, _ in self.limits.calls if run_id == run_context.run_id) > ceiling
        ):
            raise LimitExceededError(
                "the run has spent its lease", metric="cost_usd", scope_type="run"
            )
        permit = CallPermit(
            lease_id=self.limits.lease_ids.setdefault(self.root, uuid.uuid4()),
            call_id=uuid.uuid4(),
            occurred_at=datetime.now(UTC),
            max_output_tokens=min(
                UNBOUNDED_OUTPUT_TOKENS
                if estimate.max_output_tokens is None
                else estimate.max_output_tokens,
                self.limits.max_output_tokens,
            ),
            purpose=self.purpose,
        )
        self.limits.permits.append(permit)
        return permit

    async def abandon(self, permit: CallPermit) -> None:
        self.limits.abandoned.append(permit)

    async def beat(self) -> bool:
        self.limits.beats.append(self.root)
        return self.root not in self.limits.released_roots

    async def release(self, reason: str) -> bool:
        first = self.root not in self.limits.released_roots
        self.limits.released.append((self.root, reason))
        if reason != "paused":
            self.limits.released_roots.add(self.root)
        return first


@dataclass
class OpenLimits:
    """Implements `LimitsPort`: admits everything unless told to refuse."""

    refuse: LimitExceededError | None = None
    refuse_calls: LimitExceededError | None = None
    refuse_after_calls: int | None = None
    # The plan's ceilings `admit` and `resume` clamp a run's declared limits by.
    ceiling: RunLimits = TEST_CEILING
    # The most output any permit allows (a test of the clamp lowers it).
    max_output_tokens: int = UNBOUNDED_OUTPUT_TOKENS
    admitted: list[tuple[uuid.UUID, bool]] = field(default_factory=list)
    resumed: list[uuid.UUID] = field(default_factory=list)
    gates: list[tuple[uuid.UUID, Decimal, str]] = field(default_factory=list)
    operations: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    calls: list[tuple[uuid.UUID, CallEstimate]] = field(default_factory=list)
    permits: list[CallPermit] = field(default_factory=list)
    abandoned: list[CallPermit] = field(default_factory=list)
    beats: list[uuid.UUID] = field(default_factory=list)
    released: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    released_roots: set[uuid.UUID] = field(default_factory=set)
    lease_ids: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    async def admit(self, run_context: RunContext, *, counts_run: bool = True) -> RunLease:
        if self.refuse is not None:
            raise self.refuse
        self.admitted.append((run_context.lease_root, counts_run))
        self.released_roots.discard(run_context.lease_root)
        return OpenRunLease(self, run_context.lease_root, self._limits_of(run_context))

    async def resume(self, run_context: RunContext) -> RunLease:
        if self.refuse is not None:
            raise self.refuse
        self.resumed.append(run_context.lease_root)
        self.released_roots.discard(run_context.lease_root)
        return OpenRunLease(self, run_context.lease_root, self._limits_of(run_context))

    def _limits_of(self, run_context: RunContext) -> RunLimits:
        return clamp_run_limits(run_context.declared_limits, self.ceiling)

    async def admit_operation(
        self,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        purpose: OperationPurpose,
        operation_id: uuid.UUID,
    ) -> RunLease:
        if self.refuse is not None:
            raise self.refuse
        self.operations.append((operation_id, purpose))
        self.released_roots.discard(operation_id)
        return OpenRunLease(self, operation_id, purpose=purpose)

    async def admit_gate(
        self,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        gate_run_id: uuid.UUID,
        ceiling_usd: Decimal,
        payer: Literal["tenant", "platform"],
    ) -> RunLease:
        if self.refuse is not None:
            raise self.refuse
        self.gates.append((gate_run_id, ceiling_usd, payer))
        return OpenRunLease(self, gate_run_id)

    def lease(self, run_context: RunContext) -> RunLease:
        purpose = next(
            (kind for root, kind in self.operations if root == run_context.lease_root), "run"
        )
        return OpenRunLease(self, run_context.lease_root, purpose=purpose)
