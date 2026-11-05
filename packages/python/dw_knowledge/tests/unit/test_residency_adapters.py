"""The residency gate at every knowledge adapter that sends content out
(compliance-pdpl R2.2, R2.3; ADR-0123 decision 4; CP2, CP3).

Each adapter is tested at its own door, with a transport that counts what
would have left: embedding, rerank, document extraction and transcription. A
`vn_only` tenant's content never reaches a `foreign` or undeclared destination,
an unreadable or strange class refuses, and no adapter takes a class from its
caller: the only thing a caller hands over is the tenant and workspace.
"""

from __future__ import annotations

import inspect
import pathlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_kernel.residency import Destination, ResidencyGate, ResidencyRefusedError, TenantRouteScope
from dw_knowledge.adapters.api_parsers import DeepgramTranscriptParser, GatewayFileParser
from dw_knowledge.adapters.cohere_rerank import CohereCompatibleRerankAdapter
from dw_knowledge.adapters.memory_index import InMemoryVectorIndexAdapter
from dw_knowledge.adapters.openai_embedding import OpenAICompatibleEmbeddingAdapter
from dw_knowledge.attachment_policy import load_attachment_policy
from dw_knowledge.contracts import SearchQuery
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ports import RerankCandidate
from dw_platform.application.access_context import AccessContext
from dw_platform.testing.residency import StaticRouteClasses

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
POLICY = load_attachment_policy(REPO_ROOT / "configs" / "policies" / "attachment_ingest@1.1.0.yaml")

VN_TENANT = uuid.uuid4()
VN_WORKSPACE = uuid.uuid4()
FULL_TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
OTHER_WORKSPACE = uuid.uuid4()
STRANGE_TENANT = uuid.uuid4()

CLASSES = StaticRouteClasses(
    tenants={
        VN_TENANT: "vn_only",
        FULL_TENANT: "cross_border_full",
        OTHER_TENANT: "cross_border_full",
        # What a CHECK would refuse; the gate refuses it too.
        STRANGE_TENANT: "everywhere",
    },
    workspaces={VN_WORKSPACE: (VN_TENANT, None), OTHER_WORKSPACE: (OTHER_TENANT, None)},
)
GATE = ResidencyGate(classes=CLASSES)

VN = Destination("x", "vn", "viettel_ai")
FOREIGN = Destination("x", "foreign", "openai")
UNDECLARED = Destination("x", None, None)


def _counting(monkeypatch: pytest.MonkeyPatch, body: object) -> list[httpx.Request]:
    """Every request any httpx client of this test would send, answered."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=body)

    real_init = httpx.AsyncClient.__init__

    def fake_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)
    return sent


def _embedding(destination: Destination) -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        base_url="https://gateway.invalid/v1",
        api_key="k",
        model="text-embedding-3-large",
        _dimension=3,
        residency=GATE,
        destination=destination,
    )


def _reranker(destination: Destination) -> CohereCompatibleRerankAdapter:
    return CohereCompatibleRerankAdapter(
        base_url="https://rerank.invalid/v1",
        api_key="k",
        model="bge-reranker-v2-m3",
        residency=GATE,
        destination=destination,
    )


def _extractor(destination: Destination) -> GatewayFileParser:
    return GatewayFileParser(
        base_url="https://gateway.invalid",
        api_key="k",
        model="m",
        policy=POLICY,
        residency=GATE,
        destination=destination,
    )


def _transcriber(destination: Destination) -> DeepgramTranscriptParser:
    return DeepgramTranscriptParser(
        api_key="k", policy=POLICY, residency=GATE, destination=destination
    )


_EMBEDDED = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}
_RERANKED = {"results": [{"index": 0, "relevance_score": 0.9}]}
_EXTRACTED = {"output_text": "# Biên bản", "status": "completed"}
_TRANSCRIBED = {"results": {"channels": [{"alternatives": [{"transcript": "xin chào"}]}]}}

Call = Callable[[Destination, TenantRouteScope], Awaitable[object]]


async def _embed(destination: Destination, scope: TenantRouteScope) -> object:
    return await _embedding(destination).embed(["hợp đồng"], scope=scope)


async def _rerank(destination: Destination, scope: TenantRouteScope) -> object:
    candidate = RerankCandidate(id="c", text="hợp đồng")
    return await _reranker(destination).rerank("q", [candidate], 1, scope=scope)


async def _extract(destination: Destination, scope: TenantRouteScope) -> object:
    return await _extractor(destination).parse(b"%PDF", "application/pdf", "a.pdf", scope=scope)


async def _transcribe(destination: Destination, scope: TenantRouteScope) -> object:
    return await _transcriber(destination).parse(b"RIFF", "audio/wav", "a.wav", scope=scope)


ADAPTERS: list[tuple[str, Call, object]] = [
    ("embedding", _embed, _EMBEDDED),
    ("rerank", _rerank, _RERANKED),
    ("document extraction", _extract, _EXTRACTED),
    ("transcription", _transcribe, _TRANSCRIBED),
]
IDS = [name for name, _, _ in ADAPTERS]


@pytest.mark.parametrize(("name", "call", "body"), ADAPTERS, ids=IDS)
@pytest.mark.parametrize("destination", [FOREIGN, UNDECLARED], ids=["foreign", "undeclared"])
async def test_a_vn_only_tenant_s_content_never_leaves_for_abroad(
    monkeypatch: pytest.MonkeyPatch, name: str, call: Call, body: object, destination: Destination
) -> None:
    """CP2, CP3: refused at the adapter, 0 requests."""
    sent = _counting(monkeypatch, body)
    with pytest.raises(ResidencyRefusedError) as refused:
        await call(destination, TenantRouteScope(tenant_id=VN_TENANT, workspace_id=VN_WORKSPACE))
    assert refused.value.details["reason_code"] == "residency_refused"
    assert sent == []


@pytest.mark.parametrize(("name", "call", "body"), ADAPTERS, ids=IDS)
async def test_a_vn_destination_is_sent_to(
    monkeypatch: pytest.MonkeyPatch, name: str, call: Call, body: object
) -> None:
    """The refusals above are the gate's, not an adapter that sends nothing."""
    sent = _counting(monkeypatch, body)
    await call(VN, TenantRouteScope(tenant_id=VN_TENANT, workspace_id=VN_WORKSPACE))
    assert len(sent) == 1


