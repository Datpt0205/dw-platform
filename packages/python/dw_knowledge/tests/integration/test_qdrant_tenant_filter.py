"""Integration: real Qdrant + MinIO + Postgres — retrieval fails closed.

Both denial directions get their own test: a passing cross-tenant check says
nothing about two workspaces inside one company. The domain and clearance cases
are here for the same reason - each is a separate fence, and a fence nobody
tested is a fence nobody has.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import sqlalchemy as sa
from runtime_harness import RuntimeUrls
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import NotFoundError
from dw_knowledge.contracts import SearchQuery
from dw_knowledge.gateway import (
    DELETED_ACTION,
    GLOBAL_PUBLISH_SCOPE,
    IngestDocumentCommand,
    KnowledgeGateway,
)
from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.integration

# The `make_context` fixture lives in conftest.py; conftest is not importable as
# a module here (the test directory is not a package), so the shape is restated.
ContextFactory = Callable[..., AccessContext]

TENANT_A = uuid.UUID(int=0xAA00)
WORKSPACE_A = uuid.UUID(int=0xAA01)
TENANT_B = uuid.UUID(int=0xBB00)
WORKSPACE_B = uuid.UUID(int=0xBB01)

SECRET_TEXT = (
    "Chính sách mua hàng nội bộ của Công ty Alpha: ngân sách tối đa cho một RFQ "
    "là 500 triệu đồng, cần hai chữ ký phê duyệt."
)


async def test_ingest_then_search_same_tenant_finds_evidence(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    context_a = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title="Chính sách mua hàng", content=SECRET_TEXT),
        context_a,
    )
    assert ingested.chunk_count >= 1

    results = await gateway.search(SearchQuery(text="chính sách mua hàng ngân sách RFQ"), context_a)
    assert results, "same tenant must find its own document"
    top = results[0]
    assert "500 triệu" in top.content
    assert top.evidence.source_document_id == ingested.document_id
    assert len(top.evidence.provenance_hash) == 64


async def test_cross_tenant_search_returns_nothing(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    await gateway.ingest_document(
        IngestDocumentCommand(title="Bí mật Alpha", content=SECRET_TEXT),
        make_context(TENANT_A, WORKSPACE_A),
    )

    # Tenant B runs the EXACT text of tenant A's secret — zero results.
    results = await gateway.search(
        SearchQuery(text=SECRET_TEXT), make_context(TENANT_B, WORKSPACE_B)
    )
    assert results == [], "cross-tenant retrieval must fail closed"


async def test_cross_workspace_search_returns_nothing(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """The other denial direction. A passing cross-tenant test says nothing here.

    One tenant, two workspaces: sales and legal inside the same company must not
    read each other's uploads, and the tenant condition alone cannot express it.
    """
    other_workspace = uuid.UUID(int=0xAA02)
    await gateway.ingest_document(
        IngestDocumentCommand(title="Bí mật workspace A", content=SECRET_TEXT),
        make_context(TENANT_A, WORKSPACE_A),
    )

    results = await gateway.search(
        SearchQuery(text=SECRET_TEXT), make_context(TENANT_A, other_workspace)
    )
    assert results == [], "cross-workspace retrieval must fail closed"


async def test_a_shared_search_does_not_read_another_domain(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """ "shared" names the common pool; it is not a wildcard over every domain.

    A file attached to one CRM record is ingested on its own domain. The default
    SearchQuery asks for "shared", and that query used to carry no domain
    condition at all - so every lane in the tenant retrieved that file.
    """
    context = make_context(TENANT_A, WORKSPACE_A)
    await gateway.ingest_document(
        IngestDocumentCommand(
            title="Hợp đồng đính kèm", content=SECRET_TEXT, domain="crm_attachment"
        ),
        context,
    )

    results = await gateway.search(SearchQuery(text=SECRET_TEXT), context)
    assert results == [], "a shared search must not reach a named domain"

    scoped = await gateway.search(SearchQuery(text=SECRET_TEXT, domain="crm_attachment"), context)
    assert scoped, "the owning domain must still find it"


async def test_clearance_blocks_higher_classification(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    context = make_context(TENANT_A, WORKSPACE_A)  # clearance=internal
    await gateway.ingest_document(
        IngestDocumentCommand(
            title="Tài liệu mật",
            content="Lương thưởng ban điều hành năm 2026 chi tiết.",
            classification="restricted",
        ),
        context,
    )
    results = await gateway.search(SearchQuery(text="lương thưởng ban điều hành"), context)
    assert results == [], "internal clearance must not read restricted documents"


async def test_a_cleared_caller_reads_the_classified_document(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """The positive half: clearance must widen, or the block above proves nothing.

    This is what breaks when clearance is dropped somewhere on the way in - the
    caller is entitled to the document and simply gets an empty result set.
    """
    context = make_context(TENANT_A, WORKSPACE_A, clearance="confidential")
    await gateway.ingest_document(
        IngestDocumentCommand(
            title="Điều khoản thương mại",
            content="Chiết khấu đặc biệt cho đối tác chiến lược là 18%.",
            classification="confidential",
        ),
        context,
    )

    results = await gateway.search(SearchQuery(text="chiết khấu đối tác chiến lược"), context)
    assert results, "confidential clearance must read confidential documents"


async def test_acl_principals_narrow_a_document_to_its_uploader(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """The queue path can now narrow ACL; prove the gateway honours it.

    Everything the worker ingests used to be readable tenant-wide, so this is
    the fence that makes a per-uploader attachment possible at all.
    """
    owner = make_context(TENANT_A, WORKSPACE_A)
    colleague = make_context(TENANT_A, WORKSPACE_A)

    await gateway.ingest_document(
        IngestDocumentCommand(
            title="Ghi chú cá nhân",
            content="Ghi chú riêng về mức chiết khấu tối đa có thể nhượng bộ.",
            acl_principals=(f"user:{owner.principal_id}",),
        ),
        owner,
    )

    assert await gateway.search(SearchQuery(text="chiết khấu nhượng bộ"), owner)
    assert await gateway.search(SearchQuery(text="chiết khấu nhượng bộ"), colleague) == [], (
        "a document narrowed to one user must not be readable by a colleague"
    )


# --- asking for particular documents -----------------------------------------
# `document_ids` is a MatchAny on `source_document_id` that the gateway adds to
# the same `must` list as the trusted conditions: applied before top-k, and only
# ever narrowing.

_QUESTION = "hạn mức tín dụng nhà cung cấp thanh toán"


def _sections(count: int, body: str) -> str:
    """One markdown section per chunk: the chunker keeps a short section whole."""
    return "\n\n".join(f"## Mục {i}\n{body} {i}." for i in range(count))


async def test_a_requested_document_below_the_global_top_k_still_fills_top_k(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """Thirty chunks of another document are closer to the question than D's five.

    Filtered after the index returned its top-k, asking for D got nothing back:
    every one of the five global hits belonged to the other document.
    """
    context = make_context(TENANT_A, WORKSPACE_A)
    noise = await gateway.ingest_document(
        IngestDocumentCommand(title="Chính sách tín dụng", content=_sections(30, _QUESTION)),
        context,
    )
    wanted = await gateway.ingest_document(
        IngestDocumentCommand(
            title="Biên bản họp",
            content=_sections(5, "biên bản họp kho vận có nhắc thanh toán"),
        ),
        context,
    )
    assert noise.chunk_count == 30 and wanted.chunk_count == 5

    unfiltered = await gateway.search(SearchQuery(text=_QUESTION, top_k=5), context)
    assert {r.evidence.source_document_id for r in unfiltered} == {noise.document_id}, (
        "the premise: D ranks below the tenant's global top-k"
    )

    results = await gateway.search(
        SearchQuery(text=_QUESTION, top_k=5, document_ids=(wanted.document_id,)), context
    )
    assert len(results) == 5
    assert {r.evidence.source_document_id for r in results} == {wanted.document_id}


async def test_naming_another_tenants_document_returns_nothing(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """The document condition joins the trusted ones; it never stands in for them.

    Tenant B knows tenant A's document id and asks for exactly that document,
    with exactly its text. A document filter that replaced the tenant condition
    would hand it over.
    """
    secret = await gateway.ingest_document(
        IngestDocumentCommand(title="Bí mật Alpha", content=SECRET_TEXT),
        make_context(TENANT_A, WORKSPACE_A),
    )

    results = await gateway.search(
        SearchQuery(text=SECRET_TEXT, document_ids=(secret.document_id,)),
        make_context(TENANT_B, WORKSPACE_B),
    )
    assert results == [], "a named document id must not cross the tenant fence"


# --- deleting a document (foundations-hardening R2.1, R2.2; G1, FH2, FH3) ------


async def test_a_member_deletes_a_document_of_their_own_workspace(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """G1: the fence on deletion must not stop the one delete it is for."""
    context = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Bí mật Alpha"), content=SECRET_TEXT), context
    )
    assert await gateway.search(SearchQuery(text=SECRET_TEXT), context)

    await gateway.soft_delete_document(ingested.document_id, context)

    assert await gateway.search(SearchQuery(text=SECRET_TEXT), context) == []


def _unique(title: str) -> str:
    """A document's id derives from its title, so each test gets its own document:
    one test's delete and its audit row must not be another test's."""
    return f"{title} {uuid.uuid4().hex[:8]}"


@pytest.fixture
async def admin(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    """Reads what the caller cannot (audit rows of any tenant, a document's row):
    the migrator, which bypasses RLS and owns the schema."""
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _status(admin: AsyncEngine, document_id: uuid.UUID) -> str:
    async with admin.connect() as conn:
        status = await conn.scalar(
            sa.text("SELECT status FROM knowledge.documents WHERE id = :id"), {"id": document_id}
        )
    assert status is not None
    return str(status)


async def _deleted_audits(admin: AsyncEngine, document_id: uuid.UUID) -> int:
    async with admin.connect() as conn:
        count = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.audit_events"
                " WHERE action = :action AND resource_id = :id"
            ),
            {"action": DELETED_ACTION, "id": str(document_id)},
        )
    return int(count or 0)


async def test_another_tenant_cannot_delete_a_document(
    gateway: KnowledgeGateway, make_context: ContextFactory, admin: AsyncEngine
) -> None:
    """R2.1: tenant B naming A's document id gets the 404 of a missing one."""
    owner = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Bí mật Alpha"), content=SECRET_TEXT), owner
    )

    with pytest.raises(NotFoundError):
        await gateway.soft_delete_document(
            ingested.document_id, make_context(TENANT_B, WORKSPACE_B)
        )

    assert await gateway.search(SearchQuery(text=SECRET_TEXT), owner)
    assert await _status(admin, ingested.document_id) == "active"
    assert await _deleted_audits(admin, ingested.document_id) == 0


