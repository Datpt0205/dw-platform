"""The embedding and rerank doors (usage-and-limits/04: R6.1, R6.2; UL4).

Each door is called directly: no lease in force, a lease of another company,
or a lease the meter says is spent, and the provider adapter is never reached;
let through, the call is settled keyed by its permit, or its hold given back
when the provider failed. The search at the knowledge gateway, the one model
path a context may take through `RuntimeSeam.knowledge`, meets the same
refusal before its vector store.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from dw_kernel.errors import InfrastructureError
from dw_kernel.limits import NO_LEASE, LeaseInForce, LimitExceededError, spending_under
from dw_kernel.residency import TenantRouteScope
from dw_knowledge.adapters.embedding_factory import HASH_PRICE_KEY, build_metered_embeddings
from dw_knowledge.adapters.hash_embedding import HashEmbeddingAdapter
from dw_knowledge.metering import MeteredEmbeddings, MeteredRerank, estimated_tokens
from dw_knowledge.ports import RerankCandidate, RerankResult
from dw_knowledge.testing.meter import OpenMeter
from dw_platform.testing.residency import StaticRouteClasses

pytestmark = pytest.mark.unit

TENANT, WORKSPACE, ACTOR = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
SCOPE = TenantRouteScope(tenant_id=TENANT, workspace_id=WORKSPACE)
OPERATION = uuid.uuid4()
HOLDER = LeaseInForce(
    tenant_id=TENANT,
    workspace_id=WORKSPACE,
    lease_root=OPERATION,
    run_id=None,
    purpose="ingestion",
    actor_id=ACTOR,
    actor_kind="user",
)
SPENT = LimitExceededError("spent", metric="tokens", scope_type="tenant", window="month")


@dataclass
class _Embedder:
    """A provider adapter that counts what reached it."""

    fails: bool = False
    sent: list[list[str]] = field(default_factory=list)

    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, texts: Sequence[str], *, scope: TenantRouteScope) -> list[list[float]]:
        self.sent.append(list(texts))
        if self.fails:
            raise InfrastructureError("embedding request failed")
        return [[1.0, 0.0, 0.0] for _ in texts]


@dataclass
class _Reranker:
    sent: list[str] = field(default_factory=list)

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int,
        *,
        scope: TenantRouteScope,
    ) -> list[RerankResult]:
        self.sent.append(query)
        return [RerankResult(id=c.id, score=1.0) for c in candidates[:top_k]]


def _embeddings(inner: _Embedder, meter: OpenMeter) -> MeteredEmbeddings:
    return MeteredEmbeddings(
        inner=inner,
        meter=meter,
        provider="openai_compatible",
        model="text-embedding-3-large",
        data_location="foreign",
        processor="fpt_ai_gateway",
    )


def _rerank(inner: _Reranker, meter: OpenMeter) -> MeteredRerank:
    return MeteredRerank(
        inner=inner, meter=meter, provider="cohere_compatible", model="bge-reranker-v2-m3"
    )


_CANDIDATES = [RerankCandidate(id="a", text="một"), RerankCandidate(id="b", text="hai")]


# ---- refused before the provider ---------------------------------------------


async def test_an_embedding_with_no_lease_in_force_is_refused_unsent() -> None:
    inner, meter = _Embedder(), OpenMeter()
    with pytest.raises(LimitExceededError) as refused:
        await _embeddings(inner, meter).embed(["xin chào"], scope=SCOPE)
    assert refused.value.details["reason"] == NO_LEASE
    assert inner.sent == []
    assert meter.asked == []


async def test_an_embedding_under_another_companys_lease_is_refused_unsent() -> None:
    inner, meter = _Embedder(), OpenMeter()
    other = TenantRouteScope(tenant_id=uuid.uuid4(), workspace_id=WORKSPACE)
    with spending_under(HOLDER), pytest.raises(LimitExceededError):
        await _embeddings(inner, meter).embed(["xin chào"], scope=other)
    assert inner.sent == []
    assert meter.asked == []


async def test_an_embedding_on_a_spent_lease_is_refused_unsent() -> None:
    """R6.2 (UL4), the embedding door called directly."""
    inner, meter = _Embedder(), OpenMeter(refuse=SPENT)
    with spending_under(HOLDER), pytest.raises(LimitExceededError):
        await _embeddings(inner, meter).embed(["xin chào"], scope=SCOPE)
    assert inner.sent == []
    assert len(meter.asked) == 1
    assert meter.settled == []


async def test_a_rerank_on_a_spent_lease_is_refused_unsent() -> None:
    """R6.2 (UL4), the rerank door called directly."""
    inner, meter = _Reranker(), OpenMeter(refuse=SPENT)
    with spending_under(HOLDER), pytest.raises(LimitExceededError):
        await _rerank(inner, meter).rerank("hỏi", _CANDIDATES, 2, scope=SCOPE)
    assert inner.sent == []


async def test_a_rerank_with_no_lease_in_force_is_refused_unsent() -> None:
    inner, meter = _Reranker(), OpenMeter()
    with pytest.raises(LimitExceededError):
        await _rerank(inner, meter).rerank("hỏi", _CANDIDATES, 2, scope=SCOPE)
    assert inner.sent == []


# ---- let through: settled, or given back ------------------------------------


async def test_an_embedding_is_asked_for_what_it_sends_and_settled_by_its_permit() -> None:
    inner, meter = _Embedder(), OpenMeter()
    texts = ["xin chào", "tạm biệt bạn"]

    with spending_under(HOLDER):
        vectors = await _embeddings(inner, meter).embed(texts, scope=SCOPE)

    assert len(vectors) == 2
    ((holder, call),) = meter.asked
    assert holder == HOLDER
    tokens = estimated_tokens(texts)
    assert (call.operation, call.input_tokens, dict(call.units)) == (
        "embeddings",
        tokens,
        {"embedding_input": tokens},
    )
    assert (call.provider, call.model, call.data_location) == (
        "openai_compatible",
        "text-embedding-3-large",
        "foreign",
    )
    ((_, permit, settled),) = meter.settled
    assert settled == call
    assert meter.abandoned == []
    assert permit is not None


async def test_a_rerank_is_one_search_unit() -> None:
    inner, meter = _Reranker(), OpenMeter()
    with spending_under(HOLDER):
        ranked = await _rerank(inner, meter).rerank("hỏi", _CANDIDATES, 1, scope=SCOPE)
    assert [r.id for r in ranked] == ["a"]
    ((_, call),) = meter.asked
    assert (call.operation, dict(call.units)) == ("rerank", {"rerank_search_unit": 1})
    assert len(meter.settled) == 1


async def test_a_call_the_provider_failed_gives_its_hold_back() -> None:
    inner, meter = _Embedder(fails=True), OpenMeter()
    with spending_under(HOLDER), pytest.raises(InfrastructureError):
        await _embeddings(inner, meter).embed(["xin chào"], scope=SCOPE)
    assert len(meter.abandoned) == 1
    assert meter.settled == []


async def test_nothing_to_send_asks_nothing() -> None:
    inner, meter = _Embedder(), OpenMeter()
    assert await _embeddings(inner, meter).embed([], scope=SCOPE) == []
    assert await _rerank(_Reranker(), meter).rerank("hỏi", [], 2, scope=SCOPE) == []
    assert meter.asked == []


def test_the_hash_embedder_is_built_metered_under_its_free_price_key() -> None:
    from dw_kernel.residency import ResidencyGate

    built = build_metered_embeddings(
        "hash",
        None,
        base_url=None,
        api_key=None,
        profile_id="x",
        residency=ResidencyGate(classes=StaticRouteClasses({})),
        meter=OpenMeter(),
    )
    assert isinstance(built.inner, HashEmbeddingAdapter)
    assert (built.provider, built.model) == HASH_PRICE_KEY


# ---- the search a context reaches through the gateway --------------------------


async def test_a_search_on_a_spent_lease_is_refused_before_the_vector_store() -> None:
    """R6.2: the retrieval a context runs through `RuntimeSeam.knowledge`
    embeds its question through the metered door, which refuses first."""
    from dw_knowledge.contracts import SearchQuery
    from dw_knowledge.gateway import KnowledgeGateway
    from dw_platform.application.access_context import AccessContext

    class _Index:
        searched = 0

        async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
            type(self).searched += 1
            return []

    inner, meter = _Embedder(), OpenMeter(refuse=SPENT)
    gateway = KnowledgeGateway(
        session_factory=None,  # type: ignore[arg-type]
        vector_index=_Index(),  # type: ignore[arg-type]
        embeddings=_embeddings(inner, meter),
        object_storage=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        id_generator=None,  # type: ignore[arg-type]
    )
    context = AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=ACTOR,
        roles=frozenset({"member"}),
        scopes=frozenset(),
        plan_id="professional",
    )

    with spending_under(HOLDER), pytest.raises(LimitExceededError):
        await gateway.search(SearchQuery(text="chính sách đổi trả", domain="policy"), context)

    assert inner.sent == []
    assert _Index.searched == 0
