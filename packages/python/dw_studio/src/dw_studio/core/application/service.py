"""`ArtifactService`: the versioned envelope every Studio kind shares
(tenant-config R2, R3; ADR-0109 decisions 1-2, 4-5; ADR-0120 decision 1).

Each operation asks one question of the caller, with the key the kind's
registry entry declares, at the depth `platform.workspace_reach` says reaches
the artifact's owning workspace (ADR-0104 decision 5): another tenant, a
soft-deleted artifact or one the caller cannot read is a 404; readable and not
writable is a 403. The database holds every rule a row can break, and the store
reads its refusals back by constraint name.

One lock rule (the spec's Quyết định 3/11/2026, (5)): `save_draft`,
`create_draft` and `seal` each take the artifact row `FOR UPDATE` before
reading any of its versions, so the three writes of one artifact's versions
run one after another and a seal hashes exactly the document it read.

`seal` changes no stage and touches no other version (R2.7, R2.13, R2.16): the
stage that follows it is `LifecycleService`'s, in the same transaction, behind
`studio.guard_version_stage()` (agent-lifecycle R1.4, R2.8). It checks no
permission either; the caller that runs it (agent-lifecycle/03's submit
route) checks the kind's submit key first.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dw_kernel.canonical import CanonicalError, content_hash, ensure_hashable, to_nfc
from dw_kernel.errors import (
    ConflictError,
    DWError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
)
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.audit import AuditEvent
from dw_studio.core.application.bindings import declaration_problems
from dw_studio.core.application.ports import (
    ArtifactRow,
    ArtifactStore,
    ArtifactTx,
    DependencyRow,
    Dependent,
    ListScope,
    VersionRow,
)
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.domain.artifacts import (
    API_NAME,
    CANDIDATE_STAGES,
    PUBLISHED_STAGES,
    ClosureItem,
    DocumentInvalidError,
    DocumentProblem,
    Reference,
    Stage,
    TargetKind,
    definition_body,
    definition_hash,
    label_problems,
)
from dw_studio.core.domain.bindings import (
    binding_references,
    connection_strings,
    declaration_paths,
    merge,
    parse_declarations,
)

RESOURCE = "studio_artifact"
_PATCHABLE = frozenset({"api_name", "labels"})


def document_problems(entry: ArtifactKindEntry, document: Any) -> list[DocumentProblem]:
    """The kind's own check and the shared `bindings[]` shape (tenant-config
    R7; ticket 05 step 1): what a seal refuses, a save warns of and the run
    door checks a simulated draft with."""
    return [*entry.validate(document), *parse_declarations(document).problems]


@dataclass(frozen=True, slots=True)
class SealResult:
    version_id: uuid.UUID
    version_no: int
    content_hash: str
    definition_hash: str
    # What the definition hash pinned, for the submit's per-kind checks
    # (agent-lifecycle R2.7): the seal's own closure, not a second one.
    closure: tuple[ClosureItem, ...] = ()


@dataclass(frozen=True, slots=True)
class SavedDraft:
    """A saved draft and what its kind's check finds in it (workflow-engine
    R2.13): warnings, never a refusal, since a draft is work in progress."""

    version: VersionRow
    warnings: tuple[DocumentProblem, ...]


@dataclass(frozen=True, slots=True)
class DependentRef:
    artifact_id: uuid.UUID
    kind: str
    api_name: str


@dataclass(slots=True)
class DependentGroup:
    """The dependents of one stage group the caller may name, and how many
    others there are (TC7)."""

    items: list[DependentRef] = field(default_factory=list)
    hidden: int = 0


@dataclass(frozen=True, slots=True)
class Dependents:
    live: DependentGroup
    candidate: DependentGroup


def _reason(error: type[DWError], message: str, reason: str, **details: object) -> DWError:
    return error(message, details={"reason_code": reason, **details})


def _no_draft() -> Exception:
    return _reason(NotFoundError, "this artifact has no draft", "no_draft")


def _stale() -> Exception:
    return _reason(
        PreconditionFailedError, "the version you read is no longer current", "stale_version"
    )


async def name_or_count(
    tx: ArtifactTx, registry: ArtifactKindRegistry, dependents: Sequence[Dependent]
) -> DependentGroup:
    """Each dependent named where the caller reads it with its own kind's key,
    counted otherwise (TC7): the one rule `dependents` and agent-lifecycle's
    retire (R2.6) both answer with."""
    group = DependentGroup()
    reach: dict[str, frozenset[uuid.UUID]] = {}
    for dependent in dependents:
        entry = registry.get(dependent.kind)
        if entry is not None and entry.read_key not in reach:
            reach[entry.read_key] = await tx.reach(entry.read_key)
        if entry is not None and dependent.owning_workspace_id in reach[entry.read_key]:
            group.items.append(
                DependentRef(dependent.artifact_id, dependent.kind, dependent.api_name)
            )
        else:
            group.hidden += 1
    return group


def _unreleased(versions: Sequence[VersionRow]) -> VersionRow | None:
    """The one draft or candidate an artifact may have (R2.20)."""
    return next(
        (v for v in versions if v.stage is Stage.DRAFT or v.stage in CANDIDATE_STAGES), None
    )


def _with(people: Sequence[uuid.UUID], person: uuid.UUID) -> list[uuid.UUID]:
    """`people` with `person` added last unless already there, order kept."""
    return [*people, person] if person not in people else list(people)


def canonical_document(document: Any, *, at: str = "/document") -> Any:
    """The edge's repair and check (`to_nfc`, then `ensure_hashable`), so a draft
    that could never be hashed is refused when saved, with its pointer (gate
    MEDIUM (a), 3/11/2026), not when it is sealed."""
    if not isinstance(document, dict):
        raise DocumentInvalidError(
            "a document is a JSON object",
            [DocumentProblem(at, "document_not_object", "a document is a JSON object")],
        )
    try:
        normal = to_nfc(document)
        ensure_hashable(normal)
    except CanonicalError as exc:
        reason = str(exc.details.get("reason", "invalid"))
        pointer = f"{at}{exc.details.get('pointer', '')}"
        raise DocumentInvalidError(
            "the document has no canonical form",
            [DocumentProblem(pointer, reason, "the value has no canonical form")],
        ) from None
    return normal


class ArtifactService:
    def __init__(
        self,
        store: ArtifactStore,
        registry: ArtifactKindRegistry,
        clock: UtcClock,
        ids: IdGenerator,
    ) -> None:
        self.store = store
        self.registry = registry
        self.clock = clock
        self.ids = ids

    # ---- who may ----------------------------------------------------------

    async def _load(self, tx: ArtifactTx, artifact_id: uuid.UUID, *, lock: bool) -> ArtifactRow:
        row = await tx.artifact(artifact_id, lock=lock)
        if row is None:
            raise NotFoundError("artifact not found")
        return row

    async def _readable(self, tx: ArtifactTx, row: ArtifactRow) -> ArtifactKindEntry:
        entry = self.registry.get(row.kind)
        # A kind this process does not register has no read key: nobody reads it.
        if entry is None or row.owning_workspace_id not in await tx.reach(entry.read_key):
            raise NotFoundError("artifact not found")
        return entry

    @staticmethod
    async def _holds(tx: ArtifactTx, row: ArtifactRow, key: str) -> None:
        """403 unless `key` reaches the artifact's owning workspace."""
        if row.owning_workspace_id not in await tx.reach(key):
            raise PermissionDeniedError(
                "you may read this artifact and not do this", details={"action": key}
            )

    async def _writable(self, tx: ArtifactTx, row: ArtifactRow, entry: ArtifactKindEntry) -> None:
        await self._holds(tx, row, entry.write_key)

    async def open_for(
        self,
        tx: ArtifactTx,
        artifact_id: uuid.UUID,
        *,
        kind: str,
        key: Callable[[ArtifactKindEntry], str],
        lock: bool,
    ) -> tuple[ArtifactRow, ArtifactKindEntry]:
        """The artifact for an action keyed by `key` of its kind's entry, the
        same two questions every write here asks: 404 for one the caller cannot
        read or whose stored kind is not `kind` (a route segment names one kind),
        403 for one they read without the key (agent-lifecycle R2.1, R2.4, R2.5)."""
        row = await self._load(tx, artifact_id, lock=lock)
        if row.kind != kind:
            raise NotFoundError("artifact not found")
        entry = await self._readable(tx, row)
        await self._holds(tx, row, key(entry))
        return row, entry

    def _entry(self, kind: str) -> ArtifactKindEntry:
        entry = self.registry.get(kind)
        if entry is None:
            raise DocumentInvalidError(
                "no such kind",
                [DocumentProblem("/kind", "kind_unknown", "the kind is not registered")],
            )
        return entry

    async def check_create(self, context: AccessContext, kind: str) -> None:
        """The create's own question, for an idempotent retry (app-standards R2.30)."""
        entry = self._entry(kind)
        async with self.store.transaction(context) as tx:
            await self._may_create(tx, context, entry)

    @staticmethod
    async def _may_create(tx: ArtifactTx, context: AccessContext, entry: ArtifactKindEntry) -> None:
        if context.workspace_id not in await tx.reach(entry.write_key):
            raise PermissionDeniedError(
                "you may not create this kind here", details={"action": entry.write_key}
            )

    async def check_write(self, context: AccessContext, artifact_id: uuid.UUID) -> None:
        """404 for an artifact the caller cannot read, 403 for one they cannot change."""
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=False)
            await self._writable(tx, row, await self._readable(tx, row))

    def event(
        self,
        context: AccessContext,
        action: str,
        artifact_id: uuid.UUID,
        details: Mapping[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.ids.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type=RESOURCE,
            resource_id=str(artifact_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )

    # ---- the artifact -------------------------------------------------------

    async def create(
        self,
        context: AccessContext,
        *,
        kind: str,
        api_name: str,
        labels: Sequence[str],
        document: Any,
        effect: PendingEffect | None = None,
    ) -> tuple[ArtifactRow, VersionRow]:
        """R2.1-R2.3: the artifact, its first draft and the audit, in one
        transaction; owned by the caller's verified acting workspace."""
        entry = self._entry(kind)
        problems: list[DocumentProblem] = []
        if not API_NAME.fullmatch(api_name):
            problems.append(
                DocumentProblem(
                    "/api_name", "api_name_invalid", "2-40 of [a-z0-9_], a letter first"
                )
            )
        problems.extend(label_problems(labels))
        if problems:
            raise DocumentInvalidError("the artifact is not valid", problems)
        document = canonical_document(document)
        artifact_id = self.ids.new_uuid()
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(artifact_id))
            await self._may_create(tx, context, entry)
            row = await tx.insert_artifact(
                artifact_id=artifact_id,
                kind=kind,
                api_name=api_name,
                owning_workspace_id=context.workspace_id,
                labels=labels,
            )
            draft = await tx.insert_draft(
                version_id=self.ids.new_uuid(),
                artifact_id=artifact_id,
                document_schema=entry.document_schema,
                document=document,
                based_on_version_id=None,
                contributor_ids=[context.principal_id],
            )
            await tx.audit(
                self.event(
                    context,
                    "studio.artifact.created",
                    artifact_id,
                    {"kind": kind, "api_name": api_name},
                )
            )
            # Read back for its displayed stage, now that its draft exists.
            row = await self._load(tx, artifact_id, lock=False)
        return row, draft

    async def get(self, context: AccessContext, artifact_id: uuid.UUID) -> ArtifactRow:
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=False)
            await self._readable(tx, row)
        return row

    async def page(
        self,
        context: AccessContext,
        request: PageRequest,
        *,
        kind: str | None = None,
        label: str | None = None,
    ) -> Page[ArtifactRow]:
        """R2.11: only the kinds and workspaces the caller reads, filtered in
        SQL on the list index, so a page is never short for being filtered."""
        entries = (
            [entry for entry in (self.registry.get(kind),) if entry is not None]
            if kind is not None
            else list(self.registry)
        )
        async with self.store.transaction(context) as tx:
            scopes = [ListScope(e.kind, await tx.reach(e.read_key)) for e in entries]
            scopes = [scope for scope in scopes if scope.workspaces]
            rows = (
                await tx.list_page(
                    scopes, label=label, after=request.after, fetch_limit=request.fetch_limit
                )
                if scopes
                else []
            )
        return build_page(
            rows,
            request=request,
            position_of=lambda row: CursorPosition(sort_value=row.updated_at, tiebreaker=row.id),
        )

    async def update(
        self,
        context: AccessContext,
        artifact_id: uuid.UUID,
        expected: ExpectedVersion,
        patch: Mapping[str, Any],
        effect: PendingEffect | None = None,
    ) -> ArtifactRow:
        """`api_name` and `labels` (R2.10); bumps `row_version`, the only write that does."""
        problems = [
            DocumentProblem(f"/{name}", "not_patchable", "only api_name and labels change here")
            for name in sorted(set(patch) - _PATCHABLE)
        ]
        api_name = patch.get("api_name")
        labels = patch.get("labels")
        if "api_name" in patch and (
            not isinstance(api_name, str) or not API_NAME.fullmatch(api_name)
        ):
            problems.append(
                DocumentProblem(
                    "/api_name", "api_name_invalid", "2-40 of [a-z0-9_], a letter first"
                )
            )
        if "labels" in patch:
            if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
                problems.append(DocumentProblem("/labels", "labels_invalid", "a list of labels"))
            else:
                problems.extend(label_problems(labels))
        if problems:
            raise DocumentInvalidError("the patch is not valid", problems)
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(artifact_id))
            row = await self._load(tx, artifact_id, lock=True)
            await self._writable(tx, row, await self._readable(tx, row))
            if not expected.matches(row.row_version):
                raise _stale()
            changes: dict[str, Any] = {}
            if "api_name" in patch and api_name != row.api_name:
                if any(v.stage in PUBLISHED_STAGES for v in await tx.versions(artifact_id)):
                    raise _reason(
                        ConflictError,
                        "the API name is fixed once a version has been live",
                        "api_name_immutable",
                    )
                changes["api_name"] = api_name
            if "labels" in patch and tuple(labels or ()) != row.labels:
                changes["labels"] = list(labels or ())
            if not changes:
                return row
            updated = await tx.update_artifact(
                artifact_id, **changes, row_version=row.row_version + 1
            )
            await tx.audit(
                self.event(
                    context, "studio.artifact.updated", artifact_id, {"fields": sorted(changes)}
                )
            )
        return updated

    async def soft_delete(
        self, context: AccessContext, artifact_id: uuid.UUID, expected: ExpectedVersion
    ) -> None:
        """R3.2, R3.3: refused by `ck_artifacts_not_in_use` while another
        artifact's in-use version depends on it."""
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=True)
            await self._writable(tx, row, await self._readable(tx, row))
            if not expected.matches(row.row_version):
                raise _stale()
            await tx.soft_delete(artifact_id)
            await tx.audit(
                self.event(context, "studio.artifact.deleted", artifact_id, {"kind": row.kind})
            )

    # ---- the draft --------------------------------------------------------

    async def get_draft(self, context: AccessContext, artifact_id: uuid.UUID) -> VersionRow:
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=False)
            await self._readable(tx, row)
            unreleased = _unreleased(await tx.versions(artifact_id))
        if unreleased is None or unreleased.stage is not Stage.DRAFT:
            raise _no_draft()
        return unreleased

    async def save_draft(
        self,
        context: AccessContext,
        artifact_id: uuid.UUID,
        expected: ExpectedVersion,
        document: Any,
        effect: PendingEffect | None = None,
    ) -> SavedDraft:
        """R2.4, R2.5: the document replaced under `If-Match`; a draft sealed
        once and sent back keeps no number or hash of its old content (R2.8).
        Only a document with no canonical form is refused (R1.2); after the
        save, the kind's own check runs as warnings (workflow-engine R2.13)."""
        document = canonical_document(document)
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(artifact_id))
            row = await self._load(tx, artifact_id, lock=True)
            entry = await self._readable(tx, row)
            await self._writable(tx, row, entry)
            unreleased = _unreleased(await tx.versions(artifact_id))
            if unreleased is None:
                raise _no_draft()
            if unreleased.stage is not Stage.DRAFT:
                raise _reason(ConflictError, "a candidate is pending", "candidate_pending")
            if not expected.matches(unreleased.row_version):
                raise _stale()
            saved = await tx.update_version(
                unreleased.id,
                document=document,
                version_no=None,
                content_hash=None,
                definition_hash=None,
                row_version=unreleased.row_version + 1,
                # Everyone who saved it is an author (agent-lifecycle R5.1, R5.2).
                contributor_ids=_with(unreleased.contributor_ids, context.principal_id),
            )
            await tx.audit(
                self.event(
                    context,
                    "studio.artifact.draft_saved",
                    artifact_id,
                    {"row_version": saved.row_version},
                )
            )
        return SavedDraft(saved, tuple(document_problems(entry, saved.document)))

    async def create_draft(
        self,
        context: AccessContext,
        artifact_id: uuid.UUID,
        expected: ExpectedVersion,
        effect: PendingEffect | None = None,
    ) -> VersionRow:
        """R2.21-R2.23: a draft copied from the live version, or the highest
        numbered one, when the artifact has no draft and no candidate."""
        async with self.store.transaction(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(artifact_id))
            row = await self._load(tx, artifact_id, lock=True)
            await self._writable(tx, row, await self._readable(tx, row))
            if not expected.matches(row.row_version):
                raise _stale()
            versions = await tx.versions(artifact_id)
            unreleased = _unreleased(versions)
            if unreleased is not None and unreleased.stage in CANDIDATE_STAGES:
                raise _reason(ConflictError, "a candidate is pending", "candidate_pending")
            if unreleased is not None:
                raise _reason(ConflictError, "this artifact already has a draft", "draft_exists")
            live = [v for v in versions if v.stage is Stage.LIVE]
            numbered = [v for v in versions if v.version_no is not None]
            source = (live or sorted(numbered, key=lambda v: v.version_no or 0, reverse=True))[:1]
            if not source:
                raise _reason(ConflictError, "there is no version to copy", "no_version")
            base = source[0]
            draft = await tx.insert_draft(
                version_id=self.ids.new_uuid(),
                artifact_id=artifact_id,
                document_schema=base.document_schema,
                document=base.document,
                based_on_version_id=base.id,
                contributor_ids=[context.principal_id],
            )
            await tx.audit(
                self.event(
                    context,
                    "studio.artifact.draft_created",
                    artifact_id,
                    {"based_on_version_id": str(base.id)},
                )
            )
        return draft

    async def draft_dependencies(
        self, context: AccessContext, artifact_id: uuid.UUID
    ) -> list[Reference]:
        """R3.5: the kind's own extractor over the draft; nothing is written."""
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=False)
            entry = await self._readable(tx, row)
            unreleased = _unreleased(await tx.versions(artifact_id))
        if unreleased is None or unreleased.stage is not Stage.DRAFT:
            raise _no_draft()
        return list(entry.extract(unreleased.document))

    # ---- sealed versions ----------------------------------------------------

    async def versions(self, context: AccessContext, artifact_id: uuid.UUID) -> list[VersionRow]:
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=False)
            await self._readable(tx, row)
            versions = await tx.versions(artifact_id)
        sealed = [v for v in versions if v.stage is not Stage.DRAFT and v.version_no is not None]
        return sorted(sealed, key=lambda v: v.version_no or 0, reverse=True)

    async def version(
        self, context: AccessContext, artifact_id: uuid.UUID, version_no: int
    ) -> VersionRow:
        for version in await self.versions(context, artifact_id):
            if version.version_no == version_no:
                return version
        raise NotFoundError("version not found")

    async def dependents(self, context: AccessContext, artifact_id: uuid.UUID) -> Dependents:
        """R3.4: grouped by stage; named only where the caller reads the
        dependent with its own kind's key, counted otherwise (TC7)."""
        async with self.store.transaction(context) as tx:
            row = await self._load(tx, artifact_id, lock=False)
            await self._readable(tx, row)
            found = await tx.dependents(artifact_id)
            live = await name_or_count(
                tx, self.registry, [d for d in found if d.stage is Stage.LIVE]
            )
            candidate = await name_or_count(
                tx, self.registry, [d for d in found if d.stage is not Stage.LIVE]
            )
        return Dependents(live=live, candidate=candidate)

    async def seal(
        self, tx: ArtifactTx, artifact_id: uuid.UUID, expected_row_version: int
    ) -> SealResult:
        """R2.6-R2.8, R2.13, R2.16, R2.17, R3.1, R3.3, in the caller's transaction.

        `expected_row_version` is the draft's ETag the submit carried in
        `If-Match`; a stale one is refused before any number is given.
        """
        row = await self._load(tx, artifact_id, lock=True)
        entry = self.registry.get(row.kind)
        if entry is None:
            raise NotFoundError("artifact not found")
        unreleased = _unreleased(await tx.versions(artifact_id))
        if unreleased is None or unreleased.stage is not Stage.DRAFT:
            raise _no_draft()
        if unreleased.row_version != expected_row_version:
            raise _stale()
        problems = document_problems(entry, unreleased.document)
        if problems:
            raise DocumentInvalidError("the document is not valid", problems)
        root_hash = content_hash(unreleased.document)
        closure, rows = await self.closure_of(tx, row.kind, artifact_id, unreleased.document)
        problems = await _binding_problems(tx, unreleased.document, rows)
        if problems:
            raise DocumentInvalidError("the document is not valid", problems)
        version_no = row.last_version_no + 1
        await tx.update_artifact(artifact_id, last_version_no=version_no)
        body = definition_body(row.kind, artifact_id, root_hash, closure)
        manifest_hash = definition_hash(body)
        await tx.put_manifest(manifest_hash, body)
        await tx.replace_dependencies(artifact_id=artifact_id, version_id=unreleased.id, rows=rows)
        await tx.update_version(
            unreleased.id,
            version_no=version_no,
            content_hash=root_hash,
            definition_hash=manifest_hash,
            row_version=unreleased.row_version + 1,
        )
        return SealResult(unreleased.id, version_no, root_hash, manifest_hash, tuple(closure))

    async def closure_of(
        self, tx: ArtifactTx, kind: str, artifact_id: uuid.UUID, document: Any
    ) -> tuple[list[ClosureItem], list[DependencyRow]]:
        return await closure_of(tx, self.registry, kind, artifact_id, document)


