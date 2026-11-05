"""Deterministic ids (idempotent upsert) + plaintext/markdown parser."""

from __future__ import annotations

import uuid

import pytest

from dw_kernel.residency import PLATFORM_SCOPE
from dw_knowledge.adapters.text_parser import PlaintextParser
from dw_knowledge.identity import chunk_id_for, doc_key_for, document_id_for

pytestmark = pytest.mark.unit

T1 = uuid.uuid4()
W1 = uuid.uuid4()


def test_document_id_is_stable_for_same_logical_document() -> None:
    a = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="1"
    )
    b = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="1"
    )
    assert a == b  # idempotent re-ingest overwrites, not duplicates
    c = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="2"
    )
    assert a != c  # new version = new document id


def test_global_scope_id_is_tenant_independent() -> None:
    t2 = uuid.uuid4()
    a = document_id_for(
        tenant_id=T1,
        workspace_id=W1,
        domain="legal",
        title="Luật 22/2023",
        source_version="1",
        scope="global",
    )
    b = document_id_for(
        tenant_id=t2,
        workspace_id=uuid.uuid4(),
        domain="legal",
        title="Luật 22/2023",
        source_version="1",
        scope="global",
    )
    assert a == b  # global legal doc is the same regardless of ingesting tenant


def _attachment_id(identity_key: str | None) -> uuid.UUID:
    """The same upload, told apart only by who owns it."""
    return document_id_for(
        tenant_id=T1,
        workspace_id=W1,
        domain="crm_attachment",
        title="bao-gia.pdf",
        source_version="1",
        identity_key=identity_key,
    )


def _attachment_doc_key(identity_key: str | None) -> uuid.UUID:
    return doc_key_for(
        tenant_id=T1,
        workspace_id=W1,
        domain="crm_attachment",
        title="bao-gia.pdf",
        identity_key=identity_key,
    )


def test_a_shared_title_no_longer_means_a_shared_document() -> None:
    """Two records, one filename. Without an identity key they collapse into one.

    The second ingest then overwrites the first's row, deletes its chunks and
    drops its vectors - inside one tenant, so no isolation test sees it.
    """
    assert _attachment_id(None) == _attachment_id(None)
    assert _attachment_id("account:1111:bao-gia.pdf") != _attachment_id(
        "opportunity:2222:bao-gia.pdf"
    )


def test_a_distinct_version_does_not_rescue_a_shared_identity() -> None:
    """doc_key excludes source_version on purpose, so versioning is not a fix.

    Two documents sharing an identity share a doc_key, and the newer one
    supersedes the older through the versioning path instead of the conflict
    path - the same data loss by a different route.
    """
    assert _attachment_doc_key(None) == _attachment_doc_key(None)
    assert _attachment_doc_key("account:1111:bao-gia.pdf") != _attachment_doc_key(
        "opportunity:2222:bao-gia.pdf"
    )


def test_an_absent_identity_key_keeps_the_title_derived_id() -> None:
    """Every document ingested before this parameter existed depends on it."""
    before = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="1"
    )
    after = document_id_for(
        tenant_id=T1,
        workspace_id=W1,
        domain="policy",
        title="Quy chế",
        source_version="1",
        identity_key=None,
    )
    assert before == after
    assert doc_key_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế"
    ) == doc_key_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", identity_key=None
    )


def test_chunk_id_is_stable_per_seq() -> None:
    doc = uuid.uuid4()
    a = chunk_id_for(document_id=doc, index_version="v1", seq=3)
    assert a == chunk_id_for(document_id=doc, index_version="v1", seq=3)
    assert a != chunk_id_for(document_id=doc, index_version="v1", seq=4)
    assert a != chunk_id_for(document_id=doc, index_version="v2", seq=3)


async def test_plaintext_parser_extracts_title_and_text() -> None:
    parser = PlaintextParser()
    assert parser.supports("text/markdown", "quy-che.md")
    assert not parser.supports("application/pdf", "luat.pdf")  # an API parser reads this
    parsed = await parser.parse(
        b"# Quy che mua sam\nNoi dung...", "text/markdown", "x.md", scope=PLATFORM_SCOPE
    )
    assert parsed.detected_title == "Quy che mua sam"
    assert "Noi dung" in parsed.text
