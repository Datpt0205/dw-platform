---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../packages/python/dw_platform/tests/integration/test_rls_coverage.py
    - ../../db/migrations/sql/0013_partition_maintenance.sql
    - ../../packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py
    - ../../packages/python/dw_knowledge/src/dw_knowledge/gateway.py
    - ../../.claude/plans/studio/record-access/spec.md
---

# 0105. PostgreSQL decides which records a principal reaches, through one RLS policy set over an in-database principal-scope closure, with grants that only add

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on the requester's D1
(workspaces own data and reach each other through permissions), D3 (record owner and default access, hierarchy, sharing rules and
manual sharing with expiry, field security), D5 (port si-platform's record access and RESTRICTIVE RLS in InitPlan form)
and D12 (the scale target), and on the provisional call on DO-11.

## Context

- **Record reach is an application roll-up today.** `tenants.record_visibility`
  (`db/migrations/sql/0001_platform_baseline.sql:409`) feeds `AccessContext.record_visibility` and `visible_owners`
  (`packages/python/dw_platform/src/dw_platform/application/access_context.py:43-50`, citing an "ADR-003" this
  repository does not have), stamped into runs (`apps/api/src/dw_api/bootstrap/container.py:223-226`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:289-294`). Every reader must remember the
  filter and the first that forgets leaks (failure-modes #5); a stamped reach outlives a revocation (failure-modes #7).
- **The database owns the neighbouring fact.** CLAUDE.md:67-107 admits a second language because tenant isolation lives
  in PostgreSQL and is tested from the catalog; record reach is the same kind of fact. PostgreSQL ORs permissive
  policies, ANDs restrictive ones and denies without a policy (https://www.postgresql.org/docs/current/ddl-rowsecurity.html,
  current version, cited 2026-10-22).
- **Measured in planning** (one laptop, PostgreSQL 16.15, 2M rows; to re-run before relying on it): predicates over
  typed record columns kept broad first pages under a millisecond where a per-record access table joined in the policy
  took 1.1-1.4 s; exceptions as an OR'd subquery took 855-898 ms where an indexable array on the record took 5-42 ms.
- **What would open a record table today.** A runtime partition gets a tenant-only policy and `dw_app` default
  privileges (`db/migrations/sql/0013_partition_maintenance.sql:63-83`); `app.workspace_scope` is set only by offboarding
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:51-54`, as CLAUDE.md:174-175 says);
  knowledge principals come from global role keys fixed at ingest (`packages/python/dw_knowledge/src/dw_knowledge/gateway.py:156-167`).
- **Prior art.** Dataverse privileges are cumulative ("another role can't hide a specific contact") and sharing is for
  exceptions (https://learn.microsoft.com/en-us/power-platform/admin/wp-security-cds, 2026-10-05). Salesforce documents
  recalculation cascades and ownership skew past 10,000 records (https://resources.docs.salesforce.com/256/latest/en-us/sfdc/pdf/draes.pdf,
  Summer '25). Zanzibar's "new enemy" problem is why revocation cannot wait for a rewrite
  (https://www.usenix.org/conference/atc19/presentation/pang, 2019).

## Decision

1. **One policy set per record table and partition.** `tenant_isolation_<t>` AS RESTRICTIVE FOR ALL with USING and WITH
   CHECK `tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`, plus PERMISSIVE
   `record_access_<t>_select`, `_insert`, `_update`, `_delete`, each `tenant AND (scope OR (actor_ok AND reach))`,
   rendered by one template module the migration and the catalog test share. Settings are read as sub-SELECTs and
   closure arrays as `(SELECT f())::uuid[]` (InitPlan form), through STABLE SECURITY INVOKER SQL functions with a fixed
   `search_path` that read only the caller's closure row and return an empty array when anything is missing. `dw_app`
   holds no privilege on a partition. Per-transaction settings: `app.tenant_id`, `app.user_id`, `app.workspace_scope`,
   and new `app.actor_kind` (`user`, `agent`, `workflow`) and `app.boundary_id`; an unknown actor kind reaches nothing.
2. **Reach is the union of five additive grants; nothing denies in v1.** (a) Per-object `default_access`: `private`
   (default), `public_read`, `public_read_write` (`ck_objects_default_access`), tenant-wide for every holder of the
   object's read (update) privilege, never granting delete, assign or share. (b) Depth (ADR-0104) over the record's
   owner (`owner_id`, `owner_kind` user or team) and owning workspace (`workspace_id`, matched through `access_key`,
   a stored column generated from object and owning workspace), unioned over every membership.
   (c) Hierarchy access, switchable per object (`grant_hierarchy boolean NOT NULL DEFAULT true`): a line manager holding
   read (update) on the object at `own` or more reads (updates) records owned by any transitive subordinate, never
   deleting, assigning or sharing them. (d) Manual shares of one record to a user, team, workspace or workspace
   sub-tree, read or edit, optionally until `expires_at`, needing the share privilege's reach (edit also the granter's
   edit reach); they survive a change of record owner and are listed in the assign dialog. (e) Sharing rules: a CEL
   condition over the object's fields (ADR-0114), a team, workspace or sub-tree target, read or edit, versioned, at most
   50 active per object. No role stands in for reach, `platform_admin` included. On assignment the assigner chooses
   whether the owning workspace moves, and the default keeps it (DO-11, provisional).
3. **Exceptions live on the record as grant keys.** `read_grants uuid[]`, `edit_grants uuid[]` (subset of read; at most
   200 keys, `ck_records_grants_bounded`) and `grants_valid_until`, the earliest manual-share expiry. A key is a user,
   team or workspace id, a sub-tree marker `md5('subtree:' || workspace_id::text)::uuid` or a sharing-rule version id;
   `studio.record_shares` is the source of manual shares. Only SECURITY DEFINER functions (`studio.share_record`,
   `studio.revoke_share`, `studio.assign_record`, the `record_sharing` lane's) write owner, owning workspace, object and
   grant columns; `dw_app` updates data columns only. Expiry is enforced at read time (early, never late); a rule grants
   through its version key, so deactivating it removes that key from every closure at the next statement (an access
   epoch bump), before the lane cleans records.
4. **One SQL function computes a principal's reach.** `studio.compute_principal_scope()` (tenant and principal from the
   settings, never arguments) reads input views shared with org-and-principals, tenant-rbac and custom-objects and is
   cached in `studio.principal_scopes` (PK `(tenant_id, principal_id)`, `epoch`, `version`, `state` valid or stale, one
   array per action and arm; `dw_app` SELECT only), written only by `studio.ensure_principal_scope()` (SECURITY DEFINER,
   no arguments). Triggers on every input table mark a principal's row stale or bump the tenant's `studio.access_epochs`
   row in the changing transaction; the upsert compares the version it started from, so a computation begun before a
   revocation never publishes after it. Every Studio transaction sets its settings and calls the door; a missing or
   stale row denies. Record reach leaves the 30-second access-context cache; the `access_closure` lane only pre-warms.
5. **One tenant-wide scope, one setter.** `app.workspace_scope = 'tenant'` means every row of the bound tenant, record
   reach included. Only `tenant_wide_scope(session, tenant_id, lane)` in `tenant_session.py` sets it, for `offboarding`
   and a registry frozen at the composition root (`record_sharing`, `record_index`, custom-objects' field purge and index
   backfill, compliance-pdpl's data-subject-request lane); a test fails any other setter, and lanes audit as
   `system:<lane>` (ADR-0011).
6. **A run's actor context is required, and reach is live.** The API sets `app.actor_kind = 'user'`; the runtime's tool
   session sets `agent` with the agent version's `app.boundary_id`; the workflow runner sets `workflow` with its
   version's boundary (ADR-0103, `studio.actor_boundaries`, immutable after publish). Reach is evaluated at each
   statement: a run resumed after an approval reads with its principal's current reach and narrows if access was lost.
7. **A record indexed into knowledge keeps the record's access.** One document per record in domain `studio.record`,
   payload keys `tenant_id`, `workspace_id`, `object_id`, `record_id`, `owner_id`, `access_key`, `read_grants` and
   `fls_version`. The knowledge gateway builds the vector pre-filter from the caller's closure (no filter value comes
   from the caller), re-checks each candidate through the port it declares, `RecordAccessPort.visible(ids)`, which the
   records adapter satisfies under RLS with the run's actor settings before any text reaches a model, indexes only open
   non-personal fields (ADR-0106), and filters every index mutation on `tenant_id` and `record_id`.
8. **Uniqueness checks bypass RLS by design.** A unique index sees every row, so a refusal tells that some record holds
   the value. Accepted as a residual oracle with a generic error naming neither value nor record, a per-user rate limit
   and an audit event; de-duplication runs as the intake service principal.

## Alternatives considered

- **Filter records in application code.** Rejected: any path that forgets the filter leaks (failure-modes #5).
- **A Zanzibar-style engine** (OpenFGA, SpiceDB, Cerbos). Rejected by S5: a second decider beside RLS, and list
  filtering would still need a local index of the same shape.
- **A materialised share table per record** (Salesforce's model). Rejected: revocation rewrites rows, the fan-out grows
  with sharing rules, and the joined shape measured 1.1-1.4 s.
- **Workspace as the RLS boundary** (si-platform's model). Rejected by D1: units reach each other through permissions.
- **A second session setting for maintenance lanes** (si-platform's `app.record_scope` in
  `db/si/migrations/0056_record_rls_app_user.sql`). Rejected: two settings and two policy shapes for
  `test_rls_coverage.py` to keep.
- **Reach lists built in Python and passed as settings** (si-platform `db/si/migrations/0055_analytics_record_rls.sql`).
  Rejected: a list and a tenant from different contexts expose rows, and a second language cannot rebuild them.

## Consequences

- **Measure before freezing.** record-access ticket 01 measures the six-arm policy (tenant-wide default, workspace key,
  own, team, subordinates, grants) at D12's target (10 million records per object, 50 million per tenant, 5,000 users,
  200 workspaces, tree depth 6, hash partitions by tenant) before the template is frozen; this ADR records the numbers
  (FOG-40). The planning trial above did not measure 10^7 rows, the write path under WITH CHECK or concurrency.
- **`test_rls_coverage.py` learns the RESTRICTIVE plus PERMISSIVE shape:** the exact policy set and canonical text per
  record table and partition, from the same template; every function a record policy depends on (`pg_depend`) is
  STABLE, invoker, with a fixed `search_path`; a connection with a tenant and no actor kind reads nothing; a
  differential test against a test-only Python oracle over random organisations; a negative test and a recorded
  mutation run per arm; a plan-shape test fails a sequential scan at 10^5 rows. `_TRUSTED_SETTINGS` (lines 95-99) and
  `scope_outside_a_tenant_clause` (lines 395-411) extend to the new settings and closure functions.
- **Migrations.** Record columns and indexes leading with `tenant_id`, the policy template, the closure tables, views,
  functions and triggers, `studio.record_shares`; a child-table template (`tenant AND (scope OR EXISTS (parent))`);
  `platform._ensure_one_partition` must give a record partition the full policy set, not the tenant-only one (FOG-32).
  Retired with record-access 12: `record_visibility`,
  `visible_owners`, `worker_runs.actor_record_visibility` and `actor_visible_owners` (baseline lines 470-471).
- **Phasing.** W1 ships the owner, owning workspace, default access and depth with the actor at every door; the
  hierarchy, both kinds of sharing and knowledge come in W2.
- **Harder.** About 1 ms per statement for closure reads (planning measurement); exact counts become capped counts;
  writes pay WITH CHECK and definer functions; triggers sit on tables other specs own; upserts under per-command
  policies need care (FOG-42).
- Contradicts CLAUDE.md:174-175 ("Only the offboarding lane sets `app.workspace_scope`"): amendment A7; worth reopening
  because Studio lanes must read every record of a tenant, and one widening setting keeps one shape rule and one place
  to audit setters. CLAUDE.md:172-173 gains a second policy shape for record tables, held by the same test.
- Extends CLAUDE.md:58-59 (Qdrant receives trusted tenant, workspace and ACL filters from backend context) to the record
  closure, and supersedes the stamped reach of `approval_flow.py:289-294` and `container.py:223-226`.
  `studio.principal_scopes`, `studio.access_epochs` and `studio.record_shares` are tenant-wide rows under the
  CLAUDE.md:163 exception that ADR-0100 records (amendment A6).
- **si-platform.** Ports `packages/python/platform/si_security/src/si_security/application/record_access.py` (a
  restrictive record layer over the tenant boundary; "a share never deletes"; a superior reaches by `owner_id` only)
  and the InitPlan form of si-platform `db/si/migrations/0057_record_tenant_policies_initplan.sql`, re-deriving the
  Alembic revisions, `dw_app` and the policy text. References si-platform
  `docs/adr/0050-record-level-rls-for-analytics-and-cube-behind-the-api.md` and diverges: the arrays are computed in the
  database, and writes are under RLS too. Diverges from si-platform `docs/adr/0036-database-si-core-is-the-root-workspace-rls.md`:
  the workspace is reached by depth, not a wall (D1).

## Open

1. **DO-11 (requester).** Provisional call (agent, 2026-10-23, option (a)): public default access is tenant-wide; the
   manager relation gives transitive read and update, never delete, switchable per object; on assignment the assigner
   chooses and the default keeps the owning workspace; manual shares survive a change of record owner and are listed in the
   assign dialog. If wrong: a sub-tree-limited public default adds a workspace condition to arm (a); direct reports only
   shortens the subordinate array to one level; dropping shares makes `studio.assign_record` delete them.
2. **DO-13 (Đạt, before W1).** Studio maintenance lanes reuse `app.workspace_scope` through the allowlisted helper
   (amends CLAUDE.md:174); second-language services read record values only through the API (ADR-0106); support staff
   read no Studio record in v1 (a per-record support grant is a v2 question).
3. **DO-35 (Đạt and requester, before P1).** Accept the uniqueness oracle as residual risk with the mitigations above,
   with object-wide unique and external-id fields? FOG-11 measures the phone-number case.
4. **DO-12 (Đạt and requester, before W1).** Which principal an unattended run acts as is ADR-0103's question; this ADR
   needs a real principal with memberships, never tenant-wide reach, never wider than the publisher could grant.
5. **DO-14 (answered).** D12 fixed the scale target on 2026-10-23; ticket 01 is sized to it.
6. **FOG-43 (prototype).** A Qdrant should-filter with thousands of values at 10^6 points, and how often the re-check
   leaves fewer than `top_k` results.
