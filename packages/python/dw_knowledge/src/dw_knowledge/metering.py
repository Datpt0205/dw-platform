"""The embedding and rerank doors a process hands out: each call metered and
held to the lease in force (usage-and-limits R6.1, R6.2; ADR-0121 decision 7).

`MeteredEmbeddings` and `MeteredRerank` wrap the provider adapter the
composition root built and are the only form in which a process holds one:
`dw_knowledge.adapters.embedding_factory` returns a `MeteredEmbeddings`, and
import-linter keeps the concrete adapters out of every module but the
builders and the composition roots.

Before each call, the lease in force (`dw_kernel.limits.lease_in_force`) is
asked for a permit for what the call sends: no lease in force, a lease of
another company, or a lease with too little left, and the call is refused with
`LimitExceededError` before a byte leaves. After it, its usage is recorded
keyed by the permit, which settles it into the lease; a call that never
answered gives its hold back. Recording that fails is logged, never what
fails the call: the answer is already paid for.

The tokens of a call are estimated, four characters a token, as the lease is
asked for them; the provider's own count is not read back in W1, so the
record says `estimated`.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from dw_kernel.limits import (
    NO_LEASE,
    LeaseInForce,
    LimitExceededError,
    MeteredCall,
    MeterPermit,
    lease_in_force,
)
from dw_kernel.residency import TenantRouteScope
from dw_knowledge.ports import (
    EmbeddingPort,
    RerankCandidate,
    RerankPort,
    RerankResult,
    UsageMeterPort,
)

__all__ = ["MeteredEmbeddings", "MeteredRerank", "estimated_tokens"]

_LOG = logging.getLogger("dw_knowledge.metering")

# LangChain's approximate counter, the one every lease estimate uses.
_CHARS_PER_TOKEN: Final = 4


def estimated_tokens(texts: Sequence[str]) -> int:
    """What a call sends, at four characters a token, at least one."""
    return max(1, math.ceil(sum(len(text) for text in texts) / _CHARS_PER_TOKEN))


def _holder_for(scope: TenantRouteScope) -> LeaseInForce:
    """The lease in force, when it is this company's; refused otherwise."""
    holder = lease_in_force()
    if holder is None or holder.tenant_id != scope.tenant_id:
        raise LimitExceededError(
            "Lời gọi model không có phần giữ trước nào của công ty cho phép",
            metric="cost_usd",
            scope_type="run",
            reason=NO_LEASE,
        )
    return holder


async def _settle(
    meter: UsageMeterPort, holder: LeaseInForce, permit: MeterPermit, call: MeteredCall
) -> None:
    try:
        await meter.settle(holder, permit, call)
    except Exception:
        # Broad on purpose: the call answered and is paid for, and accounting
        # is never what fails it (as the gateway's `_record`).
        _LOG.warning("usage of a %s call was not recorded", call.operation, exc_info=True)


@dataclass(frozen=True)
class MeteredEmbeddings:
    """Implements `EmbeddingPort`: `inner`'s vectors, each call held to the
    lease in force."""

    inner: EmbeddingPort
    meter: UsageMeterPort
    provider: str
    model: str
    data_location: str | None = None
    processor: str | None = None

    @property
    def dimension(self) -> int:
        return self.inner.dimension

    async def embed(self, texts: Sequence[str], *, scope: TenantRouteScope) -> list[list[float]]:
        if not texts:
            return []
        holder = _holder_for(scope)
        tokens = estimated_tokens(texts)
        call = MeteredCall(
            operation="embeddings",
            provider=self.provider,
            model=self.model,
            input_tokens=tokens,
            units={"embedding_input": tokens},
            data_location=self.data_location,
            processor=self.processor,
        )
        permit = await self.meter.before_call(holder, call)
        try:
            vectors = await self.inner.embed(texts, scope=scope)
        except BaseException:
            await self.meter.abandon(holder, permit)
            raise
        await _settle(self.meter, holder, permit, call)
        return vectors


@dataclass(frozen=True)
class MeteredRerank:
    """Implements `RerankPort`: `inner`'s order, each call held to the lease in
    force and priced by the search unit."""

    inner: RerankPort
    meter: UsageMeterPort
    provider: str
    model: str
    data_location: str | None = None
    processor: str | None = None

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int,
        *,
        scope: TenantRouteScope,
    ) -> list[RerankResult]:
        if not candidates or top_k <= 0:
            # Nothing is sent for nothing to rank.
            return []
        holder = _holder_for(scope)
        call = MeteredCall(
            operation="rerank",
            provider=self.provider,
            model=self.model,
            input_tokens=0,
            units={"rerank_search_unit": 1},
            data_location=self.data_location,
            processor=self.processor,
        )
        permit = await self.meter.before_call(holder, call)
        try:
            ranked = await self.inner.rerank(query, candidates, top_k, scope=scope)
        except BaseException:
            await self.meter.abandon(holder, permit)
            raise
        await _settle(self.meter, holder, permit, call)
        return ranked
