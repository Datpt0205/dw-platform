---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/studio-skeleton/spec.md
    - ../../.claude/plans/studio/domain-packs/spec.md
    - ../../CLAUDE.md
    - ../../db/migrations/sql/0001_platform_grants.sql
    - ../../db/migrations/sql/0013_partition_maintenance.sql
    - ../../apps/api/src/dw_api/bootstrap/wiring.py
---

# 0100. Studio is platform code in this repository: one dw_studio distribution and one studio schema, composed before any bounded context, with domain content shipped as data

Numbered 0100, the first number of the block 0100-0199 that point 9 reserves for Studio: 0001-0003 are cited in code
and absent, 0013-0023 belong to the first product's branches (ADR 0024 took 0024 to stay clear of them), and 0025-0050
are si-platform's live range, which grows by about two a day.

## Context

Studio is the layer in which a customer defines its own objects, records, workflows, agents and tools as versioned
data (stance S1). Its pilot, Marketing lead intake (D4), scores a lead with a model, makes it a record, assigns it to
Sales and sends a message once a person approves; all of it answers to the one access model this platform owns:

- `CLAUDE.md:3-7` gives the platform "everything that is not a business domain"; `CLAUDE.md:79-83` calls it "an AI
  platform, not a general application framework"; `.claude/PLAN.md:26` and `:32-34` send products to other repos.
- A bounded context cannot be Studio: contexts never import each other (`CLAUDE.md:54-56`), so none could consume it.
- Every tenant table sits in `platform`, `knowledge` or `memory`, whose default privileges hand `dw_app` full DML
  (`db/migrations/sql/0001_platform_grants.sql:43-46`), and "the table-level grant is unaffected by a column-level
  operation" (https://www.postgresql.org/docs/16/sql-grant.html, Notes, read 2026-10-23): column grants are void there.
- Partition upkeep names its parents in one array and hard-codes schema `platform`
  (`db/migrations/sql/0013_partition_maintenance.sql:35-45`, `:71-82`, `:123`); five Studio clusters plan to add one.
- The marked seams serve bounded contexts (`apps/api/src/dw_api/bootstrap/wiring.py:332-337`,
  `apps/api/src/dw_api/main.py:165-167`, `apps/worker/src/dw_worker/main.py:436`, `scripts/run_evals.py:38`).
- si-platform, another team's one-way snapshot fork of this repository, rebuilt the seed into a CRM product
  (si-platform `CLAUDE.md`, "The product"); D5 makes it a reference and a port source. D9 keeps the plans here.

## Decision

1. **Platform, not a context, not a product.** Studio is a platform capability of this repository, not a bounded
   context made with `make new-context` and not a product repository. No platform module branches on a business
   domain, an `api_name` or a pack key: a gap the pilot finds becomes a generic capability in its owning spec.
2. **Domain content ships as data.** A domain pack is a `dw.package/v1` directory under `configs/packs/<key>@<semver>/`,
   installed only through Studio's public surfaces (the API the UI calls) as tenant-owned forks that remember their
   origin (`pack_key`, `pack_version`, `component_key`, `base_content_hash`). A pack update is a three-way proposal
   applied into drafts, never a live layer, never automatic. Marketing is the first pack (D4); no `dw_marketing` exists.
   A tenant installs a pack once, behind the entitlement `studio.pack.<key>`; the release manifest pins each pack
   version; customer packs arrive by import in v2 (DO-25).
3. **One distribution.** `packages/python/dw_studio` holds the Studio capabilities as sub-packages `core`, `records`,
   `workflows`, `agents`, `tools`, `lifecycle` and `testing`, each with `CLAUDE.md`'s layers and an `api` module (types,
   Protocols, errors, pure validators; never an adapter or a session), meeting only through `dw_studio.core` and each
   other's `api` modules. Import-linter contracts state each line: the platform core (`dw_kernel`, `dw_platform`,
   `dw_agent_runtime`, `dw_knowledge`, `dw_memory`, `dw_connectors`, `dw_observability`, `dw_evals`, the planned
   `dw_usage`) never imports `dw_studio`; `records`, `workflows`, `agents`, `tools` and `lifecycle` are independent,
   each permitted edge to another's `api` module listed by name, and `core` imports none of them; each
   `dw_studio.<capability>.domain` joins the domain contract (`pyproject.toml:278-281`); only composition roots import
   `dw_studio.*.adapters`; LangGraph appears only in the compilers (`dw_studio.workflows.workflows`,
   `dw_studio.agents.workflows`), the CEL library only in `dw_studio.core.adapters.cel` behind `ExpressionEngine` (ADR 0114).
   Each sub-package arrives with its first real module and its independence contract, so none ships empty; W1 has
   `core` only (DO-02).