async def test_another_workspace_cannot_delete_a_document(
    gateway: KnowledgeGateway, make_context: ContextFactory, admin: AsyncEngine
) -> None:
    """R2.1: RLS narrows only by tenant; the workspace fence is the statement's."""
    owner = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Bí mật workspace A"), content=SECRET_TEXT), owner
    )

    with pytest.raises(NotFoundError):
        await gateway.soft_delete_document(
            ingested.document_id, make_context(TENANT_A, uuid.UUID(int=0xAA02))
        )

    assert await gateway.search(SearchQuery(text=SECRET_TEXT), owner)
    assert await _status(admin, ingested.document_id) == "active"


async def test_no_tenant_deletes_a_global_document(
    gateway: KnowledgeGateway, make_context: ContextFactory, admin: AsyncEngine
) -> None:
    """R2.1: a global document is readable from every tenant and deletable through
    this route by none of them, its publisher included."""
    publisher = make_context(TENANT_A, WORKSPACE_A).model_copy(
        update={"scopes": frozenset({"knowledge.read", GLOBAL_PUBLISH_SCOPE})}
    )
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Luật chung"), content=SECRET_TEXT, scope="global"),
        publisher,
    )
    reader = make_context(TENANT_B, WORKSPACE_B)
    assert await gateway.search(SearchQuery(text=SECRET_TEXT), reader)

    for caller in (reader, publisher):
        with pytest.raises(NotFoundError):
            await gateway.soft_delete_document(ingested.document_id, caller)

    assert await gateway.search(SearchQuery(text=SECRET_TEXT), reader)
    assert await _status(admin, ingested.document_id) == "active"


