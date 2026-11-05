"""Rebuild a Qdrant collection from the chunks stored in Postgres.

Documents and chunks in Postgres are the source of truth; vectors are derived.
Re-deriving them is what makes changing the embedding model possible at all.

It builds into a TARGET collection and never touches the one currently serving.
The previous version dropped the live collection first and then re-embedded, so
the outage lasted as long as the rebuild - which, against a remote embedding API,
is the whole point at which retrieval is most obviously broken. Build v2, point
readers at it, keep v1 until the new one has been watched for a while.

Run INSIDE the api container, which has the wired gateway and the gateway key:

    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        exec -T -e DW_REINDEX_TARGET=dw_knowledge_v2 api \
        python - < scripts/knowledge_reindex.py

Then set QDRANT_COLLECTION=dw_knowledge_v2 for the api and worker and restart
them. Delete the old collection only after that has run long enough to trust.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import sqlalchemy as sa


async def main() -> None:
    from dw_api import bootstrap
    from dw_kernel.residency import TenantRouteScope
    from dw_knowledge import tables
    from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter
    from dw_knowledge.ports import IndexableChunk

    target = os.environ.get("DW_REINDEX_TARGET", "").strip()
    if not target:
        print("DW_REINDEX_TARGET must name the collection to build into", file=sys.stderr)
        raise SystemExit(2)

    container = bootstrap.build_container()
    gateway = container.knowledge_gateway
    assert gateway is not None, "knowledge gateway is not wired"
    live: Any = gateway.vector_index
    if getattr(live, "collection", None) == target:
        # Writing into the collection being served would mix two vector spaces
        # in one place, and there is no way to tell them apart afterwards.
        print(f"DW_REINDEX_TARGET must differ from the live collection ({target})", file=sys.stderr)
        raise SystemExit(2)

    embeddings = gateway.embeddings
    index = QdrantVectorIndexAdapter(client=live.client, collection=target)
    await index.ensure_ready(embeddings.dimension)
    print(f"building {target} at dimension {embeddings.dimension}")

    async with gateway.session_factory() as session:
        tenants = (
            (await session.execute(sa.text("select distinct tenant_id from knowledge.documents")))
            .scalars()
            .all()
        )

    total = 0
    for tenant_id in tenants:
        async with gateway.session_factory() as session, session.begin():
            # SET LOCAL semantics: a pooled connection must carry no residue
            # into whoever borrows it next.
            await session.execute(
                sa.text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            documents = (
                await session.execute(
                    sa.select(tables.documents).where(
                        tables.documents.c.is_current,
                        tables.documents.c.status == "active",
                    )
                )
            ).all()
            print(f"tenant {tenant_id}: {len(documents)} documents")

            for document in documents:
                rows = (
                    await session.execute(
                        sa.select(tables.chunks)
                        .where(
                            tables.chunks.c.document_id == document.id,
                            tables.chunks.c.status == "active",
                        )
                        .order_by(tables.chunks.c.seq)
                    )
                ).all()
                if not rows:
                    print(" -", document.title, ": no chunks, skipped")
                    continue

                sections = [
                    str((row._mapping.get("metadata") or {}).get("section_path", "") or "")
                    for row in rows
                ]
                # The breadcrumb is part of what was embedded at ingest time;
                # embedding the bare content here would put these vectors in a
                # subtly different space from every future ingest.
                texts = [
                    f"[{section}]\n{row.content}" if section else row.content
                    for row, section in zip(rows, sections, strict=True)
                ]
                # One call: the adapter splits on the API's own ceilings, which
                # it knows and this script should not have to.
                # The document's own tenant and workspace, from its row
                # (compliance-pdpl R2.3): the gate reads their class.
                vectors = await embeddings.embed(
                    texts,
                    scope=TenantRouteScope(
                        tenant_id=document.tenant_id, workspace_id=document.workspace_id
                    ),
                )

                await index.upsert(
                    [
                        IndexableChunk(
                            chunk_id=row.id,
                            document_id=document.id,
                            tenant_id=document.tenant_id,
                            workspace_id=document.workspace_id,
                            domain=document.domain,
                            content=row.content,
                            classification=document.classification,
                            source_version=document.source_version,
                            # From the row: it records the chunking that produced
                            # these chunks. Re-stamping it with today's constant
                            # would describe them as something they are not.
                            index_version=document.index_version or "v1",
                            provenance_hash=row.provenance_hash,
                            acl_principals=tuple(document.acl_principals or ("tenant:*",)),
                            vector=tuple(vector),
                            section_path=section,
                            seq=row.seq,
                            scope=document.scope,
                            extra_payload=tuple(
                                (key, str(value)) for key, value in (document.extra or {}).items()
                            ),
                        )
                        for row, vector, section in zip(rows, vectors, sections, strict=True)
                    ]
                )
                total += len(rows)
                print(" -", document.title, ":", len(rows), "chunks")

    print(f"TOTAL points written to {target}: {total}")
    print("Now set QDRANT_COLLECTION and restart; drop the old collection later.")


asyncio.run(main())