4. **One placement rule; privileges fail closed.** A table goes in schema `studio` when only Studio code touches it
   directly (SQL or import), else in `platform`. The schema's revision runs `REVOKE ALL ON SCHEMA studio FROM PUBLIC`,
   `GRANT USAGE ON SCHEMA studio TO dw_app` and `ALTER DEFAULT PRIVILEGES IN SCHEMA studio GRANT SELECT ON TABLES TO dw_app`;
   each table's creating revision grants exactly its writes (`GRANT INSERT, UPDATE (<columns>)`), or none when only
   SECURITY DEFINER functions write it. Nothing goes to `dw_provisioner` (it holds BYPASSRLS), `dw_agent_ro` or PUBLIC;
   every Studio function revokes EXECUTE from PUBLIC and grants it by name. Ids are UUIDv7 from `IdGenerator`, with no
   identity column, serial or sequence in `studio`. Catalog tests assert each line.
5. **Tenant-wide tables are a class that a test holds (S3).** A table whose rows belong to the whole tenant, such as
   a Studio definition, the tenant's members, roles and access versions, its configuration, limits and counters, its
   consent and suppression lists, a content-addressed manifest, or a child row whose parent carries the workspace,
   carries `tenant_id` and no `workspace_id`, under tenant-only RLS. When one workspace owns such a row, it is named in
   `owning_workspace_id`, the one column name for it across Studio, which access depth reads and RLS never does, with
   a composite foreign key `(tenant_id, owning_workspace_id)` to `platform.workspaces`. The list of these tables, each
   with its reason, has one owner, `test_rls_coverage.py`. Rows that each belong to one workspace (records, runs,
   inbound events, conversations) keep `workspace_id`.
6. **Composed above the context seams.** `build_studio(container, settings)` in
   `apps/api/src/dw_api/bootstrap/studio.py` runs after `container.runtime` is set (`wiring.py:307`) and before the
   context seam (`:332`), and returns `None` without a database. Its routers form one group under `/api/v1/studio`
   (records at `/api/v1/studio/objects/{api_name}/records`). `build_studio_lanes(settings, registry, reap_targets)` in
   `apps/worker/src/dw_worker/studio.py` registers lanes named `studio_*` that audit as `system_actor(<lane>)` when they
   act on their own, and as the person whose recorded decision they carry out, naming themselves in `details.lane`
   (ADR 0011). `dw_studio.testing` registers `studio.<gate>` graders at `scripts/run_evals.py:38`; the web entry is
   `apps/web/app/studio/` with one top-level nav item. Each seam lands with the first real route, lane or suite it
   carries (`CLAUDE.md:361-362`), tested by behaviour (OpenAPI lists `/api/v1/studio/` paths; an anonymous call gets 401,
   not 404, also in the built container), never by walking `app.routes`, blind to included routers under FastAPI 0.141
   (reported by the sibling product dw-proterial; not re-measured here).
7. **One partition registry.** Range-partitioned append-only tables join `platform.time_partitioned_tables`
   (`schema_name`, `table_name`, `append_only`, `registered_by`; written only by migrations) with one row in their
   creating revision; `platform.ensure_time_partitions` iterates it through a schema-aware
   `platform._ensure_one_partition` that keeps creation, ENABLE and FORCE, the tenant policy, the append-only revoke and
   the revoke of every `dw_app` privilege on the new partition in one function, for every registered table in every
   schema. Rows are read and written through the parent, so a table whose policy is narrower than the tenant may join
   the registry, and offboarding, which exports only what `dw_app` can read, exports each row once. Nobody redefines
   it; its revision registers `platform.audit_events` first. A retention term is never a registry column: the
   versioned retention policy (`configs/policies/retention@<semver>.yaml`, keyed `schema.table`, with its `enforced`
   gate) owns every term, so a changed term is a new policy version, never a migration. telemetry-and-audit owns the
   policy's format and its lane; the ticket that registers a table writes that table's term under its `schema.table`
   key in the same change, so the test that every registered append-only table has a term is green from the
   registering change on. The one exception is the registry's first row: its revision (studio-skeleton/01) edits no
   policy file, and until usage-and-limits/02, the first ticket of ADR-0122 decision 7's chain, moves the term under
   the `platform.audit_events` key, the policy model maps `audit.tables.audit_events` of `retention@1.7.0` to that
   key, so the test is green from the registry's own revision on.
