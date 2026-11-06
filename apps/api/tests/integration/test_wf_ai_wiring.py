"""Integration: the workflow assistant calls the model through the runtime's
own stack (wf-ai R1.6), as the composition root builds it on a real database.

A client of its own would skip `ResidencyGate`, the spend ledger and the
plan's daily allowance; this asserts the assistant's gateway is the one-call
wrapper around the very gateway the runner uses.
"""

from __future__ import annotations

import pytest
from pg_test_db import DatabaseUrls

from dw_agent_runtime.model.single_call import SingleCallModelGateway
from dw_api.bootstrap.wiring import build_container
from dw_api.settings import ApiSettings

pytestmark = pytest.mark.integration


async def test_the_assistant_calls_through_the_runtime_model_stack(api_db: DatabaseUrls) -> None:
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret="integration-secret-0123456789abcdef",
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    try:
        assistant, runtime = container.workflow_assistant, container.runtime
        assert assistant is not None and runtime is not None
        assert isinstance(assistant.gateway, SingleCallModelGateway)
        assert assistant.gateway.inner is runtime.gateway
    finally:
        await container.shutdown()


async def test_every_door_the_seam_hands_out_is_built_metered(api_db: DatabaseUrls) -> None:
    """usage-and-limits R6.1 (UL4), on what the composition root built: the
    chat factory is the limited one, and knowledge and memory embed and rerank
    through metered doors only."""
    from dw_agent_runtime.adapters.chat_model import LimitedChatModelFactory
    from dw_knowledge.metering import MeteredEmbeddings, MeteredRerank

    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret="integration-secret-0123456789abcdef",
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    try:
        runtime = container.runtime
        assert runtime is not None
        assert runtime.chat_models is None or isinstance(
            runtime.chat_models, LimitedChatModelFactory
        )
        assert isinstance(runtime.knowledge.embeddings, MeteredEmbeddings)
        reranker = runtime.knowledge.reranker
        assert reranker is None or isinstance(reranker, MeteredRerank)
        ranker = runtime.memory.ranker
        embedder = getattr(ranker, "embedder", None)
        assert embedder is None or isinstance(embedder, MeteredEmbeddings)
    finally:
        await container.shutdown()
