"""Batching against the embedding API's three ceilings.

Exceeding any one of them is a 400 for the whole request, which during a reindex
means losing a batch rather than a chunk. The splitting is therefore worth
pinning without a live call.
"""

from __future__ import annotations

import pytest

from dw_kernel.errors import InfrastructureError
from dw_kernel.residency import Destination, ResidencyGate
from dw_knowledge.adapters.openai_embedding import (
    MAX_TOKENS_PER_INPUT,
    MAX_TOKENS_PER_REQUEST,
    OpenAICompatibleEmbeddingAdapter,
    _estimated_tokens,
)
from dw_platform.testing.residency import StaticRouteClasses

pytestmark = pytest.mark.unit


def _adapter(batch_size: int = 256) -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        base_url="https://gateway.invalid/v1",
        api_key="not-used-here",
        model="text-embedding-3-large",
        _dimension=3072,
        residency=ResidencyGate(classes=StaticRouteClasses({})),
        destination=Destination("embedding", "vn", "fpt_ai_gateway"),
        batch_size=batch_size,
    )


def test_batches_split_on_the_input_count() -> None:
    batches = list(_adapter(batch_size=4)._batches(["chunk"] * 10))
    assert [len(batch) for batch in batches] == [4, 4, 2]


def test_batches_split_on_the_request_token_budget() -> None:
    """A count-only split sends a legal number of chunks and an illegal total.

    Only reachable with many near-limit inputs: anything big enough to blow the
    request budget on its own would hit the per-input limit first.
    """
    near_limit = "x" * int(MAX_TOKENS_PER_INPUT * 2.5 * 0.95)
    texts = [near_limit] * 60

    batches = list(_adapter(batch_size=256)._batches(texts))

    assert len(batches) > 1, "the count ceiling alone would have sent one request"
    for batch in batches:
        assert sum(_estimated_tokens(text) for text in batch) <= MAX_TOKENS_PER_REQUEST


def test_everything_is_emitted_exactly_once() -> None:
    texts = [f"chunk-{index}" for index in range(37)]
    emitted = [text for batch in _adapter(batch_size=5)._batches(texts) for text in batch]
    assert emitted == texts


def test_an_oversized_chunk_is_refused_rather_than_truncated() -> None:
    """Silently trimming would index a document that misses its own middle."""
    oversized = "x" * int(MAX_TOKENS_PER_INPUT * 2.5 * 2)
    with pytest.raises(InfrastructureError) as raised:
        list(_adapter()._batches([oversized]))
    assert raised.value.details["limit_tokens"] == MAX_TOKENS_PER_INPUT


def test_no_texts_means_no_request() -> None:
    assert list(_adapter()._batches([])) == []