8. **si-platform is reference and selective port source (D5).** Pure code is ported at a pinned commit, with its
   tests, under a first line `Ported from si-platform <path> at <commit> (<date>). Changes: <one line>. Decision: ADR 01NN.`
   Those headers are the ledger (`git grep "Ported from si-platform"`); there is no sync, and a later si fix is a new
   port. Code bound to si's database, roles, numbered SQL migrations or module seam is re-derived. Every divergence is
   stated in the owning ADR, citing si-platform by repository and file name, never by bare number. Ports rest on a
   written agreement with si-platform's PO and SA, covering pure code with its tests; until it is in place, a port
   ticket re-derives the code against the same test vectors.
9. **ADR numbers.** Studio ADRs take 0100-0199 of `docs/adr/` in its one numbering space, pre-assigned in
   `.claude/plans/studio.md`; a full block continues at 0200, never in the gaps. The `adr` rule of
   `scripts/check_plans.py` (`:1748-1751`) fails two files in `docs/adr/` that share a four-digit prefix, and CI runs
   it in a blocking step of its own (DO-03); until that step lands, CI runs the checker only with `--advisory`
   (`.github/workflows/ci.yml:74-75`), so a duplicate number fails nothing. No draft-id mapping table is kept.
10. **Documents.** Plans live here under area `studio` (D9); Studio's terms live in the platform glossary
    `docs/platform/CONTEXT.md` that `CONTEXT-MAP.md:9` names, since Studio is platform code and not a context;
    `CLAUDE.md` and `.claude/PLAN.md` change per ADR, once that ADR is accepted.

## Alternatives considered

- **A `dw_studio` bounded context.** Rejected: contexts may not depend on each other, so none could consume it.
- **A separate Studio repository.** Rejected: a second copy of tenancy, authorization and approval, which
  `CLAUDE.md:77-120` refuses even to a second language.
- **Rebuild the seed into a CRM product, as si-platform did.** Rejected by D5 (reference plus selective port).
- **One distribution per capability.** Rejected: seven registrations in every list of `CLAUDE.md` step 2 before any
  capability needs its own deployable; a split stays mechanical once the independence contract holds.
- **Studio inside `dw_platform`.** Rejected: the most-imported package would carry a records engine, and "the core
  never imports Studio" could not be stated.
