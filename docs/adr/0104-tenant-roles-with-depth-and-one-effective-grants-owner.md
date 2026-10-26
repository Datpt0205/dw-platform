---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py
    - ../../db/migrations/versions/b9862fa13a80_platform_separation_of_duty_rules_guard_.py
    - ../../packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py
    - ../../packages/python/dw_platform/src/dw_platform/application/authorization.py
    - ../../.claude/plans/studio/tenant-rbac/spec.md
---

# 0104. Roles are tenant data built from a migration-owned permission catalogue, every privilege carries a depth, and one PostgreSQL function owns effective permissions

Amends ADR-0012 (2026-10-23): its premise that roles change only in migrations, and separation of duties judged per
membership.

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on the requester's D1 (a
workspace owns data; roles grant privileges with a depth; "a Marketing lead reaches Sales through access rights, never
by copying") and D3 (record-level access in four layers), and on the call on DO-10, decided 2026-10-23.

## Context

- **A tenant cannot shape a role.** `platform.roles` and `platform.permission_sets` are global rows that only migrations
  write: "the catalogue changes only in migrations" (`db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:10`),
  held by `packages/python/dw_platform/tests/integration/test_privileges.py:131-176`. D3 needs privileges on objects a
  tenant defines at run time (`obj.lead.read`), which no migration can ship.
- **Authority is one membership.** `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:80-106`
  reads the acting workspace's membership only, so a Marketing lead reaches Sales by switching workspace, against D1.
