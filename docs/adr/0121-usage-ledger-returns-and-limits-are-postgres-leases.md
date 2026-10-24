---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/usage-and-limits/spec.md
    - ../../db/migrations/versions/0013_drop_model_usage_ledger.py
    - ../../db/migrations/versions/2b5ff2bceb06_tenant_daily_spend_guard.py
    - ../../packages/python/dw_platform/src/dw_platform/application/entitlement.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py
---

# 0121. A per-call usage ledger returns as metering with named readers, and every hard limit is a Postgres lease reserved at run admission across one scope chain

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It reverses an
owner decision: migration `aefe7c1f5d9b` dropped the per-call ledger on 2026-09-21, misdescribed
as invoicing evidence and read only by a spend cap and an admin dashboard, because "Đạt asked for
the whole feature gone" (`0013_drop_model_usage_ledger.py:3-14`). The first point stays true,
named readers answer the second, and Đạt signed the return on 2026-10-23 (DO-21.1): the ledger comes
back through a new revision, never a downgrade of `aefe7c1f5d9b`. ADR-0113, whose claim admits runs
through this ADR's `LimitsPort`, was accepted with it.

## Context

- **What bounds a tenant today.** `runs_per_day` from `DEFAULT_PLANS`
  (`dw_platform/application/entitlement.py:17-36`) on a UTC day (`dw_agent_runtime/allowance.py:63`),
  an in-process `RunBudgetLedger` bounding one run in one worker
  (`dw_agent_runtime/model/budget.py:61-68`), and `platform.tenant_daily_spend_guard`, "not a
  per-call event log" (`2b5ff2bceb06_tenant_daily_spend_guard.py:14-17`). Prices sit on model
  routes (`dw_agent_runtime/model/profiles.py:54-55`).
