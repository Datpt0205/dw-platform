"""Embeddings from an OpenAI-compatible endpoint (the configured gateway).

Implements ``EmbeddingPort``. Raw ``httpx`` rather than the OpenAI SDK, matching
`dw_agent_runtime/adapters/openai_compatible.py`: one dialect, pointed at
whatever gateway `OPENAI_BASE_URL` names, so provider keys and fallbacks stay
that gateway's configuration and never enter this application.

Batching is bounded three ways because the API is, and the smallest ceiling wins:
inputs per request, tokens per input, and tokens per request. Exceeding any of
them is a 400 for the whole batch, which would fail an entire reindex rather than
one chunk.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import httpx

from dw_kernel.errors import InfrastructureError
from dw_kernel.residency import Destination, ResidencyGate, TenantRouteScope

# API limits, measured against the configured gateway on 2026-08-17 (see
# docs/architecture/model-gateway-findings.md).
MAX_INPUTS_PER_REQUEST = 2048
MAX_TOKENS_PER_REQUEST = 300_000
MAX_TOKENS_PER_INPUT = 8192

# Well under the 2048 the gateway accepts. A full 2048-input batch measured 58s,
# which is close enough to a default HTTP timeout that one slow round trip would
# fail the whole request; smaller batches also mean a retry re-sends less.
DEFAULT_BATCH = 256

# Chunks are ~1200 characters and Vietnamese runs denser per token than English,
# so this deliberately over-counts: the cost of a conservative estimate is one
# extra request, the cost of an optimistic one is a 400.
_CHARS_PER_TOKEN = 2.5


def _estimated_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + 1


@dataclass
class OpenAICompatibleEmbeddingAdapter:
    """Implements ``EmbeddingPort`` against ``POST {base_url}/embeddings``."""

    base_url: str
    api_key: str
    model: str
    _dimension: int
    # The process's one gate and where the embedding route processes (its
    # `data_location` and `processor`, ADR-0123 decision 5): asked before any
    # text is sent (compliance-pdpl R2.3).
    residency: ResidencyGate
    destination: Destination
    # Only sent when it differs from the model's native width: the parameter is
    # rejected by pre-v3 embedding models, and this adapter is not the place to
    # know which ones those are.
    requested_dimensions: int | None = None
    timeout: float = 120.0
    batch_size: int = DEFAULT_BATCH

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str], *, scope: TenantRouteScope) -> list[list[float]]:
        if not texts:
            return []
        # Before the client exists: a refused scope sends no byte.
        await self.residency.check(scope, self.destination)
        out: list[list[float]] = []
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            ) as client:
                for batch in self._batches(texts):
                    out.extend(await self._embed_batch(client, batch))
        except httpx.HTTPError as exc:
            raise InfrastructureError(
                "embedding request failed",
                details={"model": self.model, "error": type(exc).__name__},
            ) from exc

        if len(out) != len(texts):
            # A short response would silently misalign every vector with its
            # chunk from that point on, which no later check would catch.
            raise InfrastructureError(
                "embedding response did not cover every input",
                details={"model": self.model, "asked": len(texts), "got": len(out)},
            )
        return out

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {"model": self.model, "input": batch}
        if self.requested_dimensions is not None:
            payload["dimensions"] = self.requested_dimensions
        response = await client.post("/embeddings", json=payload)
        response.raise_for_status()
        rows = response.json().get("data") or []
        # Order is the API's contract, but it costs nothing to stop trusting it.
        rows.sort(key=lambda row: row.get("index", 0))
        return [row["embedding"] for row in rows]

    def _batches(self, texts: Sequence[str]) -> Iterator[list[str]]:
        """Split on whichever ceiling is reached first."""
        batch: list[str] = []
        tokens = 0
        for text in texts:
            estimate = _estimated_tokens(text)
            if estimate > MAX_TOKENS_PER_INPUT:
                raise InfrastructureError(
                    "a single chunk exceeds the embedding input limit",
                    details={"limit_tokens": MAX_TOKENS_PER_INPUT, "estimated": estimate},
                )
            full = len(batch) >= min(self.batch_size, MAX_INPUTS_PER_REQUEST)
            over_budget = tokens + estimate > MAX_TOKENS_PER_REQUEST
            if batch and (full or over_budget):
                yield batch
                batch, tokens = [], 0
            batch.append(text)
            tokens += estimate
        if batch:
            yield batch
