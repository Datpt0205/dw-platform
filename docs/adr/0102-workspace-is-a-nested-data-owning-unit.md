---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/org-and-principals/spec.md
    - ../../db/migrations/sql/0001_platform_baseline.sql
    - ../../packages/python/dw_platform/src/dw_platform/adapters/persistence/hierarchy_repo.py
    - ../../packages/python/dw_platform/src/dw_platform/application/access_context.py
---

# 0102. A workspace is a nested, data-owning business unit, and teams, tenant members and line managers are tenant data that record reach reads

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block).

## Context

D1 makes the workspace the unit that owns data: a department or a division of the customer (Marketing, Sales), nested
as a tree (company, division, department). Every record of a tenant-defined object has a record owner (a user or a
team) and an owning workspace; roles grant permissions with an access depth (my records, my workspace, my workspace
and its sub-tree, the whole tenant); a Marketing lead reaches Sales through access rights, never by copying. These are
Dataverse's business-unit semantics, access levels per privilege and table
(https://learn.microsoft.com/en-us/power-platform/admin/security-roles-privileges, ms.date 2025-12-09, read
2026-10-22). D3 adds a line manager who sees and edits subordinates' records, and records owned by teams. D12
(2026-10-23) sizes a tenant at 200 workspaces, a tree six deep and 5,000 users.

None of these facts has a home today:

- `platform.workspaces` is flat (`db/migrations/sql/0001_platform_baseline.sql:478-485`): no parent, and archive is a
  label that `admin_console_repo.py:140-142` sets and no door reads.
- The line manager and the department sit on each membership (`0001_platform_baseline.sql:270-271`), so a person in
  two workspaces can have two managers; `hierarchy_repo.py:1-7` walks the chain inside one tenant and one workspace.
