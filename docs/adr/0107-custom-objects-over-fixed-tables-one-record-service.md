---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/custom-objects/spec.md
    - ../../db/migrations/sql/0001_platform_grants.sql # dw_app holds DML and no CREATE
    - ../../db/migrations/sql/0013_partition_maintenance.sql # ensure_time_partitions, generalised here
    - ../../db/migrations/versions/45dc1b5e0125_platform_policy_overrides.py # tenant-only precedent
---

# 0107. Tenant objects are metadata over fixed migration-created tables, and every record read and write goes through one RecordService

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block). It rests on the
requester's D1 (a workspace owns data; object definitions are tenant-wide), D2 (business admins build
objects without code), D5 (si-platform as reference and selective port source) and D12 (scale, 2026-10-23).

## Context

The Marketing slice (D4) needs records a tenant shapes, Lead and Campaign first, written by people, workflow
nodes, agents, imports and domain packs. The platform has no records engine, and four facts rule out the
obvious designs (measured by the Studio research on 2026-10-22 on PostgreSQL 16.15 and 18.6, as a non-owner
`NOBYPASSRLS` role under FORCE RLS with this repository's policy shape):

- Under RLS the planner uses an index for a user predicate only when its operator is LEAKPROOF; jsonb
  operators, `numeric`, `LIKE`/`ILIKE`, trigram, full text, arrays, `lower()` and `unaccent()` are not
  (https://www.postgresql.org/docs/current/ddl-rowsecurity.html, read 2026-10-22). On a 1M-record tenant
  jsonb equality took 1.2 to 1.9 s and GIN containment 1.1 s, typed slots 0.13 to 0.9 ms; trigram `ILIKE`
  ran 374 to 403 ms as a seq scan, GIN tsvector 781 ms against 0.8 ms.
- Runtime DDL is closed: `dw_app` holds DML and no `CREATE` (`db/migrations/sql/0001_platform_grants.sql:27-46`),
  `CREATE INDEX CONCURRENTLY` is refused inside a transaction or a function, and a table made at runtime is
  invisible to the catalog tests CI runs (failure-modes #0). Twenty's runtime DDL shipped deadlocks and a
  56-minute outage in September 2026 (https://github.com/twentyhq/twenty/issues/26895, read 2026-10-22).
- A rule enforced on one path is bypassed from another (failure-modes #5), and D3(d) applies field security
  "to agents and search results too".
- D12 answers DO-14 and fixes the scale: 10 million records per object, 50 million per tenant, 5,000 users,
  200 workspaces, tree depth 6; a tenant beyond that moves to its own cell. Every benchmark is sized to it.

## Decision

1. **Definitions are tenant-wide metadata; records live in fixed tables.** `studio.object_defs`,
   `studio.field_defs` and `studio.picklist_options` have no `workspace_id`, RLS ENABLE and FORCE, and one
   tenant policy each in the InitPlan form
   `tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`. `field_defs.id` is the
   immutable field key that slot maps, history, the dependency index, packages and generated tools use, and
   `api_name` (`^[a-z][a-z0-9_]{1,39}$`) is immutable from creation. `studio.records` has system columns (`id` UUIDv7, `object_id`, owning `workspace_id`, record owner,
   `name`, `name_key`, `version`, `create_key`, `created_*`, `updated_*`, `deleted_*`), a `data jsonb`
   capped at 32 KB for unindexed fields keyed by a per-object `field_no` never reused, and a fixed set of
   typed slots, each with the partial btree
   `(tenant_id, object_id, <slot>, id) WHERE <slot> IS NOT NULL AND deleted_at IS NULL`. Slot families and
   their only types: `t` text `COLLATE "vi-VN-x-icu"` (at most 255 characters,
   `CHECK (octet_length(tNN) <= 1024)`), `i` bigint (exact numbers and money scaled by 10^scale, scale 0 to
   6), `f` float8, `d` date, `z` timestamptz, `b` boolean; from P2 `u` unique text, `l` lookup and `m`
   master-detail uuid. No `numeric`, `jsonb` or array holds anything filterable. The proposed P1 set per
   object, `t01-t24, i01-i12, f01-f08, d01-d08, z01-z08, b01-b08`, is fixed by custom-objects/01. Only
   slot-backed fields filter and sort. No table, column or index is created at runtime.
2. **Hash partitions by tenant, if the measurement holds.** As D12 asks, `studio.records` is
   `PARTITION BY HASH (tenant_id)` with modulus 8 from its first revision (`studio.records_p0` to
   `studio.records_p7`, each ENABLE and FORCE with the parent's policies), provided custom-objects/01 keeps
   planning p95 at or under 5 ms for a three-predicate query with every slot index present and
   `CacheMemoryContext` at or under 64 MB per backend; otherwise it ships unpartitioned with the same
   composite keys. Either way the primary key is `(tenant_id, id)`, every UNIQUE and foreign key carries
   `tenant_id`, and the query compiler states `tenant_id = :tenant` in every statement (RLS still decides;
   the predicate lets the planner prune and pick the index).
3. **One RecordService.** REST routes, workflow data nodes (workflow-nodes' `RecordsPort`), agent object
   tools (tools-and-skills' `ObjectDataPort`, run as the caller), import, export and bulk operations, purge
   lanes and domain-pack seeding all call one service; each consumer declares its narrow Protocol and the
   composition root satisfies it with that service. Its pipeline is fixed: authorize the object action; take
   `pg_advisory_xact_lock_shared` on (tenant, object) and snapshot `schema_version`; coerce and normalize
   (NFC, lower-case e-mail, E.164 phone, scaled integers); required, length, picklist and lookup checks; CEL
   validation rules (ADR 0114); field security (ADR 0106); record access (ADR 0105); write the record, side
   tables and search terms; history; outbox; audit; `create_key` idempotency
   (`UNIQUE (tenant_id, object_id, create_key)`). Every error of one save comes back at once in `errors[]`
   (ADR 0108). In `simulate`, and in v1 `test`, it validates fully and returns the would-be record without
   writing (ADR 0111). No business-hook registry in v1. An architecture test fails any SQL naming
   `studio.records` or a side table outside the records adapter module.
4. **Lookups are composite foreign keys the database checks.** An `lNN` slot references
   `studio.records (tenant_id, id)` through `(tenant_id, lNN)` with `ON DELETE SET NULL (lNN)`; an `mNN`
   slot does the same with `ON DELETE CASCADE`. A lookup into another tenant cannot exist.
5. **Field keys are immutable.** Adding an optional field is free (`schema_version` plus 1; the smallest
   free slot, taken under a per-tenant advisory lock); a retype is expand, migrate, contract with a new field
   key and a gated cutover; renaming `api_name` or moving a lookup's target is refused. A field delete is
   refused while any live version, run in flight, list view, validation rule, sharing rule or layout
   references it, read from the dependency index (ADR 0109) plus a service check for what the index cannot
   see; then soft delete, then purge. A slot is released only after a verified purge: the field row moves
   from `deleted` to `purging`, a lane nulls the slot in batches, and under the exclusive
   `pg_advisory_xact_lock` on (tenant, object) an index-backed probe proves no value remains before the row
   becomes `purged`. A reused slot belongs to a new key.
6. **Record history is its own table.** `studio.record_history` is append-only and
   `PARTITION BY RANGE (occurred_at)` by month with a DEFAULT partition: one row per changed tracked field
   (`field_defs.track_history`, capped per plan) with the picklist label snapshot and values capped at 5 KB
   plus a `truncated` flag. `dw_app` holds SELECT, INSERT and DELETE, never UPDATE; reads go through
   RecordService with field security; the tenant's retention lane and a data-subject erasure delete it.
   Audit events `studio.record.*` carry field keys and versions, never values.
7. **Vietnamese text.** RecordService NFC-normalizes every text value; text slots and `name` sort with
   `COLLATE "vi-VN-x-icu"` and no fallback. Search is accent-free word prefix: an IMMUTABLE SQL wrapper
   `studio.search_key(text)` over `unaccent` feeds a STORED `name_key COLLATE "C"` and
   `studio.record_terms (tenant_id, object_id, record_id, term)`, indexed on
   `(tenant_id, object_id, term, record_id)`; the query side calls the same function. No trigram or
   full-text index on records.
8. **One generic records API.** `GET|POST /api/v1/studio/objects/{api_name}/records` and
   `GET|PATCH|DELETE .../records/{record_id}`, with custom methods as `POST` sub-resources (`query`,
   `batch-create`, `upsert`, `{record_id}/assign`, `{record_id}/undelete`, `{record_id}/expunge`, ADR 0108).
   `GET /api/v1/studio/objects/{api_name}/describe` answers for the caller: only fields the caller may read,
   and which of them filter and sort. Tenant fields sit under `fields`; a lookup is `{id, name, readable}`
   with `name: null` when the target is unreadable. Another tenant's record and a record the caller cannot
   read both answer 404; a readable record the caller cannot change answers 403. A support context reaches
   none of these routes until one is added to `SUPPORT_ALLOWED_ROUTES`
   (`apps/api/src/dw_api/bootstrap/wiring.py:110`) with a negative test.

## Alternatives considered

- **Runtime DDL per object.** Rejected: the application would need DDL rights, and `db/migrations` would
  stop being the one owner of the schema (`CLAUDE.md:89`).
- **One shared value table (EAV), or typed pivot index tables.** Rejected: every filter becomes a join and
  no value has a typed index; the pivot measured 3 times the index storage and 3.4 times the write cost.
- **A jsonb document with GIN or expression indexes.** Rejected: no typed range or sort, indexes unused
  under RLS, and a planner blind to selectivity.
- **A record path per channel, or validation in database triggers.** Rejected: agents and workflows would
  bypass field security (failure-modes #5), and PL/pgSQL cannot apply field security per user.
- **Trigram or full-text search.** Rejected: far slower under RLS (measured above), weak on diacritics.

## Consequences

- Plan limits cap objects, fields and tracked fields below the slot count custom-objects/01 fixes, which a
  partial UNIQUE on live slot assignments enforces. Every Studio writer of records (workflow nodes, object
  tools, packs, lanes) depends on a narrow Protocol the one RecordService satisfies, never on the tables.
- Migrations: Alembic revisions create the metadata tables, `studio.records` with its partitions,
  `studio.record_terms` and later `studio.record_history`, each with RLS, policies and grants in the same
  revision. `CREATE EXTENSION unaccent` is the repository's first extension (whether `dw_migrator` can create
  it is unverified, FOG-55). `platform.ensure_time_partitions`, which names only `audit_events`
  (`db/migrations/sql/0013_partition_maintenance.sql:123`), becomes one function over a constant table of
  parents, so record history and the usage ledger (ADR 0121) use it too.
- Tests that must exist: the architecture test above; `test_rls_coverage.py` and `test_privileges.py` green
  with schema `studio`, each partition's policy compared with its parent's; two concurrent field additions
  never share a slot (removing the partial UNIQUE turns it red); the field type CHECK equals the code enum,
  as `packages/python/dw_memory/tests/integration/test_fixed_set_checks_db.py:133` does; tenant B's describe
  of tenant A's object answers 404; every compiled filter and sort passes the plan-shape test of ADR 0108.
- Harder: about 80 partial indexes on one table; reusing a slot needs a purge; exact numbers stop at 18
  digits with scale at most 6; search is word-prefix only in v1; an ICU collation version change needs a
  REINDEX of collated indexes; formulas and roll-ups come later.
- Contradicts `CLAUDE.md:69-73` ("an AI platform, not a general application framework ... A CRUD-heavy
  application layer does not have to be Python"), worth reopening because Studio puts a records engine in
  the platform (stance S1); amended through ADR 0100 on acceptance.
- Contradicts `CLAUDE.md:163` ("Every tenant-scoped table has `tenant_id` and `workspace_id`."), worth
  reopening because definitions are tenant-wide by D1 and S3 while records keep an owning workspace;
  `platform.policy_overrides` is a tenant-only precedent. Amended through ADR 0100.
- Keeps `CLAUDE.md:89` ("The schema has one owner and it is `db/migrations`."), and clarifies `CLAUDE.md:250`:
  a HASH-partitioned table has no DEFAULT partition, which that line asks of append-only RANGE tables. The
  planning brief's route prefix `/api/v1/objects/...` gives way to `/api/v1/studio/objects/...` (ADR 0100).
- si-platform (D5): re-derives `docs/adr/0029-tenant-field-values-in-one-shared-table.md` and
  `docs/adr/0040-tenant-defined-custom-objects-on-si-data.md` with no `numeric` slots, every slot natively
  indexed (si indexes through a pivot), no workspace-scoped objects, Alembic and `dw_*` roles; diverges from
  `docs/adr/0041-references-checked-and-on-delete-enforced-by-the-engine.md` (the database checks lookups
  here); re-derives `docs/adr/0038-object-service-with-business-hooks.md` as this pipeline without hooks;
  ports `si_metadata/values.py`, `list_query.py`, `references.py` and the smallest-free-slot allocation.

## Open

1. **The storage model and its CLAUDE.md amendments** (DO-01, Đạt): tenant-wide definitions and a records
   engine in the platform.
2. **Hash partitions from the first revision with modulus 8, and PostgreSQL 16 in v1** (DO-15, Đạt), once
   custom-objects/01 (FOG-41) has measured planning time and relcache. D12 asks for partitions from the
   first revision; the unpartitioned form in decision 2 exists only for a failed measurement.
3. **Uniqueness scope of unique and external-id fields** (DO-35, Đạt with the requester): proposed
   object-wide, a duplicate answering 409 `duplicate_value` with the field pointer and no record id unless
   the caller can read the duplicate.
4. **What a validation rule means** (DO-37, the requester for the meaning, Đạt for the engine). Provisional
   agent call of 2026-10-23, option (a): a rule must hold (true means valid), written in CEL with
   si-platform's test vectors ported. If wrong, the evaluator's polarity and the builder's wording flip;
   the rule keeps its place in the pipeline.
