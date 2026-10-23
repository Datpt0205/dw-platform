---
status: Proposed (agent-proposed on 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/tenant-config/spec.md
    - ../../.claude/plans/studio/agent-lifecycle/spec.md
    - ../../.claude/plans/studio/workflow-engine/spec.md
    - ../../db/migrations/versions/0005_run_artifact_versions.py # the run labels this does not extend
    - ../../scripts/release_manifest.py # manifest_ref, the platform-layer pin
---

# 0109. Studio definitions are versioned documents in one shared envelope, hashed by one canonical function over their closure, and every run pins what it resolved in one run manifest

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block). Planning produced
competing answers to where versions live (one envelope with an active pointer; per-kind version tables for
agents, workflows and tools). This ADR keeps one envelope and leaves "which version runs" to the stage
contract of ADR 0120.

## Context

- Every Studio kind (object, workflow, agent, tool, skill, toolset) needs a draft, immutable numbered
  versions, a hash, where-used, packages, and runs that finish on what they started with. Five copies of
  that lifecycle would drift (failure-modes #2).
- A run's provenance today is the release manifest (`CLAUDE.md:63-64`), built from the checkout and reading
  the platform layer only (`CLAUDE.md:195-196`), plus four `varchar(16)` labels for code-defined workers
  (`db/migrations/versions/0005_run_artifact_versions.py:41-51`). A tenant's Studio version is data in
  PostgreSQL, and neither can pin it.
- Hashing today is `json.dumps(sort_keys=True)` in `executor.canonical_hash`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:69-73`) and in the release manifest ref
  (`scripts/release_manifest.py:249-254`). The research measured it disagreeing with RFC 8785 on `1.0`, on
  non-BMP key order and on large integers, and `jsonb::text` is not canonical either. RFC 8785 does not
  normalize Unicode (section 3.1, https://www.rfc-editor.org/rfc/rfc8785, read 2026-10-22) while Vietnamese
  arrives as NFC or NFD, so two identical-looking documents would hash apart and every evaluation keyed by
  the hash would go stale.
- Approvals park runs for days. Resolving "current" on resume would run a configuration nobody evaluated,
  and LangGraph completes silently when a parked node was removed (measured by the workflow-engine research
  on 2026-10-22).
- The kernel imports nothing outside the standard library (`pyproject.toml:251-254`).

## Decision

1. **One envelope for every kind.** `studio.artifacts` holds `tenant_id`, `id` (UUIDv7, the portable id
   packages and promotion carry), `kind` (CHECK, one value per registered kind), `api_name`
   (`^[a-z][a-z0-9_]{1,62}$`, unique per tenant and kind among undeleted rows, immutable after the first
   publish), `owning_workspace_id` (composite FK to `platform.workspaces (tenant_id, id)`, which gains
   `uq_workspaces_tenant_id_id`), `labels`, `origin` (pack provenance), `last_version_no`, `row_version` and
   `deleted_at`. `studio.artifact_versions` holds `artifact_id`, `version_no` (taken from `last_version_no`
   at submit and never reused), `document_schema` (`^dw\.[a-z_]+/v[0-9]+$`, that is `dw.<kind>/vN`),
   `document` (a jsonb object of at most 1 MiB with `CHECK (document::text IS NFC NORMALIZED)`),
   `content_hash`, `definition_hash`, `based_on_version_id` and `change_note`. Rows are tenant-wide with
   tenant-only RLS; `owning_workspace_id` is data that role depth reads (ADR 0104). A kind is an
   `ArtifactKindRegistry` entry at the composition root (document model, all-errors validator, pure
   dependency extractor, publish service), never a table family, and a test asserts the registry's kinds
   equal the CHECK's values read from `pg_constraint`. There is no `studio.agent_versions`,
   `studio.workflow_versions` or `studio.tool_versions`.
2. **"Live" is stored once.** Content changes only in `draft` (one draft per artifact, saved with
   `row_version`; a stale save is 409 `stale_version`). The `stage` column and its guard trigger belong to
   ADR 0120; "live" is that stage, with one partial unique index per artifact (`WHERE stage = 'live'`), so
   there is no `active_version_id` pointer.
3. **One canonical function.** `dw_kernel.canonical` is the only producer of Studio hashes. `ensure_hashable`
   refuses floats, NaN, Infinity, integers outside plus or minus (2^53 - 1), non-string keys, lone surrogates
   and text not in NFC; `canonical_bytes` writes RFC 8785 (JCS) bytes; `content_hash` returns
   `sha256:<64 hex>`. Hashed documents carry non-integers as `Decimal` strings, and the function hashes what
   the application validated, never `jsonb::text`. `rfc8785==0.1.4` is a test-only differential oracle with
   the RFC's float-free vectors. `executor.canonical_hash` stays unchanged (it keys the side effects of runs
   in flight, ADR 0108), and a test asserts that `canonical_bytes` and the release manifest ref agree on
   `contracts/release/manifest.json`.
4. **The definition hash covers the closure.** At submit the kind's extractor computes the version's
   closure: each pinned component as `(kind, key, version, content_hash)`, platform components with their
   release-manifest checksum. Its canonical hash is the `definition_hash`, fixed at submit, and the closure
   body is stored once per hash in `studio.definition_manifests (tenant_id, hash, body, created_at)`.
5. **One dependency index.** `studio.dependencies` is written in the same submit transaction:
   `from_version_id` and `from_artifact_id` (FK CASCADE), `to_kind` (CHECK `artifact`, `field`,
   `picklist_value`, `platform_artifact`, `connector`, `mcp_tool`, `binding`, `node_type`), `to_key`,
   `to_version`, `to_hash`, typed backstops `to_artifact_id`, `to_version_id` and `to_field_id` (each FK ON
   DELETE RESTRICT, each indexed), `usage` (`read`, `write`, `compare`, `invoke`, `bind`, `display`) and
   `path` (a JSON pointer), indexed on `(tenant_id, to_kind, to_key)`. It is the one source for where-used,
   delete protection, drift and a run's closure. A trigger refuses a soft delete of a target another
   artifact's version depends on, answered 409 `conflict` with `details.reason_code` `artifact_in_use`
   (the FK alone cannot see a soft delete); where-used names only what the caller may read and counts the
   rest. Drafts compute their dependencies on demand with the same extractor.
6. **Every run pins one run manifest.** `platform.worker_runs.run_manifest_hash` (required for every run with
   a Studio root; FK `(tenant_id, run_manifest_hash)` ON DELETE RESTRICT) names a content-addressed
   `dw.run_manifest/v1` stored once in `platform.run_manifests` (primary key `(tenant_id, hash)`, inserted
   with `ON CONFLICT DO NOTHING`): release manifest ref, run mode (ADR 0111), root (kind, artifact id,
   `version_no`, `definition_hash`), closure, overlay entries (layer `platform` or `tenant`, config version
   id, hash), binding entries (ADR 0110), object schema versions and an engine section.
   `platform.run_manifest_keys`, with FK RESTRICT to `studio.artifact_versions` and
   `platform.config_versions`, keeps anything a retained run pinned from being purged. A manifest holds no
   secret. `effective_hash` is the `definition_hash` plus the overlay entries, and evaluation evidence is
   keyed by it (ADR 0120).
7. **A Studio run resolves only what it pinned.** Inside a Studio run a `PinnedResolver` answers from the
   manifest alone; an unpinned key raises `ConfigError`; a resume in any process rebuilds from the
   manifest's immutable rows, extending `hosts()` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:132`)
   to database-backed versions.