async def closure_of(
    tx: ArtifactTx,
    registry: ArtifactKindRegistry,
    kind: str,
    artifact_id: uuid.UUID,
    document: Any,
) -> tuple[list[ClosureItem], list[DependencyRow]]:
    """The kind's references, an `artifact` one resolved to its target's
    `live` version within the tenant (read `FOR SHARE`); every broken one is
    one `dependency_unresolved` problem at its path. Writes nothing: the seal
    writes `studio.dependencies` itself, and ticket 04's `RunManifestBuilder`
    calls this for a draft's `simulate` run, with `definition_body`, for the
    hash the seal would give the same content."""
    entry = registry.get(kind)
    if entry is None:
        raise NotFoundError("artifact not found")
    problems: list[DocumentProblem] = []
    rows: list[DependencyRow] = []
    declared = binding_references(document)
    for ref in [*entry.extract(document), *declared]:
        if ref.to_kind is not TargetKind.ARTIFACT:
            rows.append(DependencyRow(ref.to_kind, ref.to_key, ref.usage, ref.path))
            continue
        target = None
        try:
            target_id = uuid.UUID(ref.to_key)
        except ValueError:
            target_id = None
        # Pinning itself would freeze the live version it replaces (gate (h)).
        if target_id is not None and target_id != artifact_id:
            target = await tx.live_target(target_id)
        if target is None:
            problems.append(
                DocumentProblem(
                    ref.path,
                    "dependency_unresolved",
                    "no live artifact with this id",
                )
            )
            continue
        rows.append(
            DependencyRow(
                ref.to_kind,
                str(target.artifact_id),
                ref.usage,
                ref.path,
                to_artifact_id=target.artifact_id,
                to_version_id=target.version_id,
                to_version=target.version_no,
                to_hash=target.content_hash,
            )
        )
    if problems:
        raise DocumentInvalidError("a reference does not resolve", problems)
    closure = [
        ClosureItem(row.to_kind.value, row.to_key, row.to_version, row.to_hash) for row in rows
    ]
    return closure, rows


