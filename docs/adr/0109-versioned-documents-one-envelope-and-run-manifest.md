---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
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
- A run's provenance today is the release manifest (`CLAUDE.md:70-71`), built from the checkout and reading
  the platform layer only (`CLAUDE.md:231-232`), plus four `varchar(16)` labels for code-defined workers
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
   packages and promotion carry), `kind` (a foreign key to the reference table `studio.artifact_kinds`, one row
   per registered kind, `ON DELETE RESTRICT`), `api_name` (`^[a-z][a-z0-9_]{1,39}$` for every kind, the rule
   ADR 0107 uses for objects and fields, so generated tool names stay within 64 characters; unique per tenant and
   kind among undeleted rows, immutable after the first publish), `owning_workspace_id` (composite FK to
   `platform.workspaces (tenant_id, id)` through `uq_workspaces_tenant_id_id`, which org-and-principals/01 creates,
   ADR 0102, `ON DELETE RESTRICT`), `labels`, `origin` (pack provenance), `last_version_no`, `row_version` and
   `deleted_at`. `studio.artifact_versions` holds `artifact_id` (composite FK to `studio.artifacts (tenant_id, id)`,
   `ON DELETE CASCADE`), `version_no` (taken from `last_version_no` at submit and never reused), `document_schema`
   (`^dw\.[a-z_]+/v[0-9]+$`, that is `dw.<kind>/vN`),
   `document` (a jsonb object of at most 1 MiB with `CHECK (document::text IS NFC NORMALIZED)`),
   `content_hash`, `definition_hash`, `based_on_version_id` and `change_note`. Rows are tenant-wide with
   tenant-only RLS; `owning_workspace_id` is data that role depth reads (ADR 0104). A foreign key check does not pass
   through RLS, so every foreign key from a table of this ADR to a tenant table is composite, `(tenant_id, <column>)`
   to a key of its target that carries `tenant_id`: `UNIQUE (tenant_id, id)` where the target is keyed by id (here
   `uq_artifacts_tenant_id_id` and `uq_artifact_versions_tenant_id_id`; the revision that adds such a foreign key adds
   that UNIQUE where its target lacks it), the primary key `(tenant_id, hash)` of a content-addressed one. A one-column
   key would let one tenant's row point at another's. A kind is an
   `ArtifactKindRegistry` entry at the composition root (document model, all-errors validator, pure
   dependency extractor and publish hook, each supplied by the kind's owner, the hook called by agent-lifecycle
   inside ADR 0120's publish transaction), never a table family; the ticket that registers a kind inserts its one
   row of `studio.artifact_kinds` in its own revision, so no two tickets edit one CHECK, and a test asserts the
   registry's kinds equal that table's rows. There is no `studio.agent_versions`, `studio.workflow_versions` or
   `studio.tool_versions`.
2. **"Live" is stored once.** Content changes only in `draft` (one draft per artifact, saved with
   `row_version`; a stale save is 412 `precondition_failed` with `details.reason_code` `stale_version`, as
   ADR 0108 decision 3 answers an `If-Match` mismatch). Submitting a draft is conditional the same way: the
   submit route takes the draft's ETag in `If-Match`, answers a mismatch 412 `precondition_failed` with
   `stale_version` and a missing one 428 `precondition_required`, and seals only the `row_version` that ETag
   names. The `stage` column and its guard trigger belong to ADR 0120; "live" is that stage, with one partial
   unique index per artifact (`WHERE stage = 'live'`), so there is no `active_version_id` pointer.
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
   `from_version_id` and `from_artifact_id` (composite FKs, `ON DELETE CASCADE`), `to_kind` (CHECK `artifact`,
   `field`, `picklist_value`, `platform_artifact`, `connector`, `mcp_tool`, `binding`, `node_type`), `to_key`,
   `to_version`, `to_hash`, typed backstops `to_artifact_id`, `to_version_id` and `to_field_id` (each a composite FK
   `ON DELETE RESTRICT`, indexed on `(tenant_id, <column>)`), `usage` (`read`, `write`, `compare`, `invoke`,
   `bind`, `display`) and `path` (a JSON pointer), indexed on `(tenant_id, to_kind, to_key)`. It is the one source
   for where-used, delete protection, drift and a run's closure. A trigger refuses a soft delete of a target another
   artifact's version depends on, answered 409 `conflict` with `details.reason_code` `artifact_in_use`
   (the FK alone cannot see a soft delete); where-used names only what the caller may read and counts the
   rest. Drafts compute their dependencies on demand with the same extractor.
6. **Every run pins one run manifest.** `platform.worker_runs.run_manifest_hash` (required for every run with
   a Studio root; FK `(tenant_id, run_manifest_hash)` ON DELETE RESTRICT) names a content-addressed
   `dw.run_manifest/v1` stored once in `platform.run_manifests` (primary key `(tenant_id, hash)`, inserted
   with `ON CONFLICT DO NOTHING`): release manifest ref, run mode (ADR 0111), root (kind, artifact id,
   `version_no`, `definition_hash`), closure, overlay entries (layer `platform` or `tenant`, config version
   id, hash), binding entries (the binding-set version, each connection id with the `secret_version` pinned for
   each of that connection's secret fields, a secret's version being numbered per subject and field (ADR 0115
   decision 1), and a hash of each variable value, never the value; ADR 0110), object schema versions and an
   engine section.
   A `simulate` run, and a run of no other mode, may have a draft as its root, requested only once the checks
   that submit runs for the draft's kind (ADR 0112 decision 3 for a workflow, ADR 0117 decisions 2, 4 and 7 for
   an agent) pass on the draft's content. `RunRequestService`, the one door (ADR 0113 decision 1), runs those
   checks on that content itself, whichever route asked, before it builds a run manifest or inserts a run row,
   and an error refuses the request, so no caller reaches a draft run unchecked (failure-modes #5). The run's
   root then records the version id, the stage `draft` and a provisional hash of that content, computed when the
   request is accepted the way decision 4 computes `definition_hash`.
   `platform.run_manifest_keys` names each version a retained run pinned in exactly one of `artifact_version_id`
   and `config_version_id` (CHECK `num_nonnulls(artifact_version_id, config_version_id) = 1`), each a composite FK
   `ON DELETE RESTRICT` to `studio.artifact_versions` or `platform.config_versions`, so nothing such a run pinned
   is purged. A manifest holds no secret. `effective_hash` is the `definition_hash` plus the overlay entries, and
   evaluation evidence is keyed by it (ADR 0120).
7. **A Studio run resolves only what it pinned.** Inside a Studio run a `PinnedResolver` answers from the
   manifest alone; an unpinned key raises `ConfigError`; a resume in any process rebuilds from the
   manifest's immutable rows, extending `hosts()` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:132`)
   to database-backed versions.
8. **The engine is pinned too.** The engine section pins `compiler_version`, each node's `type@major`, the
   state-schema hash, the storage format, the LangGraph version, the CEL library `dw.cel/v1` (ADR 0114) and
   the model route (ADR 0118). Six checks run before every resume or re-claim: the pinned node types and
   compiler are registered in this build; the parked node exists in the pinned graph and equals
   `run_waits.node_id`; the state-schema hash matches; the storage format is readable; the resume value is a
   non-empty envelope; and for a draft root (decision 6), the root version's content, hashed again the same
   way, still equals the pinned provisional hash. A failure parks the run as `blocked` with `error.code`
   `incompatible_resume` and audit `run.blocked`.
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
  evaluated. Tenant layers in the release manifest would break the inventory rule (`CLAUDE.md:231-232`), and
  more `varchar(16)` run columns cannot hold refs or hashes.

## Consequences

- tenant-config owns the envelope, the canonical kernel, the dependency index and the run manifest, save decision 5's
  `to_field_id` and its composite foreign key, which custom-objects adds in the revision that creates
  `studio.field_defs`, the table that key references; agent-builder, workflow-engine and tools-and-skills register kinds
  and create no version tables. Every kind ships an extractor fixture test: break the extractor, and the test turns red.
- custom-objects' field delete gate (ADR 0107) and agent-lifecycle's drift findings read
  `studio.dependencies`; every Studio resolution takes the run's manifest, not only the tenant.
- Migrations: Alembic revisions create `studio.artifact_kinds`, the envelope tables, `studio.dependencies`,
  `studio.definition_manifests`, `platform.run_manifests` and `platform.run_manifest_keys`, and add
  `platform.worker_runs.run_manifest_hash`, each tenant table with RLS and every table with the grants that
  `test_rls_coverage.py` and `test_privileges.py` assert; `uq_workspaces_tenant_id_id` comes from
  org-and-principals/01, not from here. Offboarding purges `studio.dependencies` before `studio.artifacts` before
  `studio.artifact_versions`, and `worker_runs` before `run_manifests`.
- `studio.artifacts`, `studio.artifact_versions`, `studio.dependencies`, `studio.definition_manifests`,
  `platform.run_manifests` and `platform.run_manifest_keys` are tenant-wide rows under the `CLAUDE.md:185` class that
  ADR 0100 records (A6), each listed with its reason in `test_rls_coverage.py`.
- Tests that must exist: the registry-equals-rows test; an UPDATE of a non-draft document is refused; a soft
  delete of a depended-on target answers 409; a run asking for an unpinned key fails; each of the six
  resume checks, removed, lets an incompatible resume through and turns its test red; a draft root requested
  for any mode but `simulate` is refused; a `simulate` request for a draft whose content fails the submit checks,
  sent to `RunRequestService` directly and not through a route, is refused.
- Run admission gains one insert pair (target 20 ms p95, to measure). Model profiles carry floats
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54-55`) and must move to
  `Decimal` before they can be hashed tenant configuration. A second-language verifier can reproduce every
  hash.
- Contradicts `CLAUDE.md:70-71` ("a release manifest pins the set a run used"), worth reopening because a
  Studio version is tenant data outside the repository-derived release manifest. The amendment: every run pins
  what it used, the release manifest pinning the platform layer, and a run with a Studio root also pinning one run
  manifest (`platform.worker_runs.run_manifest_hash`) with its definition hash, the tenant config versions and
  binding values it resolved, and its engine, from which alone it resolves, on resume too. It also refines
  `CLAUDE.md:214-216` (every versioned artifact resolves through `TenantOverlay`): a Studio run resolves every
  artifact it uses, platform-layer components in its closure included, only from its run manifest, and nothing
  falls back at run time; an artifact a tenant builds has no platform layer, while a tenant's own version of a
  platform artifact still resolves through `TenantOverlay` outside a run, its tenant layer the approved
  `platform.config_versions` row (ADR 0110). Both amendments apply on acceptance. Keeps `CLAUDE.md:231-232`.
- si-platform (D5): diverges from its per-engine version tables (`si.approval_versions`); ports from
  `docs/adr/0044-approval-runs-narrowed-by-the-record-workspace-history-append-only-unpartitioned.md` the
  kind list read back from the database against the code (here the rows of `studio.artifact_kinds`, there a CHECK)
  and version numbers never reused; re-derives the dependency index (si
  has none) with the response pattern of `docs/adr/0041-references-checked-and-on-delete-enforced-by-the-engine.md`
  (counts, never records).

## Open

1. **One envelope with ADR 0120's stage contract and no `active_version_id`**, instead of per-kind version
   tables (DO-05, Đạt). Answered 2026-10-23: one envelope (DO-05 (a)); Đạt confirmed the agent-lifecycle line
   that records it.
2. **API names immutable after the first publish** (DO-08, the requester). Provisional agent call of
   2026-10-23, option (a): immutable, so a rename is a new Studio artifact plus a migration. If wrong, an
   alias map gives one Studio artifact two names in packages and in the dependency index. Answered 2026-10-23:
   immutable after the first publish, under the `{1,39}` rule of decision 1 (DO-08 (a)).
3. **Retention of retired versions, run manifests and abandoned proposals** (DO-52, counsel and Đạt):
   proposed run manifests and pinned versions kept with their runs' retention, open proposals 14 days.
   Answered 2026-10-23, provisionally: a store that ADR 0122's decision 7 does not list takes DO-52's own terms,
   these above, as UNVERIFIED values in the retention policy; counsel confirms them before shadow running
   (DO-52 (a)).
4. **Children pinned or following live** (DO-30, the requester). Provisional agent call of 2026-10-23,
   option (a): pinned at submit, drift proposes the update; decision 9 rests on it. Answered 2026-10-23:
   pinned at submit (DO-30 (a)).
5. **Which run-time-resolved dependencies make a live version "not evaluated"**: a tenant override, an MCP
   definition, knowledge content, a provider's model alias (FOG-66, a grilling owed by agent-lifecycle).
   Answered 2026-10-23 for a tenant override: evaluation evidence is keyed by the effective hash, which an
   override changes, so evidence keyed by the old hash no longer counts (ADR 0110, ADR 0120). The other three
   stay with FOG-66.

## Acceptance (2026-10-23)

- Status Accepted by Đạt with evidence keyed by the effective hash (decision 6), which ADR 0120 follows.
- Decision 1: `api_name` takes ADR 0107's `{1,39}` rule for every kind; `kind` references `studio.artifact_kinds`
  instead of a CHECK (OPS-b edge 4); `uq_workspaces_tenant_id_id` is created by org-and-principals/01, not here
  (OPS-a.2).
- Decision 6: the binding entries name what the run manifest holds and never a value (ADR-0109+ADR-0120).
- Consequences: the `uq_workspaces_tenant_id_id` creation dropped from Migrations; the envelope's tables named as
  tenant-wide (A6); the amendments to `CLAUDE.md:70-71` and `:182-184` restated so platform components in a closure
  resolve from the run manifest too (DO-05 (a)).
- Open 1, 2 and 4 answered; Open 3 answered provisionally (DO-52 (a)); Open 5 answered for tenant overrides.

## Amendments (2026-10-24)

- Third consistency check (round 4), Đạt's V4.6: decision 2's stale draft save is 412 `precondition_failed` with
  `details.reason_code` `stale_version`, as ADR 0108 decision 3 answers an `If-Match` mismatch, no longer 409
  (F:ADR-0109~tenant-config:R2.5); the status stays Accepted.
- Third consistency check (round 4), second pass, the planner's provisional calls: decision 6 lets a `simulate`
  run, and a run of no other mode, take a draft as its root under a provisional hash once the checks that submit
  runs pass on the draft's content, and decision 8 adds a sixth check before a resume, the draft's content still
  hashing to that pin, else `incompatible_resume`, which completes Đạt's V4.4 (if it is wrong, both sentences
  leave this ADR and the specs cite V4.4 alone); decision 2 makes the submit conditional on the draft's
  `If-Match`, 412 with `stale_version` on a mismatch and 428 `precondition_required` without one (V4.6, ADR 0108
  decision 3; if it is wrong, a submit seals whatever draft was saved last); decision 1 names the publish hook a
  kind's registry entry carries, which agent-lifecycle calls in the publish transaction, so that no kind has a path
  of its own to live.
- Third consistency check (round 4), third pass, the planner's provisional calls: decision 1 gives `kind` and
  `owning_workspace_id` their `ON DELETE RESTRICT` (`CLAUDE.md`, Data model rules) and makes every foreign key from
  this ADR's tables to a tenant table composite, `artifact_id` and the keys of decisions 5 and 6 included, because a
  foreign key check does not pass through RLS; decision 6 makes `platform.run_manifest_keys` name exactly one of
  `artifact_version_id` and `config_version_id`, as tenant-config states, and pins a `secret_version` per
  connection and field, the unit in which ADR 0115 decision 1 numbers a secret's versions; and decision 6 has
  `RunRequestService` run the submit checks on a draft's content itself, whichever route asked, with a test that
  calls the door directly, so a check held only by the test-run route cannot be bypassed from another caller
  (failure-modes #5; if it is wrong, the door refuses a draft root whose request carries no passing check result
  instead of running the checks). The second pass's line above now names only the publish hook that agent-lifecycle
  calls, no longer the per-kind path it replaced, `LifecycleService` being the one writer of `live` (ADR 0120
  decision 1).
- Third consistency check (round 4), fourth pass, the planner's provisional calls: decision 6 names by kind the
  checks a draft passes before it roots a `simulate` run, ADR 0112 decision 3 for a workflow and ADR 0117 decisions 2,
  4 and 7 for an agent, whose draft ADR 0117 decision 5 now compiles for such a run (if it is wrong, only a workflow
  draft is simulated and the sentence names ADR 0112 alone); Consequences leave `to_field_id` and its composite
  foreign key to custom-objects, which adds them with `studio.field_defs`, the table they reference, as tenant-config
  states (if it is wrong, tenant-config adds them in a revision after custom-objects' own).