- **What Studio needs (D6).** Limits and usage per workspace, agent, workflow and user, a usage
  dashboard and reconciliation, embedding, rerank and code sandbox included. A daily total
  attributes none of it; traces are sampled (`.claude/skills/reviewing-feature-security/SKILL.md:114`);
  a check after the call "is accounting, not a ceiling" (`:129-131`), as N parallel runs that each
  see money left all spend it; the spend ceiling once missed the agent loop (`failure-modes.md` #5).

## Decision

1. **The usage ledger.** `platform.usage_events` holds one usage event per metered call: `chat`,
   `embeddings`, `rerank`, `extraction`, `transcription`, `sandbox_exec`, `server_tool`, connector
   units (the manifest's `usage_unit`, for example `zns_message`) and the reaper's
   `unsettled_estimate`. A row names tenant, workspace, run, `root_run_id`, lease, node, the agent
   or workflow version, `purpose` (`run`, `test_run`, `builder_assist`, `eval_offline`,
   `eval_online`, `ingestion`, `retrieval`, `compaction`, `memory`), `payer` (`platform`, or
   `tenant` for BYOM), tokens, units and `cost_usd` with its `cost_source`, never content. Monthly
   partitions with a DEFAULT one, RLS forced on each, append-only for `dw_app`, kept 13 months (395
   days). Settlement is idempotent (`id` and `occurred_at` set before the call, insert
   `ON CONFLICT DO NOTHING`). It meters consumption and is never invoicing evidence.
2. **Its readers ship with it** (`failure-modes.md` #1), three in W1: lease settlement and the
   reaper, which also bound evaluation spend, since a gate run holds a lease of purpose
   `eval_offline` (DO-21.4); `GET /api/v1/runs/{run_id}/usage`; and the `usage_rollup` lane feeding
   `platform.usage_daily`, `GET /api/v1/usage/summary` and the usage dashboard. The operator
   reconciliation aggregate `platform.usage_provider_daily(day)` (SECURITY DEFINER, by provider and
   model, no tenant ids) and cost per workflow outcome over the runs of one `root_run_id` (which needs
   an outcome event no spec emits yet; fees a tenant pays a provider directly, such as ZNS on its own
   account, stay outside it) are not readers until a ticket ships each with its consumer (DO-21.1).
3. **One price book.** `configs/pricing/price_book@<semver>.yaml`, pinned in the release manifest,
   prices every metered operation by effective-dated entries per provider, model and usage type,
   cache state, code sandbox time by profile (reserved vCPU and GB times wall time, ADR 0119) and
   server tool calls included. Tenant BYOM entries live in
   `platform.tenant_price_entries`, resolved like `TenantOverlay`: the tenant's own, else the
   platform's, never another tenant's. Model profiles lose their prices in the same change; history
   is never re-priced. When `settings.is_deployed`, a platform-paid route without a price refuses
   startup; a BYOM route may stay unpriced (`cost_source = 'unpriced'`, token limits only).
4. **One limit scope chain.** Every limit is a policy at one scope of the chain plan, tenant,
   workspace and each ancestor (D1), agent or workflow, from W2 (YC79) user, and run (a child run
   shares its root's lease); a run proceeds only while every scope in the chain with a policy passes.
   Kinds are `hard` and `soft` in v1, `approval` in v1.5. Behavioural limits (steps, model and tool
   calls, wall clock, per-run cost and tokens) live in the agent or workflow version, clamped by plan
   maxima; operational limits on money, tokens and runs per window, and from W2 (YC79) on
   concurrency, live in audited `platform.limit_policies` rows a tenant admin changes without
   republishing. A row names its scope through typed foreign keys, `scope_workspace_id`,
   `scope_artifact_id` (an agent or workflow) and, from W2 with the user scope, `scope_user_id`,
   each `ON DELETE CASCADE`, exactly one of them set below the tenant
   (`num_nonnulls(...) = 1`) and none for a tenant-wide limit, the way ADR 0115 keys secret subjects,
   so a limit whose workspace, user or artifact is deleted goes with it; the `scope_` prefix is there
   because the table is tenant-wide and so carries no `workspace_id` column (`CLAUDE.md`, Tenancy and
   authorization). Lowering a limit takes one person and an audit event;
   raising one takes a maker and a different checker (DO-07), a path W1 does not have, so W1 refuses
   every raise (closed while missing) and the pilot's caps are seeded at the right numbers
   (DO-59.1). From W2 (YC79), each with its reader, a policy may name its purposes, so builder
   assistance, test runs and evaluations get caps of their own, and threshold alerts at 80% and
   100% emit `usage.limit.threshold_crossed` once per policy, window and threshold.
5. **Hard money and token limits are leases.** At admission, in one database transaction, the
   runner locks the chain's `platform.budget_counters` rows in canonical order (scope rank, then id,
   so admissions cannot deadlock), counts runs (and from W2, YC79, concurrent runs), and opens one
   `platform.budget_leases` row per root run for no more than every scope has left. The lease caps
   each model call's `max_tokens`; each call settles idempotently into the ledger and the lease;
   counters move only at admission, top-up, a 60-second heartbeat roll and close. A wait for a
   person releases the lease and the resume opens a new one. A `ReapTarget` on the reaper lane
   settles crashed runs' leases as `system:reaper` (ADR 0011). Code sandbox time, in the unit of
   decision 3, uses the same leases (ADR 0119), and so, from W2, does concurrency. A lane prunes the
   counters of past windows, since each window adds a row (`failure-modes.md` #6), reading its
   terms from the retention policy: a counter goes 13 months after its window ends, as the ledger
   does, and a lease 30 days after it closes (ADR 0122).
6. **When a limit is hit.** Admission happens in one place, the runner, when the `studio_runs`
   lane claims the run (ADR 0113 decision 3); no API dependency answers 429 for a Studio run, and
   429 stays only on the old inline path (`langgraph_runner.py:246-264`). From W2 (YC79), missing
   concurrency re-queues every kind. A spent window ends an interactive run (`chat`, `manual`,
   `test`, `replay`, `fork`; ADR 0113 decision 3) `failed` with
   `details.reason_code = limit_exceeded`, the metric, scope, window and `resets_at`; holds a
   `datahub`, `provider_app` or `record_event` run `queued` until `resets_at` or a raised limit,
   never dropped; records a `schedule` fire (W2) as `limit_refused` and skips it instead of holding
   it, because holding every missed fire would release them all at once when the window resets; and
   ends a gate run `error` with `limit_exceeded` and no HTTP status. A child run shares its root's
   lease and is not admitted again (DO-21.3). Mid-run the run stops at the next model call, tool
   call or node boundary with `limit_exceeded` and no retry, executed effects kept and audited;
   never a silent downgrade.
7. **One owner, no back door.** `RunBudgetLedger`, `RunBudgetMiddleware`, `RunAllowancePort`,
   `DailyAllowance`, `RuntimeSeam.budget` and `platform.tenant_daily_spend_guard` are replaced in the
   same slice by a new package, `packages/python/dw_usage`; the runtime declares `LimitsPort` and
   knowledge `UsageMeterPort`, wired at the composition root where `RunAllowancePort` is today
   (DO-21.2).
   `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort` and `MeteredRerankPort`
   are the only model-reaching doors; import-linter forbids the concrete adapters elsewhere.
8. **Valkey holds rate, never money or concurrency.** `RateLimiterPort` keeps GCRA buckets keyed
   by tenant and workspace, a provider governor with fair shares per tenant by plan, and dispatch
   pacing; without Valkey it falls back to per-process buckets (limit divided by replicas), so a
   lost replica lowers the total and never raises it. W1 ships the port with that per-process
   adapter, which the 60 inbound events per minute of YC44 need; GCRA on Valkey follows in W2
   (DO-49 (a), requirements Q3 (a)), and the plan's `requests_per_minute` and `tokens_per_minute`
   join `platform.plan_limits` with it, since those buckets are what reads them (failure-modes #1).
9. **One plan catalogue, in the database.** `platform.plans` and a typed `platform.plan_limits` (no
   RLS, `dw_app` SELECT only; NULL means no limit, a missing row refuses, per-run maxima NOT NULL)
   replace `DEFAULT_PLANS` and the `quotas` jsonb. Windows follow the tenant's time zone (default
   `Asia/Ho_Chi_Minh`) through one function, `window_for(tenant_id, window_kind, at)`; the ledger
   is kept in USD.

### Calls confirmed on 2026-10-23 (option (a) of DO-50 and DO-43)

- Windows are cut in the tenant's time zone; a hard limit hit mid-run stops the run at the next
  boundary.
- Builder assistance, test runs and evaluations count against the tenant's limits under separate
  purpose caps (W2, YC79) and not toward runs per day; only root runs count toward runs per day. The
  tenant pays its own evaluations, and the platform the re-evaluations it triggers (DO-29.2 (a)).
- BYOM tokens count only against caps the tenant sets, and a failing tenant model never falls back
  to a platform-paid route (ADR 0118).

## Alternatives considered

- **Keep the ledger removed.** Rejected: limits, the usage dashboard, the evaluation cost bound and
  reconciliation would have no source.
- **Counters in Valkey.** Rejected: Valkey is never a source of truth (`CLAUDE.md:64`); LiteLLM's
  budgets read a Redis counter on the hot path whose restart can under-read spend
  (https://docs.litellm.ai/docs/proxy/users, fetched 2026-10-22).
- **Check spend after the call.** Rejected: it overspends by one loop's length, the agent loop's
  gap; the same page says `disable_budget_reservation` lets concurrent requests exceed a budget.
- **A rate limiter per cluster.** Rejected: two answers to one question, two failure behaviours.
- **Prices on model profiles.** Rejected: one fact in many places (`failure-modes.md` #2), no price
  for embedding, rerank or the code sandbox, and providers price by date and cache state
  (https://ai.google.dev/gemini-api/docs/pricing, fetched 2026-10-22).

## Consequences

- Migrations, as new alembic revisions: `platform.usage_events` (DEFAULT partition, forced RLS,
  append-only grants), `platform.usage_daily`, `platform.limit_policies`, `platform.budget_counters`,
  `platform.budget_leases`, `platform.plan_limits`, `platform.tenant_price_entries`; the partition
  function takes an array of append-only parents; `platform.tenant_daily_spend_guard` is dropped and
  `platform.plans.quotas` retired once its data has moved.
- Tests, each shown red with its guard removed: `test_rls_coverage.py` and `test_privileges.py`
  cover the new tables (no UPDATE or DELETE on `usage_events` for `dw_app`); parallel admissions
  never exceed a small ceiling; each model-reaching door refuses without a lease; the reaper settles
  a killed run's lease; an unpriced platform-paid route refuses a deployed startup; a missing
  `plan_limits` row refuses; with Valkey stopped, money limits, and from W2 concurrency limits, still
  hold.
- Harder: two small writes per model call (to be measured); a resumed run can be stopped by an
  exhausted month; model profiles change shape; `test_only_the_platform_lanes_are_wired` changes;
  offboarding exports the ledger and then purges it with the rest of the tenant's Studio data
  (YC6); its `user_id` is personal data, so erasing it on a data subject's request still needs
  counsel's decision (DO-52, ADR 0122). `usage-and-limits` lands before any deployed Studio run is
  admitted.
- The pruning lane of decision 5 reads its terms from the retention policy (ADR 0122):
  `platform.budget_counters` 13 months (395 days) after a window ends and `platform.budget_leases`
  30 days after close, provisional and UNVERIFIED like every term there. A limit whose workspace,
  user or artifact is deleted goes with it through decision 4's typed foreign keys, so no cleanup
  rule is needed.

### Contradictions and divergences

- _Contradicts migration `aefe7c1f5d9b` (`0013_drop_model_usage_ledger.py:3`, `:16`), the guard
  of `2b5ff2bceb06_tenant_daily_spend_guard.py:14-17` and `DEFAULT_PLANS`, but worth reopening
  because Studio needs a per-call source, now shipped with its readers, and a code copy of the plan
  catalogue drifts (`failure-modes.md` #2)._ `configs/policies/retention@1.7.0.yaml:72-73` goes too.
- Generalises `CLAUDE.md:260-265` (the plan's limit enforced where a run begins, through
  `RunAllowancePort`) into the `LimitsPort` scope chain; the runner stays the place. The sentence is
  amended on acceptance (DO-21.2): a run's limits are still enforced where it begins, in the runner,
  and a Studio run begins when the `studio_runs` lane hands it over; every limit on the scope chain
  comes through `LimitsPort`, which the runtime declares and `dw_usage` satisfies, and
  `RunAllowancePort` goes. Since 2026-10-24 the same rule names decision 6's `schedule` exception
  beside "a triggered one waits in the queue, never dropped" (Q-R7).
- _Contradicts `CLAUDE.md:185` (every tenant-scoped table has `workspace_id`) for the tenant-level
  `platform.limit_policies` and `platform.budget_counters`, but worth reopening because a workspace
  is one scope of the chain, as with `platform.policy_overrides`
  (`45dc1b5e0125_platform_policy_overrides.py:35-38`)._ Settled by amendment A6 (ADR 0100): both
  tables are tenant-wide and listed with this reason in `test_rls_coverage.py`;
  `platform.budget_counters` is keyed by `(scope_type, scope_id)`, and `platform.limit_policies` by
  decision 4's typed scope columns.
- _Contradicts `dw_agent_runtime/adapters/langgraph_runner.py:255-257` (no limit refuses a
  resume), but worth reopening because money spent after a resume is new spend; runs per day is
  still not counted again._
- _Contradicts ADR-0011's "Not applied, on purpose" list naming spend-guard counters
  (`0011-a-background-lane-audits-as-itself.md:40-43`), but worth reopening because an expired
  lease settles spend against a tenant's limits, so the reaper audits it as itself._
- si-platform: re-derived, as si-platform has no ledger (si-platform
  `packages/python/platform/si_agent_runtime/src/si_agent_runtime/adapters/telemetry_usage.py`);
  ports the limiter of si-platform `packages/python/hosts/si_api/src/si_api/http/rate_limit.py` and
  the typed table of si-platform `db/si/migrations/0043_plan_limits.sql`; GCRA in Valkey is new.

## Open

1. **DO-21, Đạt.** Accept the per-call ledger, reversing `aefe7c1f5d9b`, with decision 2's readers?
   Answered 2026-10-23: yes, a per-call ledger kept 13 months, metering and never invoicing
   evidence, back through a new revision, with the three W1 readers of decision 2 (DO-21.1 (a)).
2. **DO-59, the requester with Đạt.** Plan numbers for cost, tokens, concurrency, RPM and TPM, and
   the unit tenants see and set (a USD estimate in the pilot, credits before selling). Answered
   2026-10-23: in W1 a USD estimate, plan rows seeded with today's numbers and money left NULL (no
   plan-level money cap, as today), the pilot's caps as `platform.limit_policies` rows the requester
   names for the demo tenant before the demo, a pilot tenant holding its own cap before its first
   `live` run, and per-run maxima still NOT NULL (DO-59.1 (a)); before GA a fixed plan fee with a
   monthly AI cost ceiling, `cost_usd_per_month`, and no credits in v1 (DO-59.2 (a)).
3. **DO-50, the requester.** Mid-run stop in v1, approval kind in v1.5, never a silent downgrade;
   who pays builder assistance, test runs and evaluations (provisional (a) above; DO-29, Đạt).
   Answered 2026-10-23: the calls above stand (DO-50 (a)); windows fall back to `Asia/Ho_Chi_Minh`
   when the tenant's time zone is NULL, and purpose caps come in W2; who pays evaluations is
   DO-29.2 (a).
4. **DO-43, the requester.** Do BYOM tokens count against plan caps? Provisional (a) above.
   Answered 2026-10-23: no, only against caps the tenant sets (DO-43 (a)).
5. **DO-49, Đạt.** Per-process rate buckets while Valkey is unreachable, rather than failing closed.
   Answered 2026-10-23: yes, through the one `RateLimiterPort`, shipped in W1 with that adapter
   (decision 8; DO-49 (a)).
6. **DO-07, Đạt with the requester.** D11 gives every tenant configuration change a maker and a
   checker; whether that covers every `platform.limit_policies` change or only loosening is open.
   Answered 2026-10-23 by the requester and Đạt: lowering a limit takes one person and an audit
   event, and raising one always takes a maker and a different checker. On 2026-10-24 they added
   that W1, having no two-person path for a raise, refuses every raise (decision 4).

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23, together with ADR-0113, with these amendments from the decision
brief:

- Decision 2: three W1 readers ship with the ledger; operator reconciliation and cost per outcome
  wait for a ticket each, and evaluation spend is bounded through its `eval_offline` lease (DO-21.1,
  DO-21.4).
- Decisions 3 and 5: code sandbox time is priced and leased as the profile's reserved vCPU and GB
  times wall time (DO-45.1 (a)); a lane prunes past windows' counters (the limit-tables CRITICAL,
  option (a)).
- Decision 6: admission happens once, at the `studio_runs` claim, with the refusal shapes of
  ADR 0113 decision 3; the 429 for a conversation turn goes (DO-21.3 (a)).
- Decision 7: `RunAllowancePort` goes with `DailyAllowance` (DO-21.2 (a)).
- Decision 8: the per-process adapter ships in W1, GCRA on Valkey in W2 (DO-49 (a), Q3 (a)).
- Confirmed calls: DO-50 and DO-43 confirmed, DO-29.2 added.
- Consequences and Contradictions: offboarding purges the ledger after the export (YC6); the
  counters' term and orphaned limits owed; the `CLAUDE.md:260-265` amendment written out; both
  limit tables tenant-wide under amendment A6.
- Open: DO-21, DO-59, DO-50, DO-43, DO-49 and DO-07 answered.

## Amendments (2026-10-24)

Amended by Đạt on 2026-10-24, who accepted every recommendation the second consistency check left
open, with the D11 cases scoped by the requester and Đạt:

- Decision 4: `platform.limit_policies` names its scope through typed foreign keys with
  `ON DELETE CASCADE` instead of `(scope_type, scope_id)`, so an orphaned limit removes itself
  (F:ADR-0121~usage-and-limits:dữ-liệu); lowering a limit takes one person and raising one two,
  and W1, which has no two-person path, refuses every raise while the pilot's caps are seeded
  right.
- Decision 5 and Consequences: counters are kept 13 months and leases 30 days after close, both
  read from the retention policy, provisional and UNVERIFIED (D:ADR-0121~usage-and-limits:R5.7).
- Decision 6 and Contradictions: the `schedule` exception states its reason, and `CLAUDE.md`
  (Agent and tool rules) now names it (Q-R7); `replay` and `fork` are interactive runs, as
  ADR 0113 decision 3 now lists them.
- Third consistency check (round 4), Đạt's V4.12: decision 4's scope columns are
  `scope_workspace_id`, `scope_user_id` and `scope_artifact_id`, as usage-and-limits names them,
  since a tenant-wide table carries no `workspace_id` (F:ADR-0121~usage-and-limits:spec).
- Third consistency check (round 4), second pass: decisions 4 to 6 place the user scope with its
  `scope_user_id`, purpose caps, the 80% and 100% threshold alerts, and concurrency, counted at
  admission and answered by a re-queue when it is missing, in W2 with YC79, each with its reader,
  as ADR-0113 decision 3 now does for the re-queue; decision 8 adds the plan's
  `requests_per_minute` and `tokens_per_minute` to W2 with the GCRA buckets that read them
  (failure-modes #1). V4.P6, the planner's provisional call
  (H:usage-and-limits:R4.1\~usage-and-limits:spec); if it is wrong, W1 takes the user scope and the
  concurrency caps, and these sentences lose their "from W2".