@pytest.mark.parametrize(("name", "call", "body"), ADAPTERS, ids=IDS)
async def test_a_full_cross_border_tenant_may_send_abroad(
    monkeypatch: pytest.MonkeyPatch, name: str, call: Call, body: object
) -> None:
    sent = _counting(monkeypatch, body)
    await call(FOREIGN, TenantRouteScope(tenant_id=FULL_TENANT, workspace_id=None))
    assert len(sent) == 1


@pytest.mark.parametrize(("name", "call", "body"), ADAPTERS, ids=IDS)
@pytest.mark.parametrize(
    "scope",
    [
        # Another tenant's workspace: a row RLS does not return.
        TenantRouteScope(tenant_id=FULL_TENANT, workspace_id=OTHER_WORKSPACE),
        # A tenant whose row holds a value outside the three.
        TenantRouteScope(tenant_id=STRANGE_TENANT, workspace_id=None),
        # A tenant the reader cannot see at all.
        TenantRouteScope(tenant_id=uuid.uuid4(), workspace_id=None),
    ],
    ids=["unreadable workspace", "strange value", "unreadable tenant"],
)
async def test_a_class_that_cannot_be_known_refuses(
    monkeypatch: pytest.MonkeyPatch, name: str, call: Call, body: object, scope: TenantRouteScope
) -> None:
    """CP2 (failure-modes #7): closed when the class is unknown, 0 requests."""
    sent = _counting(monkeypatch, body)
    with pytest.raises(ResidencyRefusedError):
        await call(FOREIGN, scope)
    assert sent == []


@pytest.mark.parametrize(
    "method",
    [
        OpenAICompatibleEmbeddingAdapter.embed,
        CohereCompatibleRerankAdapter.rerank,
        GatewayFileParser.parse,
        DeepgramTranscriptParser.parse,
    ],
)
def test_no_adapter_takes_a_class_from_its_caller(method: Callable[..., Any]) -> None:
    """CP2: a job cannot hand an adapter `cross_border_full` for a `vn_only`
    tenant, because nothing it passes is a class: the scope is a tenant and a
    workspace, and the gate reads their class itself."""
    parameters = inspect.signature(method).parameters
    assert not any("class" in name or "route" in name for name in parameters)
    assert "TenantRouteScope" in str(parameters["scope"].annotation)


# ---- the knowledge gateway hands the verified context's scope -------------------


@dataclass
class _Embeddings:
    scopes: list[TenantRouteScope] = field(default_factory=list)

    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, texts: Any, *, scope: TenantRouteScope) -> list[list[float]]:
        self.scopes.append(scope)
        return [[1.0, 0.0, 0.0] for _ in texts]


async def test_a_search_embeds_under_the_verified_context_s_tenant_and_workspace() -> None:
    """The query names no tenant; the gate is asked about the access context's."""
    embeddings = _Embeddings()
    gateway = KnowledgeGateway(
        session_factory=cast("async_sessionmaker[AsyncSession]", None),
        vector_index=InMemoryVectorIndexAdapter(),
        embeddings=embeddings,
        object_storage=cast(Any, None),
        clock=FixedClock(datetime(2026, 11, 5, tzinfo=UTC)),
        id_generator=SequentialIdGenerator(),
    )
    context = AccessContext(
        tenant_id=VN_TENANT,
        workspace_id=VN_WORKSPACE,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"knowledge.read"}),
        plan_id="professional",
    )

    await gateway.search(SearchQuery(text="hợp đồng", domain="general"), context)

    assert embeddings.scopes == [TenantRouteScope(tenant_id=VN_TENANT, workspace_id=VN_WORKSPACE)]
