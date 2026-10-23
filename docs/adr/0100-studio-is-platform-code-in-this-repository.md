---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
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

- `CLAUDE.md:3-7` gives the platform "everything that is not a business domain"; `CLAUDE.md:69-73` calls it "an AI
  platform, not a general application framework"; `.claude/PLAN.md:25` and `:31-33` send products to other repos.
- A bounded context cannot be Studio: contexts never import each other (`CLAUDE.md:50-52`), so none could consume it.
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
4. **One placement rule; privileges fail closed.** A table goes in schema `studio` when only Studio code touches it
   directly (SQL or import), else in `platform`. The schema's revision runs `REVOKE ALL ON SCHEMA studio FROM PUBLIC`,
   `GRANT USAGE ON SCHEMA studio TO dw_app` and `ALTER DEFAULT PRIVILEGES IN SCHEMA studio GRANT SELECT ON TABLES TO dw_app`;
   each table's creating revision grants exactly its writes (`GRANT INSERT, UPDATE (<columns>)`), or none when only
   SECURITY DEFINER functions write it. Nothing goes to `dw_provisioner` (it holds BYPASSRLS), `dw_agent_ro` or PUBLIC;
   every Studio function revokes EXECUTE from PUBLIC and grants it by name. Ids are UUIDv7 from `IdGenerator`, with no
   identity column, serial or sequence in `studio`. Catalog tests assert each line.
5. **Definitions are tenant-wide (S3).** A definition table carries `tenant_id` and an `owning_workspace_id` that
   access depth reads, never the RLS policy, which narrows by tenant only. Business rows keep `workspace_id`.
6. **Composed above the context seams.** `build_studio(container, settings)` in
   `apps/api/src/dw_api/bootstrap/studio.py` runs after `container.runtime` is set (`wiring.py:307`) and before the
   context seam (`:332`), and returns `None` without a database. Its routers form one group under `/api/v1/studio`
   (records at `/api/v1/studio/objects/{api_name}/records`). `build_studio_lanes(settings, registry, reap_targets)` in
   `apps/worker/src/dw_worker/studio.py` registers lanes named `studio_*` that audit as `system_actor(<lane>)`
   (ADR 0011). `dw_studio.testing` registers `studio.<gate>` graders at `scripts/run_evals.py:38`; the web entry is
   `apps/web/app/studio/` with one top-level nav item. Each seam lands with the first real route, lane or suite it
   carries (`CLAUDE.md:314-315`), tested by behaviour (OpenAPI lists `/api/v1/studio/` paths; an anonymous call gets 401,
   not 404, also in the built container), never by walking `app.routes`, blind to included routers under FastAPI 0.141
   (reported by the sibling product dw-proterial; not re-measured here).
7. **One partition registry.** Range-partitioned append-only tables join `platform.time_partitioned_tables`
   (`schema_name`, `table_name`, `append_only`, `retention_months`, `registered_by`; written only by migrations) with
   one row in their creating revision; `platform.ensure_time_partitions` iterates it through a schema-aware
   `platform._ensure_one_partition` that keeps creation, ENABLE and FORCE, the tenant policy and the append-only revoke
   in one function. Nobody redefines it; its revision registers `platform.audit_events` first.
8. **si-platform is reference and selective port source (D5).** Pure code is ported at a pinned commit, with its
   tests, under a first line `Ported from si-platform <path> at <commit> (<date>). Changes: <one line>. Decision: ADR 01NN.`
   Those headers are the ledger (`git grep "Ported from si-platform"`); there is no sync, and a later si fix is a new
   port. Code bound to si's database, roles, numbered SQL migrations or module seam is re-derived. Every divergence is
   stated in the owning ADR, citing si-platform by repository and file name, never by bare number.
9. **ADR numbers.** Studio ADRs take 0100-0199 of `docs/adr/` in its one numbering space, pre-assigned in
   `.claude/plans/studio.md`; a full block continues at 0200, never in the gaps. A check in the architecture CI job
   fails two files in `docs/adr/` that share a four-digit prefix. No draft-id mapping table is kept.