8. **The engine is pinned too.** The engine section pins `compiler_version`, each node's `type@major`, the
   state-schema hash, the storage format, the LangGraph version, the CEL library `dw.cel/v1` (ADR 0114) and
   the model route (ADR 0118). Five checks run before every resume or re-claim: the pinned node types and
   compiler are registered in this build; the parked node exists in the pinned graph and equals
   `run_waits.node_id`; the state-schema hash matches; the storage format is readable; the resume value is a
   non-empty envelope. A failure parks the run as `blocked` with `error.code` `incompatible_resume` and
   audit `run.blocked`.
9. **Children are pinned, never followed.** Sub-workflow and agent-node references are pinned in the
   version's closure at submit and stay pinned when it is published; drift proposes an update and never
   follows the child's live version.

## Alternatives considered

- **Per-kind version tables** (`studio.agent_versions`, `studio.workflow_versions`, and `studio.tools` with
  `studio.tool_versions`, as planning proposed). Rejected: three copies of one column contract, three
  triggers, and polymorphic foreign keys from the dependency index.
- **An `active_version_id` pointer beside the stage.** Rejected: two stored answers to "which version runs"
  (failure-modes #2).
- **Hashing `jsonb::text` or `json.dumps` output.** Rejected: key order and number forms differ (measured).
  `rfc8785` at runtime would break the kernel's stdlib-only contract and tie every hash to a quiet 0.x
  package (0.1.4 dates from 2024-09-27, https://pypi.org/project/rfc8785/, read 2026-10-22).
- **Hashing the document alone.** Rejected: a changed dependency would not invalidate evaluation evidence.
- **Resolving overlays live during a run.** Rejected: a resume after an override would run something nobody
  evaluated. Tenant layers in the release manifest would break the inventory rule (`CLAUDE.md:195-196`), and
  more `varchar(16)` run columns cannot hold refs or hashes.

## Consequences

- tenant-config owns the envelope, the canonical kernel, the dependency index and the run manifest;
  agent-builder, workflow-engine and tools-and-skills register kinds and create no version tables. Every kind
  ships an extractor fixture test: break the extractor, and the test turns red.
- custom-objects' field delete gate (ADR 0107) and agent-lifecycle's drift findings read
  `studio.dependencies`; every Studio resolution takes the run's manifest, not only the tenant.
- Migrations: Alembic revisions create the envelope tables, `studio.dependencies`,
  `studio.definition_manifests`, `platform.run_manifests` and `platform.run_manifest_keys`, and add
  `platform.worker_runs.run_manifest_hash` and `uq_workspaces_tenant_id_id`, each with RLS and grants that
  `test_rls_coverage.py` and `test_privileges.py` assert. Offboarding purges `studio.dependencies` before
  `studio.artifacts` before `studio.artifact_versions`, and `worker_runs` before `run_manifests`.
- Tests that must exist: the registry-equals-CHECK test; an UPDATE of a non-draft document is refused; a soft
  delete of a depended-on target answers 409; a run asking for an unpinned key fails; each of the five
  resume checks, removed, lets an incompatible resume through and turns its test red.
- Run admission gains one insert pair (target 20 ms p95, to measure). Model profiles carry floats
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54-55`) and must move to
  `Decimal` before they can be hashed tenant configuration. A second-language verifier can reproduce every
  hash.
- Contradicts `CLAUDE.md:63-64` ("a release manifest pins the set a run used"), worth reopening because a
  Studio version is tenant data outside the repository-derived release manifest: the release manifest keeps
  pinning the platform layer, and a Studio run also pins its run manifest and definition hash. It also
  refines `CLAUDE.md:182-184` (every versioned artifact resolves through `TenantOverlay`): Studio artifacts
  have no platform layer to fall back to and resolve through the run manifest. Both amendments are owed on
  acceptance. Keeps `CLAUDE.md:195-196`.
- si-platform (D5): diverges from its per-engine version tables (`si.approval_versions`); ports from
  `docs/adr/0044-approval-runs-narrowed-by-the-record-workspace-history-append-only-unpartitioned.md` the
  CHECK read back against the enum and version numbers never reused; re-derives the dependency index (si
  has none) with the response pattern of `docs/adr/0041-references-checked-and-on-delete-enforced-by-the-engine.md`
  (counts, never records).

## Open

1. **One envelope with ADR 0120's stage contract and no `active_version_id`**, instead of per-kind version
   tables (DO-05, Đạt).
2. **API names immutable after the first publish** (DO-08, the requester). Provisional agent call of
   2026-10-23, option (a): immutable, so a rename is a new Studio artifact plus a migration. If wrong, an
   alias map gives one Studio artifact two names in packages and in the dependency index.
3. **Retention of retired versions, run manifests and abandoned proposals** (DO-52, counsel and Đạt):
   proposed run manifests and pinned versions kept with their runs' retention, open proposals 14 days.
4. **Children pinned or following live** (DO-30, the requester). Provisional agent call of 2026-10-23,
   option (a): pinned at submit, drift proposes the update; decision 9 rests on it.
5. **Which run-time-resolved dependencies make a live version "not evaluated"**: a tenant override, an MCP
   definition, knowledge content, a provider's model alias (FOG-66, a grilling owed by agent-lifecycle).