async def test_a_tombstone_for_another_tenant_leaves_the_vectors_alone(
    gateway: KnowledgeGateway, make_context: ContextFactory
) -> None:
    """FH2's filter, below the gateway: the gateway never tombstones when no row
    matched, so the adapter is called directly with the wrong tenant."""
    owner = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Bí mật Alpha"), content=SECRET_TEXT), owner
    )

    await gateway.vector_index.tombstone_document(ingested.document_id, TENANT_B)

    assert await gateway.search(SearchQuery(text=SECRET_TEXT), owner), (
        "tenant B's tombstone reached tenant A's points"
    )


async def test_a_delete_writes_one_audit_row_and_a_second_delete_is_a_404(
    gateway: KnowledgeGateway, make_context: ContextFactory, admin: AsyncEngine
) -> None:
    """R2.2: one `knowledge.document.deleted`; deleting again finds nothing to mark."""
    context = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Bí mật Alpha"), content=SECRET_TEXT), context
    )

    await gateway.soft_delete_document(ingested.document_id, context)
    with pytest.raises(NotFoundError):
        await gateway.soft_delete_document(ingested.document_id, context)

    assert await _deleted_audits(admin, ingested.document_id) == 1
    async with admin.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT tenant_id, workspace_id, actor_id FROM platform.audit_events"
                    " WHERE action = :action AND resource_id = :id"
                ),
                {"action": DELETED_ACTION, "id": str(ingested.document_id)},
            )
        ).one()
    assert (row.tenant_id, row.workspace_id, row.actor_id) == (
        TENANT_A,
        WORKSPACE_A,
        context.principal_id,
    )