- A tenant member is not a row: the tenant-wide member list is derived from memberships
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:1-8`), so "suspended in this
  tenant" has nowhere to live; the tenant-members spec deferred it
  (`.claude/plans/platform-runtime/tenant-members-and-invitations/spec.md:44`).
- `AccessContext.groups` is an untyped set of strings (`application/access_context.py:38`).
- Tenant status already has `locked` and `offboarding`
  (`db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:80`); what each means at each door is unwritten.

## Decision

1. **One tree, one copy.** `platform.workspaces` gains `parent_id`. Every workspace but one root per tenant has a
   parent in the same tenant, by the composite foreign key `fk_workspaces_tenant_id_workspaces` on
   `(tenant_id, parent_id)` referencing `uq_workspaces_tenant_id_id UNIQUE (tenant_id, id)`, `ON DELETE RESTRICT`,
   with `uq_workspaces_one_root` on `(tenant_id) WHERE parent_id IS NULL` and `ck_workspaces_parent_not_self`. Both
   key names come from `NAMING_CONVENTION` (`packages/python/dw_kernel/src/dw_kernel/naming.py:25-27`), and
   org-and-principals/01 is the one creator of `uq_workspaces_tenant_id_id`, which every composite foreign key to a
   workspace uses. Each tenant's `main` workspace becomes its root, never moved or archived. Trigger
   `platform.guard_workspace_tree()` takes `pg_advisory_xact_lock(hashtext('ws_tree:' || tenant_id))` (two moves each
   valid alone can close a cycle together) and refuses with `ck_workspaces_tree_acyclic`, `ck_workspaces_tree_depth`
   (more than six levels, root included) or `ck_workspaces_parent_live`. `parent_id` is the tree's only stored copy;
   every reader calls
   `platform.workspace_ancestors(p_tenant_id, p_workspace_id)` or `platform.workspace_subtree(p_tenant_id, p_workspace_id)`
   (SQL, STABLE, SECURITY INVOKER, returning `(workspace_id, distance)` with self at 0), and no other code walks
   `parent_id`. A move (`POST /api/v1/admin/workspaces/{id}/move`, with a reason) audits `platform.workspace.moved`;
   records never move, their reach changes because the tree changed.
2. **Never a wall, never an environment.** A workspace keeps its tenant-only policy (`0001_platform_baseline.sql:878`)
   and is neither an RLS boundary for records nor an environment (ADR 0111). Reach across workspaces comes from access
   depth (ADR 0104), the manager relation and sharing (ADR 0105), never from copying data (D1).
3. **Standing in a tenant is one row.** `platform.tenant_members`: `PRIMARY KEY (tenant_id, user_id)`, `status` CHECK
   IN (`invited`, `active`, `suspended`), `manager_user_id`, `employee_code` (unique per tenant when set), `source`
   CHECK IN (`admin`, `csv`, `scim`, `jit`); tenant RLS plus a self-select policy so a person sees their own status in
   each tenant. `platform.memberships` references it `ON DELETE CASCADE`, so removing a person from a tenant removes
   every membership, team membership and attribute value in one statement. One line manager per person per tenant:
   `fk_tenant_members_tenant_id_tenant_members` on `(tenant_id, manager_user_id)`
   `ON DELETE SET NULL (manager_user_id)`, guarded by
   `platform.guard_reporting_line()` (no self, no manager who is not an active human member, no service principal on
   either side, no cycle). `platform.subordinates(p_tenant_id, p_manager_user_id)` is the only reader record access
   calls. `memberships.manager_user_id` and `memberships.department` retire, each dropped by the change that moves its
   last reader, with no dual-write window.
4. **Teams.** `platform.teams` (an `owning_workspace_id`, a name unique among that workspace's live teams,
   `archived_at`) and `platform.team_members` (any member of the tenant, from any workspace; never a service principal)
   are tenant-wide rows. A team owns records, receives shares and pools assignments; v1 has one kind, owner teams.
   `platform.teams.manage` (risk `elevated`) needs reach over the team's workspace; audit `platform.team.created`,
   `.archived`, `.member_added` and `.member_removed`. An archived team stops giving team reach. `AccessContext.groups`
   is replaced by a typed `directory` snapshot (team ids, workspace ancestors, audience attributes); record reach never
   reads team ids from the access context.
5. **Owner and owning workspace.** Every record of a tenant-defined object has a record owner (`owner_kind` user or
   team, `owner_id`) and an owning workspace, both NOT NULL (D1, D3a).
6. **Lock, offboarding and archive live in the owners of "may this act".** They are enforced only at the AccessContext
   build, which refuses a tenant or a tenant member that is not active at every route (`/me` included), through
   `platform.effective_grants` (ADR 0104) on the SQL path, and through `RunControlPort` (ADR 0120) for runs, with reason
   codes `tenant_locked`, `tenant_offboarding`, `workspace_archived` and `principal_inactive` (a run whose principal is
   no longer an active member stops at its next door); no third "is this tenant live" function is written. A lock
   refuses every member, stops running runs at the next door, keeps paused runs paused with every decision refused,
   skips schedules, and answers inbound events 503 with `Retry-After`, storing nothing. Offboarding does the same
   and, in its filing transaction, revokes every API key and suspends every service principal. Archive is refused for
   the root and for a workspace with live children; an archived workspace refuses new members, role assignments,
   teams, records, artifacts, connections and triggers (`ck_workspace_archived`), outbox `platform.workspace.archived`
   disables its triggers and cancels its paused runs with their approvals, and its records stay, reached only from
   elsewhere.
7. **Attributes and audiences.** Each member attribute has one declared writer (`platform.member_attribute_defs.writer`:
   `admin`, `csv`, `scim` or `idp_claim`); a trigger refuses a value from any other source (409
   `attribute_managed_by_<writer>`). v1 writers are the admin API and a CSV import; SCIM and IdP claims arrive in v2.
   An audience is a typed condition list `dw.audience/v1` (`any_of` of `all_of` lists over attributes marked
   `usable_in_audience`, `workspace_subtree` and `team`; at most 20 conditions), evaluated per request against the
   `directory` snapshot and never materialised. It decides who may find and invoke an agent or a workflow and never
   widens data access; its reverse view ("who may use this") compiles to positive SQL, for admins only.

## Alternatives considered

- **Workspace as a hard wall.** Rejected by D1: a Marketing lead must reach Sales through access rights.
- **Workspace as UI grouping only.** Rejected by D1: the workspace owns data and anchors access depth.
- **A separate org-unit tree that workspaces reference.** Rejected: under D1 the workspace is the unit, and two trees
  give two answers to "which unit owns this"; a unit that owns no data (an office) is an attribute.
- **A closure table or an `ltree` path for the tree.** Rejected: a second copy kept in step by triggers (failure-modes
  #2), while six levels keep recursion cheap. The Studio identity research measured a 626-unit sub-tree at 7.3-12.8 ms
  by recursive query against 3.5-4.2 ms through a closure table, in a 5,009-unit directory (PostgreSQL 16, 2026-10-22,
  not re-run here); the tree is read when an access snapshot is built, never per record. Revisit past 1,000 workspaces.
- **The manager stored per membership.** Rejected: a person in two workspaces could have two managers, and the copies
  drift.
- **A lock that holds inbound events like a freeze.** Rejected: a lock can be legal or commercial and may never lift,
  so storing new personal data for that tenant breaks minimisation; a freeze is an incident pause that must lose nothing.
- **Audiences in CEL.** Rejected: the reverse view needs SQL generation, which a typed list gives; a typed list has no
  arithmetic, so it is not a second expression language.

## Consequences

- org-and-principals migrates memberships to hang off `tenant_members`, backfilling one row per person and tenant
  (`active` with a login identity, else `invited`) and the manager (from the root workspace's membership, else the most
  frequent value, conflicts printed by the migration; dev and seed data only today).
- record-access and tenant-rbac read the tree only through the two functions; record access's principal keys grow by
  at most six sub-tree markers per membership.
- Phasing: W1 ships `uq_workspaces_tenant_id_id` and `tenant_members` with its status (org-and-principals 01 and 02),
  the 503 answer to a locked or offboarding tenant's inbound events (workflow-triggers), and a minimal audience: a
  `dw.audience/v1` holding the workspace condition only (W1's tree is flat, so a workspace's sub-tree is itself),
  answered by `platform.audience_matches` from a W1 ticket of org-and-principals that agent-builder calls (an empty
  audience 422, no match 404). The tree, teams, the manager relation, archive enforcement, attributes and the other
  audience conditions are W2, with no change to the document format.
- Tests, each shown red by removing its guard: a parent in another tenant is impossible; two concurrent moves that
  would close a cycle are refused; a seventh level is refused; a suspended member's effective permissions are empty;
  tenant B reads none of tenant A's members, teams or attributes; a value written by the wrong source is refused; a
  broad audience never widens what a run reads; a locked tenant's inbound event gets 503 and leaves no row.
- Harder: every Studio table owner adds the archived check; the access-context cache serializer must name each
  `directory` field (failure-modes #2 and #7); attributes are personal data, exported and erased through the
  data-subject lane; the tenant-members code paths change, and the archive button becomes a control that lists its
  effects before it confirms.

### Contradictions

- Contradicts `CLAUDE.md:181` ("Every tenant-scoped table has `tenant_id` and `workspace_id`"), worth reopening because
  tenant members, teams and attribute definitions belong to the tenant, not to one workspace; ADR 0100 carries the
  amendment (A6), and `test_rls_coverage.py` lists each such table with its reason.
- Retires `memberships.manager_user_id` and `memberships.department` (`0001_platform_baseline.sql:270-271`) and the
  per-workspace walk of `hierarchy_repo.py`, worth reopening because a person has one line manager per tenant.
- Removes `AccessContext.groups` (`access_context.py:38`) and turns archive from the label of
  `admin_console_repo.py:140-142` into a control.
- Contradicts ADR 0114 (CEL is the one expression language for tenant text) for audiences only, worth reopening
  because an audience must also be answered in reverse; recorded here as an explicit exception, as DO-40 decided on
  2026-10-23, and in ADR 0114 too.
- Plans the per-tenant lock that `.claude/plans/platform-runtime/tenant-members-and-invitations/spec.md:44` left out.

### Relation to si-platform

- Diverges from si-platform `docs/adr/0030-workspace-is-the-rls-boundary-accounts-are-tenant-wide.md` and
  `docs/adr/0036-database-si-core-is-the-root-workspace-rls.md`: here a workspace is reached by depth, never an RLS
  boundary (D1), and teams span workspaces where si-platform's record teams stay inside one. Nothing is ported.

## Open

1. **DO-14 (requester): answered.** D12 (2026-10-23) fixes the tree at six levels, with 200 workspaces and 5,000 users
   per tenant; kept here for the trace, no longer blocking.
2. **DO-10 (requester for the team depth; Đạt for separation of duties).** Does the team depth cover only records owned
   by me and my teams, or also fellow members' own records? Provisional (agent, tạm theo khuyến nghị, 2026-10-23):
   me and my teams only. If wrong, record access's closure gains a member arm and its benchmark is re-run. Answered
   2026-10-23: me and my teams only (DO-10.1 (a)); separation of duties is judged per person across the tenant
   (DO-10.2 (a), ADR 0104).
3. **FOG-45 (grilling).** Does each team belong to exactly one workspace, as a total depth order requires? Point 4
   assumes it does; the grilling confirms it, with where the manager relation for task escalation comes from.
4. **DO-39 (requester).** While a tenant is locked, answer inbound events 503 and store nothing, or hold them like a
   freeze? Provisional (agent, tạm theo khuyến nghị): 503 and store nothing. If wrong, a lock holds events, and their
   retention for a tenant that may never return goes to counsel. Answered 2026-10-23: 503 with `Retry-After`, nothing
   stored, from W1 (DO-39.1 (a)).
5. **DO-40 (Đạt and requester).** Audience format: the typed condition list of point 7 (recommended) or CEL? Answered
   2026-10-23: the typed condition list (DO-40 (a)).
6. **DO-04 (requester).** Keep "workspace" as the Vietnamese UI term? Provisional: keep it. If wrong, screens rename to
   the chosen term and code keeps `workspace`. Answered 2026-10-23: keep "workspace" (DO-04 (a)); the "(phòng ban)"
   gloss leaves the two screens that ship it.

## Acceptance (2026-10-23)

- Status Accepted by Đạt with the decision brief's amendments.
- Key names follow `NAMING_CONVENTION`: `uq_workspaces_tenant_id_id`, created only by org-and-principals/01,
  `fk_workspaces_tenant_id_workspaces` and `fk_tenant_members_tenant_id_tenant_members` (OPS-a.2).
- Decision 4: a team's owning workspace is `owning_workspace_id`, the one name ADR 0100 fixes for tenant-wide rows
  (DO-01 (a)).
- Decision 6: the AccessContext build joins the owners of "may this act" and refuses a member who is not active
  (A:org-and-principals:R4.3 (b)); `RunControlPort` gains the reason `principal_inactive`
  (H:org-and-principals:R4.6 (b)).
- Phasing: the minimal workspace-only audience through `platform.audience_matches` moves into W1
  (H:agent-builder:R5.1 (a)), and the lock's 503 for inbound events ships in W1 (DO-39.1 (a)).
- Open 2, 4, 5 and 6 answered; DO-40's exception recorded as decided.