10. **Documents.** Plans live here under area `studio` (D9); the glossary is `packages/python/dw_studio/CONTEXT.md`,
    named by one line in `CONTEXT-MAP.md`; `CLAUDE.md` and `.claude/PLAN.md` change per ADR, once that ADR is accepted.

## Alternatives considered

- **A `dw_studio` bounded context.** Rejected: contexts may not depend on each other, so none could consume it.
- **A separate Studio repository.** Rejected: a second copy of tenancy, authorization and approval, which
  `CLAUDE.md:67-107` refuses even to a second language.
- **Rebuild the seed into a CRM product, as si-platform did.** Rejected by D5 (reference plus selective port).
- **One distribution per capability.** Rejected: seven registrations in every list of `CLAUDE.md` step 2 before any
  capability needs its own deployable; a split stays mechanical once the independence contract holds.
- **Studio inside `dw_platform`.** Rejected: the most-imported package would carry a records engine, and "the core
  never imports Studio" could not be stated.
- **Full-DML default privileges on `studio`.** Rejected: fails open by omission (failure-modes #7), voids column grants.
- **Highest-number-plus-one, or continuing from 0025.** Rejected: it collides as hand-picked revision ids did
  (`CLAUDE.md:254-260`; si-platform renumbered migrations and ADRs within two days, si-platform commits `b444666` and
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
  registry equals the range-partitioned parents that have a DEFAULT partition; the import contracts; the 401 smoke.
- Harder: every Studio table's writes are granted by hand, deliberately; non-Studio code that needs a Studio fact
  declares a Protocol `dw_studio` satisfies at a composition root, or the table belongs in `platform`. Later Studio
  ADRs cite this one for their number and their si-platform relation.

### Contradictions (each amendment applies only when this ADR is accepted)

- Contradicts `CLAUDE.md:3-7` ("everything that is not a business domain"), worth reopening because tenant records are
  business data an agent must reach under the platform's own access model; amendment A1 appends Studio there.
- Contradicts `CLAUDE.md:69-73` ("an AI platform, not a general application framework"), worth reopening because
  Studio carries generated CRUD as the system of record digital workers act on; amendment A2 replaces the paragraph.
- Contradicts `CLAUDE.md:163` ("Every tenant-scoped table has `tenant_id` and `workspace_id`"), worth reopening
  because definitions are tenant-wide (point 5); amendment A6 writes the exception.
- Contradicts `CLAUDE.md:12-44` (contexts are the only plug-in), worth reopening because Studio is wired before the
  context seams so contexts can consume it; amendment A9.
- Keeps `CLAUDE.md:265-274` but supersedes the array and `platform`-only schema of `0013_partition_maintenance.sql`,
  worth reopening because five clusters need parents; amendment A8 names the registry.
- Contradicts `db/migrations/sql/0001_platform_grants.sql:43-46` (full-DML defaults) for schema `studio` only, worth
  reopening because those defaults void column grants.
- Contradicts `.claude/PLAN.md:25` and `:31-33` ("platform seed, with no bounded context"; "Products live in their own
  repos"), worth reopening because Studio is platform and the Marketing pack ships here as configuration; amendment A5.
- Contradicts `CLAUDE.md:33-37` and `:288-289` (datasets and graders per context) for packs, worth reopening because a
  pack has no context package: its evaluation sets are tenant data that the platform's `studio.<gate>` graders grade.

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
   `CLAUDE.md` amended per ADR on acceptance, never in bulk?
2. **DO-02 (Đạt).** One `dw_studio` distribution, one distribution per capability, or Studio inside `dw_platform`? And
   the `studio`/`platform` placement rule with SELECT-only default privileges? Blocks studio-skeleton 01 and 02.
3. **DO-03 (Đạt, with si-platform's PO and SA).** May si-platform code be ported, on what written terms (a pinned
   commit per port, provenance headers, no sync)? And confirm the 0100-0199 block, pre-assignment in the area file and
   no mapping table: the question as filed still proposes a mapping in ADR 0101, which this ADR drops.
4. **DO-25 (requester and Đạt).** Packs live here as configuration (Marketing first), customer packs by import in v2?
5. **DO-16 (Đạt).** Records under `/api/v1/studio/` rather than a bare `/api/v1/objects/`, which would split body
   limits, rate classes, OpenAPI tags and the 401 smoke?
