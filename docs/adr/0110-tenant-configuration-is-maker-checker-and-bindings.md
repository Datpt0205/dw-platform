---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/tenant-config/spec.md
    - ../../.claude/plans/studio/connections-and-vault/spec.md
    - ../../db/migrations/versions/45dc1b5e0125_platform_policy_overrides.py
    - ../../packages/python/dw_kernel/src/dw_kernel/overlay.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py
---

# 0110. A tenant's configuration, its overrides of platform artifacts and the values a version binds, is immutable rows one person proposes and another approves, and documents name their needs only as bindings

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block). Planning proposed the design on
2026-10-22; its rule that every change takes a maker and a different checker is the requester's D11 (2026-10-23,
DO-07), so the status names the requester's direction.

## Context

- **The tenant layer is promised and absent.** CLAUDE.md:223-224 says a tenant's override is "loaded at runtime from
  storage, never from the checkout". `TenantOverlay` holds both layers in memory
  (`packages/python/dw_kernel/src/dw_kernel/overlay.py:30-70`), and the prompt, tool spec, toolset and model profile
  registries are filled from `configs/` only: "nothing loads a tenant layer into them in production"
  (`db/migrations/versions/45dc1b5e0125_platform_policy_overrides.py:7-11`). The one store built since,
  `platform.policy_overrides`, is one row per `(tenant_id, policy_id)` overwritten in place
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/policy_overrides.py:69-72`) with no history and no
  second person, and its `PolicyOverridePort` (`packages/python/dw_platform/src/dw_platform/application/ports.py:120`)
  has no reader outside its adapter and tests: failure-modes #1.
- **Studio needs values apart from content.** The pilot workflow (D4) sends through this tenant's Zalo OA and email
  connections, runs unattended as a service principal (ADR 0103) and may fire on a schedule; a domain pack (ADR 0100)
  and a v2 sandbox tenant (ADR 0111) move definitions between tenants. A connection id inside the document would make
  every tenant's copy, and every swap of a connection, a new version through the quality gate (ADR 0120).
- **The two-person mechanics exist.** A run-less approval announces its decision as `<approval_type>.decided` in the
  decision's transaction, a strict prefix refuses the requester as decider, and a `decision_guards` entry adds a
  per-type condition (CLAUDE.md:274-279; `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:88-101`,
  `:115-120`, `:244-245`). ADR 0012 kept separation-of-duties waivers out of it, in a table of their own. dw-proterial,
  a product built on this platform, decides tenant rule versions on the platform approval (its migrations
  `57a241ea182b` and `218118b8f0e5`).
- **Prior art.** Power Platform keeps a definition apart from the value each environment supplies and never overwrites
  the customer's value (https://learn.microsoft.com/en-us/power-apps/maker/data-platform/environmentvariables,
  2026-10-09), and a flow names its connection indirectly so that an import supplies it
  (https://learn.microsoft.com/en-us/power-apps/maker/data-platform/create-connection-reference, 2026-01-09); its
  layering lets a tenant's change mask a platform update
  (https://learn.microsoft.com/en-us/power-apps/maker/data-platform/solution-layers, 2026-01-09); GitHub environments
  offer "Prevent self-reviews" (https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
  Documented, cited by the planning research on 2026-10-22, not re-read here.

## Decision

1. **Tenant config versions.** `platform.config_versions` is the storage-backed tenant layer behind `TenantOverlay` and
   the store of binding values. Rows are immutable and numbered per `(tenant_id, kind, key, target_version)`, where
   `target_version` is the platform version a prompt, tool spec or toolset replaces, and `version_no` is never reused.
   Each carries `action` (`set`, or `revert` to the platform default), `base_version` (the platform version current at
   proposal), a whole `document` (a jsonb object of at most 256 KiB, NFC, NULL only for `revert`), `document_hash` and
   `status` `proposed`, `approved`, `rejected`, `withdrawn` or `superseded`, with at most one approved row and one open
   proposal per key (partial uniques). RLS is tenant-only.
2. **In force only after a second person approves, unless it only tightens.** One transaction writes the proposal,
   a run-less approval of type `config.version` stamped with the kind's approve permission as `required_scope`
   (ADR 0004) and the audit event
   `config.version.proposed`; a proposal nobody but its maker could decide is refused before it exists (409
   `conflict`, `details.reason_code` `no_checker_available`). `config.` joins `strict_approval_prefixes` with `|=` in
   the API and the worker, so a maker deciding their own proposal gets 409 `conflict` with `second_person_required`,
   and a decision guard refuses a moved base (`decision_stale`) before the decision is written. The database holds
   the rest for every writer: `ck_config_versions_checker_not_maker`; a trigger that lets a row become `approved` only
   when its linked approval is approved; a column grant limiting `dw_app` UPDATE to `status`, `decided_by`,
   `decided_at`, `decision_comment` and `superseded_at`. The worker's idempotent handler for `config.version.decided`
   supersedes the previous approved row in the same transaction, audits `config.version.approved` or
   `config.version.rejected` in the decider's name (`decided_by`) with `details.lane = outbox` (ADR 0011), emits
   outbox `config.version.approved` for cache invalidation and drift, and marks a row whose world moved `rejected`
   with `settlement_conflict`. Rollback is a new proposal, approved like any other. D11 as the requester and Đạt
   scoped it on 2026-10-23 is "close with one, open with two": every change that widens takes the second person
   above, and a change that only tightens, such as a narrower data route, takes one person and an audit event. The
   database holds that branch too: the row carries `tighten_only`, which the kind's registered comparator computes at
   proposal against the approved row whose `document_hash` the row records; `ck_config_versions_checker_not_maker`
   admits the maker as decider only on a `tighten_only` row; the trigger lets such a row become `approved` with no
   linked approval only while that compared row is still the approved one; and the audit names the maker with
   `details.path = tighten_only`, as ADR 0120 decision 1's branch does for versions. A kind with no comparator has no
   such branch: W1's one kind, `binding_set`, registers none, so every binding-set change takes two people in W1, and
   the first comparator ships with kind `policy` in W2. Đạt placed D11's remaining cases on 2026-10-24: re-enabling a
   connection and adding an allowed host each take two people, through a strict run-less approval of type
   `connections.enable` or `egress.allowed_host` whose `.decided` handler applies the change (ADR 0115); lifting a
   tenant's freeze takes two (ADR 0120 decision 7); soft-deleting a role (ADR 0104 decision 10) and narrowing
   `default_access` (ADR 0120 decision 1) take one person and an audit event. W1 has no two-person path for raising a
   limit or widening the data route, so both are refused in W1 (409 `conflict`, `second_person_required`), and the
   pilot's ceilings are set right when it is seeded.
3. **Kinds are registered, and only readable ones exist.** `binding_set` (key: the Studio artifact id) in W1 P1;
   `prompt`, `tool_spec`, `toolset`, `model_profile` (ADR 0118) and `policy` in W2; tenant settings, the tenant's
   data route among them (YC91), are policy documents, not a kind. The kind CHECK lists only kinds that ship. A
   `ConfigKindRegistry` entry supplies the JSON Schema, a validator with the tenant author's restrictions, the
   platform default, the propose and approve permissions and a reader test, and the registry accepts only keys whose
   readers resolve per tenant (422 otherwise).
4. **Resolution never goes sideways.** `TenantArtifactSource`, declared by the runtime and satisfied by `dw_platform`,
   answers readers outside a run with the approved row or the platform default, filling fields a stored version
   predates from the current default (`read_over`); inside a Studio run ADR 0109's `PinnedResolver` answers from the
   run manifest. Fallback is to the platform layer, never to another tenant, and inventory answers read the platform
   layer only. A `base_version` behind the platform's current one is drift, computed on read and shown to ADR 0120's
   lifecycle.
5. **Prompt overrides are narrow.** A tenant may override a platform prompt only where its readers resolve per tenant,
   never with `raw_variables` (ADR 0010) and with no `string.Formatter().parse` field but a declared plain name
   (ADR 0114); a containment prompt such as the agent frame (ADR 0117) is not overridable. An override changes the
   effective hash, so evaluation evidence keyed by the old one no longer counts (ADR 0109).
6. **Documents name their needs as bindings.** A document declares `bindings: [{name, kind, required, description}]`:
   `connection` (connector key and major version, required scopes), `variable` (typed, constrained, with a
   string-encoded default) and `principal` (the run-as principal of unattended runs, ADR 0103, or the person an
   assignment falls back to, checked through `effective_grants` like every candidate) in W1; `secret`,
   `webhook_endpoint` and `schedule` when their readers ship, a schedule's time being a binding value, so moving 09:00
   to 10:00 needs no new gate run. Nodes, tools, toolsets and agents name a binding, never a connection id, and publish
   refuses a document holding one.
7. **Values are one approved binding set per artifact.** A `binding_set` config version keyed by the artifact id is
   validated against the latest published declarations: a connection must be in the tenant, of the declared connector,
   hold the declared scopes and pass `connection_usable` for the proposer, asked again at approval (ADR 0115). No
   version is published while a required binding has no approved value (`binding_unset`); a connection that degrades
   later fails run admission (`binding_degraded`) and raises drift.
8. **Runs pin what they bound.** The run manifest (ADR 0109) records the binding-set version, each connection id and
   credential version, and a hash of each variable value; handlers read them through `RunBindingsPort`, served from the
   manifest, and `connection_usable` still runs at admission and before every egress call.
9. **Packages carry declarations only.** A domain pack, and in v2 a promotion, moves binding names; every tenant, a
   sandbox tenant included, supplies its own values.

## Alternatives considered

- **Connection ids inside the definition document** (the connections planning's map from a name to a connection id,
  hashed with the version). Rejected: a pack or a promotion could not move between tenants, and swapping a connection
  would force a new version through the gate.
- **Self-approval below two admins** (si-platform turns the second person off below two active admins). Rejected: it
  fails open in exactly the tenants with the least oversight (failure-modes #7), and D11 makes the second person
  mandatory.
- **Mutable override rows** (today's `platform.policy_overrides`). Rejected: no history, no rollback, no approval to
  point at.
- **Keep `policy_overrides` beside `config_versions`.** Rejected: two owners of one fact (failure-modes #2).
- **A table per kind, or one of its own as ADR 0012 chose for waivers.** Rejected: five maker-checker pipelines and a
  second inbox, where one approval type, one strict prefix and one guard serve every kind. Role changes are the one
  exception (ADR 0104 decision 10): they keep ADR 0012's pattern, a request table applied in the checker's own
  transaction, because the anti-escalation triggers read the acting person from `app.user_id`, while this table's
  settlement runs in the outbox lane, whose audit names the decider (ADR 0011) but whose transaction carries the
  lane's own actor in `app.user_id`, the actor the triggers would see. The two mechanisms share the SQL function that
  finds a checker over `platform.effective_grants` (tenant-wide for roles, the proposal's workspace here), the reason
  codes `no_checker_available` and `second_person_required`, and the proposal expiry rule.
- **Decide and apply in one transaction** (si-platform's choice). Rejected for now: CLAUDE.md:274-279 prescribes the
  outbox announcement for run-less approvals, and the guard, one open proposal per key and an idempotent settlement
  narrow the window between decision and settlement; revisit if `settlement_conflict` is ever observed.
- **A third layer per workspace, or a field-level merge with the platform default.** Rejected: the overlay stays two
  layers (a business unit's own definitions are Studio artifacts), and whole documents are this repository's choice
  (`45dc1b5e0125_platform_policy_overrides.py:29-33`).

## Consequences

- tenant-config owns the table, the registry, the settlement handler and `TenantArtifactSource`; connections-and-vault
  implements `connection_usable` and `ConnectionDependentsPort`; workflow-engine and agent-builder implement
  `RunBindingsPort` over the run manifest, not over their documents. Phasing: binding sets with maker and checker in
  W1 P1 (tenant-config/05); the five artifact kinds and the removal of `platform.policy_overrides` in W2.
- A tenant with one admin changes configuration and publishes only what tightens (decision 2, ADR 0120 decision 1)
  until it adds a second checker (D11), and sales must say that Studio needs at least two admins. Tenant-wide
  configuration is proposed from the maker's workspace and decided there, because an approval is a workspace row.
- Ports: `DecisionGuard` is synchronous (`approval_flow.py:47`), so the stale-base guard needs the async
  `ApprovalDecisionGuard` and `ProposedDecision` of dw-proterial's `dw_agent_runtime/approval_flow.py`, ported with its
  rule-version pattern (`dw_sales/application/rules.py`: `OVERRIDABLE`, `read_over`, `TenantRuleBook`,
  `RuleSettlement`). `ModelProfile` needs a version and `Decimal` fields before it is a hashed tenant kind (ADR 0109).
- Migrations: an Alembic revision creates `platform.config_versions` with RLS, grants and constraints that
  `test_rls_coverage.py` and `test_privileges.py` assert; it is a tenant-wide row, tenant-only RLS as
  `platform.policy_overrides` has today, listed with its reason under the `CLAUDE.md:185` class ADR 0100 records (A6).
  A later revision, in W2 with kind `policy`, drops `platform.policy_overrides`, `PolicyOverridePort` and
  `SqlPolicyOverrideRepository` once a count shows no rows in uat and production, and the table leaves the
  tenant-wide list of `test_rls_coverage.py` in the same change.
- Tests, each shown red by removing its guard: an UPDATE of `document` is refused; a maker cannot approve their own
  row, through the CHECK or the strict prefix; a row cannot become `approved` without its approval; a key no reader
  resolves per tenant is 422; tenant A never resolves tenant B's row
  (`packages/python/dw_agent_runtime/tests/unit/test_tenant_overlay.py`, extended); a document holding a connection id
  fails publish; an unset required binding blocks publish; a run keeps its pinned binding set after a newer one is
  approved.
- Contradicts `db/migrations/versions/45dc1b5e0125_platform_policy_overrides.py` (a mutable upsert, retired), worth
  reopening because a tenant's value must be approvable and reversible; its whole-document rule is kept. Makes
  CLAUDE.md:223-224 true, declared and never loaded today; uses CLAUDE.md:274-279 as written and keeps
  CLAUDE.md:228-232. Departs from the reasoning of ADR 0012 (lines 31-34) for configuration only; ADR 0012's
  pattern stands for waivers and for role changes (ADR 0104).
  Replaces the connections planning's map from a name to a connection id inside the document, so a connection is
  checked when its binding value is approved (ADR 0115) instead of when a version is published.
- si-platform: diverges from si-platform `docs/adr/0047-two-person-setup-changes-are-decided-and-applied-in-one-transaction.md`,
  which turns the second person off below two active admins and decides and applies in one transaction of a separate
  table: here the conflict check moves before the decision and the platform approval is reused. si-platform has only
  an in-memory overlay, so nothing is ported from it.

## Open

1. **DO-07 (answered by D11, 2026-10-23).** Every tenant configuration change needs a maker and a different checker,
   and a tenant with one admin cannot publish; revisited after the pilot only with evidence. Read here as tenant config
   versions and binding sets; whether it also covers role assignments is ADR 0104's Open 3. Answered 2026-10-23 (the
   requester and Đạt): it also covers every role change and assignment from W1, invitations included, through ADR
   0104's own mechanism, and an object's `default_access`, a field's `access_mode` and every `dw.object/v1` publish;
   a change that only tightens takes one person and an audit event (decision 2).
2. **DO-06 (Đạt, before W1).** Binding names in the version with values in an approved binding set pinned per run,
   replacing connection ids in the document (to settle with the connections-and-vault author)? And is a schedule's
   time a binding value (recommended: moving 09:00 to 10:00 needs no new gate run) or part of the version? Answered
   2026-10-23: binding names in the version, values in an approved binding set pinned per run (DO-06 (a)); a
   schedule's time is a binding value of kind `schedule` once schedules ship in W2.
3. **DO-27 (Đạt, before P1).** Tenant overrides of platform prompts in v1 only where readers resolve per tenant
   (recommended), or none in v1; and drop `platform.policy_overrides` once no deployment holds rows? Answered
   2026-10-23: overrides only where readers resolve per tenant, each a two-person change after which evidence keyed
   by the old effective hash no longer counts (DO-27.1 (a)); `platform.policy_overrides` is dropped in W2 with kind
   `policy`, after zero rows are counted in every deployment (DO-27.2 (a)).
4. **FOG-53 (research).** Whether dw-proterial's schema form fits the binding-set and policy editors, and at what
   porting cost.

## Acceptance (2026-10-23)

- Status Accepted by Đạt with the decision brief's amendments.
- Decision 2: D11's scope recorded, two people to widen and one person with an audit event to tighten (D11
  override).
- Decision 3: the tenant's data route is a `policy` document of W2 (D:tenant-config/05~tenant-rbac:R7.1 (b)).
- Decision 6: a schedule's time is a binding value (DO-06 (a)); a `principal` binding also names an assignment's
  fallback person (Q6 (a)).
- Alternatives: role changes keep ADR 0012's pattern, with the reason, the shared checker function, error code and
  expiry rule (D:tenant-config/05~tenant-rbac:R7.1 (b)).
- Consequences: `platform.config_versions` listed as tenant-wide (A6); the removal of `platform.policy_overrides`
  timed to kind `policy` and a zero-row count (DO-27.2 (a)).
- Open 1 to 3 answered.

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Decision 2: the settlement audits `config.version.approved` and `config.version.rejected` in the decider's name
  with `details.lane = outbox` (ADR 0011), not as `system:outbox`
  (E:CLAUDE.md#agent-and-tool-rules~tenant-config:R8.10).
- Decision 2: both refusals are 409 `conflict`, with `details.reason_code` `no_checker_available` or
  `second_person_required`, shared with ADR 0104 (B:tenant-config:R8.8~tenant-rbac:R7.2).
- Decision 2: the database holds the one-person branch for a change that only tightens (`tighten_only` from the
  kind's comparator, checked against the approved row it was compared with); `binding_set` has no comparator, so W1
  binding-set changes take two people and the branch ships with kind `policy` in W2 (F:ADR-0110~tenant-config:R8.12).
- Decision 2: D11's remaining cases placed: re-enabling a connection and adding an allowed host take two people through
  strict run-less approvals, lifting a freeze two, soft-deleting a role and narrowing `default_access` one; raising a
  limit and widening the data route are refused in W1 (D:ADR-0110~connections-and-vault:api, D11, 2026-10-24).
- Alternatives: role changes keep ADR 0012's pattern for the stated reason, restated now that the outbox lane audits
  the decider: its transaction still carries the lane's own actor in `app.user_id`.
