---
status: Accepted (Đạt, 2026-10-24, on the direction in the decision brief; details revisited when its wave starts)
date: 2026-10-24
source:
    - ../../.claude/plans/studio/custom-objects/spec.md
    - ../../.claude/plans/studio/field-security/spec.md
    - ../../.claude/plans/studio/record-access/spec.md
    - ../../.claude/plans/studio/requirements.md
    - ../../CLAUDE.md
    - 0105-record-reach-is-decided-by-postgresql.md
    - 0106-field-access-follows-personal-data-category.md
    - 0107-custom-objects-over-fixed-tables-one-record-service.md
    - 0101-studio-canvas-is-an-allowlisted-ui-exception.md
---

# 0127. Reports go through the platform aggregate API, and a semantic layer reads only a per-tenant analytics store: no analytics engine connects to the PostgreSQL system of record

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on Đạt's decision N10 of
2026-10-24, one of the coverage review's proposals N1-N10 of 2026-10-23, after the research into Cube of 2026-10-23
and its verification the same day, which asked whether record and field security reach deep enough to put Cube on top
of Studio. The aggregate API is W3 (v1.5); a semantic layer comes only through option PA4, after the aggregate API, so
W3 at the earliest, with no wave assigned yet. The custom-objects spec owns the aggregate query and field-security the
decision it applies; the W3 specs are written when that wave starts.

## Context

- **Reports have no path, and no requirement asks for one yet.** RecordService answers lists and capped counts:
  `count=exact` stops at 10,000 with `count_capped` (custom-objects R8.8), and record-access budgets a capped count of
  1,001 at 300 ms p95 (R9.4). custom-objects parks "reports and group-by aggregates" at v2 until the field decision for
  aggregated numbers is made; the requirements' Không làm line on formula and roll-up fields is about fields, not
  report queries. Nothing in W1 or W2 reports.
- **Two owners decide what a reader sees.** PostgreSQL decides record reach through one RLS policy set over an
  in-database closure, which needs the caller's settings and the closure door in every transaction and returns
  nothing without them (ADR-0105 decisions 1, 4 and 6; YC18). Field access is one application function, because
  tenant fields are slot columns shared across objects and one `dw_app` serves everyone (ADR-0106 decision 4, ADR-0107
  decision 1); a filter, sort, group-by or count on a hidden field is refused before SQL (field-security R3.2). So a
  non-Python service reads Studio record values only through the platform API (`CLAUDE.md`, "A second language",
  condition 5; ADR-0106 decision 8; DO-13.3 (a)).
- **Sources on Cube.** Cube's documentation, repository, releases, security advisories and vendor blog, read on
  2026-10-23 and re-read the same day to verify; the documentation pages carry no date or version, and nothing below
  was measured.
