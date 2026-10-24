---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/org-and-principals/spec.md
    - ../../.claude/plans/studio/record-access/spec.md
    - ../../.claude/plans/studio/foundations-hardening/spec.md
    - ../../packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py
    - ../../infra/keycloak/dw-realm.json
    - 0024-customer-granted-support-access.md
---

# 0103. Only people and service principals act; an agent or a workflow is a boundary, and every run acts as its invoking person or a bound service principal intersected with that boundary

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block). It rests on the requester's D1
(workspaces own data and reach each other through access rights, never by copying) and D3 (record access in four
layers, field security applied to agents and search too), and on the call on DO-39, decided 2026-10-23.

## Context

- **Who acts is a stamp today.** A run carries `actor_id` with the roles and scopes stamped when it started and a record
  roll-up that defaults to `"open"` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:108-127`);
  `platform.worker_runs` keeps the same stamps beside `requested_by uuid NOT NULL`
  (`db/migrations/sql/0001_platform_baseline.sql:460-471`). The pilot's intake workflow (D4) runs at night on a form
  submission with no person to name, and an agent many people invoke must never reach more than the one who asked.
- **Sign-in trusts an email.** A new identity is linked to an existing user by `users.subject` across issuers, then by
  `lower(email)` over the global user table, with no `email_verified` check and no tenant filter
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:138-166`, "Trusted because
  the email comes from the IdP-verified token" at `:154-155`); `membership_lookup.py:200-202` matches `users.subject`
  the same way. Planning reproduced the takeover this allows from an unlinked IdP on Keycloak 26.7.2 and from an
  organization-linked IdP on 26.8.1 (`.claude/plans/studio/discovery/research.md` section 13, measured 2026-10-22).
  ADR 0024 asks for it to close before customer SSO is brokered (`0024-customer-granted-support-access.md:129-131`).