async def test_a_failing_audit_leaves_the_document_undeleted(
    gateway: KnowledgeGateway, make_context: ContextFactory, admin: AsyncEngine
) -> None:
    """R2.2: the mark and its audit row commit together or not at all.

    The audit insert is made to fail in the database itself, for this one
    document, so the gateway runs unchanged.
    """
    context = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title=_unique("Bí mật Alpha"), content=SECRET_TEXT), context
    )
    async with admin.begin() as conn:
        await conn.execute(
            sa.text(
                "CREATE FUNCTION platform.test_refuse_audit() RETURNS trigger"
                " LANGUAGE plpgsql AS $fn$ BEGIN"
                f" IF NEW.resource_id = '{ingested.document_id}' THEN"
                " RAISE EXCEPTION 'audit refused by the test'; END IF;"
                " RETURN NEW; END $fn$"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE TRIGGER test_refuse_audit BEFORE INSERT ON platform.audit_events"
                " FOR EACH ROW EXECUTE FUNCTION platform.test_refuse_audit()"
            )
        )
    try:
        with pytest.raises(Exception, match="audit refused by the test"):
            await gateway.soft_delete_document(ingested.document_id, context)
    finally:
        async with admin.begin() as conn:
            await conn.execute(sa.text("DROP TRIGGER test_refuse_audit ON platform.audit_events"))
            await conn.execute(sa.text("DROP FUNCTION platform.test_refuse_audit()"))

    assert await _status(admin, ingested.document_id) == "active"
    assert await gateway.search(SearchQuery(text=SECRET_TEXT), context)
