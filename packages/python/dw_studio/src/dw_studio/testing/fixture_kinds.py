"""`fixture` and `fixture_gateless`: two kinds that exist only in tests.

A document is `{"title": str, "uses": [<artifact id>, ...], "size": int}`;
`extract` returns one `artifact` reference per string in `uses`, at its
pointer. `fixture` is gated (`has_quality_gate = true`), `fixture_gateless`
is not. Their keys are test keys, outside `studio.` (test (d) of
`test_permission_catalogue.py`), and their hook does nothing.

`planted_fixture_kinds` is an async context manager for a module-scoped
fixture: it registers the keys and the two `studio.artifact_kinds` rows as
the migrator, and on the way out moves every company holding an artifact of
either kind to `offboarding`, deletes those rows in foreign-key order, removes
the two kinds and the keys, and asserts nothing of them is left. So a test
that runs later in the same process (`test_permission_catalogue.py`, the
registry-against-table test) never sees them. They reach an app only through
`build_studio(kinds=...)`, never through `PLATFORM_KINDS`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from dw_platform.testing.rbac import register_key, unregister_key
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.core.domain.artifacts import DocumentProblem, Reference, TargetKind, Usage

FIXTURE_READ: Final = "fixture.artifacts.read"
FIXTURE_WRITE: Final = "fixture.artifacts.write"
FIXTURE_SUBMIT: Final = "fixture.artifacts.submit"
FIXTURE_KEYS: Final = (FIXTURE_READ, FIXTURE_WRITE, FIXTURE_SUBMIT)


def validate_fixture(document: Any) -> list[DocumentProblem]:
    problems: list[DocumentProblem] = []
    if not isinstance(document, dict):
        return [DocumentProblem("", "document_not_object", "a document is an object")]
    if not isinstance(document.get("title"), str):
        problems.append(DocumentProblem("/title", "title_required", "a title is a string"))
    uses = document.get("uses", [])
    if not isinstance(uses, list):
        problems.append(DocumentProblem("/uses", "uses_not_list", "uses is a list"))
    else:
        problems.extend(
            DocumentProblem(f"/uses/{n}", "use_not_string", "a use is an artifact id")
            for n, item in enumerate(uses)
            if not isinstance(item, str)
        )
    size = document.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        problems.append(DocumentProblem("/size", "size_invalid", "size is a whole number"))
    return problems


def extract_fixture(document: Any) -> list[Reference]:
    uses = document.get("uses", []) if isinstance(document, dict) else []
    if not isinstance(uses, list):
        return []
    return [
        Reference(TargetKind.ARTIFACT, item, Usage.READ, f"/uses/{n}")
        for n, item in enumerate(uses)
        if isinstance(item, str)
    ]


async def _no_hook(_tx: ArtifactTx, _version_id: uuid.UUID) -> None:
    return None


def _entry(kind: str) -> ArtifactKindEntry:
    return ArtifactKindEntry(
        kind=kind,
        document_schema="dw.fixture/v1",
        read_key=FIXTURE_READ,
        write_key=FIXTURE_WRITE,
        submit_key=FIXTURE_SUBMIT,
        publish_hook=_no_hook,
        validate=validate_fixture,
        extract=extract_fixture,
    )


FIXTURE: Final = _entry("fixture")
FIXTURE_GATELESS: Final = _entry("fixture_gateless")
FIXTURE_KINDS: Final[tuple[ArtifactKindEntry, ...]] = (FIXTURE, FIXTURE_GATELESS)
# The flag each kind's `studio.artifact_kinds` row states.
_GATED: Final = {FIXTURE.kind: True, FIXTURE_GATELESS.kind: False}


async def _remove_rows(engine: AsyncEngine, kinds: Sequence[str]) -> None:
    async with engine.begin() as conn:
        tenants = [
            row.tenant_id
            for row in await conn.execute(
                sa.text("SELECT DISTINCT tenant_id FROM studio.artifacts WHERE kind = ANY(:k)"),
                {"k": list(kinds)},
            )
        ]
        if tenants:
            # Only the offboarding pass deletes these rows (tenant-config R3.8).
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = ANY(:t)"),
                {"t": tenants},
            )
            for statement in (
                # A run pinning a manifest, then the manifests and (by
                # CASCADE) their keys, before the versions they hold.
                "DELETE FROM platform.worker_runs"
                " WHERE tenant_id = ANY(:t) AND run_manifest_hash IS NOT NULL",
                "DELETE FROM platform.run_manifests WHERE tenant_id = ANY(:t)",
                "DELETE FROM studio.dependencies WHERE tenant_id = ANY(:t)",
                "DELETE FROM studio.artifact_versions WHERE tenant_id = ANY(:t)",
                "DELETE FROM studio.artifacts WHERE tenant_id = ANY(:t)",
                "DELETE FROM studio.definition_manifests WHERE tenant_id = ANY(:t)",
            ):
                await conn.execute(sa.text(statement), {"t": tenants})
        await conn.execute(
            sa.text("DELETE FROM studio.artifact_kinds WHERE kind = ANY(:k)"), {"k": list(kinds)}
        )
        for key in FIXTURE_KEYS:
            await unregister_key(conn, key)


@asynccontextmanager
async def planted_fixture_kinds(
    migrator: AsyncEngine,
) -> AsyncIterator[tuple[ArtifactKindEntry, ...]]:
    """The two kinds and their keys in the catalogue for the block, then gone."""
    kinds = [entry.kind for entry in FIXTURE_KINDS]
    await _remove_rows(migrator, kinds)  # a run that died midway left them
    async with migrator.begin() as conn:
        for key in FIXTURE_KEYS:
            await register_key(conn, key)
        for kind, gated in _GATED.items():
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.artifact_kinds (kind, has_quality_gate) VALUES (:k, :g)"
                ),
                {"k": kind, "g": gated},
            )
    try:
        yield FIXTURE_KINDS
    finally:
        await _remove_rows(migrator, kinds)
        async with migrator.connect() as conn:
            left = await conn.scalar(
                sa.text(
                    "SELECT (SELECT count(*) FROM studio.artifact_kinds WHERE kind = ANY(:k))"
                    " + (SELECT count(*) FROM platform.permissions WHERE key = ANY(:p))"
                ),
                {"k": kinds, "p": list(FIXTURE_KEYS)},
            )
        assert left == 0, "the fixture kinds outlived their module"