- **Cube decides rows and members itself.** Row filters come from `access_policy` `row_level` and are "combined
  together with filters defined using the query_rewrite configuration option", which is "Called on each request"
  (https://docs.cube.dev/docs/data-modeling/data-access-policies, https://docs.cube.dev/reference/configuration/config);
  with no policy, "By default, all rows are public"
  (https://docs.cube.dev/docs/data-modeling/access-control/row-level-security), the opposite of ADR-0105's closed
  default (failure-modes #7). Member-level policies include or exclude members
  (https://docs.cube.dev/reference/data-modeling/data-access-policies), and "A member is accessible if any matching
  policy grants it" (the data-access-policies page above), which would copy ADR-0106's grants into a second store
  (failure-modes #2).
- **Cube cannot carry this platform's settings.** Its Postgres driver takes `CUBEJS_DB_*`, with a pool of 8 by default
  and no session-parameter or role option (https://docs.cube.dev/admin/connect-to-data/data-sources/postgres);
  `driverFactory` runs once per data source and orchestrator id, and no documented hook runs `set_config(..., true)`
  per transaction (the configuration reference above). Cube "is not designed to access data files directly or fetch
  data from REST, or GraphQL, or any other API" (https://docs.cube.dev/admin/connect-to-data/data-sources). Its
  pre-aggregations "may require write access to the pre-aggregations schema in the source database"
  (https://docs.cube.dev/docs/pre-aggregations), a schema whose contents Cube "will wipe out ... before use" (the
  configuration reference), though with Cube Store and batching the Postgres driver can run read-only (the Postgres
  page above).
- **Its cache cannot see RLS.** "The cache key is a generated SQL statement", and "There's no straightforward way to
  disable caching in Cube" (https://docs.cube.dev/docs/pre-aggregations). `contextToAppId` "scopes multitenancy to data
  model compilation only", "tenants whose data models generate the same SQL will share queue entries, cached results,
  and pre-aggregation tables", one orchestrator serves every tenant by default, and each app or orchestrator id costs
  "single-digit MBs on the lower end and dozens of MBs on the higher end" (https://docs.cube.dev/embedding/multitenancy).
  Reach decided inside PostgreSQL is invisible to a key made of SQL, so two readers with different reach asking the
  same question could get each other's answer (inferred, not measured); pre-aggregations are built by the refresh
  worker for its `scheduledRefreshContexts`, never per viewer.
- **It has been bypassed** (https://github.com/cube-js/cube/security/advisories): GHSA-6jqm-3c9g-pch7 (2022-12-09,
  `/v1/sql-runner` skipping row-level security); GHSA-v226-32c7-x2v7, CVE-2026-25958 (2026-02-09, privilege escalation
  with a valid token, High 7.7); GHSA-hfjj-rfm5-6x53 (2026-09-21, SQL injection through the Presto, Trino, Athena,
  Pinot, Dremio and JDBC drivers, which "may bypass row-level security and disclose data ... including data belonging
  to other tenants"); GHSA-cfx6-94gc-h774 (2026-09-21, SQL injection in the legacy planner, High 8.1); and
  GHSA-mrw5-538h-3298 (2026-09-21, High 7.5: a crafted packet crashes Cube wherever its PostgreSQL-style SQL API is
  reachable, with no login, and "SQL authentication alone does not mitigate this issue"). The patched releases are
  1.4.4, 1.6.70 and 1.7.11 and later.
- **It can be self-hosted, at a size.** The repository is under Apache 2.0 or MIT and Cube Store under Apache 2.0,
  with no clause against running it as a service (https://github.com/cube-js/cube/blob/master/LICENSE,
  https://github.com/cube-js/cube/blob/master/rust/cubestore/README.md); Cube Cloud would process data outside our
  infrastructure (ADR-0123 decision 2). The documented minimum production topology adds up to about 34 GB of RAM
  (https://docs.cube.dev/cube-core/deployment), above D14's 16 GB host. Releases come several a week (v1.8.8 to
  v1.8.11 between 2026-10-16 and 2026-10-22), the LTS line v1.6.x is supported until 2027-07-10, and from v1.7 Cube
  needs Node.js 22 or later (https://github.com/cube-js/cube/releases,
  https://docs.cube.dev/admin/account-billing/distribution, and the vendor's v1.7 post of 2026-07-08,
  https://cube.dev/blog/cube-core-v1-7-tesseract-ga-data-modeling-performance). `CUBEJS_DEV_MODE` is "an
  authentication bypass", and `CUBESQL_AUTH_EXPIRE_SECS` defaults to 300 s, so a revocation reaches a directly exposed
  SQL API only when its token expires (https://docs.cube.dev/reference/configuration/environment-variables).
- **si-platform** puts Cube behind its API over record-level RLS for analytics (si-platform
  `docs/adr/0050-record-level-rls-for-analytics-and-cube-behind-the-api.md`), with reach lists built in Python and
  passed as settings (si-platform `db/si/migrations/0055_analytics_record_rls.sql`), which ADR-0105 rejected here.

## Decision

1. **Reports are aggregate queries over RecordService (PA3), in W3 (v1.5).** `RecordService` gains one aggregate query
   beside its records query (ADR-0107 decision 3), a `POST` sub-resource of the records API like `query` (ADR-0107
   decision 8), in the shape a semantic layer uses: measures (a count, or a sum, average, minimum or maximum of a
   numeric field), dimensions, time dimensions (day, week or month in the tenant's time zone) and filters, every member
   named by field key (`field_defs.id`), the filters in the JSON filter AST with its limits (ADR-0108 decision 2). It
   runs in the caller's transaction under RLS with the caller's settings and closure (ADR-0105 decisions 1, 4 and 6),
   so it counts only what the caller reaches, and field access applies before SQL: a measure, dimension or filter on a
   field hidden from the caller is refused with 422 `field_not_readable` (ADR-0106 decision 4), which is the field
   decision custom-objects waits for. Dimensions and filters take indexed fields only (ADR-0107 decision 1). It needs
   the object's read permission and returns nothing that paging through the caller's own reads would not, and every
   caller of `RecordService` gets the same decisions.
2. **Measured before it is built.** Discovery ticket 30 (N10) measures counts and sums grouped by a field, by day and
   by month through `RecordService` under RLS at D12's scale (10 million records per object, 50 million per tenant),
   for one reader at tenant depth and one at `own`, and records its numbers here before the W3 spec is written.
3. **No analytics engine connects to the system of record.** Cube, a BI tool or any other analytics engine never
   connects to the PostgreSQL that holds Studio records, under any role, `dw_agent_ro` included, and is never handed a
   credential for it.
4. **A semantic layer reads only a per-tenant analytics store (PA4).** A semantic layer such as Cube, if one is
   adopted, reads only a store of each tenant's own, filled by a platform export lane through `RecordService`, and
   nothing else:
    - The lane reads as a service principal that the dataset definition names, approved the way an unattended run's
      principal is (ADR-0103 decision 4), so the store holds what that principal reaches and no more; it never takes the
      tenant-wide scope (ADR-0105 decision 5).
    - It exports only fields with `access_mode` `open` and `pd_category` `none`, chosen by field key, the rule knowledge
      indexing follows (ADR-0106 decision 4), and no system column that can carry personal data, the record name
      included. Each export is stamped with `fls_version`, and the platform serves no dataset exported under an older
      one, so a field secured since the last export never reaches a viewer.
    - A viewer holds read at tenant depth on every object of the dataset, which the platform checks on each request,
      so the store never widens anyone's reach.
    - Cube stands behind the platform API: the platform authorizes every request and signs a short-lived token for it,
      and Cube's own REST and SQL APIs are reachable only from the platform, never from a browser or an outside tool,
      so a revocation applies at the next request (YC14).
    - Cube runs self-hosted in Vietnam (ADR-0123 decision 2) on its own VM outside the main host (D14), pinned by
      digest to one LTS line at or above its patched release, with `CUBEJS_DEV_MODE` off in every deployed profile
      (gated on `settings.is_deployed`) and no Cube Store port published.
    - Its app id (`contextToAppId`), orchestrator id (`contextToOrchestratorId`), pre-aggregation schema
      (`preAggregationsSchema`), refresh contexts (`scheduledRefreshContexts`) and data-source credentials
      (`driverFactory`) are set per tenant, never per viewer and never shared, and each tenant's store is reachable
      only with that tenant's credentials.
    - The store is a tenant data store like any other: offboarding exports and destroys it (YC6), the retention policy
      names its term and remover (ADR-0122 decision 7, YC88), and it registers a `DataSubjectPort`, since its rows
      still concern data subjects (ADR-0106 decision 7, YC90).
5. **Its amendments travel with it.** `CLAUDE.md`, "A second language", condition 5 and ADR-0106 decision 8 keep
   record values to the platform API until the change that turns PA4 on, and that change amends both in the same
   commit, never earlier. Condition 5 keeps its sentence and gains one: "An analytics engine is the exception, and a
   stricter one: it never connects to this database, and reads only a per-tenant analytics store that a platform lane
   fills through RecordService (ADR 0127)." ADR-0106 decision 8 gains the same exception, citing this ADR.
6. **A chart needs its own ADR.** A report screen with a chart brings a chart library, which ADR-0101 decision 6
   refuses until an ADR admits it; until then reports show antd `Statistic`, `Table` and `Progress`.
7. **No ETL, sync or warehouse in v1.** Nothing in W1 or W2 copies records into another store for analysis. PA4 has no
   wave yet: it comes after the aggregate API, and only when PA3's measurement misses its thresholds or a tenant needs
   an outside BI tool.

## Alternatives considered

- **PA1: Cube reads the system of record under RLS, on a connection carrying the viewer's context.** Rejected: with no
  hook for per-transaction settings it needs a driver of our own kept up with weekly releases; results keyed by SQL
  would cross viewers unless every viewer had an orchestrator (single-digit to dozens of MB each, roughly 5 to 250 GB
  for D12's 5,000 users, inferred) or caching were off, and no pre-aggregation could be built per viewer; Cube would
  see every slot of every object, past field security (ADR-0106 decision 8); and an SQL injection in Cube would become
  a read of another tenant.
- **PA2: Cube reads a reporting table that the platform fills inside the same PostgreSQL.** Rejected: fields would
  hold (open, non-personal only) and reach would hold for tenant-depth viewers, but the tenant boundary would still be
  `app.tenant_id` on a shared database, set by Cube per connection, so one injection in Cube's SQL builder reads
  another tenant; analytics load and pre-aggregation builds would fall on the transactional database at 50 million
  records per tenant, and a foreign engine would need its own role and grants there.
- **PA3: the platform's own aggregate API over RecordService, no Cube.** Chosen for v1.5 (decision 1): record reach
  and field access hold by construction and each keeps one owner, and no service is added; its cost is the aggregate
  compiler, the report screen and a chart ADR, and its risk, performance at D12, is measured first (decision 2).
- **PA4: a per-tenant analytics store filled by a platform lane, which Cube or a BI tool reads.** Chosen as the only way
  a semantic layer is admitted (decision 4): the tenant boundary is physical, field access is decided before the
  export and reach before each request. It is the costliest option (a store, a lane, Cube's topology and a VM, all in
  Vietnam and inside offboarding, retention and data-subject requests), it cannot narrow per person inside a tenant,
  and it lags the records by the export interval, so it waits for the aggregate API and a reason (decision 7).
- **Cube's access policies or `query_rewrite` deciding record reach or field access.** Rejected: a second decider
  beside RLS and `resolve_field_access` (ADR-0105, ADR-0106; `CLAUDE.md`, "A second language", condition 4), and open
  by default.
- **ETL, sync or a warehouse in v1.** Rejected (N10): a second copy of every record, with its own residency, retention
  and data-subject duties, before any requirement asks for a report.

## Consequences

- **Owners and wave.** custom-objects owns the aggregate query in `RecordService`, field-security the decision it
  applies, and custom-objects replaces its v2 row "reports and group-by aggregates" with a W3 (v1.5) row under this
  ADR. The requirements record the aggregate reports, the semantic layer and the no-ETL rule under Không làm, and the
  discovery map gains ticket 30 (decision 2). W1 and W2 build nothing for reports, and the usage screen stays on antd
  (ADR-0101 decision 6). The glossary records the analytics store; the aggregate query and the dataset definition
  enter it with their W3 spec.
- **No answer is shared between two viewers.** An aggregate depends on the caller's reach, so a result cache keyed
  without the caller is PA1's shared-result risk: PA3 keeps none, and PA4's cache is per tenant over data that every
  viewer of that tenant may read.
- **YC3 and YC18 hold on both paths.** PA3 reads under the caller's RLS; PA4's export reads under its service
  principal's, its store belongs to one tenant, and its viewers hold tenant depth, so record reach is still decided in
  one place and no tenant reaches another's rows.
- **PA4 owes before it is built:** the export added to the paths ADR-0106 decision 4 names; and tests, each red when
  its guard is removed: two tenants whose models are identical get different results, red when the orchestrator stops
  being per tenant; dev mode is off and no Cube Store port is published in the compose overlay; a field secured after
  an export makes its dataset unservable until the next export.
- **Tests that must exist** for PA3 (W3), each red when its guard is removed: an aggregate on a hidden field is refused
  before SQL, with zero matching records too; an `own`-depth caller's count equals the records it can page through;
  every statement names `tenant_id` and passes the plan-shape test (ADR-0108 decision 2).
- **Revisit** if the measurement shows PA3 cannot meet its thresholds (then PA4 opens under decision 7, never PA1 or
  PA2), or if Cube gains a per-transaction hook and a cache key that carries the caller (then PA1's first two reasons
  fall, and the field and injection reasons still stand).

### Contradictions and amendments

- Keeps `CLAUDE.md`, "A second language", condition 5 and ADR-0106 decision 8 as they are; decision 5 states the
  amendment PA4 brings and when it lands.
- Narrows `CLAUDE.md`, "A second language", whose conditions would let a non-Python service connect as `dw_app` or
  `dw_agent_ro`: an analytics engine gets no connection at all (decision 3), because its cache and SQL builder sit where
  the catalog tests cannot look (failure-modes #0). Until PA4, condition 5 already keeps Studio record values off any
  such connection, so the text changes only with PA4, when the sentence of decision 5 writes the narrowing and its
  exception into condition 5 together.
- Differs from ADR-0100 decision 10, under which `CLAUDE.md` changes once an ADR is accepted: this ADR's one amendment
  waits for the change that turns PA4 on, because an exception nothing uses is a hole nobody watches
  (failure-modes #1).
- Reinforces ADR-0105 (record reach has one owner) and ADR-0106 (field access has one function) on every report path,
  and gives custom-objects' "reports and group-by" row the field decision it was waiting for.
- si-platform: keeps "Cube behind the API" from si-platform
  `docs/adr/0050-record-level-rls-for-analytics-and-cube-behind-the-api.md` and diverges: here Cube never reads the
  system of record, no reach list is passed as a setting (ADR-0105's rejected alternative), and each tenant has its own
  store.

## Open

1. **PA3's thresholds and its fallback** (Đạt, with ticket 30's numbers): the latency an online report must meet at
   D12, and, if it misses, a bounded background report through the long-running operation resource (ADR-0108 decision 3) or per-tenant rollups for tenant-depth viewers. Blocks neither W1 nor W2.
2. **PA4's store and lane** (when PA4 opens): the store's engine and how each tenant's copy is separated, the export
   interval, the actor kind the lane sets (ADR-0105 decision 1 knows `user`, `agent` and `workflow`, and an unknown
   kind reaches nothing), and whether it audits as itself (ADR-0011) or names its service principal as a run does
   (ADR-0103 decision 5).
3. **An outside BI tool** (when PA4 opens): how it reaches a dataset through the platform API, since Cube's own APIs
   stay unreachable from outside (decision 4).
