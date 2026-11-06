"""A memory's embedding on the outbox lane spends an operation lease of its
company (usage-and-limits/04, R6.2): no run is in force there, and the metered
embedder refuses without a lease.

Refused, the memory is kept unranked and the delivery is not failed: indexing
never raises, as the ranker's own `index` does not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from dw_agent_runtime.testing.limits import OpenLimits
from dw_kernel.limits import LeaseInForce, LimitExceededError, lease_in_force
from dw_kernel.ports import Uuid4Generator
from dw_worker.consumers.memory import LeasedMemoryIndex

pytestmark = pytest.mark.unit

TENANT, WORKSPACE, MEMORY = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@dataclass
class _Index:
    held: list[LeaseInForce | None] = field(default_factory=list)

    async def index(
        self,
        *,
        memory_id: uuid.UUID,
        content: str,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        worker_id: str,
    ) -> None:
        self.held.append(lease_in_force())


async def _index(limits: OpenLimits, inner: _Index) -> None:
    await LeasedMemoryIndex(inner, limits, Uuid4Generator()).index(
        memory_id=MEMORY,
        content="khách thích gọi buổi sáng",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        worker_id="sales_chat",
    )


async def test_the_embedding_runs_under_an_ingestion_lease_of_the_memorys_company() -> None:
    limits, inner = OpenLimits(), _Index()

    await _index(limits, inner)

    (held,) = inner.held
    assert held is not None
    assert (held.tenant_id, held.workspace_id, held.purpose) == (TENANT, WORKSPACE, "ingestion")
    assert (held.run_id, held.actor_id, held.actor_kind) == (None, None, "system")
    ((operation, purpose),) = limits.operations
    assert purpose == "ingestion"
    assert limits.released == [(operation, "completed")]


async def test_a_spent_period_keeps_the_memory_unranked_without_raising() -> None:
    limits = OpenLimits(refuse=LimitExceededError("spent", metric="tokens", scope_type="tenant"))
    inner = _Index()

    await _index(limits, inner)

    assert inner.held == []