- **Full-DML default privileges on `studio`.** Rejected: fails open by omission (failure-modes #7), voids column grants.
- **Highest-number-plus-one, or continuing from 0025.** Rejected: it collides as hand-picked revision ids did
  (`CLAUDE.md:298-304`; si-platform renumbered migrations and ADRs within two days, si-platform commits `b444666` and
  `566c551`), and 0025-0050 collide in citation with si-platform.
- **ADR 0101 holding a draft-id-to-number mapping table.** Rejected: the planning drafts' ids never enter the
  repository, so it would map to nothing a reader can open; the area file owns the numbers (one owner per fact).

## Consequences

- `studio-skeleton` (P0) lands the distribution, the schema and its grants, the import contracts, the seams, the
  partition registry and the duplicate-number check before any capability; its first real module (tenant-config's
  version envelope) merges in the same branch, so no seam ships empty.
- The root `pyproject.toml` lists, `scripts/verify_architecture.py:21` (`IMPORT_TO_DIST`), the Dockerfile COPY lists
  (`infra/docker/api.Dockerfile:21-31`, the worker's) and `apps/api/pyproject.toml` gain `dw_studio`, and scaffold-smoke
  passes with it present. Two migrations, with alembic's random ids, create schema `studio` (in the warning DO-block
  style of `0001_platform_grants.sql:18-25`) and the registry, rewriting both partition functions.
- Tests, each shown red by removing its guard: a probe table the migrator creates in `studio` is readable and not
  writable by `dw_app`; no `studio` object grants to PUBLIC, `dw_provisioner` or `dw_agent_ro`; `_PLATFORM_SCHEMAS`
  (`test_rls_coverage.py:64`) gains `studio` with the first tenant table; `MetaData(schema="studio")` matches the
  catalog; offboarding exports every `studio` tenant table or names it, with a reason, in an exclusion list; the
  registry equals the range-partitioned parents that have a DEFAULT partition; a partition read by its own name as
  `dw_app` is refused with permission denied (the new expectation of `test_rls_coverage.py:187-225`); every
  append-only table in the registry has a term in the retention policy; the import contracts; the 401 smoke.
- `test_rls_coverage.py` holds the tenant-wide class of decision 5 the way it holds `_PRINCIPAL_ONLY_ON_PURPOSE`
  (`:108-131`): it reads from the catalog every parent table (`relkind IN ('r', 'p')`, not a partition) with
  `tenant_id` and no `workspace_id`, compares that set both ways with a `_TENANT_WIDE_ON_PURPOSE` dict of reasons
  (seeded with today's tables, such as `platform.policy_overrides` and `platform.sod_waivers`), and fails a listed
  table whose policy reads `app.workspace_id` or whose `owning_workspace_id` lacks the composite foreign key; a probe
  table `(tenant_id uuid)` created in a rolled-back transaction shows it red.
- Harder: every Studio table's writes are granted by hand, deliberately; non-Studio code that needs a Studio fact
  declares a Protocol `dw_studio` satisfies at a composition root, or the table belongs in `platform`. Later Studio
  ADRs cite this one for their number and their si-platform relation.

### Contradictions (each amendment applies only when this ADR is accepted)

- Contradicts `CLAUDE.md:3-7` ("everything that is not a business domain"), worth reopening because tenant records are
  business data an agent must reach under the platform's own access model; amendment A1 appends Studio there.
- Contradicts `CLAUDE.md:79-83` ("an AI platform, not a general application framework"), worth reopening because
  Studio carries generated CRUD as the system of record digital workers act on; amendment A2 replaces the paragraph.
- Contradicts `CLAUDE.md:185` ("Every tenant-scoped table has `tenant_id` and `workspace_id`"), worth reopening
  because definitions and the other rows of decision 5 belong to the whole tenant, and tables without `workspace_id`
  already run unnoticed (`test_rls_coverage.py:44-59` looks for `tenant_id` only); amendment A6 writes the tenant-wide
  class with examples and names `test_rls_coverage.py` as the one owner of its list.
- Contradicts `CLAUDE.md:14-48` (contexts are the only plug-in), worth reopening because Studio is wired before the
  context seams so contexts can consume it; amendment A9.
- Keeps `CLAUDE.md:309-321` but supersedes the array and `platform`-only schema of `0013_partition_maintenance.sql`,
  worth reopening because five clusters need parents; amendment A8 names the registry and adds the revoke of every
  `dw_app` privilege on a new partition to the one function.
- Contradicts `db/migrations/sql/0001_platform_grants.sql:43-46` (full-DML defaults) for schema `studio` only, worth
  reopening because those defaults void column grants.
- Contradicts `.claude/PLAN.md:26` and `:32-34` ("platform seed, with no bounded context"; "Products live in their own
  repos"), worth reopening because Studio is platform and the Marketing pack ships here as configuration; amendment A5.
- Contradicts `CLAUDE.md:37-41` and `:288-289` (datasets and graders per context) for packs, worth reopening because a
  pack has no context package: its evaluation sets are tenant data that the platform's `studio.<gate>` graders grade.
  The amendment adds to `:288-289` "and per domain pack, inside the pack, graded by the platform's `studio.<gate>`
  graders".

### Relation to si-platform

- Diverges from si-platform's rebuild of the seed into a product (si-platform `CLAUDE.md`, "The product").
- Adopts si-platform `docs/adr/0025-packages-meet-only-through-their-api-module.md` inside Studio only, enforced by
  import-linter instead of si-platform `scripts/verify_module_interfaces.py`.
- Re-derives si-platform's `ModuleSpec` seam (`packages/python/platform/si_seam/src/si_seam/api.py`), its
  `db/si/migrations/NNNN_*.sql` files and its `si_owner` and `app_user` roles as Alembic revisions and `dw_*` roles.
- Ports with provenance `packages/python/platform/si_metadata/src/si_metadata/values.py` and its siblings `rules.py`
  (structure only; predicates are CEL), `list_query.py`, `references.py`, and
  `packages/python/platform/si_security/src/si_security/application/record_access.py` (RESTRICTIVE RLS, InitPlan form).

## Open

1. **DO-01 (Đạt).** Accept Studio as platform (S1), with tenant-wide definitions that carry an owning workspace, and
   `CLAUDE.md` amended per ADR on acceptance, never in bulk? Answered 2026-10-23: yes (DO-01 (a)); tenant-wide tables
   are the class of decision 5, their list held by `test_rls_coverage.py`.
2. **DO-02 (Đạt).** One `dw_studio` distribution, one distribution per capability, or Studio inside `dw_platform`? And
   the `studio`/`platform` placement rule with SELECT-only default privileges? Blocks studio-skeleton 01 and 02.
   Answered 2026-10-23: one distribution (DO-02.1 (a)); the placement rule with SELECT-only defaults, and no `dw_app`
   privilege on a new partition of any registered table, in any schema (DO-02.2 (a)).
3. **DO-03 (Đạt, with si-platform's PO and SA).** May si-platform code be ported, on what written terms (a pinned
   commit per port, provenance headers, no sync)? And confirm the 0100-0199 block, pre-assignment in the area file and
   no mapping table: the question as filed still proposes a mapping in ADR 0101, which this ADR drops. Answered
   2026-10-23: yes, under a written agreement requested now from si-platform's PO and SA (DO-03.2 (a)); the block,
   pre-assignment and no mapping table are confirmed, and the `adr` rule gets a blocking CI step (DO-03.1 (a)).
4. **DO-25 (requester and Đạt).** Packs live here as configuration (Marketing first), customer packs by import in v2?
   Answered 2026-10-23: yes, as decision 2 states (DO-25 (a)).
5. **DO-16 (Đạt).** Records under `/api/v1/studio/` rather than a bare `/api/v1/objects/`, which would split body
   limits, rate classes, OpenAPI tags and the 401 smoke? Answered 2026-10-23: under `/api/v1/studio/` (DO-16.1 (a)).

## Acceptance (2026-10-23)

- Status Accepted by Đạt with the decision brief's amendments; amendments A1, A2, A6, A8, A9 (`CLAUDE.md`) and A5
  (`.claude/PLAN.md`) now apply.
- Decision 5: tenant-wide tables are a class given by example, `owning_workspace_id` is the one name for an owning
  workspace, and `test_rls_coverage.py` alone holds the list (DO-01 (a)).
- Decision 7: `retention_months` removed, the retention policy owns every term (DO-52, F:ADR-0100~studio-skeleton);
  every registered table's new partitions give `dw_app` no privilege, in every schema (DO-02.2 (a)).
- Decision 9 matches CI: the `adr` rule as a blocking step, today's advisory run stated (DO-03.1 (a)).
- Decision 10: the glossary is `docs/platform/CONTEXT.md`.
- Decision 6: a lane carrying out one person's recorded decision audits that person and names itself in `details.lane`
  (OPS-a.1).
- Decisions 2, 3 and 8: pack install and entitlement (DO-25 (a)), no empty sub-package (DO-02.1 (a)), the written
  port agreement (DO-03.2 (a)).
- Citations of `.claude/PLAN.md` corrected to `:26` and `:32-34`; Consequences gain the tenant-wide, partition and
  retention tests; the pack graders' amendment text recorded.
- Open 1 to 5 answered.

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Decision 7: telemetry-and-audit owns the retention policy's format (keys `schema.table`) and its lane, and each
  ticket that registers a table adds that table's term in the same change (F:ADR-0100~studio-skeleton:R3.7).
- Third consistency check (round 4), second pass: decision 7 names its one exception, the registry's first row,
  `platform.audit_events`, whose revision edits no policy file and whose term the policy model maps from
  `retention@1.7.0` until usage-and-limits/02, the head of ADR-0122 decision 7's chain, moves it under its
  `schema.table` key (V4.P1, the planner's provisional call; if it is wrong, studio-skeleton/01 releases the first
  version with that key and the exception goes).
