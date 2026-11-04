"""`RunManifestBuilder`: the run manifest a Studio run pins before its first
node (tenant-config R6.1, R6.2, R6.7, R6.8; ADR-0109 decisions 6, 8, 9).

Called by the one door that accepts a Studio run (`RunRequestService`,
workflow-engine/02) inside its own transaction, which then writes the run row
naming the hash; `build` writes no run row. No tenant argument: the tenant is
the transaction's `app.tenant_id`, and every read goes through RLS, so another
tenant's version is a version that does not exist (CLAUDE.md, Per-tenant
artifacts).

The closure has one source per root. A sealed root: its definition manifest's
`closure`, verbatim, and the versions its where-used index pins. A draft root
(a `simulate` run only): `closure_of` and `definition_body`, the seal's own two
functions, over the content read at receipt, so the provisional hash is what
the seal gives the same content and nothing is written to the draft, the
where-used index or the definition manifests.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from dw_kernel.canonical import content_hash
from dw_kernel.errors import ConfigError, ConflictError, NotFoundError
from dw_kernel.run_mode import RunMode
from dw_studio.core.application.ports import RunManifestTx
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import closure_of
from dw_studio.core.domain.artifacts import Stage, definition_body, definition_hash
from dw_studio.core.domain.run_manifest import RUN_MANIFEST_SCHEMA, RunManifest

# R6.8 (TC32): every root's runs checkpoint synchronously.
ENGINE: Final[dict[str, Any]] = {"durability": "sync"}


class RunManifestBuilder:
    def __init__(self, registry: ArtifactKindRegistry, release_manifest_ref: str) -> None:
        self.registry = registry
        self.release_manifest_ref = release_manifest_ref

    async def build(self, uow: RunManifestTx, root_version_id: uuid.UUID, run_mode: RunMode) -> str:
        """The manifest's hash, its row and its key rows written in `uow`."""
        found = await uow.root_version(root_version_id)
        if found is None or self.registry.get(found.kind) is None:
            raise NotFoundError("version not found")
        version = found.version
        draft = version.stage is Stage.DRAFT
        # R6.7 (TC28): whoever asks, before anything is written.
        if draft and run_mode != "simulate":
            raise ConflictError(
                "only a simulated run may start from a draft",
                details={"reason_code": "draft_root_not_simulate"},
            )
        if draft:
            # CanonicalError (with its pointer) and `dependency_unresolved`
            # both refuse here, before any write.
            root_hash = content_hash(version.document)
            closure, rows = await closure_of(
                uow, self.registry, found.kind, version.artifact_id, version.document
            )
            definition = definition_body(found.kind, version.artifact_id, root_hash, closure)
            pinned_hash = definition_hash(definition)
            pinned = [row.to_version_id for row in rows if row.to_version_id is not None]
        else:
            pinned_hash = version.definition_hash or ""
            stored = await uow.definition_manifest(pinned_hash)
            if stored is None:
                raise ConfigError(
                    "the root's definition manifest is missing",
                    details={"reason": "definition_manifest_missing"},
                )
            definition = stored
            pinned = await uow.pinned_versions(version.id)
        manifest = RunManifest.model_validate(
            {
                "schema": RUN_MANIFEST_SCHEMA,
                "release_manifest_ref": self.release_manifest_ref,
                "run_mode": run_mode,
                "root": {
                    "kind": found.kind,
                    "artifact_id": version.artifact_id,
                    "version_id": version.id,
                    "version_no": None if draft else version.version_no,
                    "definition_hash": pinned_hash,
                    **({"stage": Stage.DRAFT.value} if draft else {}),
                },
                "closure": definition["closure"],
                "engine": ENGINE,
            }
        )
        body = manifest.as_body()
        manifest_hash = content_hash(body)
        await uow.put_run_manifest(manifest_hash, body)
        await uow.put_run_manifest_keys(manifest_hash, list(dict.fromkeys([version.id, *pinned])))
        return manifest_hash