- **Three readers disagree.** `effective_scopes` unions roles and permission sets (`membership_lookup.py:33-41`);
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:252-269` reads roles only,
  and `/auth/bootstrap` hands that answer to the web (`apps/api/src/dw_api/routes/v1/auth.py:21-30`), which mirrors
  the admin-grant rule itself (`apps/web/components/admin/members-manager.tsx:39-49`): the drift CLAUDE.md:104-106 warns of.
- **Privilege escalation is a prefix rule in one service.** `forbid_escalation`
  (`packages/python/dw_platform/src/dw_platform/application/membership_admin.py:56-65`) knows only `platform.*` keys;
  separation of duties is judged per membership (`db/migrations/versions/b9862fa13a80_platform_separation_of_duty_rules_guard_.py:12-14`).
- **Routes evict the access cache.** HTTP handlers delete `membership_cache_pattern` and `tenant_cache_pattern`
  (`packages/python/dw_platform/src/dw_platform/application/cache.py:23-32`); a lane or a migration leaves the old
  context for the 30-second TTL (`packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`).
- **`platform_admin` is tenant data.** It sits in `memberships.role_keys`, `ScopeAuthorizationService.is_allowed`
  passes every check for it (`packages/python/dw_platform/src/dw_platform/application/authorization.py:68-71`), and the
  record roll-up treats it as seeing everything (`membership_lookup.py:152`).
- **Prior art.** Dataverse builds security roles from a fixed privilege list with one depth per privilege (its "access
  level"), held from several business units (https://learn.microsoft.com/en-us/power-platform/admin/security-roles-privileges, dated
  2025-12-09). Kubernetes pairs "hold what you grant" with a `bind` verb (https://kubernetes.io/docs/reference/access-authn-authz/rbac/, undated).

## Decision

1. **The catalogue stays code-owned.** `platform.permissions` (global, no `tenant_id`, no RLS, written only by
   migrations as `dw_migrator`; `dw_app`, `dw_provisioner`, `dw_agent_ro` hold SELECT) has one row per permission key
   with `area`, `label_vi`, `status`, `owner_package` and `scope_kind`: a `record` key takes every depth, a `workspace`
   key `workspace`, `workspace_subtree` or `tenant`, a `tenant` key `tenant` only (`ck_tenant_role_permissions_depth_kind`).
   `tenant_grantable` and `risk` arrive with the tickets that read them. Tenants never author keys.
2. **Roles are tenant data.** `platform.tenant_roles` (`kind` `role` or `permission_set`, `is_system`, a `key` unique per
   tenant across soft-deleted rows, never re-keyed), `platform.tenant_role_permissions` and `platform.role_assignments`
   (membership, role, optional `expires_at`) carry tenant-only RLS `tenant_isolation_<table>` and are written by one
   admin service. A permission set is a tenant
   role of kind `permission_set`. `platform.roles` and `platform.permission_sets` stay global and migration-only as role
   templates, cloned into a tenant at provisioning, backfill or on request, never resolved by overlay fallback; a
   template edit never changes a clone. System roles: `tenant_owner` (privileges computed: every tenant-grantable key,
   every enforced object action and every `fld.*` key of every live field (decision 4), all at `tenant` depth) and
   `member` (the editable default for invitations). The computation is the owner's alone: a `fld.*` key added to any
   other role is still a change that widens, and takes two people (decision 10).
3. **Every privilege carries a depth.** `own < team < workspace < workspace_subtree < tenant`, anchored at the workspace
   of the membership holding the assignment; `team` covers records owned by me or by a team I belong to (DO-10,
   decided 2026-10-23). Effective permissions are the union of all of a person's assignments in the tenant.
   `AccessContext.scopes` stays a projection for the acting workspace, so `authz.require(action)` keeps its meaning.
4. **Per-object keys are generated, not stored.** `obj.<api_name>.<action>` exists for every live object definition and
   enforced action: `read`, `create`, `update`, `delete`, `assign` in P1; `share` and `export` only with the migration
   that ships their reader. `fld.<object>.<field>.read|edit` exists for secured fields (ADR-0106). `assign` needs the
   record and its new record owner within reach; `export` never exceeds read. Per-object permission rows reference the
   object or field definition through a composite foreign key, `(tenant_id, object_id)` or `(tenant_id, field_id)`,
   `ON DELETE CASCADE`, so deleting a definition removes its privileges and no row names another tenant's definition.
5. **One owner.** `platform.effective_grants(p_tenant_id uuid, p_user_id uuid)` returns
   `(permission_key, depth, anchor_workspace_id, role_id)`: SQL, STABLE, SECURITY INVOKER (under `dw_app`, RLS bounds it
   to the bound tenant), skipping expired assignments, deleted roles, tenant members who are not active and inactive
   tenants, adding `tenant_owner`'s computed grants; `platform.scopes_in` (the projection) and
   `platform.workspace_reach` sit beside it. The AccessContext build (`effective_scopes` becomes a thin adapter),
   `scope_holders.py`, separation of duties, the anti-escalation triggers, record access (ADR-0105) and the web
   through `GET /me` read it. The copies in `identity_provisioning.py:252-269` and in the web are deleted;
   `/auth/bootstrap` stops returning `roles` and `scopes`.
   Two doors, two questions: the AccessContext build refuses a member who is not active, as it refuses a tenant that is
   not active, and owns "may this person act in the tenant", so routes that check no scope (`/me`, the inbox) refuse
   too; the function owns "which grants", on the SQL path as well; `scope_holders.py` drops its own filter.
6. **Anti-escalation through one function.** A privilege enters a role, an assignment or a revocation only from someone
   holding it at the same or broader reach over the grantee's anchor; a holder of `platform.roles.bind` may assign or
   revoke roles whose privileges are all non-critical, where a role carrying `fld.*` on a sensitive field (ADR-0106)
   counts as critical, so read on sensitive data enters only through someone who holds it, and the person who confirms
   an assignment made through `bind` holds `platform.roles.bind` too (decision 10); nobody assigns a role to
   themselves; system roles are protected;
   `ck_role_assignments_last_owner` (AFTER trigger) keeps one active `tenant_owner`, cascades included.
   `platform.rbac_refusals(...)` serves both doors: the service asks it first and answers 403 with `details.reason_code`
   (`rbac_escalation`, `rbac_self_assignment`, `rbac_not_grantable`); BEFORE triggers on the privilege and assignment
   tables call it for every writer (SQLSTATE 23514). The actor is `app.user_id`, and a `dw_app` write without one is
   refused; `dw_provisioner` and `dw_migrator` are exempt by `session_user` and audited; the function takes `FOR SHARE`
   on the actor's assignments, as `db/migrations/versions/f381f1694395_platform_sod_waiver_second_person_and_.py:75-83`
   does for waivers.
7. **The cache key carries an access version.** `platform.tenant_access_versions` (`tenant_id` PK and FK
   `ON DELETE CASCADE`, `version bigint`, `changed_at timestamptz`; `dw_app` SELECT only) is bumped by
   `platform.bump_access_version()` (SECURITY DEFINER) from triggers on every table feeding authorization: the role
   tables, `memberships`, `tenants`, `entitlements`, `platform_admin_grants` and those later specs add. The key becomes
   `ml:{tenant}:{version}:{workspace}:{issuer}:{subject}`, the version read before the data in the same transaction;
   route-level `delete_pattern` eviction is removed, the tenant `lock`, `unlock` and `offboard` routes of
   `apps/api/src/dw_api/routes/v1/platform.py` included, where foundations-hardening R3.3 adds it only until
   tenant-rbac/02 replaces it with the trigger on `tenants`.
8. **`platform_admin` leaves tenant data.** `platform.platform_admin_grants` (`tenant_id`, `workspace_id`, `user_id`,
   `reason`, `granted_by`, `granted_at`, `expires_at NOT NULL`, at most 8 hours after `granted_at`) is written by
   `scripts/grant_platform_admin.py` as
   `dw_migrator` with the tenant audit event `platform.platform_admin.grant`. A grant in force is read only by
   `ScopeAuthorizationService.is_allowed`; it never bypasses approval stamps (ADR-0004), support access (ADR-0024), the
   tool executor, anti-escalation, separation of duties, or record and field access. It retires after support-access 03.
9. **Separation of duties reads effective permissions.** `platform.sod_violation` evaluates the keys of
   `effective_grants` at any depth and anchor, excluding `tenant_owner`'s (the emergency role, as `platform.admin` is
   today, `b9862fa13a80_platform_separation_of_duty_rules_guard_.py:37-38`). AFTER triggers on `role_assignments` and
   the role privilege tables refuse a change leaving any holder in breach of an unwaived rule (SQLSTATE 23514); the
   service answers 409 naming up to 20 holders.
10. **Two people unless a change only narrows (D11).** Every role change that does not only narrow (creating,
    renaming or re-describing a role, adding a privilege or deepening one) and every assignment, an invitation's
    `member` assignment included, is a proposal in `platform.role_change_requests` that takes effect only when another
    active holder of the same permission confirms it, and it is applied in the confirming person's own transaction, so
    the triggers of decision 6 read that person in `app.user_id`. This keeps the pattern of ADR-0012 rather than
    ADR-0110's settlement, which runs in a lane that the triggers would see instead of a person. A tenant where nobody
    else could confirm gets 409 `conflict` with `details.reason_code` `no_checker_available` and no proposal, so a
    tenant left with one owner changes no role, and invites nobody, until an operator installs a second owner through
    `POST /api/v1/platform/tenants/{tenant_id}/org-admins`; a proposer who confirms their own proposal gets 409
    `conflict` with `second_person_required`. A change that only narrows (an assignment revoked, privileges removed or
    made shallower with nothing added, a role soft-deleted) is applied in its sender's transaction with one audit event
    and no proposal. One SQL function over `platform.effective_grants` finds a checker (an active holder of the
    permission other than the proposer) for this mechanism and ADR-0110's, which also share the proposal expiry rule
    and both reason codes. A tenant starts with two owners (V4.38, YC114): `POST /api/v1/platform/tenants` (tenant-rbac
    R3.1, its ticket 02) takes two, and the tenant stays in a new status `setup`, which `ck_tenants_status` gains in
    that ticket's revision while foundations-hardening R3.2's status trigger stays as it is, until the second owner
    turns `active`, the tenant turning `active` in the transaction that activates that person (org-and-principals'
    member activation calls the transition). The second owner may be the customer's partner, a person outside the
    customer's company invited as a member like any other member, and is never a platform operator or a support staff
    member: neither ever holds `tenant_owner`, `studio.publish.approve` or `platform.roles.write` in a customer's
    tenant, which PostgreSQL refuses, with a negative test (ADR-0024 (Proposed) decision 6, cited and not amended).
    Once each time the `active` holders of `studio.publish.approve` or `platform.roles.write` fall below two, the
    tenant-depth holders of `platform.members.write` are warned, and the operators' screen lists the tenants in
    `setup` and those below two (H-15). Who may do what while a tenant is `setup`, and whether `setup` leads anywhere
    but `active`, wait on Đạt (Open 7 and 8).
11. **Three answers to a refused decider.** A person refused the decision of an approval, or the confirmation of a
    role change under decision 10, gets one of three answers, and specs cite them from here:
    - 404 `not_found` when the request lies outside what they may see: another workspace's request, or a stamped one
      they may not decide and did not ask for (ADR-0004, amendment of 2026-10-07), answered as a request that never
      existed.
    - 409 `conflict` for every separation-of-duties rule, the rule in `details.reason_code`:
      `second_person_required` for the strict prefix's refusal of a requester or run-as principal deciding, for every
      approval type, and for a proposer deciding their own proposal (decision 10, ADR-0110); `author_cannot_approve`
      for an author approving their own version's publish, the guard of `studio.publish.` (ADR-0120). The strict
      prefix's check runs before any guard, so an author who is also the request's requester gets
      `second_person_required`.
    - 403 `permission_denied` when they see the request but lack `approvals.decide` or its stamp (ADR-0004), are not
      among its assignees, or cannot read a field it stamped (ADR-0106 decision 6, ADR-0112 decision 7). From W2 an
      approval delegation (YC104) lets a person decide in an assignee's place only while they hold the type's stamp
      and `approvals.decide`, are not the run's requester (YC51) and act between the delegation's start and end,
      audited; outside those conditions the answer stays 403.

    ADR-0004 keeps the stamp and the visibility rule that these answers follow.

## Alternatives considered

- **A Salesforce-style role as a hierarchy node** (si-platform's `core.roles` tree, `db/si/migrations/0005_permission.sql`).
  Rejected by S4: reach comes from depth, the workspace tree, the manager relation and sharing.
- **Roles stay code-only.** Rejected: D3 needs tenant-defined per-object privileges. Tenant-authored permission keys
  are rejected too: keys no code checks (failure-modes #1).
- **OpenFGA, SpiceDB or Cerbos.** Rejected by S5: a second decider beside PostgreSQL RLS.
- **Effective permissions computed in Python.** Rejected: a second copy beside the SQL triggers and RLS that read the
  answer inside PostgreSQL, and a trigger cannot call Python (failure-modes #2).
- **Permissions per acting membership only (today).** Rejected: D1 needs reach across units from one person.
- **Overlay fallback from a tenant role to its template.** Rejected: a template edit would silently widen every
  tenant's role, the risk `648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:11-13` closed.
- **NOTIFY-based cache eviction.** Rejected: a writer outside the API (a lane, a migration) would leave stale contexts;
  kept as the fallback if the per-request version read costs too much (FOG-38).
- **Role changes as ADR-0110 configuration versions.** Rejected: a decision there settles in the outbox lane, whose
  audit names the decider but whose transaction carries the lane's own actor in `app.user_id`, so the anti-escalation
  triggers would see the lane, never the person (CLAUDE.md:254-259); role changes keep ADR-0012's request table,
  applied in the checker's transaction (decision 10).

## Consequences

- **Migrations.** New Alembic revisions for the catalogue, the tenant tables, the functions and triggers; a backfill
  clones every key a tenant's memberships use into a tenant role at today's depth (`workspace` for workspace keys,
  `tenant` for tenant keys) and gives `org_admin` clones `platform.roles.bind`. Then `memberships.role_keys` and
  `permission_set_keys` refuse non-empty writes, and are dropped one release later.
- **Tests.** `test_privileges.py` is rewritten in the same change (its premise at line 132 is reversed; it still bars
  application writes to `platform.permissions` and the templates, and covers the tenant tables). A privilege escalation
  written as raw SQL under `dw_app` is refused by the trigger, and removing the trigger call turns it red; so are
  self-assignment, losing the last tenant owner through a cascade and a rule broken across two workspaces.
  `effective_grants` is empty for another tenant although `memberships_self_select`
  (`db/migrations/sql/0001_platform_baseline.sql:818`) shows those memberships; a lane's role edit reaches the next request.
- **Readers and phasing.** Record access, field security and every permission check read `effective_grants`;
  tenant-rbac's P1 tickets wait on custom-objects for per-object keys. W1 ships `own`, `workspace` and `tenant`; `team`
  and `workspace_subtree` arrive in W2 with teams and the workspace tree.
- **Harder.** An admin holding the administrative keys can make another admin (today only `platform_admin` can), and
  tenant owners reach all data (DO-32); admin writes serialise on the version row; each request pays one key read.
  Products that insert into `platform.roles` now insert templates; one writing `memberships.role_keys` fails (FOG-49),
  so dw-proterial's maintainer moves its writes off that column before tenant-rbac/03 refuses them.
  A tenant with one owner changes no role and invites nobody until an operator installs a second owner (decision 10),
  so the migration prints the tenants with fewer than two owners and those with no `org_admin` in their root
  workspace; a tenant created once tenant-rbac/02 lands has two owners from the start (V4.38).
- Contradicts `CLAUDE.md:185` ("Every tenant-scoped table has `tenant_id` and `workspace_id`") for
  `platform.tenant_roles`, `platform.tenant_role_permissions`, `platform.tenant_access_versions`,
  `platform.role_change_requests` and `platform.tenant_role_object_privileges`, worth reopening because a role, its
  privileges, its change requests and the access version belong to the whole tenant: tenant-wide rows under the class
  ADR-0100 records (A6), each listed with its reason in `test_rls_coverage.py`. `platform.role_assignments` keeps
  `workspace_id`, its anchor.
- Contradicts migration `648e2f7c3edb` (line 10): kept for the catalogue and templates, reversed for tenant roles;
  worth reopening because D3 makes per-object privileges tenant data, while the widening risk stays closed.
- Contradicts ADR-0012 (`docs/adr/0012-a-sod-waiver-takes-two-people.md:43`, "both tables change only in migrations")
  and its per-membership evaluation: amended; worth reopening because today one person may hold a rule's two sides in
  two workspaces and pass the check (failure-modes #5).
- Contradicts `test_privileges.py:131-176` (rewritten), `memberships.role_keys` carrying `platform_admin`, and the
  docstrings at `packages/python/dw_platform/src/dw_platform/application/admin_console.py:9-12` and
  `membership_admin.py:11-16`. Completes ADR-0024, whose Context names `platform_admin` as the wrong way in yet leaves
  it in tenant data with no end date: its retirement is sequenced after support-access 03.
- CLAUDE.md "Tenancy and authorization" (line 161) gains a line on acceptance (amendment A4): roles are tenant data over
  a code-owned catalogue, and `platform.effective_grants` owns effective permissions; CLAUDE.md:101-106 then names it.
- **si-platform.** References si-platform `docs/adr/0031-permission-sets-and-roles-are-tenant-data.md` and diverges on
  the role concept (S4: a privilege bundle with depth, not a hierarchy node). Diverges from si-platform
  `docs/adr/0046-tenant-permissions-are-a-platform-package-served-by-one-module.md` (a SQL function, not a module, owns
  effective permissions) and from si-platform `docs/adr/0048-role-and-group-membership-computed-when-the-caller-is-resolved.md`
  (an access version in the cache key instead of NOTIFY eviction).

## Open

1. **DO-09 (Đạt, before W1).** Tenant roles become data, reversing the migrations-only premise (amends ADR-0012 and
   migration `648e2f7c3edb`), with effective permissions the union of all assignments, each anchored at its
   assignment's workspace? Blocks tenant-rbac/02 and every `studio.*` permission. Answered 2026-10-23: yes
   (DO-09.1 (a)); this ADR amends ADR-0012, and `test_privileges.py` is rewritten in the same change.
2. **DO-33 (Đạt, before P1).** `platform_admin` as a platform-written, time-bound break-glass grant of at most 8 hours
   until support-access 03 ships, then retired; retired now; or kept as today? Answered 2026-10-23: the time-bound
   grant of at most 8 hours, retired after support-access 03 (DO-33 (a)); due before GA, since tenant-rbac moved the
   work to W2.
3. **DO-32 (requester and Đạt, before P1).** May an admin make another admin under the hold rule; may
   `platform.roles.bind` assign non-critical roles the actor does not hold; does assigning a critical permission take two
   people (recommended: notice to every tenant owner in P1, a second person in v1 once there are two tenant owners); who
   is the first `tenant_owner` of an existing tenant (recommended: the `org_admin` holders of its root workspace, audited
   as `system:rbac_migration`)? D11 (DO-07) asks two people for every tenant configuration change, role changes and
   assignments included (tenant-rbac, 2026-10-23). Answered 2026-10-23: an admin may make another admin under the hold
   rule, and `bind` assigns roles with no critical privilege, a role carrying `fld.*` on a sensitive field counting as
   critical (DO-32.1); the first `tenant_owner` is the root workspace's `org_admin` holders, audited as
   `system:rbac_migration`, an operator assigning one where none exists (DO-32.2). The requester and Đạt confirmed
   D11 for roles from W1: every change that does not only narrow takes two people, invitations included, and one that
   only narrows takes one person and an audit event (decision 10).
4. **DO-10 (requester; Đạt for separation of duties).** Provisional call (agent, 2026-10-23, option (a)): permission
   sets stay a role kind, `team` covers me and my teams, separation of duties is judged per person across the tenant.
   If wrong: a wider `team` adds a closure arm, measured first; per-membership judging reopens the two-workspace gap.
   Answered 2026-10-23: option (a) as stated (DO-10.1 (a), DO-10.2 (a)).
5. **FOG-49 (grilling).** Who migrates downstream products (dw-proterial) that write `memberships.role_keys` and insert
   roles, and when; how a domain pack's role templates name the pack's object keys. Answered in part 2026-10-24:
   dw-proterial's maintainer moves it off `memberships.role_keys` before tenant-rbac/03 locks the column; how a pack's
   role templates name its object keys stays open.
6. **FOG-38 (prototype).** Cost of `effective_grants` and the version read per request; triggers under bulk assignment
   and on a role with 1,000 holders; whether `FOR SHARE` closes the revoke-while-assigning race on PostgreSQL 16.
7. **Q-h1 (Đạt, before tenant-rbac/02 is ready).** Who may do what while a tenant is `setup` (decision 10)? Proposed:
   `setup` behaves as `locked` at every tenant route, except the two owners' first sign-in and their acceptance of the
   owner invitation, and the operators' routes; no run, no publish and no other invitation until the tenant is
   `active`. ADR-0102 decision 6, read as written, refuses a tenant that is not active at every route, `/me` included,
   which would refuse those two steps as well, so the answer also names that exception. Answered 2026-10-26: as
   proposed (tenant-rbac R3.14); the exception is recorded in ADR-0102's amendments.
8. **Q-h2 (Đạt, before tenant-rbac/02 is ready).** May a tenant in `setup` be offboarded (`setup` to `offboarding`)?
   Proposed: yes, by the operators through the existing offboarding flow, so a tenant whose second owner never arrives
   does not stay `setup` for good (failure-modes #6). Answered 2026-10-26: as proposed; `setup` to `locked` and every
   other exit but `active` and `offboarding` are refused (tenant-rbac R3.15).
9. **Q-h7 (Đạt, before tenant-rbac/02 is ready).** In W1, does the `platform_admin` bypass (the value in
   `memberships.role_keys` that passes every scope check without an approval mark, tenant-rbac G2) count as holding
   `platform.roles.write` in a customer's tenant under decision 10? If it does, it contradicts the operator rule there
   until W2 withdraws the value. Proposed: yes; the role-administration and role-assignment routes do not accept the
   bypass, as it already does not pass an approval mark (DO-33), and G2 holds for every other route. Answered
   2026-10-26: as proposed (tenant-rbac R3.16).

## Acceptance (2026-10-23)

- Status Accepted by Đạt; the body opens with "Amends ADR-0012" and ADR-0012 carries "Amended by ADR-0104"
  (DO-09.1 (a), DO-10.2 (a)).
- Decision 10 added: D11 for roles from W1 as the requester and Đạt scoped it (two people for every change that does
  not only narrow, invitations included; one person and an audit event for one that does), applied in the confirming
  person's transaction, with the checker function and expiry rule shared with ADR-0110 (D11 override, DO-09.2 (a),
  D:tenant-config/05~tenant-rbac:R7.1 (b)).
- Decision 5: `effective_grants` skips members who are not active, and the AccessContext build refuses them at every
  route (A:org-and-principals:R4.3 (b)).
- Decision 6: for `platform.roles.bind`, a role with `fld.*` on a sensitive field counts as critical, and the confirmer
  of a `bind` assignment holds `bind` (DO-32.1).
- Decision 7: the lock, unlock and offboard routes lose their `delete_pattern` once tenant-rbac/02 lands
  (A:foundations-hardening:R3.3~tenant-rbac:R4.1 (a)).
- Decision 8: a `platform_admin` grant lasts at most 8 hours (DO-33 (a)).
- Alternatives and Consequences: role changes through ADR-0110 rejected with the reason; the one-owner consequence and
  the migration's printout; the tenant-wide tables of this ADR named against `CLAUDE.md:185` (A6).
- Open 1 to 4 answered; Open 3 no longer reads D11 as configuration only.

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Decision 2: `tenant_owner`'s computed privileges include every `fld.*` key of every live field, and a `fld.*` key
  added to any other role still takes two people (N1).
- Decision 10: soft-deleting a role only narrows, so it takes one person and an audit event (D11, 2026-10-24); the
  two refusals are 409 `conflict` with `details.reason_code` `no_checker_available` or `second_person_required`,
  shared with ADR-0110 (B:tenant-config:R8.8~tenant-rbac:R7.2).
- Decision 11 added: the three answers to a refused decider (404, 409, 403), which specs had cited from ADR-0004,
  where no such table is written (F:ADR-0004~workflow-engine:quyết-định).
- Alternatives: the outbox lane now audits the decider (ADR-0011), and the reason stands because its transaction
  carries the lane's own actor in `app.user_id` (E:CLAUDE.md#agent-and-tool-rules~tenant-config:R8.10).
- Open 5 answered in part: dw-proterial's maintainer moves its writes off `memberships.role_keys` before
  tenant-rbac/03 locks the column (FOG-49).
- Third consistency check (round 4): decision 11 gives the strict prefix's refusal of a requester or run-as principal
  the code `second_person_required` for every approval type, `author_cannot_approve` staying the `studio.publish.`
  guard's, and since the strict check runs first an author who requested the approval gets the former (V4.P9, the
  planner's provisional call, B:packages:spec\~tenant-config/05; if it is wrong, each approval type names its own code
  through its `decision_guards` entry); it also states from W2 the conditions under which an approval delegation
  decides, 403 outside them (Đạt's V4.10; D:ADR-0112\~workflow-nodes:spec).
- Third consistency check (round 4), third pass: decision 4's per-object permission rows reference their definition
  through a composite foreign key, `(tenant_id, object_id)` or `(tenant_id, field_id)`, as tenant-rbac's object and
  field privilege tables state them, because a foreign key check does not pass through RLS and a one-column key would
  let one tenant's privilege name another tenant's definition (`CLAUDE.md`, Data model rules).

## Amendments (2026-10-25)

- Third consistency check (round 4), eighth pass, Đạt's V4.38 with the planner's call H-15: decision 10 has a tenant
  created with two owners, kept in the new status `setup` until the second is `active` and turned `active` in that
  person's activating transaction; lets the customer's partner be the second owner and never a platform operator or a
  support staff member, who never hold `tenant_owner`, `studio.publish.approve` or `platform.roles.write` in a
  customer's tenant (ADR-0024 (Proposed) decision 6 cited, not amended); and warns the tenant-depth holders of
  `platform.members.write` once each time the `active` holders of either key fall below two (H-15). Open 7 (Q-h1, what
  `setup` allows) and Open 8 (Q-h2, whether `setup` may lead to `offboarding`) are Đạt's, and nothing here guesses
  them; Consequences note that a tenant created after tenant-rbac/02 starts with two owners.

## Amendments (2026-10-26)

- Đạt answered Open 7, 8 and 9 as proposed ("theo khuyến nghị hết cho tôi"): a `setup` tenant behaves as `locked`
  except the two owners' first sign-in and acceptance and the operators' routes; it leaves `setup` only for `active` or,
  through the operators' offboarding flow, `offboarding`; the role-administration and role-assignment routes do not
  accept the `platform_admin` bypass. The status stays Accepted.