async def _binding_problems(
    tx: ArtifactTx, document: Any, rows: Sequence[DependencyRow]
) -> list[DocumentProblem]:
    """What the seal refuses beyond the document's own shape (tenant-config
    ticket 05 step 1): a string that is the id of one of the tenant's
    connections, where only a binding's name may stand (R7.1, TC23), and one
    name declared with two kinds across the root and the versions its closure
    pins (gate 4/11/2026 (n))."""
    problems: list[DocumentProblem] = []
    strings = connection_strings(document)
    if strings:
        found = await tx.connection_ids(sorted({value for _, value in strings}))
        problems += [
            DocumentProblem(
                pointer,
                "connection_id_in_document",
                "a document names a binding, never a connection",
            )
            for pointer, value in strings
            if value in found
        ]
    root = parse_declarations(document)
    paths = declaration_paths(document)
    problems += declaration_problems(root.items, paths)
    pinned = [row.to_version_id for row in rows if row.to_version_id is not None]
    groups = [root.items]
    if pinned:
        documents = await tx.version_documents(pinned)
        groups += [parse_declarations(documents[v]).items for v in pinned if v in documents]
    problems += [
        DocumentProblem(
            paths.get(name, ""),
            "binding_conflict",
            "this name is declared with another kind in the closure",
        )
        for name in merge(groups).conflicts
    ]
    return problems