- **Revocation waits eight hours.** Access tokens and SSO sessions live 28,800 s (`infra/keycloak/dw-realm.json:12-14`).
- **Prior art.** OIDC Core 1.0 section 5.7: `sub` and `iss` "are the only Claims that an RP can rely upon as a stable
  identifier" (https://openid.net/specs/openid-connect-core-1_0.html); Microsoft says never to authorise on `email`
  (https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation, updated 2026-06-15). OWASP LLM06:2025
  asks to "execute extensions in user's context" (https://genai.owasp.org/llmrisk/llm062025-excessive-agency/); RFC 8693
  keeps the party that acts apart from the party it acts for (https://www.rfc-editor.org/rfc/rfc8693, 2020); AWS
  computes permissions under a boundary as an intersection
  (https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html). Cited by the planning research on
  2026-10-22, not re-read for this ADR.

## Decision

1. **One vocabulary of who acts.** `principal_kind` is `user`, `service_principal`, `system_lane` (ADR 0011) or
   `support_staff` (ADR 0024), the one vocabulary of `RunContext`, audit and the usage ledger (whose columns ADR 0121
   owns). An agent or a workflow is a boundary, never a principal: no `platform.users` row, no role, no grant. A team
   owns records and receives shares (ADR 0102) but never acts. `app.actor_kind` (`user`, `agent`, `workflow`; ADR 0105)
   names the boundary in force; `app.user_id` stays the acting principal of a tenant transaction
   (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:26`) and `app.principal_id` the
   signed-in identity on identity-plane policies (`0001_platform_baseline.sql:818`); neither is renamed.
2. **A service principal is a user row a tenant owns.** `platform.users` gains `kind` (`human` or `service`, NOT NULL,
   CHECK) and `owner_tenant_id` (set exactly when `kind = 'service'`, FK `ON DELETE CASCADE`, indexed); the detail row
   `platform.service_principals` carries its name, description, owning workspace and accountable owner, while active or
   suspended is its `tenant_members.status` (ADR 0102), one fact in one place. It holds memberships and role assignments
   like a person, so `platform.effective_grants` (ADR 0104), separation of duties and scope holders need no branch. It
   never gains a login identity, never holds `tenant_owner` or a role with a `critical` permission (checked on
   assignment and on a role's permission change), has memberships only in its own tenant, and every identity-plane
   listing filters `kind = 'human'`. Permissions `platform.service_principals.manage` and `.use`, risk `elevated`.
3. **Every agent, workflow and service principal has an accountable owner.** `owner_user_id`, FK
   `(tenant_id, owner_user_id)` to `platform.tenant_members` `ON DELETE SET NULL (owner_user_id)`, guarded by one
   trigger function, `platform.guard_accountable_owner()`: set on insert, and every value names an active human member.
   When the accountable owner is removed or suspended, the lane `principal_ownership` (audited as
   `system:principal_ownership`) alerts the tenant-depth holders of `platform.members.write`, and publishing a version,
   binding the service principal or creating its API key answers 409 `owner_missing` until a new accountable owner is
   set; live versions keep running.
4. **Interactive runs act as their person; unattended runs act as a bound service principal.** Chat, manual, test and
   agent-tool runs act as the caller. A run started by a Data Hub event, a provider's webhook, a schedule or a record
   event acts as the value of the version's binding of kind `principal`, approved in its binding set (ADR 0110), never
   as the publisher; publish refuses such a version without an approved value (`binding_unset`). The proposer of that
   binding needs `platform.service_principals.use` over the service principal's owning workspace and must hold every
   grant it holds (`platform.grants_cover`, answered by ADR 0104's anti-escalation rule, not a second copy). When its
   grants grow, admission refuses (`binding_needs_review`) until someone who covers them approves the binding again.
   `worker_runs.requested_by` keeps the person who asked or the trigger lane's system actor; `run_as_principal_id`
   (ADR 0113) names whose reach the run uses.
5. **Reach is the principal's live reach intersected with the version's boundary.** A published version fixes its
   boundary in `studio.actor_boundaries` (ADR 0105), immutable after publish: an agent's is derived from its toolset's
   object tools and field caps (ADR 0117), a workflow's from the data nodes of its document (ADR 0112). It is evaluated
   at every statement, never read from a stamp, so a run resumed after an approval narrows if access was lost. The
   database refuses every Studio record read and write when the actor context is missing or names an unknown kind. A
   child run (agent node, workflow tool, linked agent) carries the root's principal intersected with every boundary on
   its chain. Audit names the principal as `actor_id` and the agent or workflow version in `details`.
6. **An integrator authenticates with an API key of one service principal.** `dwk_<key_id>_<secret>`: the secret
   HMAC-SHA-256-hashed under a server pepper, shown once, `expires_at` at most 366 days after creation, at most two live
   keys per principal. `platform.resolve_service_key(key_id)` (SECURITY DEFINER) returns the key's tenant and never its
   hash; a tenant header that disagrees gets 403, so no header names the tenant. Creating a key needs
   `platform.service_principals.manage` and the same cover rule; audit names the `key_id`, never the secret.
7. **Keycloak Organizations route; the platform binds.** The one realm turns on Organizations, one per tenant; in v1
   operators configure a tenant's IdPs on request, and a domain reaches Keycloak only after a DNS TXT proof re-checked
   every 90 days. Only the platform binds an identity to a tenant: by `(iss, sub)`; by a single-use invitation claim
   (at most 7 days, its verified email equal to the invited one); by the login policy `local_or_sso` or `sso_required`,
   checked in the one door that builds access contexts (`DbAccessContextFactory.build`,
   `packages/python/dw_platform/src/dw_platform/application/identity.py:89-94`). The `organization` claim routes to an
   IdP and is never a condition of access.
8. **From P0, the interim linking rule.** A sign-in links to an existing user only through its own `(iss, sub)`, or
   through an `email_verified` email to a user who has never signed in and is neither an operator nor support staff; a
   verified email of a user who has signed in is refused (403 `identity_email_in_use`); matching on `users.subject`
   alone stays for the dev issuer `dw-dev`. A trigger refuses a new login identity for an operator or a support staff
   member, who gain one only through `dw_provisioner`. Invitation claims replace the email step in W2.
9. **Revocation within minutes.** Access tokens live 300 s; SSO sessions idle out after 30 minutes and end after 10
   hours; a refresh token is used once. The per-request membership check, keyed by the access version (ADR 0104), is the
   revocation gate: from an accepted signal (suspension, removal, lock) to no effect, p99 60 s and at most 5 minutes.
   MFA for operators, support staff and holders of a `critical` permission, and step-up (`auth_time` within 15 minutes)
   for sensitive exports, are verified by the platform from `amr` against the one `SECOND_FACTOR_METHODS`
   (`packages/python/dw_platform/src/dw_platform/application/support_access.py:708`), refusing 403 `mfa_required`.

## Alternatives considered

- **An agent as a principal with its own roles** (the research's recommendation, `research.md:340`). Rejected: a second
  holder of rights that can exceed every person who invokes it, the super-agent CLAUDE.md:54 forbids, and a confused
  deputy for prompt injection.
- **Unattended runs act as the publisher.** Rejected: the publisher's reach would leak to anonymous senders, a later
  demotion would not narrow running versions, and a leaver would break the workflow.
- **A tenant-wide system principal, or the lane's system actor.** Rejected: tenant-wide reach is what ADR 0105 refuses,
  and a lane audits as itself (ADR 0011) but holds no reach over records.
- **A realm or an issuer per tenant** (si-platform `docs/adr/0035-each-tenant-signs-in-with-its-own-idp.md`).
  Rejected: cost and configuration grow with every realm (measured in planning on Keycloak 26.7.2, on a contended host,
  ratios only), while Organizations route within one realm.
- **The organization claim as the tenant binding.** Rejected: a token claim would become tenant context
  (CLAUDE.md:192-193), and a membership list kept in Keycloak would have to agree with the platform's (failure-modes #2).
- **A separate principal table.** Rejected for v1: every foreign key to `platform.users` would move, and two identity
  tables would answer one question; revisit if agent identities with their own grants arrive (FOG-80).
- **Remove email linking at once.** Rejected: invitations rely on it until claims ship; the interim rule narrows it.

## Consequences

- Phasing: the interim linking rule (foundations-hardening/02) and the 300 s realm (org-and-principals/01) in W1 P0;
  service principals and run-as (org-and-principals/03), the actor context at every door with the boundaries
  (record-access/04), the principal binding on manual and Data Hub runs (workflow-triggers/01), and workflow-triggers'
  reader of outbox `platform.service_principal.grants_changed`, through which admission refuses
  `binding_needs_review` (decision 4; after org-and-principals/03), in W1 P1; Organizations, invitation claims,
  per-tenant SSO, MFA, step-up and API keys in W2.
- A version with an unattended trigger cannot be published until a service principal is bound (workflow-triggers);
  record-access keys its closure by principal, so a service principal gets a `studio.principal_scopes` row (ADR 0105).
- `platform.users` holds tenant-owned rows and stays without RLS, stated: offboarding suspends them at filing and
  deletes them with the tenant (ADR 0102), and every identity-plane listing filters by kind, because a check that cannot
  see them is failure-modes #0.
- Tests, each shown red by removing its guard: a service principal cannot sign in or hold `tenant_owner`; a proposer
  without cover cannot bind one; an unattended version without an approved principal fails publish; a prompt-injected
  request for another user's record fails at RLS, not in the prompt; a transaction without an actor kind reads no
  record; a child run never reaches more than its parent; a verified email of a signed-in user is refused; a suspended
  member reaches nothing at the next request; an API key sent with a disagreeing tenant header gets 403.
- Harder: provisioning holds a Keycloak admin credential limited to `manage-organizations`, kept in the vault; Keycloak
  sessions are left to their idle expiry, because logging them out needs a realm-wide `manage-users` credential the
  platform does not hold; a person whose IdP sends no `email_verified` cannot claim an invitation until claims ship.
- Contradicts `identity_provisioning.py:138-166` with its docstring at `:14-19` (rewritten) and
  `membership_lookup.py:200-202`, worth reopening because an email is not a stable identifier and a `sub` is unique
  only within its issuer; contradicts `infra/keycloak/dw-realm.json:12-14` (8-hour tokens). Closes ADR 0024's Open 2 in
  two steps (the interim rule, then claims). Retires the stamped reach of `contracts.py:126-127` with ADR 0105.
  Reinforces CLAUDE.md:192-193; consistent with ADR 0011 (a lane audits as itself) and ADR 0024.
- si-platform: diverges from si-platform `docs/adr/0035-each-tenant-signs-in-with-its-own-idp.md` (one realm with
  Organizations and a platform-side binding, not an issuer per tenant), porting its `amr` check and the
  `email_verified` semantics of `packages/python/platform/si_core/src/si_core/application/identity.py`.

## Open

1. **DO-12 (Đạt and requester, before W1).** An unattended run acts as a per-version service principal through an
   approved binding, never the publisher (recommended), or as the publisher, or as a tenant-wide system principal?
   Decisions 4 and 5 rest on the first. Answered 2026-10-23: the per-version service principal through an approved
   `principal` binding, never wider than its proposer (DO-12 (a)).
2. **DO-17 (Đạt, before W1).** Keycloak Organizations in one realm rather than a realm or an issuer per tenant; a
   service principal as a `platform.users` row of kind `service` in v1; and the interim linking rule now, after asking
   dw-proterial whether any import path depends on unverified email linking? Answered 2026-10-23: yes to all three.
   Organizations in one realm, the claim only routing (DO-17.3 (a)); a `platform.users` row of kind `service` with
   `platform.service_principals` as its detail (DO-17.2 (a)); the interim rule in P0, with dw-proterial asked in
   parallel and before foundations-hardening/02 merges (DO-17.1 (a)).
3. **DO-39 (requester).** Provisional (agent, tạm theo khuyến nghị, 2026-10-23, option (a)): an accountable owner
   leaving alerts and blocks publishing while live versions keep running; invitations by an admin-copied claim link;
   MFA for operators, support staff and critical-permission holders. If wrong: ownership passes to the leaver's manager,
   invitations wait for a mailer, or MFA covers every member. Answered 2026-10-23: option (a) on all three, each in W2
   (DO-39.2 (a)).
4. **FOG-45 (grilling).** For nested actors (an agent node in a workflow, a workflow called as a tool, linked agents),
   which boundaries intersect along the chain and how the intersection is bound to `app.boundary_id`; decision 5
   proposes every boundary on the chain.
5. **FOG-78 (prototype).** Does Entra or Google MFA reach `amr` through Keycloak brokering, and does the realm's token
   carry `email_verified`? Decisions 8 and 9 assume both.

## Acceptance (2026-10-23)

- Status Accepted by Đạt; no decision text changes, and no `CLAUDE.md` line changes (`:166-167` is reinforced).
- Open 1 answered with DO-12 (a), Open 2 with DO-17.1, DO-17.2 and DO-17.3 (a), Open 3 with DO-39.2 (a); the line
  that rested on a provisional DO-39 now names it decided.
- dw-proterial is asked, before foundations-hardening/02 merges, whether an import path depends on unverified email
  linking (DO-17.1 (a)).

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Phasing: decision 4's `binding_needs_review` has its W1 reader, workflow-triggers' handler of
  `platform.service_principal.grants_changed`, so a service principal whose grants grew after binding stops at
  admission (H:org-and-principals:R6.6~workflow-triggers:R3.4).
