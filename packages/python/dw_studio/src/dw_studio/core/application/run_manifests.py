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

The root's bindings (ticket 05): what the root and the versions it pins
declare is handed to the caller's `pin`, before anything is written; the door
checks the approved Binding set there and refuses, or answers what the
manifest's `bindings` section pins, and the Binding set gets a key row of its
own (`config_version_id`, R2.18, R7.4).

The run's models (model-connections ticket 02; R1.4): the profiles the root's
kind says its document names (`ArtifactKindEntry.model_profiles`) and the
deployment's default, pinned by value under `engine` by `ModelRoutePinPort`
for the tenant and plan the caller verified, before anything is written. A
named profile the plan does not list refuses the build; the default it does
not list is pinned as null and refuses only a call that asks for it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final

from dw_kernel.canonical import content_hash
from dw_kernel.errors import ConfigError, ConflictError, NotFoundError
from dw_kernel.run_mode import RunMode
from dw_studio.core.application.bindings import PinnedBindings
from dw_studio.core.application.ports import ModelRoutePinPort, RunManifestTx
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import closure_of
from dw_studio.core.domain.artifacts import Stage, definition_body, definition_hash
from dw_studio.core.domain.bindings import BindingDecl, merge, parse_declarations
from dw_studio.core.domain.run_manifest import RUN_MANIFEST_SCHEMA, RunManifest

# R6.8 (TC32): every root's runs checkpoint synchronously.
ENGINE: Final[dict[str, Any]] = {"durability": "sync"}

Pin = Callable[[Sequence[BindingDecl]], Awaitable[PinnedBindings | None]]
"""Given what the root's closure declares, the bindings the run pins, or a
refusal raised before the manifest is written (the door's `BindingPins`)."""


class RunManifestBuilder:
    def __init__(
        self,
        registry: ArtifactKindRegistry,
        release_manifest_ref: str,
        models: ModelRoutePinPort,
    ) -> None:
        self.registry = registry
        self.release_manifest_ref = release_manifest_ref
        self.models = models

    async def build(
        self,
        uow: RunManifestTx,
        root_version_id: uuid.UUID,
        run_mode: RunMode,
        *,
        tenant_id: uuid.UUID,
        plan_id: str | None,
        pin: Pin | None = None,
    ) -> str:
        """The manifest's hash, its row and its key rows written in `uow`.

        `tenant_id` is the transaction's own and `plan_id` that tenant's plan,
        both from the caller's verified context, never from a request; they
        decide which model profiles the run may use and nothing else."""
        found = await uow.root_version(root_version_id)
        entry = None if found is None else self.registry.get(found.kind)
        if found is None or entry is None:
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
        documents = await uow.version_documents(pinned) if pinned else {}
        declared = merge(
            [parse_declarations(version.document).items]
            + [parse_declarations(documents[v]).items for v in pinned if v in documents]
        )
        # R1.4: refused here, before the bindings are asked or anything written.
        models = await self.models.pin(tenant_id, plan_id, entry.model_profiles(version.document))
        bindings = None if pin is None else await pin(list(declared.items.values()))
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
                "engine": {**ENGINE, **models},
                "bindings": None if bindings is None else bindings.as_section(),
            }
        )
        body = manifest.as_body()
        manifest_hash = content_hash(body)
        await uow.put_run_manifest(manifest_hash, body)
        await uow.put_run_manifest_keys(
            manifest_hash,
            list(dict.fromkeys([version.id, *pinned])),
            None if bindings is None else bindings.config_version_id,
        )
        return manifest_hash
